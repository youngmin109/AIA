import { ThemeToggle } from '../common/ThemeToggle'
import { usePreflight } from '../../hooks/usePreflight'
import { useShellStore } from '../../state/shellStore'

export function SettingsView() {
  const { data: preflight } = usePreflight()
  const { openSettingsModal } = useShellStore()
  return (
    <div className="product-page narrow-page">
      <header className="page-heading"><div><span className="page-eyebrow">PRODUCT SETTINGS</span><h2>제품 설정</h2><p>화면 환경과 로컬 보호 연결을 관리합니다.</p></div></header>
      <section className="soft-card settings-group">
        <div><h3>화면 테마</h3><p>라이트 모드는 밝은 운영 콘솔, 다크 모드는 차분한 슬레이트 계열로 전환됩니다.</p></div><ThemeToggle />
      </section>
      <section className="soft-card settings-group">
        <div><h3>보호 실행 연결</h3><p>{preflight?.next_step ?? 'Codex와 Hook 연결 상태를 확인하고 있습니다.'}</p><div className="check-chip-row">{(preflight?.checks ?? []).map((check) => <span key={check.name} className={`check-chip ${check.ok ? 'ok' : 'warn'}`}>{check.ok ? '✓' : '!'} {check.label}</span>)}</div></div><button type="button" className="secondary-action" onClick={openSettingsModal}>보호 세팅 열기</button>
      </section>
      <section className="soft-card settings-group"><div><h3>데이터와 개인정보</h3><p>모든 실행 기록과 결과 번들은 로컬 Control Root에 저장됩니다. 조직 계정·클라우드 동기화는 현재 지원하지 않습니다.</p></div><span className="status-pill neutral">로컬 전용</span></section>
      <section className="soft-card settings-group"><div><h3>지원 범위</h3><p>현재 제품화 범위는 Codex CLI, Hook·Process·File Sensor, 정책 판정, 복구 및 결과 번들입니다.</p></div><span className="status-pill good">Alpha</span></section>
    </div>
  )
}
