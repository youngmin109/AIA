import type { ReactNode } from 'react'

// Minimal Markdown for Codex answers: headings, lists, quotes, fenced code,
// inline code, bold/italic and links. It builds React elements only (no
// innerHTML), so model output can never inject markup. Links are shown as
// text plus URL rather than anchors: navigating would replace the desktop
// app's own window. Unclosed fences (while streaming) render as code.

type Block =
  | { kind: 'code'; text: string }
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'list'; ordered: boolean; items: string[] }
  | { kind: 'quote'; text: string }
  | { kind: 'rule' }
  | { kind: 'paragraph'; text: string }

const LIST_ITEM = /^\s*(?:([-*+])|(\d+)[.)])\s+(.*)$/

function parseBlocks(source: string): Block[] {
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
      !lines[index].startsWith('>')
    ) {
      paragraph.push(lines[index])
      index += 1
    }
    blocks.push({ kind: 'paragraph', text: paragraph.join('\n') })
  }
  return blocks
}

const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*|__[^_\n]+__)|(\*[^*\s][^*\n]*\*|_[^_\s][^_\n]*_)|(\[[^\]\n]+\]\([^)\s]+\))/g

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = []
  let last = 0
  let count = 0
  for (const match of text.matchAll(INLINE)) {
    const start = match.index ?? 0
    if (start > last) nodes.push(text.slice(last, start))
    const token = match[0]
    const key = `${keyPrefix}-${count++}`
    if (match[1]) nodes.push(<code key={key}>{token.slice(1, -1)}</code>)
    else if (match[2]) nodes.push(<strong key={key}>{renderInline(token.slice(2, -2), key)}</strong>)
    else if (match[3]) nodes.push(<em key={key}>{renderInline(token.slice(1, -1), key)}</em>)
    else {
      const link = token.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/)
      nodes.push(
        <span key={key} className="md-link">
          {link?.[1] ?? token}
          {link && <span className="md-link-url"> ({link[2]})</span>}
        </span>,
      )
    }
    last = start + token.length
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

export function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      {parseBlocks(text).map((block, index) => {
        const key = `b${index}`
        switch (block.kind) {
          case 'code':
            return <pre key={key} className="md-code">{block.text}</pre>
          case 'heading':
            return <div key={key} className={`md-heading md-h${Math.min(block.level, 3)}`}>{renderInline(block.text, key)}</div>
          case 'list': {
            const items = block.items.map((item, itemIndex) => <li key={`${key}-${itemIndex}`}>{renderInline(item, `${key}-${itemIndex}`)}</li>)
            return block.ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>
          }
          case 'quote':
            return <blockquote key={key}>{renderInline(block.text, key)}</blockquote>
          case 'rule':
            return <hr key={key} />
          case 'paragraph':
            return <p key={key}>{renderInline(block.text, key)}</p>
        }
      })}
    </div>
  )
}
