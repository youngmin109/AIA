// Ported near-verbatim from the hand-rolled VT100/ANSI subset emulator in
// workbench.html (terminalScreen IIFE). Framework-agnostic and
// DOM-independent: the original wrote directly into a DOM node's
// textContent from inside its own requestAnimationFrame batching; this
// version instead calls `onFrame()` once per animation frame after new
// data lands, and lets the caller read `text()`/`hasOutput()` from inside
// that callback to own the DOM write and scroll-follow behavior.
//
// SGR color codes are intentionally not interpreted (plain readable text
// surface only) -- this mirrors the original's explicit design choice, not
// an oversight.

export interface TerminalScreen {
  consume(data: string): void
  resize(nextRows: number, nextCols: number): void
  reset(): void
  text(): string
  hasOutput(): boolean
  /** Re-schedules onFrame without marking hasOutput or touching the
   * buffer -- used when a caller-side state change (e.g. going idle)
   * should re-derive the visible text (transient-line filtering depends
   * on that state) without implying new PTY output arrived. */
  refresh(): void
}

export interface CreateTerminalScreenOptions {
  initialRows?: number
  initialCols?: number
  /** True while the caller's activity state is "WAITING" (idle). Used to
   * filter a transient "Working (Ns)" progress line Codex can leave behind
   * in a replayed screen. */
  isWaiting?: () => boolean
  /** Scheduled via requestAnimationFrame, coalesced like the original. */
  onFrame?: () => void
}

