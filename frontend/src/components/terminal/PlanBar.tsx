import { useState } from 'react'
import { Icon } from '../common/Icon'
import type { CodexPlan } from './codexConversation'

const STATUS_LABEL: Record<string, string> = { pending: '대기', inProgress: '진행 중', completed: '완료' }

/** Codex's own step plan for the current request, folded by default. */
export function PlanBar({ plan }: { plan: CodexPlan }) {
  const [open, setOpen] = useState(false)
  if (!plan.steps.length) return null
  const done = plan.steps.filter(step => step.status === 'completed').length
  const current = plan.steps.find(step => step.status === 'inProgress')
  return (
    <section className="chat-plan" aria-label="Codex 작업 계획">
      <button type="button" className="chat-plan-head" aria-expanded={open} onClick={() => setOpen(value => !value)}>
        <strong>작업 계획 {done}/{plan.steps.length}</strong>
        <span className="muted">{current ? `지금 · ${current.step}` : done === plan.steps.length ? '모두 끝났어요' : plan.explanation ?? ''}</span>
        <span className={`chat-plan-caret${open ? ' is-open' : ''}`} aria-hidden="true"><Icon name="arrowRight" size={14} /></span>
      </button>
      {open && (
        <ol className="chat-plan-steps">
          {plan.steps.map((step, index) => (
            <li key={`${index}:${step.step}`} className={`is-${step.status}`}>
              <span className="chat-plan-mark" aria-hidden="true">{step.status === 'completed' ? <Icon name="check" size={14} /> : null}</span>
              <span>{step.step}</span>
              <small className="muted">{STATUS_LABEL[step.status] ?? step.status}</small>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
