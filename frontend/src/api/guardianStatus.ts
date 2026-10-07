import type { RunStatus } from './types'
import type { ResultView } from './resultTypes'
import { isSessionRunning } from './display.ts'

export type GuardianState = 'normal' | 'review' | 'blocked' | 'recovery'
export interface GuardianStatus { state: GuardianState; label: string; headline: string; detail: string }

/** Display state is independent of authority: it cannot approve or block a tool. */
export function guardianStatus({ ready, selected, status, result, approval, error }: {
  ready: boolean; selected: boolean; status?: RunStatus | null; result?: ResultView | null; approval?: boolean; error?: boolean
}): GuardianStatus {
  if (!selected) return { state: ready ? 'normal' : 'review', label: ready ? '준비 완료' : '연결 필요',
    headline: ready ? '보호 실행을 시작할 준비가 됐습니다' : '보호 연결을 먼저 확인해주세요',
    detail: '아이아는 에이전트의 작업을 관찰하는 안내자예요. 작업공간을 선택하면 보호 실행을 시작할 수 있어요.' }
  if (error || !status) return { state: 'review', label: '확인 중', headline: '최신 보호 상태를 확인하고 있습니다', detail: '연결이 복구되기 전에는 이전 표시를 현재 상태로 해석하지 마세요.' }
  const running = isSessionRunning(status.session?.status, status.runtime_reconciliation?.orphaned)
  if (!running) {
    const reconciliation = status.runtime_reconciliation as { orphaned?: boolean; agent_process_status?: string } | undefined
    if (!result && reconciliation?.orphaned) {
      // No result will ever arrive for an orphaned run; say what was verified instead of "checking".
      return reconciliation.agent_process_status === 'NOT_STARTED'
        ? { state: 'review', label: '준비 중 중단', headline: '준비하던 중에 앱이 닫힌 실행이에요', detail: 'Codex는 시작되지 않았어요. 같은 폴더로 새 보호 실행을 시작하면 돼요.' }
        : { state: 'review', label: '연결 끊김', headline: '이전 실행의 연결이 끊겼어요', detail: '기록에서 저장된 상태를 확인하세요. 살아 있는 프로세스를 자동으로 강제 종료하지 않아요.' }
    }
    if (!result) return { state: 'review', label: '결과 확인 중', headline: '실행이 끝났습니다. 결과를 확인하고 있어요', detail: '감사 결과가 확인되기 전에는 보호 성공이나 복구 완료를 확정하지 않습니다.' }
    if (result.bundle_status !== 'VALID' || /DEGRADED|UNKNOWN/.test(result.protection_state ?? '') || result.session_status === 'FAILED') {
      return { state: 'review', label: '검증 확인 필요', headline: result.session_status === 'ABORTED' ? '실행이 중지됐습니다. 보호 결과를 확인해주세요' : '보호 결과가 완전히 확인되지 않았습니다', detail: '관찰 이상과 정책 위반은 다릅니다. 감사 기록에서 검증 상태와 제한사항을 확인하세요.' }
    }
    const policyIncident = result.incidents?.some(item => item.policy_effect === 'DENY' || item.policy_decision === 'VIOLATION')
    if (policyIncident) return { state: 'blocked', label: '정책 사건', headline: '정책상 제한된 요청이 기록됐습니다', detail: '차단 판정과 실제 차단 성공은 다릅니다. 사건의 실행 결과를 확인해주세요.' }
    if (result.recovery_status === 'RESTORED' && result.integrity_status === 'VERIFIED') return { state: 'recovery', label: '복구·검증 완료', headline: '작업공간 복구와 무결성 검증을 마쳤습니다', detail: '복구 기록과 원래 실행의 감사 결과는 별도로 확인할 수 있어요.' }
    return { state: 'normal', label: result.session_status === 'ABORTED' ? '사용자 중지' : '실행 종료', headline: result.session_status === 'ABORTED' ? '요청하신 실행 중지를 확인했습니다' : '실행이 종료되고 감사 기록이 확인됐습니다', detail: '실행 종료는 복구 완료와 다릅니다. 결과 화면에서 각 검증 항목을 확인해주세요.' }
  }
  if (Object.values(status.sensor_health ?? {}).some(value => value === 'FAILED') || /DEGRADED/.test(status.protection?.state ?? '') || status.runtime_reconciliation?.orphaned) return { state: 'review', label: '관찰 확인 필요', headline: '일부 보호 조건을 확인할 수 없습니다', detail: '센서와 연결 상태를 확인해주세요. 정책 위반으로 확정된 상태는 아닙니다.' }
  if (approval) return { state: 'review', label: '사용자 확인', headline: '실행 전에 확인할 요청이 있습니다', detail: '도구, 대상, 이유와 허용 범위를 읽어주세요. 정책상 금지된 행동은 승인으로 해제되지 않습니다.' }
  const latest = (status.events ?? []).filter(event => event.category !== 'SENSOR').at(-1)
  if (latest?.category === 'ENFORCEMENT') return { state: 'blocked', label: '통제 요청', headline: '제한된 요청의 대응 결과를 확인해주세요', detail: 'AIA 판단과 실제 실행 결과를 활동 기록에서 나눠 확인할 수 있어요.' }
  return { state: 'normal', label: '관찰 중', headline: '에이전트의 작업을 함께 확인하고 있어요', detail: '지원되는 실행 요청, 관리 프로세스와 작업공간 파일 변화를 관찰합니다. 모든 도구나 외부 파일을 보호하는 것은 아닙니다.' }
}
