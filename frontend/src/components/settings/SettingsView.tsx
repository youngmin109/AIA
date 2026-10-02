import { readinessNextStep, checkLabel } from '../../api/display'
import { useEffect, useState } from 'react'
import { ThemeToggle } from '../common/ThemeToggle'
import { usePreflight } from '../../hooks/usePreflight'
import { useShellStore } from '../../state/shellStore'
import { consoleInfo, type ConsoleInfo } from '../../api/endpoints'
import { apiPost } from '../../api/client'
import { readMotionPreference, type MotionPreference } from '../../api/motionPreference'

export function SettingsView() {
  const { activeView, openSettingsModal, setView } = useShellStore()
  const { data: preflight, error, refetch } = usePreflight(30_000, activeView === 'settings')
  const [info, setInfo] = useState<ConsoleInfo | null>(null)
  const [motion, setMotion] = useState(readMotionPreference)
  const [systemReduced, setSystemReduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [exporting, setExporting] = useState(false)
  const [notice, setNotice] = useState('')
  const mcpCheck = preflight?.checks?.find(check => check.name === 'mcp_tools')
  const mcpWarning = mcpCheck && !mcpCheck.ok ? `Hook 밖 MCP 도구 · ${mcpCheck.detail ?? '확인 필요'}` : null
  useEffect(() => { consoleInfo().then(setInfo).catch(() => setInfo(null)) }, [])
  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setSystemReduced(preference.matches)
    preference.addEventListener('change', update)
    return () => preference.removeEventListener('change', update)
  }, [])
  function changeMotion(value: MotionPreference) {
    setMotion(value)
    document.documentElement.dataset.motion = value
    try { localStorage.setItem('aia.motion', value) } catch { /* In-memory preference still works. */ }
  }
  async function exportDiagnostics() {
    setExporting(true); setNotice('')
    try {
      const bundle = await apiPost<Record<string, unknown>>('/api/support-bundle', {})
      const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' }))
      const anchor = document.createElement('a')
      anchor.href = url; anchor.download = 'AIA-진단정보.json'; anchor.click()
      setTimeout(() => URL.revokeObjectURL(url), 10_000)
      setNotice('진단 정보를 저장했습니다. 공유 전 내용을 확인하세요. 자동 전송하지 않습니다.')
    } catch (failure) { setNotice(failure instanceof Error ? failure.message : '진단 정보를 만들지 못했습니다.') }
    finally { setExporting(false) }
  }
  return <div className="product-page narrow-page">
    <header className="page-heading"><div><p>화면 환경과 내 PC의 보호 연결을 관리합니다.</p></div><span className="status-pill neutral">{info?.product_version ? `버전 ${info.product_version}` : '버전 확인 중'}</span></header>
    <section className="soft-card settings-group"><div><h3>화면 테마</h3><p>밝은 화면과 어두운 화면 중 편한 환경을 선택하세요.</p></div><ThemeToggle /></section>
    <section className="soft-card settings-group"><div><h3>화면 모션</h3><p>가디언의 움직임, 메뉴 전환, 카드 등장, 복구 효과를 사용합니다. 기본은 Windows 접근성 설정을 따릅니다.</p><p role="status">{motion === 'reduced' ? '현재 움직임을 최소화합니다.' : motion === 'auto' && systemReduced ? 'Windows의 모션 감소 설정이 적용 중입니다. 움직임을 보고 싶다면 전체 모션을 선택하세요.' : motion === 'full' ? '전체 모션이 켜져 있습니다. Windows 설정을 바꾸지 않고 이 앱에만 적용합니다.' : '자동 모드 · 애니메이션이 켜져 있습니다.'}</p></div><label className="motion-select">모션 설정<select aria-label="모션 설정" value={motion} onChange={event => changeMotion(event.target.value as MotionPreference)}><option value="auto">자동 · Windows 설정 따름</option><option value="full">전체 모션</option><option value="reduced">모션 줄이기</option></select></label></section>
    <section className="soft-card settings-group"><div><h3>보호 실행 연결</h3><p>{error ? '연결 상태를 가져오지 못했습니다.' : preflight ? readinessNextStep(preflight.readiness_code) : 'Codex와 실행 전 연결 상태를 확인하고 있습니다.'}</p>{error && <button type="button" onClick={refetch}>다시 확인</button>}<div className="check-chip-row">{(preflight?.checks ?? []).map(check => <span key={check.name} className={`check-chip ${check.ok ? 'ok' : 'warn'}`} title={check.detail}>{check.ok ? '✓' : '!'} {checkLabel(check.label)}</span>)}</div>{mcpWarning && <p className="validation-note" role="note">{mcpWarning}</p>}</div><button type="button" className="secondary-action" onClick={openSettingsModal}>보호 연결 설정</button></section>
    <section className="soft-card settings-group"><div><h3>데이터와 개인정보</h3><p>감사 기록과 결과 묶음은 이 PC의 로컬 기록 폴더에 저장됩니다. Codex 대화·승인 화면의 원문은 메모리에서만 다룹니다. 별도로 수집하는 프로세스 명령행은 원시 증거에 포함될 수 있으므로 감사 원본을 공유하기 전 내용을 확인하세요. 계정·클라우드 동기화는 지원하지 않습니다.</p></div><span className="status-pill neutral">로컬 전용</span></section>
    <section className="soft-card settings-group"><div><h3>오류 진단 정보</h3><p>기존 Python 진단 도구로 버전·연결 상태를 모읍니다. 원시 증거, 명령 원문, 파일 내용은 포함하지 않습니다.</p>{notice && <p role="status">{notice}</p>}</div><button type="button" className="secondary-action" disabled={exporting} onClick={exportDiagnostics}>{exporting ? '준비 중…' : '진단 정보 저장'}</button></section>
    <section className="soft-card settings-group"><div><h3>지원 범위</h3><p>{info?.supported_environment ?? 'Windows · Codex · 로컬 보호 실행'}</p><p>아이아는 AI의 내부 사고가 아닌 실제 실행 요청·파일 변화·관리 프로세스를 관찰합니다.</p></div><button type="button" className="text-action" onClick={() => setView('agents')}>에이전트 지원 정보</button></section>
    <section className="soft-card settings-group"><div><h3>실행 기록 요약</h3><p>저장된 세션과 감사 묶음의 무결성 검증 상태를 확인합니다.</p></div><button type="button" className="text-action" onClick={() => setView('reports')}>보고서 보기</button></section>
  </div>
}
