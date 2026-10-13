export interface PolicyRule {
  rule_id: string; priority: number; asset_type: string
  path_patterns?: string[]; command_patterns?: string[]
  operation_effects: Record<string, string>
}
export interface PolicyDocument {
  schema_version: string; policy_id: string; policy_version: string; profile: string
  default_effect: string; rules: PolicyRule[]
}
export const EFFECTS: Record<string, string> = { ALLOW: '허용', AUDIT: '허용하고 기록', DENY: '금지' }
export const OPS: Record<string, string> = { READ: '읽기', CREATE: '생성', MODIFY: '수정', DELETE: '삭제', MOVE: '이동', RENAME: '이름 변경', EXECUTE: '명령 실행' }
