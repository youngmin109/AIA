import { localSessionToken, resetLocalSessionToken } from '../../api/localSession'
import type { Usage } from '../../api/usageView'
import { useCallback, useEffect, useRef, useState } from 'react'
import { applyEvents, EMPTY_CONVERSATION, isInteractiveResponse, type ApprovalRequest, type CodexEvent, type CodexPlan, type ConversationState, type ElicitationRequest, type PermissionsRequest, type QuestionRequest } from './codexConversation'

// Talks to WS /api/runs/{id}/codex. The server pushes structured events as
// Codex produces them; this hook only folds them into a transcript and sends
// user commands. There is no screen scraping and no input gating on guessed
// Codex state: the input is usable whenever the conversation is READY or
// WORKING (a message during a turn steers it).

// EXTERNAL: the run is coordinated by another AIA window on the same control
// root; this window can only show that and forward an end request.
export type CodexStatusName = 'NOT_ATTACHED' | 'NOT_STARTED' | 'STARTING' | 'READY' | 'WORKING' | 'CLOSING' | 'EXITED' | 'FAILED' | 'EXTERNAL'

export interface CodexStatus {
  status: CodexStatusName
  pid: number | null
  active_turn_id: string | null
  pending_approvals: ApprovalRequest[]
  pending_questions?: QuestionRequest[]
  pending_elicitations?: ElicitationRequest[]
  pending_permissions?: PermissionsRequest[]
  usage?: Usage
  turn_settings?: { model: string | null; effort: string | null }
  plan?: CodexPlan | null
  effective: { model?: string | null; sandbox?: string | null; approval_policy?: string | null }
  error: string | null
  last_sequence: number
  owner_pid?: number | null
  end_requested?: boolean
}

export type ConnectionTone = 'ok' | 'warn' | 'bad'

const RECONNECT_DELAYS_MS = [500, 1000, 2000, 4000]
const TERMINAL_STATUSES = new Set<CodexStatusName>(['EXITED', 'FAILED'])

let clientCounter = 0
function nextClientId(): string {
  clientCounter += 1
  return `c${Date.now().toString(36)}${clientCounter}`
}

/** Requests not yet resolved, one per id; a later copy (a newer event) replaces the snapshot's. */
function stillOpen<T>(requests: T[], idOf: (request: T) => string, resolved: Set<string>): T[] {
  const byId = new Map<string, T>()
  for (const request of requests) {
    const id = idOf(request)
    if (!resolved.has(id)) byId.set(id, request)
  }
  return [...byId.values()]
}

