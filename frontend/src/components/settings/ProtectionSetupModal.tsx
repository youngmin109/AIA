import { Button } from '../common/Button'
import { useEffect, useState } from 'react'
import { useDialog } from '../common/useDialog'
import { Icon } from '../common/Icon'
import { useShellStore } from '../../state/shellStore'
import {
  createProtectedRun,
  listProfiles,
  reconcileRun,
  validateWorkspace,
  type PolicyProfile,
  type WorkspaceRecovery,
} from '../../api/endpoints'
import { HookStatusControl } from './HookStatusControl'
import { readDefaultPolicyProfile } from '../policy/policyStorage'
import { chooseNativeWorkspace, hasNativeWorkspacePicker } from '../../desktopBridge'

type WorkspaceState = { status: 'idle' | 'checking' | 'valid' | 'invalid'; message?: string }
const isStandardProfile = (profile: PolicyProfile) => profile.value !== 'CUSTOM'

// service.py's reconcile_orphaned_run reason codes, mapped to copy that
// explains *why* automatic cleanup was refused -- never a "force anyway"
// option, since each of these guards exists specifically to avoid severing
// protection out from under a still-running AIA coordinator or Codex Agent.
const RECONCILE_REFUSAL_COPY: Record<string, string> = {
  RUN_IS_CONTROLLED_BY_THIS_AIA_PROCESS: '이 실행은 현재 AIA가 직접 관리하고 있어 아직 정리할 수 없습니다. 잠시 후 다시 시도하세요.',
  ORPHANED_COORDINATOR_NOT_PROVEN: '이전 AIA 창이 아직 실행 중인 것으로 보입니다. 이전 AIA 창을 완전히 종료한 뒤 다시 시도하세요.',
  RECORDED_AGENT_ROOT_NOT_PROVEN_GONE: 'Codex 프로세스가 아직 실행 중인 것으로 확인됩니다. Codex를 먼저 완전히 종료한 뒤 다시 시도하세요.',
}

