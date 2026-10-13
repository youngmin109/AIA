/** Commands in the conversation as one quiet row each: the Hook check before, the command, the Hook record after. */
import type { TranscriptItem } from './codexConversation'

type CommandItem = Extract<TranscriptItem, { kind: 'command' }>
type HookItem = Extract<TranscriptItem, { kind: 'hook' }>

export type TranscriptEntry =
  | { kind: 'item'; item: TranscriptItem }
  | { kind: 'command'; key: string; command: CommandItem; hooks: HookItem[] }

/**
 * Folds each command with its AIA Hook lines: the check right before it, the
 * record right after it, and the check right after it when Codex reported the
 * command first.  A check followed by the next command stays with that one.
 */
export function groupCommands(items: TranscriptItem[]): TranscriptEntry[] {
  const entries: TranscriptEntry[] = []
  let index = 0
  while (index < items.length) {
    const item = items[index]
    const leadingCheck = item.kind === 'hook' && item.eventName === 'preToolUse' && items[index + 1]?.kind === 'command'
    const command = leadingCheck ? items[index + 1] : item
    if (command.kind !== 'command') {
      entries.push({ kind: 'item', item })
      index += 1
      continue
    }
    const hooks: HookItem[] = leadingCheck && item.kind === 'hook' ? [item] : []
    index += leadingCheck ? 2 : 1
    while (index < items.length) {
      const after = items[index]
      if (after.kind !== 'hook') break
      const ownCheck = after.eventName === 'preToolUse'
        && !hooks.some(hook => hook.eventName === 'preToolUse')
        && items[index + 1]?.kind !== 'command'
      if (after.eventName !== 'postToolUse' && !ownCheck) break
      hooks.push(after)
      index += 1
    }
    entries.push({ kind: 'command', key: command.key, command, hooks })
  }
  return entries
}

const SHELL_WRAPPER = /^\s*(?:"[^"]*?(?:powershell|pwsh|cmd)(?:\.exe)?"|[^\s"]*?(?:powershell|pwsh|cmd)(?:\.exe)?)\s+(?:-(?:NoProfile|NoLogo|NonInteractive)\s+|-ExecutionPolicy\s+\S+\s+)*(?:-Command|-c|\/c)\s+([\s\S]+)$/i

/** One-line view of a command: the PowerShell/cmd wrapper Codex adds is dropped and whitespace collapsed. The full command stays visible when the row is opened. */
export function commandPreview(command: string): string {
  let text = command.trim()
  const wrapped = SHELL_WRAPPER.exec(text)
  if (wrapped) {
    text = wrapped[1].trim()
    const quote = text[0]
    if ((quote === '"' || quote === "'") && text.length > 1 && text.endsWith(quote)) text = text.slice(1, -1)
  }
  return text.replace(/\s+/g, ' ').trim() || command.trim()
}

/** Short mark for the collapsed row; anything other than a normal check stays visible there. */
export function hookMark(hooks: HookItem[]): { text: string; tone: 'hook' | 'warn' | 'bad' } | null {
  if (hooks.length === 0) return null
  if (hooks.some(hook => hook.status === 'blocked')) return { text: '실행 전 중단 요청', tone: 'bad' }
  if (hooks.some(hook => hook.status === 'failed')) return { text: 'Hook 오류', tone: 'bad' }
  if (hooks.some(hook => hook.status === 'stopped')) return { text: 'Hook 확인 취소', tone: 'warn' }
  return { text: hooks.every(hook => hook.phase === 'completed') ? 'Hook 확인' : 'Hook 확인 중', tone: 'hook' }
}
