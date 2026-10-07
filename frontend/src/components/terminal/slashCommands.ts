/** Slash commands of the Codex composer, in one place (EPIC-021 TASK-112). */
export type SlashCommandName =
  | 'model' | 'compact' | 'review' | 'status' | 'diff' | 'goal' | 'resume' | 'mcp'
  | 'policy' | 'why' | 'restore' | 'report'

export interface SlashCommand {
  name: SlashCommandName
  label: string
  description: string
  group: 'codex' | 'aia'
  takesArgument?: boolean
}

// Left out on purpose: /approvals and /permissions (they change the run's protection),
// /new (a new conversation is a new protected run), `!` shell commands (they skip the
// agent and AIA's checks), and /logout.
export const SLASH_COMMANDS: SlashCommand[] = [
  { name: 'model', label: '모델 바꾸기', description: '다음 요청부터 쓸 모델과 생각 깊이', group: 'codex' },
  { name: 'compact', label: '대화 줄이기', description: '지금까지의 대화를 요약해 사용량을 아껴요', group: 'codex' },
  { name: 'review', label: '코드 검토', description: '작업 폴더의 바뀐 내용을 Codex가 검토해요', group: 'codex' },
  { name: 'status', label: '사용량 보기', description: '남은 한도와 이번 대화 사용량', group: 'codex' },
  { name: 'diff', label: '바뀐 내용 전체', description: '이번 대화에서 바뀐 내용을 한 번에', group: 'codex' },
  { name: 'goal', label: '목표 정하기', description: '/goal 다음에 목표를 적어요', group: 'codex', takesArgument: true },
  { name: 'resume', label: '이전 대화 이어하기', description: '새 보호 실행에서 이전 대화를 골라요', group: 'codex' },
  { name: 'mcp', label: '커넥터', description: '연결된 외부 도구와 보호 범위', group: 'codex' },
  { name: 'policy', label: '지금 정책', description: '이 실행에 적용된 보호 정책', group: 'aia' },
  { name: 'why', label: '마지막 차단 판정 이유', description: '가장 최근 차단 판정의 규칙과 단계', group: 'aia' },
  { name: 'restore', label: '복구 열기', description: '실행이 끝난 뒤 작업 폴더 되돌리기', group: 'aia' },
  { name: 'report', label: '보안 요약', description: '이번 실행의 보호 상황을 한눈에', group: 'aia' },
]

/** Commands offered while the first word is still being typed; empty otherwise. */
export function matchSlashCommands(draft: string): SlashCommand[] {
  if (!draft.startsWith('/') || /\s/.test(draft)) return []
  const typed = draft.slice(1).toLowerCase()
  return SLASH_COMMANDS.filter(command => command.name.startsWith(typed))
}

/** A known command and its argument; null sends the text to Codex as a normal message. */
export function parseSlashCommand(draft: string): { command: SlashCommand; argument: string } | null {
  const match = /^\/(\S+)(?:\s+([\s\S]*))?$/.exec(draft.trim())
  if (!match) return null
  const command = SLASH_COMMANDS.find(item => item.name === match[1].toLowerCase())
  return command ? { command, argument: (match[2] ?? '').trim() } : null
}
