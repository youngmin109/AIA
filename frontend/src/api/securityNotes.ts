/** Answers of the AIA security slash commands, built from data the console already has (EPIC-022 TASK-114). */
export interface AiaNote { title: string; lines: string[]; footnote?: string }

interface NoteAction {
  enforcement_decision?: string
  policy_decision?: string
  operation?: string
  observation_stage?: string
  matched_rule_ids?: unknown
}

const OPERATION_LABEL: Record<string, string> = {
  EXECUTE: '명령 실행', READ: '파일 읽기', WRITE: '파일 쓰기', DELETE: '파일 삭제', NETWORK: '네트워크', TOOL: '도구 사용',
}
const STAGE_LABEL: Record<string, string> = { PRE_ACTION: '실행 전 검사', POST_ACTION: '실행 후 관찰' }

export function policyNote(name: string | null | undefined, description: string | null | undefined): AiaNote {
  return {
    title: '지금 정책',
    lines: [name ? `정책: ${name}` : '정책 정보를 아직 받지 못했어요.', ...(description ? [description] : [])],
    footnote: '정책은 실행 중에 바뀌지 않아요. 다음 보호 실행에서 다른 정책을 고를 수 있어요.',
  }
}

/** The most recent block decision; never says the action was actually stopped. */
export function whyNote(actions: NoteAction[] | null | undefined): AiaNote {
  const last = [...(actions ?? [])].reverse().find(action => action.enforcement_decision === 'CONTAIN' || action.policy_decision === 'VIOLATION')
  if (!last) return { title: '마지막 차단 판정 이유', lines: ['이번 실행에서 아직 차단 판정이 없어요.'] }
  const rules = Array.isArray(last.matched_rule_ids) ? last.matched_rule_ids.filter((rule): rule is string => typeof rule === 'string') : []
  return {
    title: '마지막 차단 판정 이유',
    lines: [
      `판정: ${last.enforcement_decision === 'CONTAIN' ? '차단 판정' : '정책 위반'}${last.observation_stage ? ` · ${STAGE_LABEL[last.observation_stage] ?? last.observation_stage}` : ''}`,
      `동작: ${OPERATION_LABEL[last.operation ?? ''] ?? last.operation ?? '확인 불가'}`,
      `규칙: ${rules.length ? rules.join(', ') : '일반 규칙'}`,
    ],
    footnote: '차단 판정은 실제로 막혔다는 확인과 달라요. 원문 명령은 보여주지 않아요.',
  }
}

export function reportNote(input: {
  pretool?: number | null
  blocks: number
  files?: number | null
  grants: number
  sensorsHealthy?: boolean | null
}): AiaNote {
  return {
    title: '보안 요약',
    lines: [
      `실행 전 검사 ${input.pretool ?? 0}건 · 차단 판정 ${input.blocks}건`,
      input.files == null ? '파일 변경 확인 불가' : `파일 변경 ${input.files}개`,
      input.grants ? `사용자가 넓혀 준 권한 ${input.grants}건` : '넓혀 준 권한 없음',
      input.sensorsHealthy === false ? '감시 장치 중 확인이 필요한 것이 있어요' : input.sensorsHealthy ? '감시 장치 모두 정상' : '감시 장치 상태 확인 중',
    ],
    footnote: '실행이 끝나면 결과 화면에서 증거와 함께 자세히 볼 수 있어요.',
  }
}

export function restoreNote(ended: boolean): AiaNote {
  return ended
    ? { title: '복구 열기', lines: ['결과 화면에서 기준점과 비교한 뒤 작업 폴더를 되돌릴 수 있어요.'] }
    : { title: '복구 열기', lines: ['복구는 실행이 끝난 뒤에 할 수 있어요.', '"작업 종료"로 실행을 끝내면 결과 화면에서 기준점으로 되돌릴 수 있어요.'] }
}
