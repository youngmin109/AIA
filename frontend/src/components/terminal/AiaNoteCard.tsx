import type { ReactNode } from 'react'
import { Button } from '../common/Button'
import { GlossyIcon } from '../common/Glass'
import { Icon } from '../common/Icon'
import type { AiaNote } from '../../api/securityNotes'

/** AIA's answer to a slash command; local to this window and dismissed with ×. */
export function AiaNoteCard({ note, onClose, children }: { note: AiaNote; onClose: () => void; children?: ReactNode }) {
  return (
    <section className="glass-card question-card aia-note" aria-label={note.title}>
      <div className="question-head">
        <GlossyIcon tone="accent" icon="shieldPlain" size="sm" />
        <strong>{note.title}</strong>
        <Button variant="icon" className="aia-note-close" onClick={onClose} aria-label="닫기"><Icon name="close" size={14} /></Button>
      </div>
      <ul className="aia-note-lines">
        {note.lines.map(line => <li key={line}>{line}</li>)}
      </ul>
      {note.footnote && <p className="faint-note">{note.footnote}</p>}
      {children}
    </section>
  )
}
