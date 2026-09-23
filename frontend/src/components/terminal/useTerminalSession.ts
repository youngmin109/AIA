import { useEffect, useRef, useState } from 'react'
import { createXtermAdapter, type XtermAdapter } from './xtermAdapter'

// Ported near-verbatim from workbench.html's terminal WebSocket client,
// activity state machine, and Codex-TUI screen-scraping heuristics
// (trust-directory / command-approval detection, composer-ready gating,
// submit-settle). The wire protocol and detection regexes are unchanged --
// only the renderer changed: xterm.js (xtermAdapter.ts) now owns painting,
// scrollback, and escape-sequence parsing instead of a hand-rolled VT100
// emulator, so this hook only asks it for a plain-text snapshot of the
// visible screen when the detection regexes need one.

export type ActivityMode =
  | 'IDLE'
  | 'STARTING'
  | 'WAITING'
  | 'SUBMITTING'
  | 'WORKING'
  | 'OUTPUTTING'
  | 'ACTION'
  | 'ERROR'
  | 'STOPPED'
  | 'STOPPING'

export type TerminalAction = 'TRUST_DIRECTORY' | 'COMMAND_APPROVAL' | null

interface ConnectionState {
  label: string
  tone: 'ok' | 'warn' | 'bad'
}

// Codex's Workbench launch binds composer.submit to Ctrl+X. It is sent as a
// separate WebSocket message so the text stays ordinary input and the
// submit key is not swallowed as part of a paste burst.
const SUBMIT_SETTLE_MS = 250
const SUBMIT_ECHO_WAIT_MS = 3000

// Codex's own model call can legitimately go silent for a minute or more
// (confirmed against bare `codex exec`, outside AIA entirely -- this is a
// Codex/model-API characteristic, not an AIA pipeline issue). Codex's local
// "Working (Ns)" redraw freezes too during that wait, since its own event
// loop blocks on the same network read -- so without a signal of our own,
// a long-but-normal response is indistinguishable from AIA itself being
// stuck. This threshold only decides when to show that signal.
const HEARTBEAT_STALL_SECONDS = 15

export interface UseTerminalSessionOptions {
  sessionId: string
  terminalOutputRef: React.RefObject<HTMLDivElement | null>
  runEnded: boolean
  protectionDisconnected: boolean
  onTerminalStatus?: (status: { status?: string; pid?: number | null; rows?: number; cols?: number }) => void
}

