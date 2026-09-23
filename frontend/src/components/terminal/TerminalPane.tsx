import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useRunStatus } from '../../hooks/useRunStatus'
import { useTerminalSession } from './useTerminalSession'
import { useShellStore } from '../../state/shellStore'

const CONTROL_KEYS: Record<string, string> = {
  Backspace: '\x7f',
  Tab: '\t',
  ArrowUp: '\x1b[A',
  ArrowDown: '\x1b[B',
  ArrowRight: '\x1b[C',
  ArrowLeft: '\x1b[D',
  Escape: '\x1b',
}

const RUN_ENDED_STATUSES = new Set(['COMPLETED', 'ABORTED', 'FAILED'])

export function TerminalPane({ runId, isFocused = true }: { runId: string; isFocused?: boolean }) {
  const terminalOutputRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const [draft, setDraft] = useState('')
  const composingRef = useRef(false)
  const submitAfterCompositionRef = useRef(false)

  // Only the focused tab's run status polls at 1s; a backgrounded tab's
  // terminal WebSocket (owned by useTerminalSession below) stays connected
  // regardless, so output keeps arriving even while its status poll is
  // paused -- this bounds backend load to one 1s poll per visible tab.
  const { data: status } = useRunStatus(runId, { enabled: isFocused })
  const runEnded = RUN_ENDED_STATUSES.has(String(status?.session?.status))
  const protectionDisconnected = Boolean(status?.runtime_reconciliation?.orphaned)

  const session = useTerminalSession({
    sessionId: runId,
    terminalOutputRef,
    runEnded,
    protectionDisconnected,
  })

  // Reported up to shellStore so GuardianHero (mounted in the dashboard
  // view, not a descendant of TerminalPane) can reflect live Codex
  // activity without this hook's DOM-ref-coupled internals ever moving.
  const { reportTerminalActivity, clearTerminalActivity } = useShellStore()
  useEffect(() => {
    reportTerminalActivity({ runId, mode: session.activity.mode, terminalAction: session.terminalAction })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, session.activity.mode, session.terminalAction])
  useEffect(() => {
    return () => clearTerminalActivity(runId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])

  function submitLine() {
    const value = draft
    session.sendLine(value)
    // TRUST_DIRECTORY / COMMAND_APPROVAL and normal submission all clear
    // the draft synchronously on the happy path; on a rejected send the
    // hook surfaces errorMessage instead, so clearing here matches the
    // original's clear-then-report-error ordering closely enough for a
    // textarea (no separate "accepted" echo to gate on client-side).
    setDraft('')
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && event.nativeEvent.isComposing && !event.shiftKey) {
      submitAfterCompositionRef.current = true
      return
    }
    if (event.nativeEvent.isComposing || composingRef.current) return
    if (event.key === 'Enter' && event.shiftKey) return
    if (event.ctrlKey && event.key.length === 1) {
      event.preventDefault()
      session.sendRaw(String.fromCharCode(event.key.toUpperCase().charCodeAt(0) - 64))
      return
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      submitLine()
      return
    }
    const control = CONTROL_KEYS[event.key]
    if (control && !draft) {
      event.preventDefault()
      session.sendRaw(control)
    }
  }

  const activityBusy = ['SUBMITTING', 'WORKING', 'OUTPUTTING', 'STOPPING'].includes(session.activity.mode)
  const disabled = !session.terminalReady
  const sendDisabled = !session.terminalReady || (session.awaitingResponse && !session.commandApprovalRequired)

  return (
    <div className="terminal-pane">
      <div className="terminal-toolbar">
        <span className={`badge is-${session.connection.tone}`}>{session.connection.label}</span>
        {session.activity.mode !== 'IDLE' && session.activity.mode !== 'STOPPED' && (
          <span className="terminal-activity-label">
            {session.activity.label}
            {activityBusy && session.activity.elapsedSeconds > 0 ? ` · ${session.activity.elapsedSeconds}s` : ''}
          </span>
        )}
        <div className="tab-strip-spacer" />
        {session.pid ? <span className="terminal-pid">PID {session.pid}</span> : null}
        {session.interruptVisible && (
          <button
            type="button"
            className={session.heartbeat.visible ? 'icon-button-text is-urgent' : 'icon-button-text'}
            disabled={session.interruptPending}
            onClick={session.interrupt}
          >
            {session.interruptPending ? '중지 요청 전송됨' : '현재 요청 중지'}
          </button>
        )}
        {session.reconnectVisible && (
          <button type="button" className="icon-button-text" disabled={session.reconnectPending} onClick={session.reconnect}>
            {session.reconnectPending ? '연결 중…' : '터미널 다시 연결'}
          </button>
        )}
      </div>

      <div className="terminal-output" ref={terminalOutputRef} aria-busy={activityBusy} onClick={() => inputRef.current?.focus()} />

      {session.errorMessage && (
        <div className="terminal-error" role="alert">
          <span>{session.errorMessage}</span>
          <button type="button" className="icon-button" onClick={session.dismissError} title="닫기">
            ×
          </button>
        </div>
      )}

      {session.terminalAction && (
        <div className="terminal-action-banner">
          <span>{session.trustRequired ? 'Codex가 Workspace 신뢰 확인을 기다리고 있습니다.' : 'Codex가 명령 실행 승인을 기다리고 있습니다.'}</span>
          <button type="button" className="cta-button" onClick={session.continueAction}>
            {session.trustRequired ? '신뢰하고 계속' : 'y로 승인'}
          </button>
        </div>
      )}

      {session.heartbeat.visible && (
        <div className="terminal-heartbeat-banner" role="status">
          <span>Codex 응답을 기다리는 중입니다 · {session.heartbeat.seconds}초 경과 · 정상적으로 진행 중일 수 있습니다.</span>
        </div>
      )}

      <form
        className="terminal-input-row"
        onSubmit={(event) => {
          event.preventDefault()
          submitLine()
        }}
      >
        <textarea
          ref={inputRef}
          value={draft}
          disabled={disabled}
          placeholder={
            protectionDisconnected
              ? 'AIA 보호 연결이 끊겨 작업창을 사용할 수 없습니다.'
              : session.commandApprovalRequired
                ? 'y 또는 1·2·3 입력 · Enter로 승인'
                : session.trustRequired
                  ? '먼저 "신뢰하고 계속"을 눌러주세요.'
                  : !session.composerReady
                    ? 'Codex 작업창이 준비되는 중입니다…'
                    : '여기에 입력하세요 · 한글 입력 지원 · Enter로 전송'
          }
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          onCompositionStart={() => {
            composingRef.current = true
          }}
          onCompositionEnd={() => {
            composingRef.current = false
            if (submitAfterCompositionRef.current) {
              submitAfterCompositionRef.current = false
              setTimeout(submitLine, 0)
            }
          }}
        />
        <button type="submit" className="cta-button" disabled={sendDisabled}>
          {session.commandApprovalRequired
            ? '승인 전송'
            : session.awaitingResponse
              ? session.activity.mode === 'OUTPUTTING'
                ? '응답 수신 중'
                : '응답 대기 중'
              : '전송'}
        </button>
      </form>
    </div>
  )
}
