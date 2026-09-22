import { useEffect, useState } from 'react'
import { Icon } from '../common/Icon'
import { useShellStore } from '../../state/shellStore'
import { createProtectedRun, listProfiles, validateWorkspace, type PolicyProfile } from '../../api/endpoints'

type WorkspaceState = { status: 'idle' | 'checking' | 'valid' | 'invalid'; message?: string }

export function ProtectionSetupModal() {
  const { settingsModalOpen, closeSettingsModal, openTab } = useShellStore()
  const [workspace, setWorkspace] = useState('')
  const [workspaceState, setWorkspaceState] = useState<WorkspaceState>({ status: 'idle' })
  const [profiles, setProfiles] = useState<PolicyProfile[]>([])
  const [policyProfile, setPolicyProfile] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  useEffect(() => {
    if (!settingsModalOpen) return
    listProfiles()
      .then((list) => {
        setProfiles(list)
        if (!policyProfile && list.length > 0) setPolicyProfile(list[0].value)
      })
      .catch(() => setProfiles([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settingsModalOpen])

  useEffect(() => {
    if (!workspace.trim()) {
      setWorkspaceState({ status: 'idle' })
      return
    }
    setWorkspaceState({ status: 'checking' })
    const timer = setTimeout(() => {
      validateWorkspace(workspace.trim())
        .then((result) => {
          if (result.valid) setWorkspaceState({ status: 'valid' })
          else setWorkspaceState({ status: 'invalid', message: result.error ?? '폴더를 확인할 수 없습니다.' })
        })
        .catch((err) => setWorkspaceState({ status: 'invalid', message: err instanceof Error ? err.message : String(err) }))
    }, 400)
    return () => clearTimeout(timer)
  }, [workspace])

  if (!settingsModalOpen) {
    return null
  }

  const canSubmit = workspaceState.status === 'valid' && !submitting

  async function handleSubmit() {
    if (!canSubmit) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const result = await createProtectedRun({
        workspace: workspace.trim(),
        agent: 'codex',
        policy_profile: policyProfile || undefined,
        mode: 'ENFORCE',
        interactive: true,
        launch_mode: 'web_terminal',
      })
      openTab({ id: result.session_id, title: `#${result.session_id.slice(0, 8)}`, kind: 'terminal' })
      closeSettingsModal()
      setWorkspace('')
      setWorkspaceState({ status: 'idle' })
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
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
            <input
              value={workspace}
              onChange={(event) => setWorkspace(event.target.value)}
              placeholder="C:\workspace\my-project"
              style={{ width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-inset)', color: 'var(--text)' }}
            />
            <p style={{ marginTop: 6, fontSize: 11 }}>
              {workspaceState.status === 'checking' && '폴더를 확인하는 중입니다…'}
              {workspaceState.status === 'valid' && <span className="success-text" style={{ color: 'var(--success)' }}>폴더를 확인했습니다.</span>}
              {workspaceState.status === 'invalid' && <span style={{ color: 'var(--danger)' }}>{workspaceState.message}</span>}
              {workspaceState.status === 'idle' && '이미 만들어 둔 프로젝트 폴더의 전체 경로를 입력하세요.'}
            </p>
          </div>
          <div className="panel-section">
            <p className="panel-section-title">보호 정책</p>
            <select
              value={policyProfile}
              onChange={(event) => setPolicyProfile(event.target.value)}
              style={{ width: '100%', padding: '8px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--bg-inset)', color: 'var(--text)' }}
            >
              {profiles.map((profile) => (
                <option key={profile.value} value={profile.value}>
                  {profile.label}
                </option>
              ))}
            </select>
          </div>
          {submitError && (
            <div className="terminal-error" style={{ borderRadius: 8, marginTop: 8 }}>
              <span>{submitError}</span>
            </div>
          )}
          <button type="button" className="cta-button" style={{ marginTop: 16 }} disabled={!canSubmit} onClick={handleSubmit}>
            {submitting ? '시작하는 중…' : '보호 작업 시작'}
          </button>
        </div>
      </div>
    </div>
  )
}
