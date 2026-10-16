/** AI permission of a Workbench run: the Codex app's three choices, same words and order. */
export type PermissionMode = 'workspace' | 'auto_review' | 'full_access'

/**
 * AIA's product stance: let the agent work without Codex's sandbox or approval
 * prompts and keep protection in AIA's own layer (Hook before every command,
 * sensors, recovery of the work folder).  "승인 요청" stays one click away for a
 * stricter run, and a Codex config that forbids full access falls back to it.
 */
export const PERMISSION_DEFAULT: PermissionMode = 'full_access'

/** The Codex app's own question above its permission menu. */
export const PERMISSION_TITLE = 'ChatGPT 액션은 어떻게 승인할까요?'

export interface PermissionOption {
  mode: PermissionMode
  label: string
  /** Text on the chip once chosen (the Codex app shows "전체 액세스"). */
  chip: string
  note: string
  icon: 'hand' | 'shield' | 'alertCircle'
  /** The Codex permission profile this choice needs (from permissionProfile/list). */
  profile: ':workspace' | ':danger-full-access'
}

export const PERMISSION_OPTIONS: PermissionOption[] = [
  { mode: 'workspace', label: '승인 요청', chip: '승인 요청', note: '외부 파일 수정 및 인터넷 사용 시 항상 확인합니다', icon: 'hand', profile: ':workspace' },
  { mode: 'auto_review', label: '나 대신 승인', chip: '나 대신 승인', note: '잠재적으로 위험한 것으로 감지된 작업에만 승인을 요청합니다', icon: 'shield', profile: ':workspace' },
  { mode: 'full_access', label: '전체 권한', chip: '전체 액세스', note: '인터넷과 컴퓨터의 모든 파일에 제한 없이 액세스합니다', icon: 'alertCircle', profile: ':danger-full-access' },
]

export interface PermissionProfile { id: string; allowed: boolean }

/** A choice Codex's config forbids cannot be picked; an unknown profile list allows all. */
export function permissionAllowed(option: PermissionOption, profiles: PermissionProfile[]): boolean {
  const profile = profiles.find(item => item.id === option.profile)
  return profiles.length === 0 || profile?.allowed !== false
}

export function permissionOption(mode: PermissionMode | null): PermissionOption | null {
  return PERMISSION_OPTIONS.find(option => option.mode === mode) ?? null
}

export function permissionModeOf(value: unknown): PermissionMode | null {
  return value === 'workspace' || value === 'auto_review' || value === 'full_access' ? value : null
}

/** The mode Codex reports for a started conversation (sandbox plus who reviews approvals). */
export function permissionModeFromCodex(sandbox: string | null | undefined, reviewer: string | null | undefined): PermissionMode | null {
  if (sandbox === 'dangerFullAccess') return 'full_access'
  if (sandbox === 'workspaceWrite') return reviewer === 'auto_review' ? 'auto_review' : 'workspace'
  return null
}

/** Codex's applied sandbox in plain words (session.ready reports camelCase names). */
export function sandboxLabel(sandbox: string | null | undefined): string {
  if (sandbox === 'dangerFullAccess' || sandbox === 'danger-full-access') return '전체 권한'
  if (sandbox === 'workspaceWrite' || sandbox === 'workspace-write') return '작업 폴더'
  if (sandbox === 'readOnly' || sandbox === 'read-only') return '읽기 전용'
  return '확인 불가'
}
