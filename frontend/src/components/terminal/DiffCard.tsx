import { useState } from 'react'
import { Button } from '../common/Button'
import { codexDiff } from '../../api/endpoints'
import { parseUnifiedDiff, type DiffFile } from '../../api/diffView'

/** What one request changed. The text stays in AIA's memory and is fetched only when opened. */
export function DiffCard({ runId, turnId, files, fileCount, added, removed }: {
  runId: string
  turnId: string | null
  files: string[]
  fileCount: number
  added: number
  removed: number
}) {
  const [open, setOpen] = useState(false)
  const [parsed, setParsed] = useState<{ files: DiffFile[]; cut: boolean } | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function toggle() {
    if (open) {
      setOpen(false)
      return
    }
    setOpen(true)
    setError(null)
    try {
      const result = await codexDiff(runId, turnId)
      const view = parseUnifiedDiff(result.diff)
      setParsed({ files: view.files, cut: view.cut || Boolean(result.truncated) })
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '바뀐 내용을 불러오지 못했어요.')
    }
  }

  return (
    <div className="chat-card is-diff">
      <div className="chat-card-head">
        <strong>바뀐 내용</strong>
        <span className="muted">파일 {fileCount}개 · <span className="diff-add">+{added}</span> <span className="diff-del">−{removed}</span></span>
        <Button variant="text" className="is-compact" onClick={toggle}>{open ? '접기' : '바뀐 내용 보기'}</Button>
      </div>
      {!open && <span className="muted diff-files">{files.slice(0, 3).join(', ')}{fileCount > 3 ? ` 외 ${fileCount - 3}개` : ''}</span>}
      {open && error && <p className="danger-text">{error}</p>}
      {open && !error && !parsed && <p className="muted">불러오는 중…</p>}
      {open && parsed && (
        <div className="diff-body">
          {parsed.files.map((file, index) => (
            <section key={`${index}:${file.path}`} className="diff-file">
              <code className="diff-path">{file.path}</code>
              <pre>{file.lines.map((line, lineIndex) => <span key={lineIndex} className={`diff-line is-${line.kind}`}>{line.text || ' '}{'\n'}</span>)}</pre>
            </section>
          ))}
          {parsed.cut && <p className="faint-note">내용이 길어서 일부만 표시했어요.</p>}
        </div>
      )}
    </div>
  )
}
