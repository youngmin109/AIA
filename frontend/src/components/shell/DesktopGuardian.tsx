import { useEffect, useRef, useState } from 'react'
import { apiGet } from '../../api/client'
import { guardianStatus, type GuardianStatus } from '../../api/guardianStatus'
import type { RunStatus, RunSummary } from '../../api/types'
import { GuardianFigure } from '../common/GuardianAvatar'
import { Button } from '../common/Button'
import { readPetSize } from '../../api/petSizePreference'
import { isRunActive } from '../../api/sessionNavigation'

const UNKNOWN: GuardianStatus = { state: 'review', label: '확인 필요', headline: '보호 상태를 확인하는 중이에요', detail: '현재 상태를 확인하기 전에는 정상 보호로 해석하지 마세요.' }
const POLICY: Record<string, string> = { PROTECTED_DEVELOPMENT: '표준 보호', BASIC_DEVELOPMENT: '협업 개발', CONSERVATIVE_SECURITY: '변경 통제 강화', FREE_DEVELOPMENT: '관찰 전용', CUSTOM: '사용자 지정' }

/** Read-only observer in a separate native window; no security authority. */
export function DesktopGuardian() {
  useEffect(() => {
    const updateSize = () => { document.documentElement.dataset.petSize = readPetSize() }
    window.addEventListener('storage', updateSize)
    return () => window.removeEventListener('storage', updateSize)
  }, [])
  const [guardian, setGuardian] = useState(UNKNOWN)
  const [selected, setSelected] = useState<string | null>(null)
  const [policy, setPolicy] = useState('보호 실행 없음')
  const [folded, setFolded] = useState(false)
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
  function fold(next: boolean) {
    const setWindow = window.pywebview?.api?.set_guardian_folded
    if (!setWindow) return
    setFolded(next)
    setWindow(next).then(ok => { if (!ok) setFolded(!next) }).catch(() => setFolded(!next))
  }

  if (folded) {
    // The ring keeps the status colour; a drag moves the bubble and also ends in a click, so only a press that stayed put unfolds.
    return <button type="button" className={`desktop-guardian-bubble is-${guardian.state}`} aria-label={`아이아 펼치기 · ${guardian.label}`} title={`${guardian.label} · 누르면 펼쳐요, 끌면 옮겨요`}
      onMouseDown={event => { press.current = { x: event.screenX, y: event.screenY } }}
      onClick={event => {
        const start = press.current
        press.current = null
        if (start && Math.hypot(event.screenX - start.x, event.screenY - start.y) > 4) return
        fold(false)
      }}>
      <GuardianFigure state={guardian.state} alt="" />
    </button>
  }

  return <div className={`desktop-guardian is-${guardian.state}`}>
    <div className="desktop-guardian-drag pywebview-drag-region" title="끌어서 바탕화면 어디로든 옮겨요"><GuardianFigure state={guardian.state} alt="아이아 가디언" /></div>
    <div className="desktop-guardian-note">
      <div role="status" aria-live="polite"><strong>{guardian.label} · {policy}</strong><p>{guardian.headline}</p></div>
      <div className="desktop-guardian-actions">
        <Button variant="text" onClick={() => window.pywebview?.api?.open_main?.(selected ? 'work' : 'home', selected)}>AIA 열기</Button>
        <Button variant="text" title="작은 동그라미로 접어 두고, 누르면 다시 펼쳐요" onClick={() => fold(true)}>접기</Button>
      </div>
    </div>
  </div>
}
