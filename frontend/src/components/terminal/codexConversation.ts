// Workbench conversation model for the Codex app-server transport.
//
// The backend (src/aia_app/codex_app_server.py) already normalizes Codex's
// app-server notifications into a small, stable event vocabulary. This file
// folds those events into transcript items. It never inspects screen text:
// every state change comes from a structured event.

export interface CodexEvent {
  sequence: number
  type: string
  recorded_at?: string
  item_id?: string | null
  turn_id?: string | null
  text?: string
  status?: string | null
  error?: string | null
  command?: string
  cwd?: string
  exit_code?: number | null
  paths?: string[]
  tool?: string
  phase?: 'started' | 'completed'
  hook_run_id?: string | null
  event_name?: string | null
  message?: string
  will_retry?: boolean
  approval_id?: string
  kind?: ApprovalKind
  reason?: string
  timeout_seconds?: number
  expires_at?: string
  decision?: string
  model?: string | null
  sandbox?: string | null
  approval_policy?: string | null
  unexpected?: boolean
}

// 'command' / 'file_change' are Codex sandbox approvals. 'aia_tool' is AIA's
// human-in-the-loop review of a tool AIA cannot interpret (auto-refused when
// the review window closes).
export type ApprovalKind = 'command' | 'file_change' | 'aia_tool'

export interface ApprovalRequest {
  approval_id: string
  kind: ApprovalKind
  command: string
  cwd: string
  reason: string
  paths: string[]
  tool?: string
  timeout_seconds?: number
  expires_at?: string
}

export type TranscriptItem =
  | { kind: 'user'; key: string; text: string }
  | { kind: 'agent'; key: string; text: string; streaming: boolean }
  | { kind: 'reasoning'; key: string; text: string; done: boolean }
  | { kind: 'command'; key: string; command: string; cwd: string; output: string; status: string | null; exitCode: number | null }
  | { kind: 'file_change'; key: string; paths: string[]; status: string | null }
  | { kind: 'tool'; key: string; tool: string; status: string | null }
  | { kind: 'hook'; key: string; eventName: string; status: string; phase: 'started' | 'completed' }
  | { kind: 'approval'; key: string; request: ApprovalRequest; decision: string | null }
  | { kind: 'notice'; key: string; tone: 'info' | 'warn' | 'bad'; text: string }

export interface ConversationState {
  items: TranscriptItem[]
  positions: Record<string, number>
  lastSequence: number
  activeTurnId: string | null
  pendingApprovals: ApprovalRequest[]
  lastEventAt: number
}

export const EMPTY_CONVERSATION: ConversationState = {
  items: [],
  positions: {},
  lastSequence: 0,
  activeTurnId: null,
  pendingApprovals: [],
  lastEventAt: 0,
}

// Command output is display-only and can be long; keep the most recent part.
const MAX_COMMAND_OUTPUT_CHARS = 20_000
// eslint-disable-next-line no-control-regex
const ANSI_PATTERN = /\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Z0-9]/g

export function stripAnsi(value: string): string {
  return value.replace(ANSI_PATTERN, '')
}

function upsert(state: ConversationState, key: string, create: () => TranscriptItem, update: (item: TranscriptItem) => TranscriptItem) {
  const position = state.positions[key]
  if (position === undefined) {
    state.positions[key] = state.items.length
    state.items.push(create())
  } else {
    state.items[position] = update(state.items[position])
  }
}

function notice(state: ConversationState, event: CodexEvent, tone: 'info' | 'warn' | 'bad', text: string) {
  const key = `notice:${event.sequence}`
  upsert(state, key, () => ({ kind: 'notice', key, tone, text }), (item) => item)
}

