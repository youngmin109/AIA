import { useEffect, useRef, useState } from 'react'
import { apiGet } from '../../api/client'
import { guardianStatus, type GuardianStatus } from '../../api/guardianStatus'
import type { RunStatus, RunSummary } from '../../api/types'
import { GuardianFigure } from '../common/GuardianAvatar'
import { readPetSize, displayPetSize } from '../../api/petSizePreference'
import { isRunActive } from '../../api/sessionNavigation'

const UNKNOWN: GuardianStatus = { state: 'review', label: '확인 필요', headline: '보호 상태를 확인하는 중이에요', detail: '현재 상태를 확인하기 전에는 정상 보호로 해석하지 마세요.' }
const POLICY: Record<string, string> = { PROTECTED_DEVELOPMENT: '표준 보호', BASIC_DEVELOPMENT: '협업 개발', CONSERVATIVE_SECURITY: '변경 통제 강화', FREE_DEVELOPMENT: '관찰 전용', CUSTOM: '사용자 지정' }

/** Read-only observer in a separate native window; no security authority. */
export function DesktopGuardian() {
  useEffect(() => {
    const updateSize = () => displayPetSize(readPetSize())
    window.addEventListener('storage', updateSize)
    return () => window.removeEventListener('storage', updateSize)
  }, [])
  const [guardian, setGuardian] = useState(UNKNOWN)
  const [selected, setSelected] = useState<string | null>(null)
  const [policy, setPolicy] = useState('보호 실행 없음')
  const press = useRef<{ x: number; y: number } | null>(null)
  // The page starts unfolded; make the window match it (after a reload too).
  useEffect(() => {
    const unfold = () => { window.pywebview?.api?.set_guardian_folded?.(false).catch(() => {}) }
    if (window.pywebview?.api) unfold()
    window.addEventListener('pywebviewready', unfold)
    return () => window.removeEventListener('pywebviewready', unfold)
  }, [])
  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout>
    async function refresh() {
      try {
        const response = await apiGet<RunSummary[] | { runs: RunSummary[] }>('/api/runs')
        const runs = Array.isArray(response) ? response : response.runs
        // Runs left behind by a closed app (orphaned) are not live; never watch them.
        const active = runs.filter(isRunActive)
        const observations = await Promise.all(active.map(async run => {
          const status = await apiGet<RunStatus>(`/api/runs/${encodeURIComponent(run.session_id)}`)
          const conversation = run.launch_mode === 'codex_app_server' ? await apiGet<{ pending_approvals?: unknown[] }>(`/api/runs/${encodeURIComponent(run.session_id)}/codex/status`) : null
          return { id: run.session_id, profile: status.policy?.profile, guardian: guardianStatus({ ready: false, selected: true, status, approval: Boolean(conversation?.pending_approvals?.length) }) }
        }))
        const severity = { blocked: 3, review: 2, recovery: 1, normal: 0 }
        observations.sort((a, b) => severity[b.guardian.state] - severity[a.guardian.state])
        if (!cancelled) {
          const current = observations[0]
          setSelected(current?.id ?? null); setPolicy(current ? POLICY[current.profile ?? ''] ?? '정책 확인 필요' : '보호 실행 없음')
          setGuardian(current?.guardian ?? { state: 'normal', label: '실행 대기', headline: '지금 보호 실행 중인 작업은 없어요', detail: '최소화해도 여기서 실행 상태를 안내해요.' })
        }
      } catch {
        if (!cancelled) { setGuardian({ ...UNKNOWN, headline: 'AIA 연결을 확인해 주세요' }); setPolicy('최신 상태 확인 불가') }
      } finally { if (!cancelled) timer = setTimeout(refresh, 3000) }
    }
    refresh()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [])
  return <div className={`desktop-guardian is-${guardian.state}`}>
    <button type="button" className="desktop-guardian-figure pywebview-drag-region" aria-label={`AIA 열기 · ${guardian.label}`} title={`${guardian.label} · ${policy}\n${guardian.headline}\n누르면 AIA가 열려요. 끌어서 옮길 수 있어요.`}
      onMouseDown={event => { press.current = { x: event.screenX, y: event.screenY } }}
      onClick={event => {
        const start = press.current
        press.current = null
        if (event.detail !== 0 && start && Math.hypot(event.screenX - start.x, event.screenY - start.y) > 4) return
        window.pywebview?.api?.open_main?.(selected ? 'work' : 'home', selected).catch(() => {})
      }}>
      <GuardianFigure state={guardian.state} alt="아이아 가디언" />
    </button>
    <span className="desktop-guardian-indicator" role="status" aria-live="polite" aria-label={`${guardian.label} · ${policy} · ${guardian.headline}`} title={`${guardian.label} · ${policy}`} />
    <button type="button" className="desktop-guardian-help" aria-label="아이아 도움말과 오류 신고" title="도움말 · 오류 신고" onClick={() => window.pywebview?.api?.open_guardian_help?.('start').catch(() => {})}>?</button>
  </div>
}
