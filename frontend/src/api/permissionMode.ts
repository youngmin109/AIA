/** AI permission of a Workbench run: full access (YOLO) or the work folder only. */
export type PermissionMode = 'full_access' | 'workspace'

/** The product's motto: let Codex run freely (YOLO); AIA checks every command and keeps the folder recoverable. */
export const PERMISSION_DEFAULT: PermissionMode = 'full_access'

export interface PermissionOption {
  mode: PermissionMode
  label: string
  badge: string | null
  note: string
}

export const PERMISSION_OPTIONS: PermissionOption[] = [
  {
    mode: 'full_access',
    label: '전체 권한',
    badge: 'YOLO 모드',
    note: 'Codex가 묻지 않고 마음껏 실행해요. 모든 명령은 AIA가 실행 전에 검사하고, 작업 폴더는 되돌릴 수 있어요.',
  },
  {
    mode: 'workspace',
    label: '작업 폴더만',
    badge: null,
    note: 'Codex 샌드박스가 작업 폴더 밖 쓰기와 인터넷을 막고, 필요하면 허용을 물어요.',
  },
]

export function permissionModeOf(value: unknown): PermissionMode | null {
  return value === 'full_access' || value === 'workspace' ? value : null
}

/** Chip text: "YOLO · 전체 권한" stands out; the other mode reads plainly. */
export function permissionChipText(mode: PermissionMode | null): string {
  if (mode === 'full_access') return 'YOLO · 전체 권한'
  if (mode === 'workspace') return '작업 폴더만'
  return 'AI 권한 확인 중'
}

/** Codex's applied sandbox in plain words (session.ready reports camelCase names). */
export function sandboxLabel(sandbox: string | null | undefined): string {
  if (sandbox === 'dangerFullAccess' || sandbox === 'danger-full-access') return '전체 권한(YOLO)'
  if (sandbox === 'workspaceWrite' || sandbox === 'workspace-write') return '작업 폴더만'
  if (sandbox === 'readOnly' || sandbox === 'read-only') return '읽기 전용'
  return '확인 불가'
}
