/** Human-facing labels only. Never used to make policy or enforcement decisions. */
const LABELS: Record<string, string> = {
  READY: '준비 완료', CHECKING: '연결 확인 중', RUNNING: '실행 중', CREATED: '생성됨', PREPARING: '보호 준비 중',
  PROTECTING: '보호 준비 중', STARTING: '시작 중', COMPLETED: '종료됨', ABORTED: '사용자 중지', FAILED: '실패',
  VALID: '유효함', INVALID: '검증 실패', PENDING: '확정 전', UNVERIFIED: '미검증', NOT_FOUND: '기록 없음',
  VERIFIED: '검증 완료', RESTORED: '복구 완료', NOT_ATTEMPTED: '수행하지 않음', NOT_CHECKED: '확인 전', NOT_REQUIRED: '필요 없음',
  HEALTHY: '관찰 정상', STOPPED: '관찰 종료', DEGRADED: '보호 확인 불완전', UNKNOWN: '확인 어려움', NOT_OBSERVED: '관찰되지 않음',
  COMPLIANT: '정책 준수', VIOLATION: '정책 위반', INDETERMINATE: '판단 보류', ALLOW: '허용', AUDIT: '기록', DENY: '차단',
  CONTINUE: '실행 유지', CONTAIN: '통제 승인', REFUSE: '대응 거부', BLOCKED: '차단됨', TERMINATED: '종료 확인', SUCCEEDED: '성공 확인',
  EXACT: '직접 연결', PROCESS: '프로세스 관련', TEMPORAL: '시간상 관련', READ: '읽기', MODIFY: '수정', DELETE: '삭제', EXECUTE: '실행',
  COMPLETED_VERIFIED: '종료·보호 검증 완료', ABORTED_VERIFIED: '중지·보호 검증 완료', COMPLETED_DEGRADED: '종료·보호 확인 불완전',
  ABORTED_DEGRADED: '중지·보호 확인 불완전', FAILED_DEGRADED: '실패·보호 확인 불완전', ACTIVE_DEGRADED: '실행 중·보호 확인 불완전',
  HOOK_VERIFICATION_REQUIRED: '보호 연결 재확인 필요', CODEX_HOOK_NOT_INSTALLED: '보호 연결 설치 필요',
  CODEX_HOOK_TRUST_REQUIRED: 'Codex에서 신뢰 승인 필요', CODEX_EXECUTABLE_UNAVAILABLE: 'Codex 설치 확인 필요',
  CONTROL_ROOT_NOT_WRITABLE: '기록 폴더 권한 확인 필요', TRUSTED: '신뢰 승인됨', UNTRUSTED: '신뢰 승인 전', MODIFIED: '설정 변경됨',
  MATCHED: '적용 정책 일치', PARTIAL: '일부 정보만 확인', MISSING: '누락', ERROR: '오류',
}
export function displayStatus(value?: string | null): string {
  if (!value) return '확인 전'
  return LABELS[value.toUpperCase()] ?? '상세 확인 필요'
}
export function statusTone(value?: string | null): 'ok' | 'warn' | 'bad' | 'neutral' {
  if (['VALID', 'VERIFIED', 'RESTORED', 'HEALTHY', 'READY', 'COMPLIANT', 'SUCCEEDED', 'MATCHED'].includes(value ?? '')) return 'ok'
  if (['INVALID', 'FAILED', 'VIOLATION', 'MISSING'].includes(value ?? '')) return 'bad'
  if (['STOPPED', 'COMPLETED', 'ABORTED', 'NOT_ATTEMPTED', 'NOT_REQUIRED'].includes(value ?? '')) return 'neutral'
  return 'warn'
}
export const ACTIVE_STATUSES = new Set(['RUNNING', 'CREATED', 'PROTECTING', 'STARTING', 'PREPARING', 'READY'])
export function isSessionRunning(status?: string, orphaned = false): boolean {
  return !orphaned && ACTIVE_STATUSES.has(status ?? '')
}
export const TEMPLATE_NAMES: Record<string, string> = {
  PROTECTED_DEVELOPMENT: 'Standard Protection', BASIC_DEVELOPMENT: 'Development Collaboration',
  CONSERVATIVE_SECURITY: 'Change Control', FREE_DEVELOPMENT: 'Observation Only',
}

export function readinessNextStep(code?: string): string {
  const steps: Record<string, string> = {
    READY: '작업할 폴더와 정책을 선택해 보호 실행을 시작하세요.',
    CODEX_EXECUTABLE_UNAVAILABLE: 'Codex 설치 또는 실행 경로를 확인한 뒤 보호 연결을 다시 확인하세요.',
    CODEX_HOOK_NOT_INSTALLED: '보호 연결 설정에서 Hook 설치를 누르세요. 설치 뒤 Codex에서 신뢰 승인합니다.',
    CODEX_HOOK_TRUST_REQUIRED: 'Codex에서 /hooks를 열고 AIA Hook을 검토한 뒤 Trust를 선택하세요.',
    HOOK_VERIFICATION_REQUIRED: '보호 연결 설정에서 연결 검증을 눌러 실제 요청 전달을 확인하세요.',
    CONTROL_ROOT_NOT_WRITABLE: '로컬 기록 폴더에 쓰기 권한이 있는지 확인하세요.',
  }
  return steps[code ?? ''] ?? '보호 연결 설정을 열고 필요한 단계를 확인하세요.'
}
export function checkLabel(label: string): string {
  return ({ 'Codex 실행 파일': 'Codex 설치', 'PreToolUse Hook': '실행 전 연결', 'PostToolUse 관찰': '실행 후 관찰',
    '실제 Hook 연결 증명': '실제 요청 전달', 'AIA Control Root': '로컬 기록 폴더' } as Record<string, string>)[label] ?? label
}
