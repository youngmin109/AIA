// Replaces the hand-rolled VT100 emulator (terminalScreen.ts) with the same
// renderer Orca/VS Code/Hyper use -- xterm.js owns escape-sequence parsing,
// painting, scrollback, and SGR colors, none of which the previous emulator
// had. AIA's Hook trust / command-approval / composer-ready detection still
// needs a plain-text snapshot of the visible screen to run its regexes
// against; bufferText() reconstructs that from xterm's buffer instead of
// consume()'s old return value, but the detection regexes themselves are
// unchanged and live in useTerminalSession.ts.
//
// xterm renders here in a fixed dark palette regardless of app theme,
// matching the .terminal-card container's own fixed-dark styling (see
// shell.css) -- this is not app-theme-driven on purpose.

import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

const THEME = {
  background: '#101827',
  foreground: '#d6e3fb',
  cursor: '#d6e3fb',
  cursorAccent: '#101827',
  selectionBackground: 'rgba(255, 255, 255, 0.22)',
  black: '#101827',
  red: '#ef6b74',
  green: '#6be2b7',
  yellow: '#eab04a',
  blue: '#5479f5',
  magenta: '#c792ea',
  cyan: '#5cd3f2',
  white: '#d6e3fb',
  brightBlack: '#5b6b8a',
  brightRed: '#ff8b93',
  brightGreen: '#8ff5cf',
  brightYellow: '#ffd27a',
  brightBlue: '#7b9bff',
  brightMagenta: '#e0aefc',
  brightCyan: '#8fe6ff',
  brightWhite: '#ffffff',
}

// Codex redraws this transient status line while a request is active. A
// bounded replay (reconnect, or the backend's own output cap) can leave a
// stale copy on screen after the real clear sequence fell outside the
// replay window; once the composer is back, showing it makes an idle
// session look stuck. Ported verbatim from terminalScreen.ts.
const TRANSIENT_PROGRESS_LINE = /^\s*[◦•]\s+Working\s+\(\d+s\b.*\)\s*$/i

export interface XtermAdapter {
  terminal: Terminal
  /** Re-measures the container and resizes the terminal to fit; returns the
   * resulting rows/cols so the caller can push them to the backend PTY. */
  fit: () => { rows: number; cols: number } | null
  write: (data: string, onDone?: () => void) => void
  /** Plain-text snapshot of the currently visible screen (not scrollback),
   * for the trust/approval/composer regex detection in useTerminalSession. */
  bufferText: (isWaiting: boolean) => string
  reset: () => void
  dispose: () => void
}

export function createXtermAdapter(container: HTMLDivElement): XtermAdapter {
  const terminal = new Terminal({
    fontFamily: '"Cascadia Code", Consolas, ui-monospace, monospace',
    fontSize: 13,
    lineHeight: 1.45,
    cursorBlink: true,
    scrollback: 5000,
    theme: THEME,
    // AIA's own textarea+button below the terminal is the only input path
    // (preserves the submit-settle/composer-echo/IME logic verbatim) --
    // xterm here is output-only and must never steal keyboard focus.
    disableStdin: true,
  })
  const fitAddon = new FitAddon()
  terminal.loadAddon(fitAddon)
  terminal.open(container)

  function fit(): { rows: number; cols: number } | null {
    try {
      fitAddon.fit()
    } catch {
      return null
    }
    return { rows: terminal.rows, cols: terminal.cols }
  }

  function bufferText(isWaiting: boolean): string {
    const buffer = terminal.buffer.active
    const lines: string[] = []
    for (let row = 0; row < terminal.rows; row += 1) {
      const line = buffer.getLine(buffer.baseY + row)
      if (line) lines.push(line.translateToString(true))
    }
    return lines.filter((line) => !(isWaiting && TRANSIENT_PROGRESS_LINE.test(line))).join('\n')
  }

  return {
    terminal,
    fit,
    write: (data, onDone) => terminal.write(data, onDone),
    bufferText,
    reset: () => terminal.reset(),
    dispose: () => terminal.dispose(),
  }
}
