import { Icon } from '../common/Icon'
import { useShellStore } from '../../state/shellStore'

// Milestone 3: layout skeleton only. Wired to GET /api/workspaces/validate,
// GET /api/profiles, POST /api/policy/*, POST /api/hook/*, POST /api/runs
// (the same contracts the old 3-step setup.html wizard already used) in
// milestone 5.
export function ProtectionSetupModal() {
  const { settingsModalOpen, closeSettingsModal } = useShellStore()

  if (!settingsModalOpen) {
    return null
  }

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="보호 세팅" onClick={closeSettingsModal}>
      <div className="modal-panel" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h2>보호 세팅</h2>
          <button type="button" className="icon-button" onClick={closeSettingsModal} title="닫기">
            <Icon name="close" />
          </button>
        </div>
        <div className="modal-body">
          <div className="panel-section">
            <p className="panel-section-title">Workspace 경로</p>
            <p>보호할 기존 프로젝트 폴더의 전체 경로를 입력하세요. (마일스톤 5에서 실제 검증 연결)</p>
          </div>
          <div className="panel-section">
            <p className="panel-section-title">보호 정책</p>
            <p>보호 우선 개발형 / 자유 개발형 등 정책 프리셋을 선택합니다.</p>
          </div>
          <div className="panel-section">
            <p className="panel-section-title">AIA Hook 연결</p>
            <p>Codex Hook 자동 설정 및 연결 검증 상태를 표시합니다.</p>
          </div>
        </div>
      </div>
    </div>
  )
}
