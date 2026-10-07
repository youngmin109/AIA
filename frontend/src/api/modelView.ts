/** Visible Codex models, read from Codex itself (EPIC-022 TASK-109). */
export interface CodexModel {
  model: string
  display_name: string
  description: string
  is_default: boolean
  default_effort: string | null
  efforts: Array<{ effort: string; description: string }>
}

const EFFORT_LABEL: Record<string, string> = {
  none: '생각 안 함',
  minimal: '아주 얕게',
  low: '얕게',
  medium: '보통',
  high: '깊게',
  xhigh: '아주 깊게',
  max: '최대',
  ultra: '최대 · 작업 나눠 맡기기',
}

export function effortLabel(effort: string | null | undefined): string {
  if (!effort) return '기본값'
  return EFFORT_LABEL[effort] ?? effort
}

/** Efforts offered for a model; the default model's when none is chosen. */
export function effortsFor(models: CodexModel[], model: string | null): CodexModel['efforts'] {
  const chosen = models.find(item => item.model === model) ?? models.find(item => item.is_default)
  return chosen?.efforts ?? []
}

/** "GPT Fast · 깊게"; falls back to the model Codex reported applying. */
export function modelChipText(models: CodexModel[], model: string | null, effort: string | null, applied?: string | null): string {
  const name = model ?? applied ?? null
  const display = models.find(item => item.model === name)?.display_name ?? name ?? 'Codex 기본 모델'
  return `${display} · ${effortLabel(effort)}`
}
