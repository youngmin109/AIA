import { Button } from '../common/Button'
import { Badge, type BadgeTone } from '../common/Badge'
import { useDialog } from '../common/useDialog'
import { Icon } from '../common/Icon'
import { RingTimer } from '../common/Charts'
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
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

function commandStatus(item: Extract<TranscriptItem, { kind: 'command' }>): { label: string; tone: BadgeTone } {
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
        <div className="chat-row is-user">
          <span className="chat-bubble">{item.text}</span>
        </div>
      )
    case 'agent':
      return (
        <div className="chat-row is-agent">
          <Markdown text={item.text} />
          {item.streaming && <span className="codex-caret" aria-hidden="true" />}
        </div>
      )
    case 'reasoning':
      return item.done && !item.text ? null : (
        <div className="chat-reasoning">{item.done ? item.text : `Codex 진행 요약… ${item.text}`}</div>
      )
    case 'command': {
      const state = commandStatus(item)
      const lines = item.output ? item.output.split('\n').length : 0
      return (
        <div className="chat-card is-command">
          <div className="chat-card-head">
            <span className="glossy-icon is-sm is-hook chat-dollar" aria-hidden="true">$</span>
            <code className="chat-command">{item.command}</code>
            <Badge tone={state.tone}>{state.label}</Badge>
          </div>
          {item.output && (lines > 6
            ? <details className="chat-output"><summary>출력 {lines}줄 보기</summary><pre>{item.output}</pre></details>
            : <pre className="chat-output">{item.output}</pre>)}
        </div>
      )
    }
    case 'file_change':
      return (
        <div className="chat-card is-file">
          <div className="chat-card-head">
            <span className="glossy-icon is-sm is-file" aria-hidden="true"><Icon name="file" size={15} /></span>
            <strong>파일 변경 {item.paths.length}개</strong>
            <Badge tone={item.status === 'completed' ? 'ok' : item.status === 'inProgress' ? 'warn' : 'neutral'}>
              {item.status === 'inProgress' ? '진행 중' : item.status === 'completed' ? '완료' : item.status === 'declined' ? '거절됨' : item.status ?? '확인 중'}
            </Badge>
          </div>
          <ul className="chat-paths">{item.paths.length ? item.paths.map(path => <li key={path} className="mono">{path}</li>) : <li>(경로 없음)</li>}</ul>
        </div>
      )
    case 'tool':
      return <div className="chat-meta">도구 {item.tool} · {item.status ?? '실행 중'}</div>
    case 'hook': {
      const line = hookLine(item)
      return <div className={`chat-hook is-${line.tone}`}>{line.text}</div>
    }
    case 'approval':
      return (
        <div className={`chat-hook ${item.decision ? 'is-hook' : 'is-warn'}`}>
          {approvalTitle(item.request)}
          {item.decision ? ` · ${DECISION_LABELS[item.decision] ?? item.decision}` : ' · 결정 대기 중'}
        </div>
      )
    case 'notice':
      return <div className={`chat-notice is-${item.tone}`}>{item.text}</div>
  }
}