export function useTerminalSession({
  sessionId,
  terminalOutputRef,
  runEnded,
  protectionDisconnected,
  onTerminalStatus,
}: UseTerminalSessionOptions) {
  const [activityMode, setActivityMode] = useState<ActivityMode>('IDLE')
  const [activityLabel, setActivityLabel] = useState('')
  const [activityStartedAt, setActivityStartedAt] = useState(0)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [silentSeconds, setSilentSeconds] = useState(0)
  const [connection, setConnection] = useState<ConnectionState>({ label: '연결 대기', tone: 'warn' })
  const [terminalAction, setTerminalActionState] = useState<TerminalAction>(null)
  const [composerReady, setComposerReady] = useState(false)
  const [awaitingResponse, setAwaitingResponse] = useState(false)
  const [interruptPending, setInterruptPending] = useState(false)
  const [reconnectPending, setReconnectPending] = useState(false)
  const [socketConnected, setSocketConnected] = useState(false)
  const [connectionFailed, setConnectionFailed] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [pid, setPid] = useState<number | null>(null)
  const [terminalRuntimeStatus, setTerminalRuntimeStatus] = useState('UNKNOWN')

  const socketRef = useRef<WebSocket | null>(null)
  const socketEverConnectedRef = useRef(false)
  const socketRetryRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pendingSubmissionRef = useRef<{ value: string; timer: ReturnType<typeof setTimeout> | null } | null>(null)
  const detectionBufferRef = useRef('')
  const responseStartedAtRef = useRef(0)
  const terminalClosedRef = useRef(false)
  const lastResizeSignatureRef = useRef('')
  const resizeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const xtermRef = useRef<XtermAdapter | null>(null)
  // Batches same-frame WS `output` messages into one xterm.write() + one
  // processTerminalOutput() pass (see appendTerminal below) -- a fast
  // server poll tick delivers many small messages during an active Codex
  // response, and running the full trust/approval/composer regex scan on
  // every single one of them let the browser fall behind visibly on long
  // output, even though each individual message is cheap on its own.
  const pendingOutputRef = useRef<string[]>([])
  const outputFrameRef = useRef<number | null>(null)
  // Time of the last PTY byte actually received (not the last render), so
  // the heartbeat below measures real silence from the wire, independent of
  // RAF batching.
  const lastOutputAtRef = useRef(Date.now())

  // Kept in refs so the WS callbacks (registered once per socket, not per
  // render) always see the latest value without forcing a socket reopen.
  const activityModeRef = useRef(activityMode)
  activityModeRef.current = activityMode
  const awaitingResponseRef = useRef(awaitingResponse)
  awaitingResponseRef.current = awaitingResponse
  const runEndedRef = useRef(runEnded)
  runEndedRef.current = runEnded
  const protectionDisconnectedRef = useRef(protectionDisconnected)
  protectionDisconnectedRef.current = protectionDisconnected

  const setActivity = (mode: ActivityMode, label: string) => {
    const previousMode = activityModeRef.current
    activityModeRef.current = mode
    const resetClock = previousMode !== mode || (mode === 'WAITING' && awaitingResponseRef.current)
    setActivityMode(mode)
    if (resetClock) setActivityStartedAt(Date.now())
    if (resetClock && ['SUBMITTING', 'WORKING', 'OUTPUTTING'].includes(mode)) lastOutputAtRef.current = Date.now()
    setActivityLabel(label)
    if (!['SUBMITTING', 'WORKING', 'OUTPUTTING'].includes(mode)) setInterruptPending(false)
    if (['SUBMITTING', 'WORKING', 'OUTPUTTING', 'STOPPING'].includes(mode)) setAwaitingResponse(true)
    if (['WAITING', 'ACTION', 'ERROR', 'IDLE', 'STOPPED'].includes(mode)) setAwaitingResponse(false)
    if (mode === 'WORKING' && previousMode !== 'WORKING' && awaitingResponseRef.current) {
      responseStartedAtRef.current = Date.now()
    }
    if (['WAITING', 'ACTION', 'ERROR', 'IDLE', 'STOPPED'].includes(mode)) responseStartedAtRef.current = 0
  }

  const setConnectionState = (label: string, tone: ConnectionState['tone']) => setConnection({ label, tone })

  // Mounts xterm.js into the DOM node. Declared before the socket-opening
  // effect below so xtermRef is always populated before any WS message
  // could arrive -- effects for one hook fire in declaration order after
  // the same commit, and refs attach before any effect runs, so this ordering
  // is a real guarantee, not a race.
  useEffect(() => {
    const node = terminalOutputRef.current
    if (!node) return
    const adapter = createXtermAdapter(node)
    xtermRef.current = adapter
    return () => {
      if (outputFrameRef.current !== null) cancelAnimationFrame(outputFrameRef.current)
      outputFrameRef.current = null
      pendingOutputRef.current = []
      adapter.dispose()
      xtermRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  function send(message: Record<string, unknown>): boolean {
    const socket = socketRef.current
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(message))
      return true
    }
    return false
  }

  function terminalDraftIsVisible(value: string): boolean {
    const normalized = String(value || '').replace(/\s+/g, ' ').trim()
    if (!normalized) return true
    const visible = (xtermRef.current?.bufferText(activityModeRef.current === 'WAITING') ?? '').replace(/\s+/g, ' ')
    const prefix = normalized.slice(0, Math.min(48, normalized.length))
    const suffix = normalized.slice(-Math.min(48, normalized.length))
    return visible.includes(normalized) || visible.includes(prefix) || visible.includes(suffix)
  }

  function restorePendingSubmission(message: string): boolean {
    const pending = pendingSubmissionRef.current
    if (!pending) return false
    if (pending.timer) clearTimeout(pending.timer)
    pendingSubmissionRef.current = null
    setActivity('WAITING', message)
    return true
  }

  function scheduleTerminalSubmit(value: string) {
    const startedAt = Date.now()
    const submit = () => {
      const pending = pendingSubmissionRef.current
      if (!pending || pending.value !== value) return
      const elapsed = Date.now() - startedAt
      if (!terminalDraftIsVisible(value) && elapsed < SUBMIT_ECHO_WAIT_MS) {
        pending.timer = setTimeout(submit, 80)
        setActivity('SUBMITTING', 'Codex 작업창에 입력을 반영하는 중입니다.')
        return
      }
      if (send({ type: 'submit' })) {
        setActivity('WORKING', 'Codex가 요청을 처리하는 중입니다.')
      } else if (restorePendingSubmission('터미널 연결이 끊겨 전송하지 못했습니다. 다시 전송하세요.')) {
        setErrorMessage('Codex에 요청을 전송하지 못했습니다. 입력 내용을 확인한 뒤 다시 시도하세요.')
      }
    }
    pendingSubmissionRef.current = { value, timer: setTimeout(submit, SUBMIT_SETTLE_MS) }
  }

  function processTerminalOutput(data: string) {
    const text = String(data || '')
    detectionBufferRef.current = (detectionBufferRef.current + text).slice(-16000)
    const buffer = detectionBufferRef.current
    const trustPromptVisible = /Do you trust the contents of this directory\?/i.test(buffer) || /Press enter to continue/i.test(buffer)
    const currentScreen = xtermRef.current?.bufferText(activityModeRef.current === 'WAITING') ?? ''
    const commandApprovalVisible =
      /Would you like to run the following command\?/i.test(currentScreen) &&
      /Yes, proceed \(y\)/i.test(currentScreen) &&
      /Press enter to confirm or esc to cancel/i.test(currentScreen)
    const visibleLines = currentScreen.split('\n').filter((line) => line.trim()).slice(-10)
    const tailLines = visibleLines.slice(-4)
    const workingAtTail = tailLines.some((line) => /(^|\s)Working(?:\s*\(|\s+\d+s?\b|\s*$)/i.test(line))
    const composerVisible = visibleLines.some((line) => /Ask Codex to do anything|무엇을 도와드릴까요/.test(line))
    const codexStillInitializing = /(?:^|\n)\s*(?:model|directory):\s*loading\b/i.test(currentScreen)
    const responseOutputReceived = text.length > 0 && awaitingResponseRef.current && ['SUBMITTING', 'WORKING', 'OUTPUTTING'].includes(activityModeRef.current)
    const composerAtTail = tailLines.some((line) => /Ask Codex to do anything|무엇을 도와드릴까요/.test(line))

    if (trustPromptVisible) {
      setComposerReady(false)
      setTerminalActionState('TRUST_DIRECTORY')
      setActivity('ACTION', 'Codex가 Workspace 신뢰 확인을 기다리고 있습니다. "신뢰하고 계속"을 눌러주세요.')
    } else if (commandApprovalVisible) {
      setComposerReady(true)
      setTerminalActionState('COMMAND_APPROVAL')
      setActivity('ACTION', 'Codex가 명령 실행 승인을 기다리고 있습니다.')
    } else if (responseOutputReceived && !(composerAtTail && !workingAtTail)) {
      setActivity('OUTPUTTING', 'Codex 응답을 수신하는 중입니다.')
    } else if (workingAtTail && ['SUBMITTING', 'WORKING', 'OUTPUTTING', 'WAITING'].includes(activityModeRef.current)) {
      setActivity('OUTPUTTING', 'Codex 응답을 수신하는 중입니다.')
    } else if (codexStillInitializing) {
      setComposerReady(false)
      setTerminalActionState(null)
      setActivity('STARTING', 'Codex가 모델과 Workspace를 준비하는 중입니다.')
    } else if (composerVisible) {
      setComposerReady(true)
      const mode = activityModeRef.current
      if (
        awaitingResponseRef.current &&
        ['WORKING', 'OUTPUTTING'].includes(mode) &&
        composerAtTail &&
        !workingAtTail &&
        responseStartedAtRef.current &&
        Date.now() - responseStartedAtRef.current >= 750
      ) {
        setTerminalActionState(null)
        setActivity('WAITING', '응답 완료 · 다음 작업을 입력할 수 있습니다.')
      } else if (['WORKING', 'OUTPUTTING'].includes(mode) && composerAtTail && !workingAtTail && !responseStartedAtRef.current) {
        setTerminalActionState(null)
        setActivity('WAITING', 'Codex가 다음 작업 입력을 기다리고 있습니다.')
      } else if (!awaitingResponseRef.current && composerAtTail && !workingAtTail && ['STARTING', 'SUBMITTING', 'WORKING'].includes(mode)) {
        setTerminalActionState(null)
        setActivity('WAITING', 'Codex가 다음 작업 입력을 기다리고 있습니다.')
      }
    }
  }

  function appendTerminal(data: string) {
    if (!data) return
    lastOutputAtRef.current = Date.now()
    pendingOutputRef.current.push(data)
    if (outputFrameRef.current !== null) return
    outputFrameRef.current = requestAnimationFrame(() => {
      outputFrameRef.current = null
      const combined = pendingOutputRef.current.join('')
      pendingOutputRef.current = []
      if (!combined) return
      xtermRef.current?.write(combined, () => processTerminalOutput(combined))
    })
  }

  function handleTerminalStatus(status: { status?: string; pid?: number | null; rows?: number; cols?: number; error?: string | null }) {
    const value = status?.status || 'UNKNOWN'
    setTerminalRuntimeStatus(value)
    setPid(status?.pid ?? null)
    onTerminalStatus?.(status)
    const terminalEnded = runEndedRef.current
    const disconnected = protectionDisconnectedRef.current
    const connectionState: ConnectionState =
      disconnected && !terminalEnded
        ? { label: '보호 연결 끊김', tone: 'bad' }
        : value === 'RUNNING'
          ? { label: '연결됨', tone: 'ok' }
          : value === 'FAILED'
            ? { label: '연결 실패', tone: 'bad' }
            : value === 'EXITED'
              ? { label: '종료됨', tone: 'warn' }
              : terminalEnded && ['UNKNOWN', 'NOT_ATTACHED'].includes(value)
                ? { label: '종료됨', tone: 'warn' }
                : value === 'NOT_ATTACHED'
                  ? { label: '연결 대기', tone: 'warn' }
                  : { label: '확인 중', tone: 'warn' }
    setConnectionState(connectionState.label, connectionState.tone)
    if (status?.rows && status?.cols) xtermRef.current?.terminal.resize(Number(status.cols), Number(status.rows))
    if (value === 'RUNNING') scheduleTerminalResize()
    if (value === 'FAILED') setErrorMessage(status?.error || '터미널 연결에 실패했습니다.')
    if (value === 'RUNNING' && activityModeRef.current === 'IDLE') setActivity('STARTING', 'Codex 작업창에 연결하는 중입니다.')
    if (value === 'NOT_STARTED' && activityModeRef.current === 'IDLE') setActivity('STARTING', 'Codex 작업창을 시작하는 중입니다.')
    if (['FAILED', 'EXITED'].includes(value) || (terminalEnded && ['UNKNOWN', 'NOT_ATTACHED'].includes(value))) {
      setTerminalActionState(null)
      setActivity('STOPPED', 'Codex 작업창이 종료되었습니다.')
    }
  }

  function scheduleTerminalResize() {
    if (resizeTimerRef.current) clearTimeout(resizeTimerRef.current)
    resizeTimerRef.current = setTimeout(syncTerminalSize, 120)
  }

  function syncTerminalSize() {
    resizeTimerRef.current = null
    if (terminalRuntimeStatus !== 'RUNNING' || !socketConnected) return
    const result = xtermRef.current?.fit()
    if (!result) return
    const { rows, cols } = result
    const signature = `${rows}x${cols}`
    if (signature === lastResizeSignatureRef.current) return
    lastResizeSignatureRef.current = signature
    send({ type: 'resize', rows, cols })
  }

  function openSocket() {
    const existing = socketRef.current
    if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) return
    if (protectionDisconnectedRef.current) {
      terminalClosedRef.current = true
      setSocketConnected(false)
      setConnectionState('보호 연결 끊김', 'bad')
      setActivity('STOPPED', 'AIA 보호 연결이 끊겨 작업창을 사용할 수 없습니다.')
      return
    }
    if (runEndedRef.current) {
      terminalClosedRef.current = true
      setSocketConnected(false)
      return
    }
    terminalClosedRef.current = false
    setSocketConnected(false)
    setComposerReady(false)
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
    const socket = new WebSocket(`${scheme}://${location.host}/api/runs/${encodeURIComponent(sessionId)}/terminal`)
    socketRef.current = socket

    socket.onopen = () => {
      if (socketEverConnectedRef.current) {
        // The server replays the bounded terminal buffer from sequence
        // zero for every new WebSocket. Reset the renderer before a
        // reconnect so replay restores the screen instead of duplicating
        // old output.
        xtermRef.current?.reset()
        detectionBufferRef.current = ''
      }
      socketEverConnectedRef.current = true
      setConnectionFailed(false)
      setReconnectPending(false)
      setSocketConnected(true)
      setConnectionState('연결 확인 중', 'warn')
    }
    socket.onmessage = (event) => {
      if (typeof event.data !== 'string') return
      let message: { type?: string; [key: string]: unknown }
      try {
        message = JSON.parse(event.data)
      } catch {
        return
      }
      if (!message || typeof message !== 'object' || typeof message.type !== 'string') return
      if (message.type === 'output') appendTerminal(String(message.data ?? ''))
      else if (message.type === 'status') handleTerminalStatus(message as { status?: string; pid?: number | null; rows?: number; cols?: number })
      else if (message.type === 'accepted') {
        if (message.action === 'submit' && pendingSubmissionRef.current) {
          if (pendingSubmissionRef.current.timer) clearTimeout(pendingSubmissionRef.current.timer)
          pendingSubmissionRef.current = null
          setActivity('WORKING', 'Codex가 요청을 처리하는 중입니다.')
        }
        setConnectionState('연결됨', 'ok')
      } else if (message.type === 'error') {
        const text = typeof message.message === 'string' ? message.message : '터미널 요청이 거부되었습니다.'
        if (restorePendingSubmission(text)) {
          setErrorMessage('Codex에 요청을 전달하지 못했습니다. 입력 내용을 확인한 뒤 다시 시도하세요.')
        } else {
          setErrorMessage(text)
        }
      } else if (message.type === 'closed') {
        terminalClosedRef.current = true
        setSocketConnected(false)
        handleTerminalStatus(message as { status?: string; pid?: number | null })
      }
    }
    socket.onclose = () => {
      setReconnectPending(false)
      setSocketConnected(false)
      if (!socketEverConnectedRef.current) setConnectionFailed(true)
      if (restorePendingSubmission('터미널 연결이 끊겨 전송하지 못했습니다. 다시 전송하세요.')) {
        setErrorMessage('Codex에 요청을 전송하지 못했습니다. 입력 내용을 확인한 뒤 다시 시도하세요.')
      }
      if (!runEndedRef.current && !terminalClosedRef.current) {
        setConnectionState('재연결 중', 'warn')
        setActivity('STARTING', 'Workbench 터미널 연결이 끊겨 다시 연결하는 중입니다.')
        socketRetryRef.current = setTimeout(openSocket, 1000)
      }
    }
    socket.onerror = () => {
      setReconnectPending(false)
      setSocketConnected(false)
      setConnectionFailed(true)
      setConnectionState('연결 오류', 'bad')
      setErrorMessage('Workbench 터미널 연결을 확인할 수 없습니다.')
    }
  }

  useEffect(() => {
    openSocket()
    return () => {
      if (socketRetryRef.current) clearTimeout(socketRetryRef.current)
      socketRef.current?.close()
      socketRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  // Activity elapsed-time clock, mirrors updateActivityClock's 1s interval.
  useEffect(() => {
    if (activityMode === 'IDLE' || activityMode === 'STOPPED' || activityMode === 'WAITING') {
      setElapsedSeconds(0)
      setSilentSeconds(0)
      return
    }
    const tick = () => {
      setElapsedSeconds(Math.max(0, Math.floor((Date.now() - activityStartedAt) / 1000)))
      setSilentSeconds(Math.max(0, Math.floor((Date.now() - lastOutputAtRef.current) / 1000)))
    }
    tick()
    const timer = setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [activityMode, activityStartedAt])

  // Re-measure on container resize (ResizeObserver), matching the original.
  useEffect(() => {
    const node = terminalOutputRef.current
    if (!node || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(scheduleTerminalResize)
    observer.observe(node)
    window.addEventListener('resize', scheduleTerminalResize)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', scheduleTerminalResize)
      if (resizeTimerRef.current) clearTimeout(resizeTimerRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [terminalOutputRef.current])

  function sendLine(value: string) {
    if (terminalAction === 'TRUST_DIRECTORY' && !value.length) {
      continueAction()
      return
    }
    if (terminalAction === 'COMMAND_APPROVAL') {
      const approval = value.trim()
      if (!approval) return
      if (!send({ type: 'input', data: approval })) {
        setErrorMessage('Codex 터미널이 연결되지 않아 승인 내용을 전송하지 못했습니다. 연결 상태를 확인하세요.')
        return
      }
      setErrorMessage(null)
      setTerminalActionState(null)
      setActivity('WORKING', 'Codex에 명령 승인 내용을 전달하는 중입니다.')
      setTimeout(() => send({ type: 'input', data: '\r' }), 80)
      return
    }
    if (awaitingResponse) return
    if (!value.length) return
    if (!send({ type: 'input', data: value })) {
      setErrorMessage('Codex 터미널이 연결되지 않아 전송하지 못했습니다. 연결 상태를 확인하세요.')
      setActivity('WAITING', '터미널 연결을 확인한 뒤 다시 전송하세요.')
      return
    }
    setErrorMessage(null)
    scheduleTerminalSubmit(value)
    setActivity('SUBMITTING', 'Codex에 질문을 제출하는 중입니다.')
  }

  function continueAction() {
    if (terminalAction === 'COMMAND_APPROVAL') {
      sendLine('y')
      return
    }
    if (terminalAction !== 'TRUST_DIRECTORY') return
    if (!send({ type: 'input', data: '\r' })) {
      setErrorMessage('Codex에 계속 진행 신호를 보내지 못했습니다. 터미널 연결을 확인하세요.')
      return
    }
    detectionBufferRef.current = ''
    setTerminalActionState(null)
    setActivity('WORKING', 'Codex가 Workspace 확인을 처리하는 중입니다.')
  }

  function interrupt() {
    if (interruptPending || !['SUBMITTING', 'WORKING', 'OUTPUTTING'].includes(activityMode)) return
    if (pendingSubmissionRef.current?.timer) clearTimeout(pendingSubmissionRef.current.timer)
    pendingSubmissionRef.current = null
    if (!send({ type: 'input', data: String.fromCharCode(3) })) {
      setErrorMessage('Codex 터미널이 연결되지 않아 현재 요청을 중지하지 못했습니다. 연결 상태를 확인하세요.')
      return
    }
    setInterruptPending(true)
    setActivity('WORKING', '현재 Codex 요청을 중지하는 중입니다.')
  }

  function reconnect() {
    if (reconnectPending || terminalClosedRef.current || runEnded || socketConnected) return
    if (socketRetryRef.current) {
      clearTimeout(socketRetryRef.current)
      socketRetryRef.current = null
    }
    setReconnectPending(true)
    setConnectionState('다시 연결하는 중', 'warn')
    setActivity('STARTING', 'Workbench 터미널에 다시 연결하는 중입니다.')
    const socket = socketRef.current
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) socket.close()
    else openSocket()
  }

  function sendRaw(data: string) {
    send({ type: 'input', data })
  }

  const trustRequired = terminalAction === 'TRUST_DIRECTORY'
  const commandApprovalRequired = terminalAction === 'COMMAND_APPROVAL'
  const terminalReady = terminalRuntimeStatus === 'RUNNING' && socketConnected && composerReady && !trustRequired && !protectionDisconnected
  const terminalUnavailable = runEnded || protectionDisconnected || terminalClosedRef.current || ['EXITED', 'FAILED'].includes(terminalRuntimeStatus)
  const reconnectVisible = (socketEverConnectedRef.current || connectionFailed) && !socketConnected && !terminalClosedRef.current && !runEnded
  const interruptVisible = ['SUBMITTING', 'WORKING', 'OUTPUTTING'].includes(activityMode) && !terminalClosedRef.current && !protectionDisconnected
  const heartbeat = {
    visible: silentSeconds >= HEARTBEAT_STALL_SECONDS && ['SUBMITTING', 'WORKING', 'OUTPUTTING'].includes(activityMode),
    seconds: silentSeconds,
  }

  return {
    activity: { mode: activityMode, label: activityLabel, elapsedSeconds },
    heartbeat,
    connection,
    terminalAction,
    composerReady,
    awaitingResponse,
    interruptPending,
    reconnectPending,
    reconnectVisible,
    interruptVisible,
    errorMessage,
    pid,
    terminalReady,
    commandApprovalRequired,
    trustRequired,
    terminalUnavailable,
    sendLine,
    continueAction,
    interrupt,
    reconnect,
    sendRaw,
    dismissError: () => setErrorMessage(null),
  }
}
