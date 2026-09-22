import { usePreflight } from './usePreflight'
import { useRunStatus } from './useRunStatus'
import { useResult } from './useResult'
import { useShellStore } from '../state/shellStore'
import { deriveVerdict } from '../api/resultVerdict'

export type GuardianState = 'normal' | 'review' | 'blocked' | 'recovery'

export interface GuardianStatus {
  state: GuardianState
  overline: string
  headline: string
  detail: string
}

const ENDED_STATUSES = new Set(['COMPLETED', 'ABORTED', 'FAILED'])

const COPY: Record<GuardianState, { overline: string; headline: string; detail: string }> = {
  normal: {
    overline: 'GUARDIAN STATUS · 정상',
    headline: '안전하게 관찰하고 있습니다',
    detail: 'Codex의 모든 실행은 증거로 기록되고, 위험한 요청은 실행 전 정책으로 먼저 판정됩니다.',
  },
  review: {
    overline: 'GUARDIAN STATUS · 확인 필요',
    headline: '확인이 필요한 상태입니다',
    detail: 'Codex가 승인을 기다리고 있거나, 아직 판정이 확정되지 않은 사건이 있습니다. 실시간 기록에서 확인하세요.',
  },
  blocked: {
    overline: 'GUARDIAN STATUS · 정책 위반',
    headline: '정책 위반이 감지됐습니다',
    detail: '위반으로 판정된 사건이 있습니다. 실시간 기록과 정책 사건 상세를 확인하세요.',
  },
  recovery: {
    overline: 'GUARDIAN STATUS · 보호 완료',
    headline: '보호 실행이 종료됐습니다',
    detail: '실행이 끝났습니다. 보호 결과에서 검증 내용을 확인하세요.',
  },
}

// Guardian's state is derived entirely from signals that already flow
// through the app (preflight, run status events, the lifted terminal
// activity signal, and the completed-run verdict) -- no new backend
// endpoint or polling. A clean successful run with zero incidents also
// reads as "recovery" here: the Guardian mockup has no fifth "nothing to
// report" pose, so this reuses "recovery" for that case rather than
// inventing a new visual.
export function useGuardianState(): GuardianStatus {
  const { activeRunId, terminalActivity } = useShellStore()
  const { data: preflight } = usePreflight()
  const { data: status } = useRunStatus(activeRunId, { enabled: Boolean(activeRunId) })
  const sessionStatus = status?.session?.status
  const ended = Boolean(activeRunId && sessionStatus && ENDED_STATUSES.has(sessionStatus))
  const { data: result } = useResult(activeRunId ?? '', { enabled: Boolean(activeRunId) && ended })

  let state: GuardianState = 'normal'

  if (activeRunId && ended) {
    if (result) {
      const tone = deriveVerdict(result).tone
      state = tone === 'ok' ? 'recovery' : tone === 'bad' ? 'blocked' : 'review'
    } else {
      state = 'recovery'
    }
  } else if (activeRunId) {
    // event.decision's vocabulary is enforcement-decision-first
    // (CONTAIN/REFUSE/BLOCKED/TERMINATED, falling back to the raw policy
    // decision), not a plain VIOLATION/INDETERMINATE string -- category and
    // severity (set server-side from that same logic, see presenters.py's
    // format_run_events) are the fields actually meant for this check.
    const events = status?.events ?? []
    const hasEnforcement = events.some((event) => event.category === 'ENFORCEMENT')
    const hasWarning = events.some((event) => event.category !== 'SENSOR' && event.severity === 'WARNING')
    const codexActionPrompt = terminalActivity?.runId === activeRunId && terminalActivity.terminalAction !== null
    if (hasEnforcement) state = 'blocked'
    else if (hasWarning || codexActionPrompt) state = 'review'
  }

  const copy = COPY[state]

  if (!activeRunId) {
    const ready = preflight?.readiness_code === 'READY'
    return {
      state: 'normal',
      overline: copy.overline,
      headline: ready ? '보호 실행을 시작할 준비가 됐습니다' : '보호 실행을 시작하기 전입니다',
      detail: ready
        ? '왼쪽에서 새 보호 실행을 시작하면 Codex 작업을 실시간으로 지켜봅니다.'
        : 'Hook 연결 상태를 확인한 뒤 새 보호 실행을 시작하세요.',
    }
  }

  return { state, overline: copy.overline, headline: copy.headline, detail: copy.detail }
}