function ApprovalDialog({
  request,
  onDecide,
  failure,
  connected,
}: {
  request: ApprovalRequest
  failure: string | null
  connected: boolean
  onDecide: (decision: 'accept' | 'acceptForSession' | 'decline') => boolean
}) {
  const isFileChange = request.kind === 'file_change'
  const isAiaTool = request.kind === 'aia_tool'
  // AIA reviews auto-refuse when the window closes (kept inside Codex's Hook
  // timeout); use the server deadline so reconnects never extend it.
  // Escape keeps the request open: only the explicit buttons answer Codex.
  const ref = useDialog(true, () => {})
  const [pending, setPending] = useState(false)
  useEffect(() => {
    if (!failure && connected) return
    const timer = window.setTimeout(() => setPending(false), 0)
    return () => window.clearTimeout(timer)
  }, [failure, connected])
  const [openedAt] = useState(() => Date.now())
  function decide(value: 'accept' | 'acceptForSession' | 'decline') { setPending(onDecide(value)) }
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!request.timeout_seconds) return
    const timer = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(timer)
  }, [request.timeout_seconds])
  // Only AIA tool reviews carry a deadline; Codex sandbox approvals wait for the user.
  const remaining = request.timeout_seconds
    ? Math.max(0, Math.ceil(((request.expires_at ? Date.parse(request.expires_at) : openedAt + request.timeout_seconds * 1000) - now) / 1000))
    : null
  const title = isAiaTool
    ? `보호 범위 밖 도구(${request.tool ?? '알 수 없음'}) 사용을 요청해요`
    : isFileChange
      ? 'Codex가 파일 변경 승인을 요청해요'
      : 'Codex가 실행 승인을 요청해요'
  return (
    <>
      <div className="glass-scrim" aria-hidden="true" />
      <div className="glass-dialog-layer">
        <div ref={ref} tabIndex={-1} className="glass-dialog lens-dialog approval-dialog" role="dialog" aria-modal="true" aria-labelledby="approval-title">
          <div className="approval-head">
            <RingTimer remaining={remaining} total={request.timeout_seconds ?? 0} label={remaining === null ? '응답을 기다리는 중' : `남은 시간 ${remaining}초`} />
            <div>
              <h2 id="approval-title">{title}</h2>
              <p>{remaining === null ? '답할 때까지 Codex가 기다리고 있어요' : `${remaining}초 안에 답하지 않으면 거절돼요`}</p>
            </div>
          </div>
          <code className="code-line">{isFileChange ? (request.paths.join('\n') || '(경로 정보 없음)') : `$ ${request.command || '(입력 정보 없음)'}`}</code>
          {(request.cwd || request.reason) && (
            <dl className="approval-facts">
              {request.cwd && <><dt>작업 위치</dt><dd>{request.cwd}</dd></>}
              {request.reason && <><dt>이유</dt><dd>{request.reason}</dd></>}
            </dl>
          )}
          <p className="faint-note approval-note">
            <Icon name="shieldPlain" size={16} />
            {isAiaTool
              ? '허용하면 이 도구는 AIA 정책 판정 없이 실행되고, 결과에는 사용자가 허용한 보호 범위 밖 실행으로 기록돼요. 파일·프로세스 변화는 계속 관찰해요.'
              : '허용해도 AIA 정책 검사와 기록은 그대로 적용돼요.'}
          </p>
          <div className="dialog-actions">
            <Button variant="secondary" className="is-danger" disabled={pending || remaining === 0} onClick={() => decide('decline')}>거절</Button>
            <Button variant="secondary" disabled={pending || remaining === 0} onClick={() => decide('acceptForSession')}>이 세션 동안 허용</Button>
            <Button variant="cta" disabled={pending || remaining === 0} onClick={() => decide('accept')}>이번만 허용</Button>
          </div>
        </div>
      </div>
    </>
  )
}

