// Block structure of the Markdown in Codex answers; rendered by Markdown.tsx.

export type Align = 'left' | 'center' | 'right' | null

export type Block =
  | { kind: 'code'; text: string }
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'list'; ordered: boolean; items: string[] }
  | { kind: 'quote'; text: string }
  | { kind: 'rule' }
  | { kind: 'table'; aligns: Align[]; header: string[]; rows: string[][] }
  | { kind: 'paragraph'; text: string }

const LIST_ITEM = /^\s*(?:([-*+])|(\d+)[.)])\s+(.*)$/
const TABLE_DELIMITER = /^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$/

/** Cells of a `| a | b |` row. A pipe inside inline code or escaped as `\|` stays in its cell. */
export function splitTableRow(line: string): string[] {
  let text = line.trim()
  if (text.startsWith('|')) text = text.slice(1)
  if (text.endsWith('|') && !text.endsWith('\\|')) text = text.slice(0, -1)
  const cells: string[] = []
  let current = ''
  let inCode = false
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]
    if (char === '\\' && text[index + 1] === '|') {
      current += '|'
      index += 1
      continue
    }
    if (char === '`') inCode = !inCode
    if (char === '|' && !inCode) {
      cells.push(current.trim())
      current = ''
      continue
    }
    current += char
  }
  cells.push(current.trim())
  return cells
}

/** A header row with pipes, followed by a `|---|:--:|` row of the same width (GFM). */
function isTableStart(lines: string[], index: number): boolean {
  const header = lines[index]
  const delimiter = lines[index + 1]
  if (delimiter === undefined || !header.includes('|') || !delimiter.includes('|') || !TABLE_DELIMITER.test(delimiter)) return false
  return splitTableRow(header).length === splitTableRow(delimiter).length
}

function alignOf(cell: string): Align {
  const left = cell.startsWith(':')
  const right = cell.endsWith(':')
  return left && right ? 'center' : right ? 'right' : left ? 'left' : null
}

export function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n/g, '\n').split('\n')
  const blocks: Block[] = []
  let index = 0
  while (index < lines.length) {
    const line = lines[index]
    const fence = line.match(/^\s*(```|~~~)/)
    if (fence) {
      const body: string[] = []
      index += 1
      while (index < lines.length && !lines[index].trim().startsWith(fence[1])) {
        body.push(lines[index])
        index += 1
      }
      index += 1
      blocks.push({ kind: 'code', text: body.join('\n') })
      continue
    }
    if (!line.trim()) {
      index += 1
      continue
    }
    if (isTableStart(lines, index)) {
      const header = splitTableRow(line)
      const aligns = splitTableRow(lines[index + 1]).map(alignOf)
      const rows: string[][] = []
      index += 2
      while (index < lines.length && lines[index].trim() && lines[index].includes('|')) {
        // Like GFM: short rows get empty cells, extra cells are dropped.
        const cells = splitTableRow(lines[index])
        rows.push(header.map((_, column) => cells[column] ?? ''))
        index += 1
      }
      blocks.push({ kind: 'table', aligns, header, rows })
      continue
    }
    const heading = line.match(/^(#{1,6})\s+(.*)$/)
    if (heading) {
      blocks.push({ kind: 'heading', level: heading[1].length, text: heading[2] })
      index += 1
      continue
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      blocks.push({ kind: 'rule' })
      index += 1
      continue
    }
    const listMatch = line.match(LIST_ITEM)
    if (listMatch) {
      const ordered = Boolean(listMatch[2])
      const items: string[] = []
      while (index < lines.length) {
        const item = lines[index].match(LIST_ITEM)
        if (item && Boolean(item[2]) === ordered) {
          items.push(item[3])
        } else if (items.length && /^\s{2,}\S/.test(lines[index])) {
          items[items.length - 1] += `\n${lines[index].trim()}`
        } else {
          break
        }
        index += 1
      }
      blocks.push({ kind: 'list', ordered, items })
      continue
    }
    if (line.startsWith('>')) {
      const quoted: string[] = []
      while (index < lines.length && lines[index].startsWith('>')) {
        quoted.push(lines[index].replace(/^>\s?/, ''))
        index += 1
      }
      blocks.push({ kind: 'quote', text: quoted.join('\n') })
      continue
    }
    const paragraph: string[] = []
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^\s*(```|~~~)/.test(lines[index]) &&
      !/^#{1,6}\s/.test(lines[index]) &&
      !LIST_ITEM.test(lines[index]) &&
      !lines[index].startsWith('>') &&
      !(paragraph.length > 0 && isTableStart(lines, index))
    ) {
      paragraph.push(lines[index])
      index += 1
    }
    blocks.push({ kind: 'paragraph', text: paragraph.join('\n') })
  }
  return blocks
}
