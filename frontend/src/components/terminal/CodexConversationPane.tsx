import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useShellStore } from '../../state/shellStore'
import type { ApprovalRequest, TranscriptItem } from './codexConversation'
import { Markdown } from './Markdown'
import { useCodexSession, type CodexStatusName } from './useCodexSession'

// Agent CLI surface for runs launched with launch_mode "codex_app_server".
// Every line here is rendered from a structured Codex event; the input stays
// usable whenever the conversation is READY or WORKING.

const SILENCE_NOTICE_SECONDS = 15

function hookLine(item: Extract<TranscriptItem, { kind: 'hook' }>): { text: string; tone: string } {
  // Codex marks a Hook run cut short by a user interrupt as "stopped";
  // "blocked" means the AIA Hook itself asked Codex not to run the tool.
  if (item.status === 'stopped') return { text: 'AIA Hook · 요청 중지로 확인이 취소되었습니다', tone: 'warn' }
  if (item.status === 'blocked') {
    // A Hook deny is not by itself proof that execution was blocked; the
    // audit record carries the confirmed outcome.
    return { text: 'AIA Hook이 실행 중단을 요청했습니다 · 실제 결과는 감사 기록에서 확인하세요', tone: 'bad' }
  }
  if (item.status === 'failed') return { text: 'AIA Hook 실행 오류', tone: 'bad' }
  const done = item.phase === 'completed'
  if (item.eventName === 'preToolUse') return { text: done ? 'AIA Hook · 실행 전 확인 완료' : 'AIA Hook · 실행 전 확인 중…', tone: 'hook' }
  if (item.eventName === 'postToolUse') return { text: done ? 'AIA Hook · 실행 결과 기록 완료' : 'AIA Hook · 실행 결과 기록 중…', tone: 'hook' }
  return { text: `AIA Hook · ${item.eventName || 'event'}`, tone: 'hook' }
}

function commandStatus(item: Extract<TranscriptItem, { kind: 'command' }>): { label: string; tone: string } {
  if (item.status === 'inProgress') return { label: '실행 중', tone: 'warn' }
  if (item.status === 'declined') return { label: '거절됨', tone: 'warn' }
  if (item.status === 'failed') return { label: '실패', tone: 'bad' }
  if (item.exitCode !== null && item.exitCode !== 0) return { label: `종료 코드 ${item.exitCode}`, tone: 'bad' }
  return { label: '완료', tone: 'ok' }
}

const DECISION_LABELS: Record<string, string> = {
  accept: '이번만 허용됨',
  acceptForSession: '세션 동안 허용됨',
  decline: '거절됨',
  cancel: '취소됨',
  timeout: '응답 시간이 지나 거절됨',
  resolved_by_codex: 'Codex가 요청을 거둠',
}

function approvalTitle(request: ApprovalRequest): string {
  if (request.kind === 'aia_tool') return `보호 범위 밖 도구 ${request.tool ?? ''} 사용 요청`
  return request.kind === 'file_change' ? '파일 변경 승인 요청' : '명령 실행 승인 요청'
}

function TranscriptRow({ item }: { item: TranscriptItem }) {
  switch (item.kind) {
    case 'user':
      return (
        <div className="codex-row codex-user">
          <span className="codex-prompt">codex ›</span>
          <span className="codex-text">{item.text}</span>
        </div>
      )
    case 'agent':
      return (
        <div className="codex-row codex-agent">
          <Markdown text={item.text} />
          {item.streaming && <span className="codex-caret" aria-hidden="true" />}
        </div>
      )
    case 'reasoning':
      return item.done && !item.text ? null : (
        <div className="codex-row codex-reasoning">{item.done ? item.text : `생각 중… ${item.text}`}</div>
      )
    case 'command': {
      const state = commandStatus(item)
      return (
        <div className="codex-command">
          <div className="codex-command-head">
            <span className="codex-command-line">$ {item.command}</span>
            <span className={`badge is-${state.tone}`}>{state.label}</span>
          </div>
          {item.output && <pre className="codex-command-output">{item.output}</pre>}
        </div>
      )
    }
    case 'file_change':
      return (
        <div className="codex-row codex-meta">
          파일 변경 · {item.paths.join(', ') || '(경로 없음)'} · {item.status === 'inProgress' ? '진행 중' : item.status === 'completed' ? '완료' : item.status ?? ''}
        </div>
      )
    case 'tool':
      return <div className="codex-row codex-meta">도구 {item.tool} · {item.status ?? '실행 중'}</div>
    case 'hook': {
      const line = hookLine(item)
      return <div className={`codex-row codex-hook is-${line.tone}`}>{line.text}</div>
    }
    case 'approval':
      return (
        <div className="codex-row codex-hook is-warn">
          {approvalTitle(item.request)}
          {item.decision ? ` · ${DECISION_LABELS[item.decision] ?? item.decision}` : ' · 결정 대기 중'}
        </div>
      )
    case 'notice':
      return <div className={`codex-row codex-notice is-${item.tone}`}>{item.text}</div>
  }
}

