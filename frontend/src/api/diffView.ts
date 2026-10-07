/** Unified diff split per file for display (EPIC-021 TASK-111). */
export type DiffLineKind = 'add' | 'del' | 'ctx' | 'hunk'
export interface DiffFile { path: string; lines: Array<{ kind: DiffLineKind; text: string }> }

/** Shows at most `maxLines` lines in total; `cut` says the rest was left out. */
export function parseUnifiedDiff(text: string, maxLines = 2000): { files: DiffFile[]; cut: boolean } {
  const files: DiffFile[] = []
  let current: DiffFile | null = null
  let shown = 0
  let cut = false
  for (const line of text.split('\n')) {
    if (line.startsWith('diff --git ')) {
      current = null
      continue
    }
    if (line.startsWith('--- ')) continue
    if (line.startsWith('+++ ')) {
      const raw = line.slice(4).trim()
      const path = raw === '/dev/null' ? '(삭제된 파일)' : raw.replace(/^[ab]\//, '')
      current = { path, lines: [] }
      files.push(current)
      continue
    }
    if (!current || line.startsWith('index ') || line.startsWith('new file mode') || line.startsWith('deleted file mode')) continue
    if (shown >= maxLines) {
      cut = true
      continue
    }
    const kind: DiffLineKind = line.startsWith('@@') ? 'hunk' : line.startsWith('+') ? 'add' : line.startsWith('-') ? 'del' : 'ctx'
    current.lines.push({ kind, text: line })
    shown += 1
  }
  return { files, cut }
}
