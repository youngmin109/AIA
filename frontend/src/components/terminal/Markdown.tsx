import { memo, type ReactNode } from 'react'
import { parseBlocks, type Align } from './markdownBlocks'

// Minimal Markdown for Codex answers: headings, lists, quotes, fenced code,
// tables, inline code, bold/italic and links. It builds React elements only
// (no innerHTML), so model output can never inject markup. Links are shown as
// text plus URL rather than anchors: navigating would replace the desktop
// app's own window. Unclosed fences (while streaming) render as code.

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

function alignClass(align: Align): string | undefined {
  return align ? `is-${align}` : undefined
}

/** Parsed again only when the text changes; a long conversation re-renders just the message that grew. */
export const Markdown = memo(function Markdown({ text }: { text: string }) {
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
          case 'table':
            return (
              <div key={key} className="md-table-wrap">
                <table className="md-table">
                  <thead>
                    <tr>{block.header.map((cell, column) => <th key={column} className={alignClass(block.aligns[column])}>{renderInline(cell, `${key}-h${column}`)}</th>)}</tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, rowIndex) => (
                      <tr key={rowIndex}>{row.map((cell, column) => <td key={column} className={alignClass(block.aligns[column])}>{renderInline(cell, `${key}-${rowIndex}-${column}`)}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          case 'paragraph':
            return <p key={key}>{renderInline(block.text, key)}</p>
        }
      })}
    </div>
  )
})
