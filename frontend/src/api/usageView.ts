/** Codex usage limits and conversation tokens in display form (EPIC-021 TASK-108). */
export interface UsageWindow { used_percent: number; window_minutes: number | null; resets_at: string | null }
export interface UsageLimits { windows: UsageWindow[]; reached?: string | null }
export interface TokenUsage { total_tokens: number; context_window: number | null }
export interface Usage { limits: UsageLimits | null; tokens: TokenUsage | null }

function count(value: number): string {
  return value.toLocaleString('ko-KR')
}

export function windowLabel(minutes: number | null): string {
  if (!minutes) return '사용 한도'
  if (minutes === 10080) return '주간'
  if (minutes % 1440 === 0) return minutes === 1440 ? '하루' : `${minutes / 1440}일`
  if (minutes % 60 === 0) return `${minutes / 60}시간`
  return `${minutes}분`
}

/** "2시간 10분 뒤 초기화"; null when Codex gave no reset time. */
export function resetLabel(resetsAt: string | null, now: number): string | null {
  const at = Date.parse(resetsAt ?? '')
  if (Number.isNaN(at)) return null
  const minutes = Math.max(0, Math.round((at - now) / 60_000))
  if (minutes < 1) return '곧 초기화'
  const days = Math.floor(minutes / 1440)
  const hours = Math.floor((minutes % 1440) / 60)
  const rest = minutes % 60
  const parts = days ? [`${days}일`, hours ? `${hours}시간` : ''] : hours ? [`${hours}시간`, rest ? `${rest}분` : ''] : [`${rest}분`]
  return `${parts.filter(Boolean).join(' ')} 뒤 초기화`
}

export function tokensLabel(tokens: TokenUsage | null): string | null {
  if (!tokens) return null
  const share = tokens.context_window ? Math.min(100, Math.round((tokens.total_tokens / tokens.context_window) * 100)) : null
  return `이번 대화 ${count(tokens.total_tokens)} 토큰${share !== null ? ` · 문맥 ${share}% 사용` : ''}`
}

/** The chip shows the tightest window; null hides it when Codex reports nothing. */
export function usageChip(usage: Usage): { text: string; low: boolean } | null {
  const windows = usage.limits?.windows ?? []
  if (windows.length) {
    const tightest = windows.reduce((a, b) => (b.used_percent > a.used_percent ? b : a))
    const left = 100 - tightest.used_percent
    return { text: `${windowLabel(tightest.window_minutes)} 한도 ${left}% 남음`, low: left <= 20 || Boolean(usage.limits?.reached) }
  }
  const tokens = tokensLabel(usage.tokens)
  return tokens ? { text: tokens, low: false } : null
}