export function ProtectionSetupModal() {
  const { settingsModalOpen, closeSettingsModal, setActiveRun, setView } = useShellStore()
  const [workspace, setWorkspace] = useState('')
  const [workspaceState, setWorkspaceState] = useState<WorkspaceState>({ status: 'idle' })
  const [profiles, setProfiles] = useState<PolicyProfile[]>([])
  const [policyProfile, setPolicyProfile] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [hookReady, setHookReady] = useState(false)
  const [recovery, setRecovery] = useState<WorkspaceRecovery | null>(null)
  const [reconciling, setReconciling] = useState(false)
  const [reconcileError, setReconcileError] = useState<string | null>(null)
  const [pickerMessage, setPickerMessage] = useState<string | null>(null)

  const dialogRef = useDialog(settingsModalOpen, () => { if (!submitting) closeSettingsModal() })
  useEffect(() => {
    if (!settingsModalOpen) return
    listProfiles()
      .then((list) => {
        const standardProfiles = list.filter(isStandardProfile)
        setProfiles(standardProfiles)
        if (standardProfiles.length > 0) {
          const defaultValue = readDefaultPolicyProfile()
          const stillValid = defaultValue && standardProfiles.some((profile) => profile.value === defaultValue)
          setPolicyProfile(stillValid ? defaultValue : standardProfiles[0].value)
        }
      })
      .catch(() => setProfiles([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settingsModalOpen])

  useEffect(() => {
    setRecovery(null)
    setReconcileError(null)
    if (!workspace.trim()) {
      setWorkspaceState({ status: 'idle' })
      return
    }
    setWorkspaceState({ status: 'checking' })
    let cancelled = false
    const timer = setTimeout(() => {
      validateWorkspace(workspace.trim())
        .then((result) => {
          if (cancelled) return
          if (result.valid) {
            setWorkspaceState({ status: 'valid' })
            setRecovery(result.recovery?.required ? result.recovery : null)
          } else {
            setWorkspaceState({ status: 'invalid', message: result.error ?? '폴더를 확인할 수 없습니다.' })
          }
        })
        .catch((err) => { if (!cancelled) setWorkspaceState({ status: 'invalid', message: err instanceof Error ? err.message : String(err) }) })
    }, 400)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [workspace])

  if (!settingsModalOpen) {
    return null
  }

  const canSubmit = workspaceState.status === 'valid' && !recovery?.required && hookReady && !submitting && profiles.some(profile => profile.value === policyProfile)

  async function handleReconcile() {
    if (!recovery?.session_id || reconciling) return
    setReconciling(true)
    setReconcileError(null)
    try {
      const result = await reconcileRun(recovery.session_id)
      if (result.reconciled) {
        setRecovery(null)
      } else {
        setReconcileError(
          (result.reason && RECONCILE_REFUSAL_COPY[result.reason]) ||
            '아직 안전하게 정리할 수 없습니다. 이전 AIA 창과 Codex가 완전히 종료됐는지 확인한 뒤 다시 시도하세요.',
        )
      }
    } catch (err) {
      setReconcileError(err instanceof Error ? err.message : String(err))
    } finally {
      setReconciling(false)
    }
  }

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
        // Structured Codex conversation (app-server) instead of the PTY/TUI
        // terminal; runs created earlier keep their original surface.
        launch_mode: 'codex_app_server',
      })
      setActiveRun(result.session_id)
      setView('terminal')
      closeSettingsModal()
      setWorkspace('')
      setWorkspaceState({ status: 'idle' })
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleChooseWorkspace() {
    setPickerMessage(null)
    if (!hasNativeWorkspacePicker()) {
      setPickerMessage('폴더 선택은 AIA Windows EXE에서 사용할 수 있습니다. 현재 브라우저에서는 전체 경로를 직접 입력하세요.')
      return
    }
    try {
      const selected = await chooseNativeWorkspace()
      if (selected) setWorkspace(selected)
    } catch (error) {
      setPickerMessage(error instanceof Error ? `폴더 선택창을 열지 못했습니다: ${error.message}` : '폴더 선택창을 열지 못했습니다.')
    }
  }

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-label="보호 세팅" onClick={closeSettingsModal}>
      <div ref={dialogRef} className="modal-panel" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h2>보호 세팅</h2>
          <Button variant="icon" onClick={closeSettingsModal} title="닫기">
            <Icon name="close" />
          </Button>
        </div>
        <div className="modal-body">
          <HookStatusControl onReadyChange={setHookReady} />
          <div className="panel-section">
            <p className="panel-section-title">작업공간 경로</p>
            <div className="workspace-picker-row">
              <input
                value={workspace}
                onChange={(event) => setWorkspace(event.target.value)}
                placeholder="폴더 선택 또는 전체 경로 입력"
              />
              <Button variant="outline" onClick={handleChooseWorkspace}>폴더 선택</Button>
            </div>
            <p className="field-hint">
              {workspaceState.status === 'checking' && '폴더를 확인하는 중입니다…'}
              {workspaceState.status === 'valid' && <span className="success-text">폴더를 확인했습니다.</span>}
              {workspaceState.status === 'invalid' && <span className="field-error">{workspaceState.message}</span>}
              {workspaceState.status === 'idle' && '이미 만들어 둔 프로젝트 폴더의 전체 경로를 입력하세요.'}
            </p>
            {pickerMessage && <p className="inline-notice">{pickerMessage}</p>}
          </div>
          {recovery?.required && (
            <div className="panel-section">
              <div className="terminal-action-banner reconcile-banner">
                <span>
                  이 작업공간에는 정리되지 않은 이전 보호 실행이 있습니다 (#{recovery.session_id?.slice(0, 8)}
                  {recovery.status ? ` · ${recovery.status}` : ''}). 이전 AIA·Codex가 완전히 종료됐는지 확인한 뒤 정리하세요.
                </span>
                <Button variant="cta" className="is-small" disabled={reconciling} onClick={handleReconcile}>
                  {reconciling ? '정리하는 중…' : '정리하고 계속'}
                </Button>
              </div>
              {reconcileError && (
                <p className="field-hint is-bad">{reconcileError}</p>
              )}
            </div>
          )}
          <div className="panel-section">
            <p className="panel-section-title">보호 정책</p>
            <select
              value={policyProfile}
              onChange={(event) => setPolicyProfile(event.target.value)}
              className="policy-select"
            >
              {profiles.map((profile) => (
                <option key={profile.value} value={profile.value}>
                  {profile.display_name}
                </option>
              ))}
            </select>
          </div>
          {submitError && (
            <div className="terminal-error submit-error">
              <span>{submitError}</span>
            </div>
          )}
          {!hookReady && workspaceState.status === 'valid' && (
            <p className="setup-footnote">
              위 AIA Hook 연결이 준비되어야 보호 작업을 시작할 수 있습니다.
            </p>
          )}
          <Button variant="cta" className="is-stacked" disabled={!canSubmit} onClick={handleSubmit}>
            {submitting ? '시작하는 중…' : '보호 작업 시작'}
          </Button>
        </div>
      </div>
    </div>
  )
}