function ApprovalDialog({
  request,
  onDecide,
}: {
  request: ApprovalRequest
  onDecide: (decision: 'accept' | 'acceptForSession' | 'decline') => void
}) {
  const isFileChange = request.kind === 'file_change'
  const isAiaTool = request.kind === 'aia_tool'
  // AIA reviews auto-refuse when the window closes (kept inside Codex's Hook
  // timeout); count down from when this dialog first appeared.
  const [openedAt] = useState(() => Date.now())
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!request.timeout_seconds) return
    const timer = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(timer)
  }, [request.timeout_seconds])
  const remaining = request.timeout_seconds
    ? Math.max(0, Math.ceil(request.timeout_seconds - (now - openedAt) / 1000))
    : null
  const title = isAiaTool
    ? `Codex가 AIA 보호 범위 밖 도구(${request.tool ?? '알 수 없음'})를 쓰려고 합니다`
    : isFileChange
      ? 'Codex가 파일 변경 승인을 요청합니다'
      : 'Codex가 명령 실행 승인을 요청합니다'
  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="Codex 승인 요청">
      <div className="modal-panel" style={{ maxWidth: 520 }}>
        <div className="modal-header">
          <h2>{title}</h2>
          {remaining !== null && <span className="badge is-warn">{remaining}초 후 자동 거절</span>}
        </div>
        <div className="modal-body">
          {isFileChange ? (
            <pre className="codex-approval-code">{request.paths.join('\n') || '(경로 정보 없음)'}</pre>
          ) : (
            <pre className="codex-approval-code">{request.command || '(입력 정보 없음)'}</pre>
          )}
          {request.cwd && <p style={{ fontSize: 12 }}>작업 위치 · {request.cwd}</p>}
          {request.reason && <p style={{ fontSize: 12 }}>사유 · {request.reason}</p>}
          <div className="policy-view-notice" style={{ marginTop: 12, marginBottom: 0 }}>
            {isAiaTool
              ? '허용하면 이 도구는 AIA 정책 판정 없이 실행되고, 결과에는 사용자가 허용한 보호 범위 밖 실행으로 기록됩니다. 파일·프로세스 변화는 계속 센서로 관찰합니다.'
              : '이 승인은 Codex 샌드박스의 권한 요청에 대한 답입니다. 승인해도 AIA Hook 정책 검사와 센서 기록은 그대로 적용됩니다.'}
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
            <button type="button" className="icon-button-text" onClick={() => onDecide('decline')}>
              거절
            </button>
            <button type="button" className="icon-button-text" onClick={() => onDecide('acceptForSession')}>
              이 세션 동안 허용
            </button>
            <button type="button" className="cta-button" style={{ width: 'auto', padding: '8px 16px' }} onClick={() => onDecide('accept')}>
              이번만 허용
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function activityLabel(statusName: CodexStatusName, approvals: number, elapsed: number, silent: number, ownerPid: number | null): string {
  if (approvals > 0) return '승인 결정을 기다리는 중'
  switch (statusName) {
    case 'EXTERNAL':
      return `다른 AIA 창${ownerPid ? `(PID ${ownerPid})` : ''}에서 진행 중`
    case 'READY':
      return '입력 대기 중'
    case 'WORKING':
      return `Codex가 작업 중 · ${elapsed}s${silent >= SILENCE_NOTICE_SECONDS ? ' · 모델 응답 대기 중' : ''}`
    case 'CLOSING':
      return '세션을 종료하는 중'
    case 'EXITED':
      return '세션 종료됨'
    case 'FAILED':
      return 'Codex 연결 실패'
    default:
      return 'Codex 연결을 준비하는 중'
  }
}

