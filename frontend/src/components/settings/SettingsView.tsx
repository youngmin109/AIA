import { useEffect, useState } from 'react'
import { Button } from '../common/Button'
import { StatusPill } from '../common/Badge'
import { Icon } from '../common/Icon'
import { StatusDot } from '../common/Glass'
import { TintPicker } from '../common/TintPicker'
import { HookStatusControl } from './HookStatusControl'
import { GuardianGuide } from '../shell/GuardianGuide'
import { useGuardianState } from '../../hooks/useGuardianState'
import { usePreflight } from '../../hooks/usePreflight'
import { useRunList } from '../../hooks/useRunList'
import { useShellStore } from '../../state/shellStore'
import { consoleInfo, type ConsoleInfo } from '../../api/endpoints'
import { apiPost } from '../../api/client'
import { applyMotionPreference, readMotionPreference, type MotionPreference } from '../../api/motionPreference'
import { applyGlassPreference, readGlassPreference, type GlassPreference } from '../../api/glassPreference'
import { applyPetPreference, readPetPreference, type PetPreference } from '../../api/petPreference'
import { connectionLights } from '../../api/settingsStatus'
import { isConnectionLost } from '../../api/connectionState'
import { syncDesktopGuardian } from '../../desktopBridge'
import { applyPetSize, readPetSize, PET_SIZE_MIN, PET_SIZE_MAX, PET_SIZE_STEP, type PetSizePreference } from '../../api/petSizePreference'

const MOTION_OPTIONS: Array<[MotionPreference, string]> = [['auto', '자동'], ['full', '켜기'], ['reduced', '줄이기']]