function applyEvent(state: ConversationState, event: CodexEvent) {
  const id = String(event.item_id ?? event.sequence)
  switch (event.type) {
    case 'session.ready':
      notice(state, event, 'info', `Codex 연결됨 · 모델 ${event.model ?? '기본값'} · 샌드박스 ${event.sandbox ?? '확인 불가'}`)
      break
    case 'turn.started':
      state.activeTurnId = event.turn_id ?? null
      break
    case 'turn.completed':
      state.activeTurnId = null
      if (event.status === 'interrupted') notice(state, event, 'warn', '요청을 중지했습니다.')
      else if (event.status === 'failed') notice(state, event, 'bad', `Codex 요청이 실패했습니다${event.error ? ` · ${event.error}` : ''}`)
      break
    case 'user_message': {
      const key = `user:${id}`
      upsert(state, key, () => ({ kind: 'user', key, text: event.text ?? '' }), (item) => item)
      break
    }
    case 'message.started':
    case 'message.delta':
    case 'message.completed': {
      const key = `agent:${id}`
      const completed = event.type === 'message.completed'
      upsert(
        state,
        key,
        () => ({ kind: 'agent', key, text: event.text ?? '', streaming: !completed }),
        (item) =>
          item.kind === 'agent'
            ? {
                ...item,
                text: completed ? (event.text || item.text) : item.text + (event.text ?? ''),
                streaming: !completed,
              }
            : item,
      )
      break
    }
    case 'reasoning.started':
    case 'reasoning.delta':
    case 'reasoning.completed': {
      const key = `reasoning:${id}`
      const done = event.type === 'reasoning.completed'
      upsert(
        state,
        key,
        () => ({ kind: 'reasoning', key, text: event.text ?? '', done }),
        (item) => (item.kind === 'reasoning' ? { ...item, text: item.text + (event.text ?? ''), done: item.done || done } : item),
      )
      break
    }
    case 'command.started':
    case 'command.output':
    case 'command.completed': {
      const key = `command:${id}`
      upsert(
        state,
        key,
        () => ({
          kind: 'command',
          key,
          command: event.command ?? '',
          cwd: event.cwd ?? '',
          output: stripAnsi(event.text ?? ''),
          status: event.type === 'command.completed' ? event.status ?? null : 'inProgress',
          exitCode: event.exit_code ?? null,
        }),
        (item) => {
          if (item.kind !== 'command') return item
          if (event.type === 'command.output') {
            const output = (item.output + stripAnsi(event.text ?? '')).slice(-MAX_COMMAND_OUTPUT_CHARS)
            return { ...item, output }
          }
          if (event.type === 'command.completed') return { ...item, status: event.status ?? null, exitCode: event.exit_code ?? null }
          return { ...item, command: event.command || item.command, cwd: event.cwd || item.cwd }
        },
      )
      break
    }
    case 'file_change.started':
    case 'file_change.completed': {
      const key = `file:${id}`
      upsert(
        state,
        key,
        () => ({ kind: 'file_change', key, paths: event.paths ?? [], status: event.status ?? null }),
        (item) => (item.kind === 'file_change' ? { ...item, paths: event.paths?.length ? event.paths : item.paths, status: event.status ?? item.status } : item),
      )
      break
    }
    case 'tool.started':
    case 'tool.completed': {
      const key = `tool:${id}`
      upsert(
        state,
        key,
        () => ({ kind: 'tool', key, tool: event.tool ?? 'tool', status: event.status ?? null }),
        (item) => (item.kind === 'tool' ? { ...item, status: event.status ?? item.status } : item),
      )
      break
    }
    case 'hook': {
      const key = `hook:${event.hook_run_id ?? event.sequence}`
      const next = {
        kind: 'hook' as const,
        key,
        eventName: event.event_name ?? '',
        status: event.status ?? '',
        phase: event.phase ?? 'started',
      }
      upsert(state, key, () => next, () => next)
      break
    }
    case 'approval.requested': {
      const request: ApprovalRequest = {
        approval_id: event.approval_id ?? '',
        kind: event.kind ?? 'command',
        command: event.command ?? '',
        cwd: event.cwd ?? '',
        reason: event.reason ?? '',
        paths: event.paths ?? [],
        tool: event.tool,
        timeout_seconds: event.timeout_seconds,
        expires_at: event.expires_at,
      }
      const key = `approval:${request.approval_id}`
      upsert(state, key, () => ({ kind: 'approval', key, request, decision: null }), (item) => item)
      state.pendingApprovals = [...state.pendingApprovals.filter((item) => item.approval_id !== request.approval_id), request]
      break
    }
    case 'approval.resolved': {
      const key = `approval:${event.approval_id}`
      upsert(
        state,
        key,
        () => ({
          kind: 'approval',
          key,
          request: { approval_id: event.approval_id ?? '', kind: 'command', command: '', cwd: '', reason: '', paths: [] },
          decision: event.decision ?? null,
        }),
        (item) => (item.kind === 'approval' ? { ...item, decision: event.decision ?? null } : item),
      )
      state.pendingApprovals = state.pendingApprovals.filter((item) => item.approval_id !== event.approval_id)
      break
    }
    case 'warning':
      notice(state, event, 'warn', event.message ?? 'Codex 경고')
      break
    case 'error':
      notice(state, event, event.will_retry ? 'warn' : 'bad', event.will_retry ? `${event.message} · 재시도 중` : event.message ?? 'Codex 오류')
      break
    case 'session.exited':
      state.activeTurnId = null
      state.pendingApprovals = []
      notice(state, event, event.unexpected ? 'bad' : 'info', event.unexpected ? 'Codex가 예기치 않게 종료되었습니다.' : 'Codex 세션이 종료되었습니다.')
      break
    default:
      break
  }
}

/** Fold a batch of events into a new state; events at or before the last
 * applied sequence are ignored so a replay after reconnect is idempotent. */
export function applyEvents(previous: ConversationState, events: CodexEvent[]): ConversationState {
  const fresh = events.filter((event) => event.sequence > previous.lastSequence)
  if (!fresh.length) return previous
  const state: ConversationState = {
    ...previous,
    items: [...previous.items],
    positions: { ...previous.positions },
    pendingApprovals: [...previous.pendingApprovals],
  }
  for (const event of fresh) {
    applyEvent(state, event)
    state.lastSequence = Math.max(state.lastSequence, event.sequence)
  }
  state.lastEventAt = Date.now()
  return state
}