export function useCodexSession(sessionId: string, { runEnded }: { runEnded: boolean }) {
  const [conversation, setConversation] = useState<ConversationState>(EMPTY_CONVERSATION)
  const [status, setStatus] = useState<CodexStatus | null>(null)
  const [connection, setConnection] = useState<{ label: string; tone: ConnectionTone }>({ label: '연결 중', tone: 'warn' })
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [closed, setClosed] = useState(false)
  const [interruptPending, setInterruptPending] = useState(false)
  const [endPending, setEndPending] = useState(false)
  const [responseRevision, setResponseRevision] = useState(0)

  const generationRef = useRef(0)
  const socketRef = useRef<WebSocket | null>(null)
  const lastSequenceRef = useRef(0)
  const closedRef = useRef(false)
  const attemptRef = useRef(0)
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pendingDraftsRef = useRef(new Map<string, string>())
  const restoreDraftRef = useRef<((text: string) => void) | null>(null)
  const runEndedRef = useRef(runEnded)

  useEffect(() => {
    runEndedRef.current = runEnded
  }, [runEnded])

  useEffect(() => {
    lastSequenceRef.current = conversation.lastSequence
  }, [conversation.lastSequence])

  const connect = useCallback(async function connectToCodex() {
    if (closedRef.current) return
    const generation = generationRef.current
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${scheme}://${location.host}/api/runs/${encodeURIComponent(sessionId)}/codex?after=${lastSequenceRef.current}`
    let token: string
    try { token = await localSessionToken() } catch (failure) {
      if (generation !== generationRef.current || closedRef.current) return
      setConnection({ label: '로컬 연결 확인 필요', tone: 'bad' })
      setErrorMessage(failure instanceof Error ? failure.message : String(failure)); return
    }
    if (closedRef.current || generation !== generationRef.current) return
    const socket = new WebSocket(url, ['aia-local.' + token])
    socketRef.current = socket

    socket.onopen = () => {
      attemptRef.current = 0
      setConnection({ label: '연결됨', tone: 'ok' })
    }
    socket.onmessage = (event) => {
      if (typeof event.data !== 'string') return
      let message: { type?: string; [key: string]: unknown }
      try {
        message = JSON.parse(event.data)
      } catch {
        return
      }
      switch (message.type) {
        case 'history_gap':
          setErrorMessage(typeof message.message === 'string' ? message.message : '이전 대화 일부를 가져올 수 없습니다.')
          break;
        case 'events': {
          const events = (message.events as CodexEvent[]) ?? []
          setConversation((previous) => applyEvents(previous, events))
          if (events.some((item) => item.type === 'turn.completed')) setInterruptPending(false)
          break
        }
        case 'status': {
          const next = message as unknown as CodexStatus
          setStatus(next)
          if (next.status !== 'WORKING') setInterruptPending(false)
          break
        }
        case 'accepted':
          if (typeof message.client_id === 'string') pendingDraftsRef.current.delete(message.client_id)
          break
        case 'error': {
          const text = typeof message.message === 'string' ? message.message : 'Codex 요청이 거부되었습니다.'
          const clientId = typeof message.client_id === 'string' ? message.client_id : null
          const draft = clientId ? pendingDraftsRef.current.get(clientId) : undefined
          if (clientId) pendingDraftsRef.current.delete(clientId)
          if (draft !== undefined) restoreDraftRef.current?.(draft)
          if (message.action === 'interrupt') setInterruptPending(false)
          if (message.action === 'end_session') setEndPending(false)
          if (isInteractiveResponse(message.action)) setResponseRevision((previous) => previous + 1)
          setErrorMessage(text)
          break
        }
        case 'closed':
          closedRef.current = true
          setClosed(true)
          setConnection({ label: '종료됨', tone: 'warn' })
          break
        default:
          break
      }
    }
    socket.onclose = (event) => {
      if (socketRef.current === socket) socketRef.current = null
      // Messages whose acceptance never arrived may not have reached Codex.
      for (const draft of pendingDraftsRef.current.values()) restoreDraftRef.current?.(draft)
      pendingDraftsRef.current.clear()
      if (closedRef.current || runEndedRef.current || generation !== generationRef.current) return
      // Do not replay replies (especially secret values). Re-enable pending
      // cards after reconnect so the user can decide again from fresh status.
      setResponseRevision((previous) => previous + 1)
      if (event.code === 1008) {
        resetLocalSessionToken()
        setConnection({ label: '연결 재확인 필요', tone: 'bad' })
        setErrorMessage('로컬 연결 정보가 바뀌었습니다. 화면을 새로 고치거나 앱을 다시 열어주세요.'); return
      }
      const delay = RECONNECT_DELAYS_MS[Math.min(attemptRef.current, RECONNECT_DELAYS_MS.length - 1)]
      attemptRef.current += 1
      setConnection({ label: '다시 연결하는 중', tone: 'warn' })
      retryTimerRef.current = setTimeout(connectToCodex, delay)
    }
  }, [sessionId])

  useEffect(() => {
    closedRef.current = false
    lastSequenceRef.current = 0
    const resetTimer = window.setTimeout(() => {
      setConversation(EMPTY_CONVERSATION)
      setStatus(null)
      setClosed(false)
      connect()
    }, 0)
    return () => {
      closedRef.current = true
      generationRef.current += 1
      window.clearTimeout(resetTimer)
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current)
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [connect])

  const send = useCallback((message: Record<string, unknown>): boolean => {
    const socket = socketRef.current
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      setErrorMessage('Codex 연결이 끊겨 전송하지 못했습니다. 다시 연결되면 한 번 더 시도하세요.')
      return false
    }
    socket.send(JSON.stringify(message))
    return true
  }, [])

  const sendMessage = useCallback(
    (text: string): boolean => {
      if (!text.trim()) return false
      const clientId = nextClientId()
      pendingDraftsRef.current.set(clientId, text)
      setErrorMessage(null)
      const sent = send({ type: 'user_message', text, client_id: clientId })
      if (!sent) pendingDraftsRef.current.delete(clientId)
      return sent
    },
    [send],
  )

  const interrupt = useCallback(() => {
    if (send({ type: 'interrupt', client_id: nextClientId() })) setInterruptPending(true)
  }, [send])

  const decideApproval = useCallback(
    (approvalId: string, decision: 'accept' | 'acceptForSession' | 'decline') => {
      setErrorMessage(null)
      return send({ type: 'approval_decision', approval_id: approvalId, decision, client_id: nextClientId() })
    },
    [send],
  )

  /** Empty answers skip the question; secret answers are only sent, never stored. */
  const answerQuestion = useCallback(
    (questionId: string, answers: Record<string, string[]>) => {
      setErrorMessage(null)
      return send({ type: 'question_answer', question_id: questionId, answers, client_id: nextClientId() })
    },
    [send],
  )

  const respondElicitation = useCallback(
    (elicitationId: string, action: 'accept' | 'decline' | 'cancel', content?: Record<string, unknown>) => {
      setErrorMessage(null)
      return send({ type: 'elicitation_response', elicitation_id: elicitationId, action, content, client_id: nextClientId() })
    },
    [send],
  )

  const decidePermissions = useCallback(
    (permissionsId: string, decision: 'turn' | 'session' | 'decline') => {
      setErrorMessage(null)
      return send({ type: 'permissions_decision', permissions_id: permissionsId, decision, client_id: nextClientId() })
    },
    [send],
  )

  /** Slash commands that reach Codex: compact, review, goal. */
  const runCommand = useCallback(
    (command: 'compact' | 'review' | 'goal', argument?: string) => {
      setErrorMessage(null)
      return send({ type: 'command', command, argument, client_id: nextClientId() })
    },
    [send],
  )

  /** Model and effort for the next turns; the server forwards nothing else. */
  const setTurnSettings = useCallback(
    (model: string | null, effort: string | null) => {
      setErrorMessage(null)
      return send({ type: 'turn_settings', model, effort, client_id: nextClientId() })
    },
    [send],
  )

  const endSession = useCallback(() => {
    if (send({ type: 'end_session', client_id: nextClientId() })) setEndPending(true)
  }, [send])

  const onRestoreDraft = useCallback((handler: (text: string) => void) => {
    restoreDraftRef.current = handler
  }, [])

  const statusName: CodexStatusName = status?.status ?? 'NOT_ATTACHED'
  const connected = connection.tone === 'ok'
  const ended = closed || runEnded || TERMINAL_STATUSES.has(statusName)
  // Pending = requested (by the server snapshot or a newer event) and not
  // yet resolved by a later event. One pass over the conversation finds what
  // was resolved.
  const resolved = new Set<string>()
  const answered = new Set<string>()
  const settled = new Set<string>()
  const decided = new Set<string>()
  for (const item of conversation.items) {
    if (item.kind === 'approval' && item.decision) resolved.add(item.request.approval_id)
    else if (item.kind === 'question' && item.outcome) answered.add(item.request.question_id)
    else if (item.kind === 'elicitation' && item.action) settled.add(item.request.elicitation_id)
    else if (item.kind === 'permissions' && item.decision) decided.add(item.request.permissions_id)
  }
  const pendingApprovals = stillOpen([...(status?.pending_approvals ?? []), ...conversation.pendingApprovals], item => item.approval_id, resolved)
  const pendingQuestions = stillOpen([...(status?.pending_questions ?? []), ...conversation.pendingQuestions], item => item.question_id, answered)
  const pendingElicitations = stillOpen([...(status?.pending_elicitations ?? []), ...conversation.pendingElicitations], item => item.elicitation_id, settled)
  const pendingPermissions = stillOpen([...(status?.pending_permissions ?? []), ...conversation.pendingPermissions], item => item.permissions_id, decided)
  // Events carry the newest values; the snapshot covers a viewer that joined late.
  const turnSettings = conversation.turnSettings ?? status?.turn_settings ?? { model: null, effort: null }
  const plan = conversation.plan ?? status?.plan ?? null
  const usage: Usage = {
    limits: conversation.usage.limits ?? status?.usage?.limits ?? null,
    tokens: conversation.usage.tokens ?? status?.usage?.tokens ?? null,
  }

  return {
    conversation,
    status,
    statusName,
    connection,
    connected,
    ended,
    canSend: connected && !ended && (statusName === 'READY' || statusName === 'WORKING'),
    working: statusName === 'WORKING',
    external: statusName === 'EXTERNAL',
    ownerPid: status?.owner_pid ?? null,
    endRequested: Boolean(status?.end_requested),
    pendingApprovals,
    pendingQuestions,
    pendingElicitations,
    pendingPermissions,
    responseRevision,
    usage,
    turnSettings,
    plan,
    errorMessage,
    interruptPending,
    endPending,
    sendMessage,
    interrupt,
    decideApproval,
    answerQuestion,
    respondElicitation,
    decidePermissions,
    setTurnSettings,
    runCommand,
    endSession,
    onRestoreDraft,
    dismissError: () => setErrorMessage(null),
  }
}