export function createTerminalScreen(options: CreateTerminalScreenOptions = {}): TerminalScreen {
  let rows = options.initialRows || 32
  let cols = options.initialCols || 120
  let cursorRow = 0
  let cursorCol = 0
  let savedRow = 0
  let savedCol = 0
  let buffer = ''
  let cells: string[][] = []
  let scrollTop = 0
  let scrollBottom = rows - 1
  let renderPending = false
  let hasOutputFlag = false
  const isWaiting = options.isWaiting ?? (() => false)
  const onFrame = options.onFrame ?? (() => {})

  const blankLine = () => Array(cols).fill(' ')

  const reset = () => {
    cells = Array.from({ length: rows }, blankLine)
    cursorRow = 0
    cursorCol = 0
    savedRow = 0
    savedCol = 0
    scrollTop = 0
    scrollBottom = rows - 1
  }

  const scrollUp = (count = 1) => {
    const amount = Math.max(1, Math.min(count, scrollBottom - scrollTop + 1))
    cells.splice(scrollTop, amount)
    cells.splice(scrollBottom - amount + 1, 0, ...Array.from({ length: amount }, blankLine))
  }
  const scrollDown = (count = 1) => {
    const amount = Math.max(1, Math.min(count, scrollBottom - scrollTop + 1))
    cells.splice(scrollBottom - amount + 1, amount)
    cells.splice(scrollTop, 0, ...Array.from({ length: amount }, blankLine))
  }
  const lineFeed = () => {
    if (cursorRow === scrollBottom) scrollUp()
    else if (cursorRow < rows - 1) cursorRow += 1
  }
  const reverseIndex = () => {
    if (cursorRow === scrollTop) scrollDown()
    else if (cursorRow > 0) cursorRow -= 1
  }
  const insertLines = (count = 1) => {
    if (cursorRow < scrollTop || cursorRow > scrollBottom) return
    const amount = Math.max(1, Math.min(count, scrollBottom - cursorRow + 1))
    cells.splice(cursorRow, 0, ...Array.from({ length: amount }, blankLine))
    cells.splice(scrollBottom + 1, amount)
  }
  const deleteLines = (count = 1) => {
    if (cursorRow < scrollTop || cursorRow > scrollBottom) return
    const amount = Math.max(1, Math.min(count, scrollBottom - cursorRow + 1))
    cells.splice(cursorRow, amount)
    cells.splice(scrollBottom - amount + 1, 0, ...Array.from({ length: amount }, blankLine))
  }
  const clamp = () => {
    cursorRow = Math.max(0, Math.min(rows - 1, cursorRow))
    cursorCol = Math.max(0, Math.min(cols, cursorCol))
  }
  const clearRange = (row: number, start: number, end: number) => {
    if (row < 0 || row >= rows) return
    for (let index = Math.max(0, start); index < Math.min(cols, end); index += 1) cells[row][index] = ' '
  }
  const clearScreen = (mode: number) => {
    if (mode === 2 || mode === 3) {
      reset()
      return
    }
    if (mode === 1) {
      for (let row = 0; row <= cursorRow; row += 1) clearRange(row, 0, row === cursorRow ? cursorCol + 1 : cols)
      return
    }
    clearRange(cursorRow, cursorCol, cols)
    for (let row = cursorRow + 1; row < rows; row += 1) clearRange(row, 0, cols)
  }
  const clearLine = (mode: number) => {
    if (mode === 2) clearRange(cursorRow, 0, cols)
    else if (mode === 1) clearRange(cursorRow, 0, cursorCol + 1)
    else clearRange(cursorRow, cursorCol, cols)
  }

  // Codex renders East Asian characters as two terminal cells. Treating
  // them as one cell makes cursor movement drift and causes Korean text to
  // appear spaced out or overwritten in the browser terminal.
  const cellWidth = (character: string): number => {
    const codePoint = character.codePointAt(0)
    if (!codePoint) return 0
    if (codePoint >= 0x0300 && codePoint <= 0x036f) return 0
    if (codePoint >= 0x1ab0 && codePoint <= 0x1aff) return 0
    if (codePoint >= 0x1dc0 && codePoint <= 0x1dff) return 0
    if (codePoint >= 0x20d0 && codePoint <= 0x20ff) return 0
    if (codePoint >= 0xfe00 && codePoint <= 0xfe0f) return 0
    if (
      (codePoint >= 0x1100 && codePoint <= 0x115f) ||
      (codePoint >= 0x2329 && codePoint <= 0x232a) ||
      (codePoint >= 0x2e80 && codePoint <= 0xa4cf) ||
      (codePoint >= 0xac00 && codePoint <= 0xd7a3) ||
      (codePoint >= 0xf900 && codePoint <= 0xfaff) ||
      (codePoint >= 0xfe10 && codePoint <= 0xfe19) ||
      (codePoint >= 0xfe30 && codePoint <= 0xfe6f) ||
      (codePoint >= 0xff00 && codePoint <= 0xff60) ||
      (codePoint >= 0xffe0 && codePoint <= 0xffe6) ||
      (codePoint >= 0x1f300 && codePoint <= 0x1faff)
    )
      return 2
    return 1
  }

  const paramNumbers = (raw: string) => raw.replace(/^\?/, '').split(';').map((item) => Number.parseInt(item || '0', 10) || 0)
  const first = (values: number[], fallback = 1) => values[0] || fallback

  const csi = (raw: string, final: string) => {
    const values = paramNumbers(raw)
    switch (final) {
      case 'A':
        cursorRow -= first(values)
        break
      case 'B':
        cursorRow += first(values)
        break
      case 'C':
        cursorCol += first(values)
        break
      case 'D':
        cursorCol -= first(values)
        break
      case 'E':
        cursorRow += first(values)
        cursorCol = 0
        break
      case 'F':
        cursorRow -= first(values)
        cursorCol = 0
        break
      case 'G':
        cursorCol = first(values) - 1
        break
      case 'H':
      case 'f':
        cursorRow = (values[0] || 1) - 1
        cursorCol = (values[1] || 1) - 1
        break
      case 'J':
        clearScreen(values[0])
        break
      case 'K':
        clearLine(values[0])
        break
      case 'P': {
        const count = first(values)
        const line = cells[cursorRow]
        line.splice(cursorCol, count)
        line.push(...Array(count).fill(' '))
        break
      }
      case '@': {
        const count = first(values)
        const line = cells[cursorRow]
        line.splice(cursorCol, 0, ...Array(count).fill(' '))
        line.length = cols
        break
      }
      case 'L':
        insertLines(first(values))
        break
      case 'M':
        deleteLines(first(values))
        break
      case 'S':
        scrollUp(first(values))
        break
      case 'T':
        scrollDown(first(values))
        break
      case 'X':
        clearRange(cursorRow, cursorCol, cursorCol + first(values))
        break
      case 's':
        savedRow = cursorRow
        savedCol = cursorCol
        break
      case 'u':
        cursorRow = savedRow
        cursorCol = savedCol
        break
      case 'd':
        cursorRow = first(values) - 1
        break
      case 'r': {
        const top = values[0] || 1
        const bottom = values[1] || rows
        if (top >= 1 && top < bottom && bottom <= rows) {
          scrollTop = top - 1
          scrollBottom = bottom - 1
          cursorRow = 0
          cursorCol = 0
        }
        break
      }
      // m (colors), h/l (modes), and n (status query) do not change the
      // readable text surface. The scroll region and line operations above
      // are needed by Codex's full-screen composer redraws.
      default:
        break
    }
    clamp()
  }

  const put = (character: string) => {
    if (character === '\r') {
      cursorCol = 0
      return
    }
    if (character === '\n') {
      lineFeed()
      return
    }
    if (character === '\b') {
      cursorCol = Math.max(0, cursorCol - 1)
      if (cells[cursorRow][cursorCol] === '' && cursorCol > 0) cursorCol -= 1
      return
    }
    if (character === '\t') {
      cursorCol = Math.min(cols, cursorCol + (8 - (cursorCol % 8)))
      return
    }
    if (character < ' ' || character === '\x7f') return
    const width = cellWidth(character)
    if (!width) return
    if (cursorCol >= cols || (width === 2 && cursorCol === cols - 1)) {
      cursorCol = 0
      lineFeed()
    }
    // A wide CJK glyph owns the next cell as an empty continuation cell.
    // Keep the continuation cell empty; CSI overwrite paths already clear
    // the affected range before writing into it.
    cells[cursorRow][cursorCol] = character
    if (width === 2 && cursorCol + 1 < cols) cells[cursorRow][cursorCol + 1] = ''
    cursorCol += width
  }

  const scheduleRender = () => {
    if (renderPending) return
    renderPending = true
    requestAnimationFrame(() => {
      renderPending = false
      onFrame()
    })
  }

  const transientProgressLine = /^\s*[◦•]\s+Working\s+\(\d+s\b.*\)\s*$/i
  const visibleText = () =>
    cells
      .map((line) => line.join('').replace(/\s+$/, ''))
      // Codex redraws this transient status line while a request is active.
      // Some terminal output paths leave the old line in the replayed
      // screen; once the composer is back, showing it makes an idle
      // session look stuck.
      .filter((line) => !(isWaiting() && transientProgressLine.test(line)))
      .join('\n')

  const consume = (data: string) => {
    buffer += String(data || '')
    let index = 0
    while (index < buffer.length) {
      const character = String.fromCodePoint(buffer.codePointAt(index)!)
      const characterLength = character.length
      if (character !== '\x1b') {
        put(character)
        index += characterLength
        continue
      }
      if (index + 1 >= buffer.length) break
      const kind = buffer[index + 1]
      if (kind === '[') {
        const match = buffer.slice(index + 2).match(/^[0-?]*[ -/]*[@-~]/)
        if (!match) break
        const sequence = match[0]
        const final = sequence[sequence.length - 1]
        csi(sequence.slice(0, -1), final)
        index += 2 + sequence.length
        continue
      }
      if (kind === ']') {
        const rest = buffer.slice(index + 2)
        const end = rest.search(/[\x07]|\x1b\\/)
        if (end < 0) break
        index += 2 + end + (rest[end] === '\x1b' ? 2 : 1)
        continue
      }
      if (kind === 'c') {
        reset()
        index += 2
        continue
      }
      if (kind === 'D') {
        lineFeed()
        index += 2
        continue
      }
      if (kind === 'M') {
        reverseIndex()
        index += 2
        continue
      }
      if (kind === 'E') {
        lineFeed()
        cursorCol = 0
        index += 2
        continue
      }
      if (kind === '7') {
        savedRow = cursorRow
        savedCol = cursorCol
        index += 2
        continue
      }
      if (kind === '8') {
        cursorRow = savedRow
        cursorCol = savedCol
        index += 2
        continue
      }
      index += 2
    }
    buffer = buffer.slice(index)
    hasOutputFlag = true
    scheduleRender()
  }

  const resize = (nextRows: number, nextCols: number) => {
    if (nextRows === rows && nextCols === cols) return
    // Preserve the empty continuation cell of a wide CJK glyph. Coercing
    // `''` to a literal space makes Korean text spread out after a resize
    // or browser reconnect.
    const next = Array.from({ length: nextRows }, (_, row) =>
      Array.from({ length: nextCols }, (_, col) => cells[row]?.[col] ?? ' '),
    )
    rows = nextRows
    cols = nextCols
    cells = next
    scrollTop = 0
    scrollBottom = nextRows - 1
    clamp()
    scheduleRender()
  }

  const clear = () => {
    reset()
    hasOutputFlag = false
    scheduleRender()
  }

  reset()

  return {
    consume,
    resize,
    reset: clear,
    text: visibleText,
    hasOutput: () => hasOutputFlag,
    refresh: scheduleRender,
  }
}
