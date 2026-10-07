// Workbench conversation model for the Codex app-server transport.
//
// The backend (src/aia_app/codex_app_server.py) already normalizes Codex's
// app-server notifications into a small, stable event vocabulary. This file
// folds those events into transcript items. It never inspects screen text:
// every state change comes from a structured event.

import type { PermissionEntry } from '../../api/permissionGrants'
import type { TokenUsage, Usage, UsageLimits } from '../../api/usageView'

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
  question_id?: string
  questions?: UserQuestion[]
  auto_resolve_at?: string | null
  answers?: Record<string, string[] | null>
  skipped?: boolean
  elicitation_id?: string
  server?: string
  mode?: string
  fields?: ElicitationField[]
  url?: string | null
  url_host?: string | null
  supported?: boolean
  action?: string
  permissions_id?: string
  network?: boolean
  filesystem?: PermissionEntry[]
  limits?: UsageLimits | null
  tokens?: TokenUsage | null
  effort?: string | null
  explanation?: string | null
  steps?: CodexPlan['steps']
}

// Codex's step plan for the current request (turn/plan/updated).
export interface CodexPlan { turn_id?: string | null; explanation: string | null; steps: Array<{ step: string; status: 'pending' | 'inProgress' | 'completed' }> }

// Codex asking to widen its sandbox (item/permissions/requestApproval).
export interface PermissionsRequest { permissions_id: string; reason: string; network: boolean; filesystem: PermissionEntry[] }

// An MCP server asking for input through Codex (mcpServer/elicitation/request).
// Submitted values go to Codex only; the resolved event carries the action alone.
export interface ElicitationField {
  name: string
  title: string
  description: string
  required: boolean
  default?: unknown
  kind: 'text' | 'number' | 'integer' | 'boolean' | 'select' | 'multi'
  options?: Array<{ value: string; label: string }>
  format?: string | null
  minimum?: number | null
  maximum?: number | null
}
export interface ElicitationRequest {
  elicitation_id: string
  server: string
  mode: string
  message: string
  fields: ElicitationField[]
  url: string | null
  url_host: string | null
  supported: boolean
}

// Codex asking the user directly (item/tool/requestUserInput). Secret answers
// come back as null: AIA never keeps a copy of them.
export interface QuestionOption { label: string; description: string }
export interface UserQuestion { id: string; header: string; question: string; options: QuestionOption[]; allow_other: boolean; secret: boolean }
export interface QuestionRequest { question_id: string; questions: UserQuestion[]; auto_resolve_at?: string | null }
export type QuestionOutcome = 'answered' | 'skipped' | 'resolved' | 'cancelled'

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
  | { kind: 'question'; key: string; request: QuestionRequest; outcome: QuestionOutcome | null; answers: Record<string, string[] | null> }
  | { kind: 'elicitation'; key: string; request: ElicitationRequest; action: string | null }
  | { kind: 'permissions'; key: string; request: PermissionsRequest; decision: string | null }
  | { kind: 'notice'; key: string; tone: 'info' | 'warn' | 'bad'; text: string }

export interface ConversationState {
  items: TranscriptItem[]
  positions: Record<string, number>
  lastSequence: number
  activeTurnId: string | null
  pendingApprovals: ApprovalRequest[]
  pendingQuestions: QuestionRequest[]
  pendingElicitations: ElicitationRequest[]
  pendingPermissions: PermissionsRequest[]
  usage: Usage
  turnSettings: { model: string | null; effort: string | null } | null
  plan: CodexPlan | null
  lastEventAt: number
}