/** ⑩ Settings: connection readiness first, then look and app information. */
export function SettingsView() {
  const { activeView, setView } = useShellStore()
  const { data: preflight, error, refetch, updatedAt, isLoading } = usePreflight(30_000, activeView === 'settings')
  const { connectionFailures = 0 } = useRunList()
  const [info, setInfo] = useState<ConsoleInfo | null>(null)
  const [motion, setMotion] = useState(readMotionPreference)
  const [glass, setGlass] = useState<GlassPreference>(readGlassPreference)
  const [pet, setPet] = useState<PetPreference>(readPetPreference)
  const [petSize, setPetSize] = useState(readPetSize)
  const [guideOpen, setGuideOpen] = useState(false)
  const guardian = useGuardianState()
  const [exporting, setExporting] = useState(false)
  const [notice, setNotice] = useState('')
  const lights = connectionLights(error ? null : preflight)
  const mcp = preflight?.checks?.find(check => check.name === 'mcp_tools')
  const mcpWarning = mcp && !mcp.ok
  const codex = preflight?.checks?.find(check => check.name === 'codex_executable')
  const controlRoot = preflight?.checks?.find(check => check.name === 'control_root')
  const ready = preflight?.readiness_code === 'READY'
  const serverLost = isConnectionLost(connectionFailures)

  useEffect(() => { consoleInfo().then(setInfo).catch(() => setInfo(null)) }, [])
  useEffect(() => {
    // Avoid a burst of concurrent native window resizes while dragging the slider.
    const timer = setTimeout(() => {
      window.pywebview?.api?.set_guardian_size?.(petSize).then(ok => {
        if (!ok) setNotice('펫 창의 크기를 바꾸지 못했어요. 다시 선택해 주세요.')
      }).catch(() => setNotice('펫 창의 크기를 바꾸지 못했어요. 다시 선택해 주세요.'))
    }, 120)
    return () => clearTimeout(timer)
  }, [petSize])

  function changeMotion(value: MotionPreference) {
    applyMotionPreference(value)
    setMotion(value)
  }

  function toggleGlass() {
    const next: GlassPreference = glass === 'on' ? 'off' : 'on'
    applyGlassPreference(next)
    setGlass(next)
  }

  // Desktop only: opens the control root in File Explorer (the path comes from the shell, not the page).
  const canOpenRecords = typeof window.pywebview?.api?.open_records_folder === 'function'
  function openRecords() {
    window.pywebview?.api?.open_records_folder?.().then(ok => { if (!ok) setNotice('기록 폴더를 열지 못했어요.') }).catch(() => setNotice('기록 폴더를 열지 못했어요.'))
  }

  function togglePet() {
    const next: PetPreference = pet === 'on' ? 'off' : 'on'
    applyPetPreference(next)
    setPet(next)
    syncDesktopGuardian()
  }

  function changePetSize(value: PetSizePreference) {
    applyPetSize(value)
    setPetSize(value)
  }

  async function exportDiagnostics() {
    setExporting(true); setNotice('')
    try {
      const bundle = await apiPost<Record<string, unknown>>('/api/support-bundle', {})
      const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' }))
      const anchor = document.createElement('a')
      anchor.href = url; anchor.download = 'AIA-진단정보.json'; anchor.click()
      setTimeout(() => URL.revokeObjectURL(url), 10_000)
      setNotice('진단 정보를 저장했어요. 공유하기 전에 내용을 확인하세요. 자동으로 보내지 않아요.')
    } catch (failure) { setNotice(failure instanceof Error ? failure.message : '진단 정보를 만들지 못했어요.') }
    finally { setExporting(false) }
  }

  return (
    <div className="page-stack settings-page view-enter">
      <header className="page-head">
        <div>
          <h1>설정</h1>
          <p>보호를 시작하기 전에 연결 상태를 확인해요.</p>
        </div>
        <StatusPill tone="neutral">{info?.product_version ? `버전 ${info.product_version}` : '버전 확인 중'}</StatusPill>
      </header>

      <section className="glass settings-connection" aria-labelledby="settings-connection-title">
        <div className="settings-connection-head">
          <div>
            <h2 id="settings-connection-title">연결 준비</h2>
            <span className="muted">{error ? '연결 상태를 가져오지 못했어요' : updatedAt ? `마지막 확인 ${new Date(updatedAt).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false })}` : '확인 중'}</span>
          </div>
          <Button variant="cta" onClick={refetch} disabled={isLoading}><Icon name="refresh" size={18} />다시 확인</Button>
        </div>
        <div className="settings-lights">
          {lights.map(light => (
            <div key={light.key} className="glass-row settings-light">
              <StatusDot tone={light.state === 'ok' ? 'ok' : light.state === 'warn' ? 'warn' : 'neutral'} />
              <span><strong>{light.label}</strong><small>{light.note}</small></span>
            </div>
          ))}
        </div>
        {mcpWarning && (
          <details className="settings-mcp-note">
            <summary><Icon name="info" size={15} />Codex 외부 도구(MCP)가 켜져 있어요 · 아이아 보호 범위 밖</summary>
            <p>{mcp?.detail ?? '켜진 MCP 서버를 확인하세요.'} 실행 전 검사를 거치는 외부 도구 요청은 작업창에서 허용 여부를 물어요. AIA는 Codex 설정을 바꾸지 않아요. Codex 설정에서 끄면 이 안내가 사라져요.</p>
          </details>
        )}
        {!ready && preflight && <HookStatusControl />}
        {serverLost && <div className="glass-notice is-danger"><strong>AIA 로컬 서버와 연결이 끊겼어요</strong><p>자동으로 다시 연결을 시도해요.</p></div>}
      </section>

      <section className="settings-grid" aria-label="화면과 정보">
        <div className="glass-card settings-card">
          <h3>색상 테마</h3>
          <p className="muted">유리 화면의 바탕색을 골라요.</p>
          <TintPicker />
        </div>
        <div className="glass-card settings-card">
          <button type="button" role="switch" aria-checked={glass === 'on'} className="glass-switch" onClick={toggleGlass}>
            <span>유리 효과<small>기본은 꺼짐이에요. 켜면 흐림·굴절 효과가 생기지만 느린 PC에서는 무거워져요</small></span>
            <span className="glass-switch-track" aria-hidden="true"><span className="glass-switch-thumb" /></span>
          </button>
          <button type="button" role="switch" aria-checked={pet === 'on'} className="glass-switch" onClick={togglePet}>
            <span>가디언 펫<small>앱을 최소화해도 바탕화면에 남아요. 아이아를 누르면 AIA가 열리고, 작은 ? 버튼에서 도움말과 오류 신고를 볼 수 있어요. 앱을 종료하면 함께 꺼져요.</small></span>
            <span className="glass-switch-track" aria-hidden="true"><span className="glass-switch-thumb" /></span>
          </button>
          <div className="settings-motion">
            <span>펫 크기<small>바탕화면 아이아 크기 조절</small></span>
            <div className="settings-pet-size">
              <label htmlFor="pet-size">작게</label>
              <input id="pet-size" type="range" min={PET_SIZE_MIN} max={PET_SIZE_MAX} step={PET_SIZE_STEP} value={petSize} aria-label="아이아 펫 크기" aria-valuetext={`${petSize}퍼센트`} onChange={event => changePetSize(Number(event.target.value))} />
              <span>크게</span><output htmlFor="pet-size">{petSize}%</output>
            </div>
          </div>
          <div className="settings-motion">
            <span>움직임<small>가디언·화면 전환 애니메이션</small></span>
            <div className="segmented" role="group" aria-label="움직임">
              {MOTION_OPTIONS.map(([value, label]) => <button key={value} type="button" aria-pressed={motion === value} onClick={() => changeMotion(value)}>{label}</button>)}
            </div>
          </div>
        </div>
        <div className="glass-card settings-card">
          <h3>AIA 정보</h3>
          <ul className="settings-facts">
            <li><span>버전</span><b>{info?.product_version ?? '확인 중'}</b></li>
            <li><span>지원 환경</span><b>{info?.supported_environment ?? 'Windows · Codex'}</b></li>
            <li><span>Codex</span><b>{codex ? (codex.ok ? '설치 확인됨' : '확인 필요') : '확인 중'}</b></li>
            <li><span>데이터 위치</span><b className="mono" title={controlRoot?.detail}>{controlRoot?.detail ?? '이 PC의 로컬 기록 폴더'}</b></li>
            {canOpenRecords && <li className="settings-facts-action"><Button variant="text" onClick={openRecords}><Icon name="folder" size={14} />기록 폴더 열기</Button></li>}
          </ul>
          <div className="settings-actions">
            <Button variant="secondary" className="is-compact" disabled={exporting} onClick={exportDiagnostics}>{exporting ? '준비 중…' : '진단 정보 저장'}</Button>
            <Button variant="text" onClick={() => setGuideOpen(true)}>도움말</Button>
            <Button variant="text" onClick={() => setView('history')}>감사 기록 보기 <Icon name="arrowRight" size={14} /></Button>
          </div>
          {notice && <p className="faint-note" role="status">{notice}</p>}
        </div>
      </section>

      <details className="glass-card settings-privacy">
        <summary>데이터와 개인정보 · 지원 범위</summary>
        <p>감사 기록과 결과 묶음은 이 PC의 로컬 기록 폴더에 저장돼요. Codex 대화·승인 화면의 원문은 메모리에서만 다뤄요. 따로 수집하는 프로세스 명령행은 원시 증거에 들어갈 수 있으니 감사 원본을 공유하기 전에 내용을 확인하세요. 계정·클라우드 동기화는 지원하지 않아요.</p>
        <p>진단 정보는 버전·연결 상태만 모아요. 원시 증거, 명령 원문, 파일 내용은 넣지 않아요.</p>
        <p>아이아는 AI의 내부 사고가 아니라 실제 실행 요청·파일 변화·관리 프로세스를 관찰해요. 지원 범위 밖 도구나 경로는 보호 수준이 낮아질 수 있어요.</p>
      </details>
      {guideOpen && <GuardianGuide guardian={guardian} initialTopic="start" onClose={() => setGuideOpen(false)} />}
    </div>
  )
}