export function CodexConversationPane({ runId, runEnded }: { runId: string; runEnded: boolean }) {
  const session = useCodexSession(runId, { runEnded })
  const [draft, setDraft] = useState('')
  // The deferred submit after an IME composition runs from an older render;
  // read the latest draft through a ref so the final syllable is included.
  const draftRef = useRef(draft)
  draftRef.current = draft
  const composingRef = useRef(false)
  const submitAfterCompositionRef = useRef(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickToBottomRef = useRef(true)
  const [workingSince, setWorkingSince] = useState(0)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    session.onRestoreDraft((text) => setDraft((current) => (current ? current : text)))
  }, [session.onRestoreDraft])

  useEffect(() => {
    if (session.working) setWorkingSince((since) => since || Date.now())
    else setWorkingSince(0)
  }, [session.working])

  useEffect(() => {
    if (!session.working) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [session.working])

  useLayoutEffect(() => {
    const node = scrollRef.current
    if (node && stickToBottomRef.current) node.scrollTop = node.scrollHeight
  }, [session.conversation.items])

  // GuardianHero (dashboard) reflects live Codex activity through the shell
  // store; map the structured state onto the same signal it already reads.
  const { reportCodexActivity, clearCodexActivity } = useShellStore()
  const approvalWaiting = session.pendingApprovals.length > 0
  useEffect(() => {
    const mode = session.ended ? 'STOPPED' : approvalWaiting ? 'ACTION' : session.working ? 'WORKING' : session.statusName === 'READY' ? 'WAITING' : 'STARTING'
    reportCodexActivity({ runId, mode, terminalAction: approvalWaiting ? 'COMMAND_APPROVAL' : null })
  }, [runId, session.ended, session.working, session.statusName, approvalWaiting, reportCodexActivity])
  useEffect(() => () => clearCodexActivity(runId), [runId, clearCodexActivity])

  function submit() {
    const value = draftRef.current
    if (!session.canSend || !value.trim()) return
    if (session.sendMessage(value)) setDraft('')
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && event.nativeEvent.isComposing && !event.shiftKey) {
      submitAfterCompositionRef.current = true
      return
    }
    if (event.nativeEvent.isComposing || composingRef.current) return
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  const elapsed = workingSince ? Math.max(0, Math.floor((now - workingSince) / 1000)) : 0
  const lastEventAt = session.conversation.lastEventAt
  const silent = session.working && lastEventAt ? Math.max(0, Math.floor((now - lastEventAt) / 1000)) : 0
  const firstApproval = session.pendingApprovals[0]
  const error = session.status?.error

  return (
    <div className="terminal-pane">
      <div className="terminal-toolbar">
        <span className={`badge is-${session.connection.tone}`}>{session.connection.label}</span>
        <span className="terminal-activity-label">
          {activityLabel(session.statusName, session.pendingApprovals.length, elapsed, silent, session.ownerPid)}
        </span>
        <div className="tab-strip-spacer" />
        {session.status?.pid ? <span className="terminal-pid">PID {session.status.pid}</span> : null}
        {session.working && (
          <button type="button" className="icon-button-text" disabled={session.interruptPending} onClick={session.interrupt}>
            {session.interruptPending ? '중지 요청 전송됨' : '현재 요청 중지'}
          </button>
        )}
        {!session.ended && (
          <button
            type="button"
            className="icon-button-text"
            disabled={session.endPending || session.endRequested || !session.connected}
            onClick={() => {
              const question = session.external
                ? '이 보호 실행은 다른 AIA 창에서 진행 중입니다. 그 창에 세션 종료를 요청할까요?'
                : 'Codex 세션을 종료하고 보호 실행 결과를 확정할까요?'
              if (window.confirm(question)) session.endSession()
            }}
          >
            {session.endRequested ? '종료 요청됨' : session.endPending ? '종료하는 중…' : '세션 종료'}
          </button>
        )}
      </div>

      <div
        className="codex-transcript"
        ref={scrollRef}
        aria-live="polite"
        aria-busy={session.working}
        onScroll={(event) => {
          const node = event.currentTarget
          stickToBottomRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80
        }}
      >
        {session.external ? (
          <div className="codex-row codex-notice is-warn">
            {`이 보호 실행은 다른 AIA 창${session.ownerPid ? `(PID ${session.ownerPid})` : ''}에서 진행 중입니다. Codex 대화는 그 창에서만 이어갈 수 있습니다.\n`}
            {session.endRequested
              ? '세션 종료를 요청했습니다. 그 창에서 Codex를 종료하고 결과를 확정하면 여기에도 표시됩니다.'
              : '작업 표시줄에서 그 AIA 창을 열어 계속하거나, 여기서 "세션 종료"를 눌러 종료를 요청할 수 있습니다.'}
          </div>
        ) : (
          session.conversation.items.length === 0 && (
            <div className="codex-row codex-notice is-info">
              {session.statusName === 'READY' ? 'Codex가 준비되었습니다. 아래에 작업을 입력하세요.' : 'Codex 세션을 준비하는 중입니다…'}
            </div>
          )
        )}
        {session.conversation.items.map((item) => (
          <TranscriptRow key={item.key} item={item} />
        ))}
      </div>

      {(session.errorMessage || error) && (
        <div className="terminal-error" role="alert">
          <span>{session.errorMessage ?? `Codex 연결 오류 · ${error}`}</span>
          {session.errorMessage && (
            <button type="button" className="icon-button" onClick={session.dismissError} title="닫기">
              ×
            </button>
          )}
        </div>
      )}

      <form
        className="terminal-input-row"
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        <textarea
          value={draft}
          disabled={session.ended}
          placeholder={
            session.ended
              ? 'Codex 세션이 종료되었습니다.'
              : session.working
                ? '진행 중인 작업에 추가 지시를 보낼 수 있습니다 · Enter로 전송'
                : '여기에 입력하세요 · 한글 입력 지원 · Enter로 전송 · Shift+Enter 줄바꿈'
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
              setTimeout(submit, 0)
            }
          }}
        />
        <button type="submit" className="cta-button" disabled={!session.canSend || !draft.trim()}>
          {session.working ? '추가 지시' : '전송'}
        </button>
      </form>

      {firstApproval && !session.ended && (
        <ApprovalDialog
          key={firstApproval.approval_id}
          request={firstApproval}
          onDecide={(decision) => session.decideApproval(firstApproval.approval_id, decision)}
        />
      )}
    </div>
  )
}
