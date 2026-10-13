/** Codex external tools (MCP servers) and whether protected runs keep them on. */
export interface ExternalTool {
  name: string
  source: 'config' | 'plugin' | 'apps'
  plugin: string | null
  /** Kept on in AIA's protected runs (allowed, and its plugin is not turned off). */
  on_in_protected_runs: boolean
  allowed: boolean
  /** False when Codex cannot turn this name off through a run setting. */
  can_turn_off: boolean
}

export interface ExternalToolsState {
  readable: boolean
  tools: ExternalTool[]
}

const SOURCE_LABEL: Record<ExternalTool['source'], string> = {
  config: 'Codex 설정',
  plugin: '플러그인',
  apps: 'ChatGPT 앱 연결',
}

/** Known tools in plain words; the rest show where they come from. */
const TOOL_NOTE: Record<string, string> = {
  node_repl: 'JavaScript 실행·브라우저 조작',
  cua_repl: '화면·마우스 조작(컴퓨터 사용)',
  'browser-harness': '브라우저 조작',
  codex_apps: 'Slack·캘린더 등 연결된 앱',
  codex_app: 'Codex 앱 스레드·자동화',
  'code-review': '코드 리뷰',
}

export function externalToolNote(tool: ExternalTool): string {
  const source = tool.plugin ? `${SOURCE_LABEL.plugin} ${tool.plugin.split('@')[0]}` : SOURCE_LABEL[tool.source]
  const note = TOOL_NOTE[tool.name]
  return note ? `${note} · ${source}` : source
}

/** The allowed list after switching one tool on or off. */
export function withToolAllowed(allowed: string[], name: string, on: boolean): string[] {
  const rest = allowed.filter(item => item !== name)
  return on ? [...rest, name].sort() : rest
}

/** Short line for the section head: how many tools stay off in protected runs. */
export function externalToolsSummary(state: ExternalToolsState | null): string {
  if (!state) return '확인 중'
  if (!state.readable) return 'Codex 설정을 읽지 못했어요'
  if (state.tools.length === 0) return '켜진 외부 도구가 없어요'
  const on = state.tools.filter(tool => tool.on_in_protected_runs).length
  if (on === 0) return `${state.tools.length}개 모두 보호 실행에서 꺼 둠`
  return `${state.tools.length}개 중 ${on}개 켜 둠 · 나머지는 꺼 둠`
}
