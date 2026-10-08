import { useState } from 'react'
import { Button } from '../common/Button'
import { GlossyIcon } from '../common/Glass'
import type { ElicitationField, ElicitationRequest } from './codexConversation'

type Value = string | boolean | string[]
type Action = 'accept' | 'decline' | 'cancel'

const INPUT_TYPES: Record<string, string> = { email: 'email', uri: 'url', date: 'date', 'date-time': 'datetime-local' }

function initialValue(field: ElicitationField): Value {
  if (field.kind === 'boolean') return field.default === true
  if (field.kind === 'multi') return Array.isArray(field.default) ? field.default.filter((item): item is string => typeof item === 'string') : []
  return typeof field.default === 'string' || typeof field.default === 'number' ? String(field.default) : ''
}

/** Submitted value for one field; undefined when it is left empty. Throws on an invalid number. */
function submitted(field: ElicitationField, value: Value): unknown {
  if (field.kind === 'boolean') return value
  if (field.kind === 'multi') return (value as string[]).length ? value : undefined
  const text = String(value).trim()
  if (!text) return undefined
  if (field.kind === 'number' || field.kind === 'integer') {
    const number = Number(text)
    if (!Number.isFinite(number) || (field.kind === 'integer' && !Number.isInteger(number))) throw new Error(field.title)
    return number
  }
  return text
}

/** An MCP server asking for input through Codex. Values go to Codex only; AIA keeps the action alone. */
export function ElicitationCard({ request, disabled, onRespond }: {
  request: ElicitationRequest
  disabled: boolean
  onRespond: (action: Action, content?: Record<string, unknown>) => boolean
}) {
  const [values, setValues] = useState<Record<string, Value>>(() => Object.fromEntries(request.fields.map((field) => [field.name, initialValue(field)])))
  const [sent, setSent] = useState(false)
  const [invalid, setInvalid] = useState<string | null>(null)
  const busy = disabled || sent

  function respond(action: Action, content?: Record<string, unknown>) {
    if (onRespond(action, content)) setSent(true)
  }

  function submitForm() {
    const content: Record<string, unknown> = {}
    try {
      for (const field of request.fields) {
        const value = submitted(field, values[field.name])
        if (value === undefined) {
          if (field.required) throw new Error(field.title)
          continue
        }
        content[field.name] = value
      }
    } catch (error) {
      setInvalid(error instanceof Error ? error.message : '입력값')
      return
    }
    setInvalid(null)
    respond('accept', content)
  }

  function openAndContinue() {
    if (!request.url) return
    window.open(request.url, '_blank', 'noopener,noreferrer')
    respond('accept')
  }

  const set = (name: string, value: Value) => setValues((prev) => ({ ...prev, [name]: value }))

  return (
    <section className="glass-card question-card" aria-label="외부 도구 입력 요청">
      <div className="question-head">
        <GlossyIcon tone="amber" icon="tree" size="sm" />
        <strong>외부 도구 {request.server}가 입력을 요청해요</strong>
        <span className="badge is-neutral">AIA 보호 범위 밖</span>
      </div>
      {request.message && <p className="question-message">{request.message}</p>}

      {request.supported && request.mode === 'url' && request.url && (
        <div className="elicitation-url">
          <span className="muted">이 주소를 바깥 브라우저로 열어요</span>
          <strong>{request.url_host}</strong>
          <code>{request.url}</code>
        </div>
      )}

      {request.supported && request.mode === 'form' && request.fields.map((field) => (
        <fieldset key={field.name} className="question-item" disabled={busy}>
          <legend>{field.title}{field.required ? ' *' : ''}</legend>
          {field.description && <small className="muted">{field.description}</small>}
          {field.kind === 'boolean' ? (
            <label className="elicitation-check">
              <input type="checkbox" checked={values[field.name] === true} onChange={(event) => set(field.name, event.target.checked)} />
              <span>{values[field.name] === true ? '예' : '아니요'}</span>
            </label>
          ) : field.kind === 'select' || field.kind === 'multi' ? (
            <div className="question-options" role={field.kind === 'select' ? 'radiogroup' : 'group'} aria-label={field.title}>
              {(field.options ?? []).map((option) => {
                const current = values[field.name]
                const checked = field.kind === 'multi' ? (current as string[]).includes(option.value) : current === option.value
                return (
                  <button
                    key={option.value}
                    type="button"
                    role={field.kind === 'select' ? 'radio' : 'checkbox'}
                    aria-checked={checked}
                    className="question-option"
                    onClick={() => set(field.name, field.kind === 'multi'
                      ? (checked ? (current as string[]).filter((item) => item !== option.value) : [...(current as string[]), option.value])
                      : option.value)}
                  >
                    <strong>{option.label}</strong>
                  </button>
                )
              })}
            </div>
          ) : (
            <input
              className="glass-input"
              type={field.kind === 'text' ? INPUT_TYPES[field.format ?? ''] ?? 'text' : 'number'}
              step={field.kind === 'integer' ? 1 : undefined}
              min={field.minimum ?? undefined}
              max={field.maximum ?? undefined}
              aria-label={field.title}
              value={String(values[field.name] ?? '')}
              onChange={(event) => set(field.name, event.target.value)}
            />
          )}
        </fieldset>
      ))}

      {!request.supported && (
        <p className="faint-note">AIA 화면에서 그릴 수 없는 입력 요청이에요. 거절하거나 취소할 수 있어요. 필요하면 Codex 앱에서 처리하세요.</p>
      )}
      {invalid && <p className="danger-text" role="alert">"{invalid}" 값을 확인해 주세요.</p>}

      <div className="dialog-actions">
        <Button variant="text" disabled={busy} onClick={() => respond('cancel')}>취소</Button>
        <Button variant="outline" disabled={busy} onClick={() => respond('decline')}>거절</Button>
        {request.supported && request.mode === 'url' && (
          <Button variant="cta" disabled={busy} onClick={openAndContinue}>{sent ? '보내는 중…' : '주소 열고 계속'}</Button>
        )}
        {request.supported && request.mode === 'form' && (
          <Button variant="cta" disabled={busy} onClick={submitForm}>{sent ? '보내는 중…' : '보내기'}</Button>
        )}
      </div>
    </section>
  )
}
