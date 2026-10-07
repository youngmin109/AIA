import { useState } from 'react'
import { Button } from '../common/Button'
import { effortLabel, effortsFor, modelChipText, type CodexModel } from '../../api/modelView'

type Apply = (model: string | null, effort: string | null) => boolean

/** Model and reasoning effort for the next requests. Only these two values ever reach Codex from here. */
export function ModelChip({ models, model, effort, applied, disabled, onApply, open, onOpenChange }: {
  models: CodexModel[]
  model: string | null
  effort: string | null
  applied: string | null
  disabled: boolean
  onApply: Apply
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  if (!models.length) return null
  return (
    <span className="usage-chip">
      <button type="button" className="chip is-small" aria-expanded={open} onClick={() => onOpenChange(!open)}>
        {modelChipText(models, model, effort, applied)}
      </button>
      {/* Mounted per opening so the choices always start from the current settings. */}
      {open && <ModelPicker models={models} model={model} effort={effort} disabled={disabled} onApply={(next, nextEffort) => {
        const sent = onApply(next, nextEffort)
        if (sent) onOpenChange(false)
        return sent
      }} />}
    </span>
  )
}

function ModelPicker({ models, model, effort, disabled, onApply }: { models: CodexModel[]; model: string | null; effort: string | null; disabled: boolean; onApply: Apply }) {
  const [nextModel, setNextModel] = useState<string>(model ?? '')
  const [nextEffort, setNextEffort] = useState<string>(effort ?? '')
  const efforts = effortsFor(models, nextModel || null)
  return (
    <span className="usage-pop glass-card" role="dialog" aria-label="모델과 생각 깊이">
      <label className="model-field">
        <span>모델</span>
        <select className="glass-input" value={nextModel} onChange={(event) => { setNextModel(event.target.value); setNextEffort('') }}>
          <option value="">Codex 기본값</option>
          {models.map(item => <option key={item.model} value={item.model}>{item.display_name}</option>)}
        </select>
      </label>
      <label className="model-field">
        <span>생각 깊이</span>
        <select className="glass-input" value={nextEffort} onChange={(event) => setNextEffort(event.target.value)}>
          <option value="">모델 기본값</option>
          {efforts.map(item => <option key={item.effort} value={item.effort}>{effortLabel(item.effort)}</option>)}
        </select>
      </label>
      <small className="faint-note">다음 요청부터 적용돼요. 보호 설정은 바뀌지 않아요.</small>
      <Button variant="cta" className="is-compact" disabled={disabled} onClick={() => onApply(nextModel || null, nextEffort || null)}>적용</Button>
    </span>
  )
}