function EndSessionDialog({ external, onConfirm, onCancel }: { external: boolean; onConfirm: () => void; onCancel: () => void }) {
  const ref = useDialog(true, onCancel)
  return (
    <>
      <div className="glass-scrim" aria-hidden="true" onClick={onCancel} />
      <div className="glass-dialog-layer">
        <div ref={ref} tabIndex={-1} className="glass-dialog" role="alertdialog" aria-modal="true" aria-labelledby="end-title">
          <h2 id="end-title" className="dialog-title">작업을 끝낼까요?</h2>
          <p className="muted dialog-text">
            {external
              ? '이 보호 실행은 다른 AIA 창에서 진행 중이에요. 그 창에 세션 종료를 요청해요.'
              : 'Codex 세션을 종료하고 보호 실행 결과를 확정해요. 끝나면 결과 요약을 보여드려요.'}
          </p>
          <div className="dialog-actions">
            <Button variant="secondary" onClick={onCancel}>계속 작업</Button>
            <Button variant="cta" onClick={onConfirm}>작업 종료</Button>
          </div>
        </div>
      </div>
    </>
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

export function CodexConversationPane({ runId, runEnded, context }: { runId: string; runEnded: boolean; context?: ReactNode }) {
  const session = useCodexSession(runId, { runEnded })
  const [draft, setDraft] = useState('')
  // The deferred submit after an IME composition runs from an older render;
  // read the latest draft through a ref so the final syllable is included.
  const draftRef = useRef(draft)
  const composingRef = useRef(false)
  const submitAfterCompositionRef = useRef(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickToBottomRef = useRef(true)
  const [workingSince, setWorkingSince] = useState(0)
  const [now, setNow] = useState(() => Date.now())

  const { onRestoreDraft } = session
  useEffect(() => {
    onRestoreDraft((text) => setDraft((current) => (current ? current : text)))
  }, [onRestoreDraft])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (session.working) setWorkingSince((since) => since || Date.now())
      else setWorkingSince(0)
    }, 0)
    return () => window.clearTimeout(timer)
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

  // The home view reflects live Codex activity through the shell store.
  const { reportCodexActivity, clearCodexActivity, endRequest } = useShellStore()
  const approvalWaiting = session.pendingApprovals.length > 0
  useEffect(() => {
    const mode = session.ended ? 'STOPPED' : approvalWaiting ? 'ACTION' : session.working ? 'WORKING' : session.statusName === 'READY' ? 'WAITING' : 'STARTING'
    reportCodexActivity({ runId, mode, terminalAction: approvalWaiting ? 'COMMAND_APPROVAL' : null })
  }, [runId, session.ended, session.working, session.statusName, approvalWaiting, reportCodexActivity])
  useEffect(() => () => clearCodexActivity(runId), [runId, clearCodexActivity])

  // The home "종료" button bumps endRequest; answer it with the same confirmation.
  const [handledEndRequest, setHandledEndRequest] = useState(endRequest)
  const [askedToEnd, setAskedToEnd] = useState(false)
  const endDialogOpen = !session.ended && (askedToEnd || endRequest !== handledEndRequest)
  function closeEndDialog() {
    setAskedToEnd(false)
    setHandledEndRequest(endRequest)
  }
  function confirmEnd() {
    closeEndDialog()
    session.endSession()
  }

  function submit() {
    const value = draftRef.current
    if (!session.canSend || !value.trim()) return
    if (session.sendMessage(value)) {
      draftRef.current = ''
      setDraft('')
    }
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
  const dotTone = session.ended ? 'neutral' : approvalWaiting ? 'warn' : session.connection.tone === 'bad' ? 'bad' : 'ok'

  return (
    <div className="chat">
      <header className="chat-head">
        <span className={`status-dot is-${dotTone}`} aria-hidden="true" />
        <span className="chat-activity">{activityLabel(session.statusName, session.pendingApprovals.length, elapsed, silent, session.ownerPid)}</span>
        <Badge tone={session.connection.tone}>{session.connection.label}</Badge>
        {context}
        <span className="chat-head-spacer" />
        {session.status?.pid ? <span className="chat-pid">PID {session.status.pid}</span> : null}
        {session.working && (
          <Button variant="secondary" className="is-compact" disabled={session.interruptPending} onClick={session.interrupt}>
            {session.interruptPending ? '중지 요청 전송됨' : '현재 요청 중지'}
          </Button>
        )}
        {!session.ended && (
          <Button variant="secondary" className="is-compact" disabled={session.endPending || session.endRequested || !session.connected} onClick={() => setAskedToEnd(true)}>
            {session.endRequested ? '종료 요청됨' : session.endPending ? '종료하는 중…' : '작업 종료'}
          </Button>
        )}
      </header>

      <div
        className="chat-transcript"
        ref={scrollRef}
        aria-live="polite"
        aria-busy={session.working}
        onScroll={(event) => {
          const node = event.currentTarget
          stickToBottomRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80
        }}
      >
        {session.external ? (
          <div className="chat-notice is-warn">
            {`이 보호 실행은 다른 AIA 창${session.ownerPid ? `(PID ${session.ownerPid})` : ''}에서 진행 중이에요. Codex 대화는 그 창에서만 이어갈 수 있어요.\n`}
            {session.endRequested
              ? '세션 종료를 요청했어요. 그 창에서 Codex를 종료하고 결과를 확정하면 여기에도 표시돼요.'
              : '작업 표시줄에서 그 AIA 창을 열어 계속하거나, "작업 종료"로 종료를 요청할 수 있어요.'}
          </div>
        ) : (
          session.conversation.items.length === 0 && (
            <div className="chat-empty">
              <strong>{session.statusName === 'READY' ? 'Codex가 준비됐어요' : 'Codex 세션을 준비하고 있어요…'}</strong>
              <span>{session.statusName === 'READY' ? '아래 입력창에 하고 싶은 작업을 적어 보세요.' : '잠시만 기다려 주세요.'}</span>
            </div>
          )
        )}
        {session.conversation.items.map((item) => (
          <TranscriptRow key={item.key} item={item} />
        ))}
      </div>

      {(session.errorMessage || error) && (
        <div className="glass-notice is-danger chat-error" role="alert">
          <span>{session.errorMessage ?? `Codex 연결 오류 · ${error}`}</span>
          {session.errorMessage && (
            <Button variant="icon" onClick={session.dismissError} aria-label="닫기">×</Button>
          )}
        </div>
      )}

      <form
        className="chat-composer"
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        <label className="visually-hidden" htmlFor={`composer-${runId}`}>Codex에게 요청</label>
        <textarea
          id={`composer-${runId}`}
          value={draft}
          rows={2}
          disabled={session.ended}
          placeholder={
            session.ended
              ? 'Codex 세션이 종료되었습니다.'
              : session.working
                ? '진행 중인 작업에 추가 지시를 보낼 수 있어요 · Enter로 전송'
                : 'Codex에게 요청하기 · Enter로 전송 · Shift+Enter 줄바꿈'
          }
          onChange={(event) => {
            draftRef.current = event.target.value
            setDraft(event.target.value)
          }}
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
        <button type="submit" className="chat-send" disabled={!session.canSend || !draft.trim()} aria-label={session.working ? '추가 지시 보내기' : '보내기'}>
          <Icon name="arrowRight" size={20} />
        </button>
      </form>

      {firstApproval && !session.ended && (
        <ApprovalDialog
          key={firstApproval.approval_id}
          request={firstApproval}
          failure={session.errorMessage}
          connected={session.connected}
          onDecide={(decision) => session.decideApproval(firstApproval.approval_id, decision)}
        />
      )}
      {endDialogOpen && !firstApproval && <EndSessionDialog external={session.external} onConfirm={confirmEnd} onCancel={closeEndDialog} />}
    </div>
  )
}
