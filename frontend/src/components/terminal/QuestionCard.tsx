import { useState } from 'react'
import { Button } from '../common/Button'
import { GlossyIcon } from '../common/Glass'
import { useNow } from '../../hooks/useElapsed'
import type { QuestionRequest, UserQuestion } from './codexConversation'

const OTHER = '__other__'

/** Answer for one question, or null while it is still incomplete. */
function answerFor(question: UserQuestion, choice: string | undefined, text: string | undefined): string[] | null {
  const typed = (text ?? '').trim()
  if (question.secret || question.options.length === 0) return typed ? [typed] : null
  if (choice === OTHER) return typed ? [typed] : null
  return choice ? [choice] : null
}

/** Codex asking the user directly. A secret answer goes to Codex only; AIA keeps no copy. */
export function QuestionCard({ request, disabled, onSubmit }: {
  request: QuestionRequest
  disabled: boolean
  onSubmit: (answers: Record<string, string[]>) => boolean
}) {
  const [choices, setChoices] = useState<Record<string, string>>({})
  const [texts, setTexts] = useState<Record<string, string>>({})
  const [sent, setSent] = useState(false)
  const deadline = Date.parse(request.auto_resolve_at ?? '')
  const now = useNow(!Number.isNaN(deadline))
  const remaining = Number.isNaN(deadline) ? null : Math.max(0, Math.ceil((deadline - now) / 1000))
  const answers = Object.fromEntries(request.questions.map((question) => [question.id, answerFor(question, choices[question.id], texts[question.id])]))
  const complete = request.questions.every((question) => answers[question.id] !== null)

  function send(value: Record<string, string[]>) {
    if (onSubmit(value)) setSent(true)
  }

  return (
    <section className="glass-card question-card" aria-label="Codex 질문">
      <div className="question-head">
        <GlossyIcon tone="amber" icon="chat" size="sm" />
        <strong>Codex가 물어봐요</strong>
        {remaining !== null && <span className="muted question-timer">{remaining}초 뒤 Codex가 알아서 넘어가요</span>}
      </div>
      {request.questions.map((question) => {
        const typedOnly = question.secret || question.options.length === 0
        return (
          <fieldset key={question.id} className="question-item" disabled={disabled || sent}>
            <legend>{question.header ? <span className="question-header">{question.header}</span> : null}{question.question}</legend>
            {!typedOnly && (
              <div className="question-options" role="radiogroup" aria-label={question.question}>
                {question.options.map((option) => (
                  <button
                    key={option.label}
                    type="button"
                    role="radio"
                    aria-checked={choices[question.id] === option.label}
                    className="question-option"
                    onClick={() => setChoices((prev) => ({ ...prev, [question.id]: option.label }))}
                  >
                    <strong>{option.label}</strong>
                    {option.description && <small>{option.description}</small>}
                  </button>
                ))}
                {question.allow_other && (
                  <button
                    type="button"
                    role="radio"
                    aria-checked={choices[question.id] === OTHER}
                    className="question-option"
                    onClick={() => setChoices((prev) => ({ ...prev, [question.id]: OTHER }))}
                  >
                    <strong>직접 입력</strong>
                  </button>
                )}
              </div>
            )}
            {(typedOnly || choices[question.id] === OTHER) && (
              <input
                className="glass-input"
                type={question.secret ? 'password' : 'text'}
                autoComplete="off"
                aria-label={question.secret ? `${question.question} (비밀 입력)` : question.question}
                placeholder={question.secret ? '비밀 값은 Codex에만 전달되고 AIA 기록에 남지 않아요' : '답을 적어 주세요'}
                value={texts[question.id] ?? ''}
                onChange={(event) => setTexts((prev) => ({ ...prev, [question.id]: event.target.value }))}
              />
            )}
          </fieldset>
        )
      })}
      <div className="dialog-actions">
        <Button variant="text" disabled={disabled || sent} onClick={() => send({})}>건너뛰기</Button>
        <Button
          variant="cta"
          disabled={disabled || sent || !complete}
          onClick={() => send(Object.fromEntries(Object.entries(answers).filter((entry): entry is [string, string[]] => entry[1] !== null)))}
        >
          {sent ? '보내는 중…' : '답 보내기'}
        </Button>
      </div>
    </section>
  )
}
