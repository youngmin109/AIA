import type { ResultView } from './resultTypes'
import { displayStatus } from './display.ts'

// Ported from result.html's Jinja-side verdict derivation (lines 11-19,
// 46-49). The backend never computes a single "outcome" field -- the old
// template combined ~5 independent status axes into one conclusion
// sentence, and this module does the same combination as a pure,
// unit-testable function instead of inline JSX branching.

export type VerdictBranch =
  | 'INCIDENTS_AND_POLICY_ATTENTION'
  | 'POLICY_ATTENTION_ONLY'
  | 'INCIDENTS_ONLY'
  | 'FAILED_DEGRADED_INVALID'
  | 'ABORTED_VERIFIED'
  | 'SUCCESS'
  | 'NEEDS_REVIEW'

export interface Verdict {
  branch: VerdictBranch
  tone: 'ok' | 'warn' | 'bad'
  headline: string
  detail: string
  /** True when execution_policy_status is DEGRADED/NOT_OBSERVED -- an axis
   * orthogonal to bundle validity, surfaced as a separate banner. */
  executionPolicyAttention: boolean
  executionPolicyStatus?: string
}

const PROTECTION_DEGRADED_STATES = new Set([
  'COMPLETED_DEGRADED',
  'ABORTED_DEGRADED',
  'FAILED_DEGRADED',
  'ACTIVE_DEGRADED',
  'UNKNOWN',
])

/** Full access is a scope the user chose, not a protection failure. */
const FULL_ACCESS_NOTE = '전체 권한으로 실행했어요. 작업 폴더 안의 모든 명령을 AIA가 실행 전에 검사했고, 작업 폴더는 되돌릴 수 있어요. 작업 폴더 밖 변경과 인터넷 사용만 보호 범위 밖이에요.'

export function isFullAccessScoped(result: ResultView): boolean {
  return (result.limitations ?? []).includes('CODEX_FULL_ACCESS_USER_SELECTED')
}

/** A policy incident that was contained before it ran (a protection win, not a problem to triage). */
function incidentBlocked(incident: { enforcement_action?: string; execution_result?: string }): boolean {
  const enforcement = String(incident.enforcement_action || '').toUpperCase()
  const execution = String(incident.execution_result || '').toUpperCase()
  return ['CONTAIN', 'REFUSE', 'BLOCKED'].includes(enforcement) || ['BLOCKED', 'NOT_EXECUTED', 'NOT_ATTEMPTED'].includes(execution)
}

export function deriveVerdict(result: ResultView): Verdict {
  const bundleVerified = result.bundle_status === 'VALID'
  const protectionState = result.protection_state || ''
  const notFailed = result.session_status !== 'FAILED'
  // Full access degrades the protection state only because Codex's sandbox is
  // off. That is the scope the user picked, so with a valid bundle it is not a
  // failure: the work folder is still checked before execution and restorable.
  const fullAccessScoped = isFullAccessScoped(result) && bundleVerified && notFailed
  const protectionVerified =
    ['COMPLETED_VERIFIED', 'ABORTED_VERIFIED'].includes(protectionState) || fullAccessScoped
  const protectionDegraded = PROTECTION_DEGRADED_STATES.has(protectionState) && !fullAccessScoped
  const executionPolicyAttention = ['DEGRADED', 'NOT_OBSERVED'].includes(result.execution_policy_status || '')
  const completedAndValid = protectionVerified && bundleVerified
  const incidents = result.incidents ?? []
  const incidentCount = incidents.length || (result.incident_count ?? 0)
  const hasIncidents = incidentCount > 0
  const allBlocked = incidents.length > 0 && incidents.every(incidentBlocked)
  const scopeDetail = fullAccessScoped ? ` ${FULL_ACCESS_NOTE}` : ''

  if (!bundleVerified || protectionDegraded || result.session_status === 'FAILED') {
    return {
      branch: 'FAILED_DEGRADED_INVALID', tone: !bundleVerified || result.session_status === 'FAILED' ? 'bad' : 'warn',
      headline: '보호 실행 결과의 검증을 확인해야 합니다.',
      detail: `감사 묶음: ${displayStatus(result.bundle_status)} · 보호 상태: ${displayStatus(protectionState)}. 정책 사건과 별도로 검토하세요.`,
      executionPolicyAttention, executionPolicyStatus: result.execution_policy_status,
    }
  }

  // Threats that were all stopped before they ran are a protection win, not a
  // review queue -- say so plainly instead of "정책 사건 N건".
  if (allBlocked && !executionPolicyAttention) {
    return {
      branch: 'SUCCESS', tone: 'ok',
      headline: `위협 ${incidentCount}건을 실행 전에 막았어요.`,
      detail: `지원 범위 안의 위험한 요청을 실행되기 전에 모두 차단했고 감사 묶음도 검증됐어요.${scopeDetail}`,
      executionPolicyAttention,
    }
  }

  if (hasIncidents && executionPolicyAttention) {
    return {
      branch: 'INCIDENTS_AND_POLICY_ATTENTION',
      tone: 'warn',
      headline: `정책 사건 ${incidentCount}건이 확인됐고 Codex 적용 정책도 확인되지 않았습니다.`,
      detail: '정책 사건 상세와 적용 정책을 함께 확인하세요.',
      executionPolicyAttention,
      executionPolicyStatus: result.execution_policy_status,
    }
  }
  if (executionPolicyAttention) {
    return {
      branch: 'POLICY_ATTENTION_ONLY',
      tone: 'warn',
      headline: 'Codex 실행 정책을 확인하지 못했습니다.',
      detail: '실제 적용 정책을 확인하기 전에는 이 실행을 완전한 보호 성공으로 해석하지 마세요.',
      executionPolicyAttention,
      executionPolicyStatus: result.execution_policy_status,
    }
  }
  if (hasIncidents) {
    return {
      branch: 'INCIDENTS_ONLY',
      tone: 'warn',
      headline: `정책 사건 ${incidentCount}건이 확인됐습니다.`,
      detail: '차단 여부와 실제 실행 결과를 정책 사건 상세에서 확인하세요.',
      executionPolicyAttention,
    }
  }
  if (protectionState === 'ABORTED_VERIFIED') {
    return {
      branch: 'ABORTED_VERIFIED',
      tone: 'ok',
      headline: '사용자 중지로 종료됐지만 보호 상태는 검증됐습니다.',
      detail: '감사 묶음과 보호 상태가 검증됐습니다. 모든 행동이 안전했다는 의미는 아닙니다.',
      executionPolicyAttention,
    }
  }
  if (completedAndValid) {
    return {
      branch: 'SUCCESS',
      tone: 'ok',
      headline: fullAccessScoped ? '작업 폴더를 보호했어요.' : '보호 실행이 정상적으로 완료됐습니다.',
      detail: `감사 묶음과 보호 상태가 검증됐습니다. 복구 여부는 별도로 확인하세요.${scopeDetail}`,
      executionPolicyAttention,
    }
  }
  return {
    branch: 'NEEDS_REVIEW',
    tone: 'warn',
    headline: '이 실행의 보호 상태를 확인해야 합니다.',
    detail: `감사 묶음: ${displayStatus(result.bundle_status)} · 실행: ${displayStatus(result.session_status)}.`,
    executionPolicyAttention,
  }
}