export const EMPTY_CONVERSATION: ConversationState = {
  items: [],
  positions: {},
  lastSequence: 0,
  activeTurnId: null,
  pendingApprovals: [],
  pendingQuestions: [],
  pendingElicitations: [],
  pendingPermissions: [],
  usage: { limits: null, tokens: null },
  turnSettings: null,
  plan: null,
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
    case 'question.requested': {
      const request: QuestionRequest = {
        question_id: event.question_id ?? '',
        questions: event.questions ?? [],
        auto_resolve_at: event.auto_resolve_at ?? null,
      }
      const key = `question:${request.question_id}`
      upsert(state, key, () => ({ kind: 'question', key, request, outcome: null, answers: {} }), (item) => item)
      state.pendingQuestions = [...state.pendingQuestions.filter((item) => item.question_id !== request.question_id), request]
      break
    }
    case 'question.answered':
    case 'question.resolved': {
      const key = `question:${event.question_id}`
      const outcome: QuestionOutcome = event.type === 'question.answered'
        ? (event.skipped ? 'skipped' : 'answered')
        : (event.reason === 'cancel' ? 'cancelled' : 'resolved')
      const answers = event.answers ?? {}
      upsert(
        state,
        key,
        () => ({ kind: 'question', key, request: { question_id: event.question_id ?? '', questions: [] }, outcome, answers }),
        (item) => (item.kind === 'question' ? { ...item, outcome, answers } : item),
      )
      state.pendingQuestions = state.pendingQuestions.filter((item) => item.question_id !== event.question_id)
      break
    }
    case 'elicitation.requested': {
      const request: ElicitationRequest = {
        elicitation_id: event.elicitation_id ?? '',
        server: event.server ?? '',
        mode: event.mode ?? '',
        message: event.message ?? '',
        fields: event.fields ?? [],
        url: event.url ?? null,
        url_host: event.url_host ?? null,
        supported: Boolean(event.supported),
      }
      const key = `elicitation:${request.elicitation_id}`
      upsert(state, key, () => ({ kind: 'elicitation', key, request, action: null }), (item) => item)
      state.pendingElicitations = [...state.pendingElicitations.filter((item) => item.elicitation_id !== request.elicitation_id), request]
      break
    }
    case 'elicitation.resolved': {
      const key = `elicitation:${event.elicitation_id}`
      const action = event.action ?? 'cancel'
      upsert(
        state,
        key,
        () => ({ kind: 'elicitation', key, request: { elicitation_id: event.elicitation_id ?? '', server: '', mode: '', message: '', fields: [], url: null, url_host: null, supported: false }, action }),
        (item) => (item.kind === 'elicitation' ? { ...item, action } : item),
      )
      state.pendingElicitations = state.pendingElicitations.filter((item) => item.elicitation_id !== event.elicitation_id)
      break
    }
    case 'permissions.requested': {
      const request: PermissionsRequest = {
        permissions_id: event.permissions_id ?? '',
        reason: event.reason ?? '',
        network: Boolean(event.network),
        filesystem: event.filesystem ?? [],
      }
      const key = `permissions:${request.permissions_id}`
      upsert(state, key, () => ({ kind: 'permissions', key, request, decision: null }), (item) => item)
      state.pendingPermissions = [...state.pendingPermissions.filter((item) => item.permissions_id !== request.permissions_id), request]
      break
    }
    case 'permissions.resolved': {
      const key = `permissions:${event.permissions_id}`
      const decision = event.decision ?? 'cancel'
      upsert(
        state,
        key,
        () => ({ kind: 'permissions', key, request: { permissions_id: event.permissions_id ?? '', reason: '', network: false, filesystem: [] }, decision }),
        (item) => (item.kind === 'permissions' ? { ...item, decision } : item),
      )
      state.pendingPermissions = state.pendingPermissions.filter((item) => item.permissions_id !== event.permissions_id)
      break
    }
    case 'plan.updated':
      state.plan = { turn_id: event.turn_id ?? null, explanation: event.explanation ?? null, steps: event.steps ?? [] }
      break
    case 'settings.changed':
      state.turnSettings = { model: event.model ?? null, effort: event.effort ?? null }
      break
    case 'usage.limits':
      state.usage = { ...state.usage, limits: event.limits ?? null }
      break
    case 'usage.tokens':
      state.usage = { ...state.usage, tokens: event.tokens ?? null }
      break
    case 'warning':
      notice(state, event, 'warn', event.message ?? 'Codex 경고')
      break
    case 'error':
      notice(state, event, event.will_retry ? 'warn' : 'bad', event.will_retry ? `${event.message} · 재시도 중` : event.message ?? 'Codex 오류')
      break
    case 'session.exited':
      state.activeTurnId = null
      state.pendingApprovals = []
      state.pendingQuestions = []
      state.pendingElicitations = []
      state.pendingPermissions = []
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
    pendingQuestions: [...previous.pendingQuestions],
    pendingElicitations: [...previous.pendingElicitations],
    pendingPermissions: [...previous.pendingPermissions],
  }
  for (const event of fresh) {
    applyEvent(state, event)
    state.lastSequence = Math.max(state.lastSequence, event.sequence)
  }
  state.lastEventAt = Date.now()
  return state
}
