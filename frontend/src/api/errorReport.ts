/** Text the user can paste into a bug report. Never includes evidence or secrets. */
export function errorReportTemplate(detail?: string): string {
  const observed = detail ? `\n- 화면 오류 내용: ${detail}` : ''
  return `[AIA Guardian 오류 신고]\n\n- 발생 시각:\n- 어떤 작업을 하려 했나요?:\n- 실제로 보인 현상:${observed}\n- 기대한 결과:\n- 선택한 정책 / 보호 상태:\n- 화면 캡처 또는 감사 기록 참고:\n\n※ API 키, 토큰, 비밀번호, 개인 경로 등 민감한 정보는 삭제해 주세요.`
}
