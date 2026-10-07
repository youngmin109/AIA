import { Button } from '../common/Button'
import { useEffect, useState } from 'react'
import { useDialog } from '../common/useDialog'
import { Icon } from '../common/Icon'
import { GlossyIcon, RoundAction, StatusDot, type GlossTone } from '../common/Glass'
import { useShellStore } from '../../state/shellStore'
import {
  createProtectedRun,
  reconcileRun,
  validateWorkspace,
  type WorkspaceRecovery,
} from '../../api/endpoints'
import { HookStatusControl } from './HookStatusControl'
import { readDefaultPolicyProfile, readCustomPolicy } from '../policy/policyStorage'
import { chooseNativeWorkspace, hasNativeWorkspacePicker } from '../../desktopBridge'
import { useProfiles } from '../../hooks/useProfiles'
import { usePreflight } from '../../hooks/usePreflight'
import { workspaceShortName } from '../shell/sessionLabel'

type WorkspaceState = { status: 'idle' | 'checking' | 'valid' | 'invalid'; message?: string }
const CARD_TONES: GlossTone[] = ['hook', 'file', 'process', 'amber']

// service.py's reconcile_orphaned_run reason codes, mapped to copy that
// explains *why* automatic cleanup was refused -- never a "force anyway"
// option, since each of these guards exists specifically to avoid severing
// protection out from under a still-running AIA coordinator or Codex Agent.
const RECONCILE_REFUSAL_COPY: Record<string, string> = {
  RUN_IS_CONTROLLED_BY_THIS_AIA_PROCESS: '이 실행은 현재 AIA가 직접 관리하고 있어 아직 정리할 수 없습니다. 잠시 후 다시 시도하세요.',
  ORPHANED_COORDINATOR_NOT_PROVEN: '이전 AIA 창이 아직 실행 중인 것으로 보입니다. 이전 AIA 창을 완전히 종료한 뒤 다시 시도하세요.',
  RECORDED_AGENT_ROOT_NOT_PROVEN_GONE: 'Codex 프로세스가 아직 실행 중인 것으로 확인됩니다. Codex를 먼저 완전히 종료한 뒤 다시 시도하세요.',
}

const CONNECTION_CHECKS: Array<[string, string]> = [
  ['pretool_hook', 'Hook 연결'],
  ['codex_hook_trust', 'Codex 신뢰'],
  ['hook_verification', '요청 전달 확인'],
]

/** ④ New protected run: folder → policy → connection → start. */
export function ProtectionSetupModal() {
  const { newRunOpen } = useShellStore()
  return newRunOpen ? <NewRunSheet /> : null
}

function NewRunSheet() {
  const { closeNewRun, setActiveRun, setView } = useShellStore()
  const { profiles: allProfiles } = useProfiles()
  const profiles = allProfiles
  const customPolicy = readCustomPolicy()
  const { data: preflight } = usePreflight()
  // Same condition HookStatusControl reports as ready; the steps stay visible until it holds.
  const hookReady = preflight?.readiness_code === 'READY'
  const [workspace, setWorkspace] = useState('')
  const [workspaceState, setWorkspaceState] = useState<WorkspaceState>({ status: 'idle' })
  const [chosenProfile, setChosenProfile] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [recovery, setRecovery] = useState<WorkspaceRecovery | null>(null)
  const [reconciling, setReconciling] = useState(false)
  const [reconcileError, setReconcileError] = useState<string | null>(null)
  const [pickerMessage, setPickerMessage] = useState<string | null>(null)

  const dialogRef = useDialog(true, () => { if (!submitting) closeNewRun() })
  const storedDefault = readDefaultPolicyProfile()
  const policyProfile = chosenProfile ?? (profiles.some(profile => profile.value === storedDefault) ? storedDefault : profiles[0]?.value) ?? ''

  function changeWorkspace(value: string) {
    setWorkspace(value)
    setRecovery(null)
    setReconcileError(null)
    setWorkspaceState({ status: value.trim() ? 'checking' : 'idle' })
  }

  useEffect(() => {
    if (!workspace.trim()) return
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

  const canSubmit = workspaceState.status === 'valid' && !recovery?.required && hookReady && !submitting && profiles.some(profile => profile.value === policyProfile) && (policyProfile !== 'CUSTOM' || Boolean(customPolicy))

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
        ...(policyProfile === 'CUSTOM' ? { custom_policy_path: customPolicy?.path } : {}),
        mode: 'ENFORCE',
        interactive: true,
        // Structured Codex conversation (app-server) instead of the PTY/TUI
        // terminal; runs created earlier keep their original surface.
        launch_mode: 'codex_app_server',
      })
      setActiveRun(result.session_id)
      setView('work')
      closeNewRun()
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleChooseWorkspace() {
    setPickerMessage(null)
    if (!hasNativeWorkspacePicker()) {
      setPickerMessage('폴더 고르기는 AIA Windows 앱에서 쓸 수 있어요. 브라우저에서는 전체 경로를 직접 입력하세요.')
      return
    }
    try {
      const selected = await chooseNativeWorkspace()
      if (selected) changeWorkspace(selected)
    } catch (error) {
      setPickerMessage(error instanceof Error ? `폴더 선택창을 열지 못했습니다: ${error.message}` : '폴더 선택창을 열지 못했습니다.')
    }
  }

  return (
    <>
      <div className="glass-scrim" aria-hidden="true" onClick={() => { if (!submitting) closeNewRun() }} />
      <div className="glass-dialog-layer">
        <div ref={dialogRef} tabIndex={-1} className="glass-dialog is-wide newrun-sheet" role="dialog" aria-modal="true" aria-labelledby="newrun-title">
          <header className="newrun-head">
            <h2 id="newrun-title">새 보호 실행</h2>
            <Button variant="icon" onClick={closeNewRun} aria-label="닫기"><Icon name="close" /></Button>
          </header>

          <section className="newrun-section" aria-labelledby="newrun-folder">
            <h3 id="newrun-folder"><span className="newrun-step">1</span>작업 폴더</h3>
            <div className="glass-row newrun-folder">
              <GlossyIcon tone="amber" icon="folder" />
              <div className="newrun-folder-main">
                <strong>{workspace.trim() ? workspaceShortName(workspace.trim()) : '폴더를 골라 주세요'}</strong>
                <label className="visually-hidden" htmlFor="newrun-path">작업 폴더 전체 경로</label>
                <input id="newrun-path" className="glass-input is-mono" value={workspace} onChange={(event) => changeWorkspace(event.target.value)} placeholder="C:\workspace\my-project" spellCheck={false} />
              </div>
              <span className={`newrun-folder-state is-${workspaceState.status}`} role="status">
                {workspaceState.status === 'checking' && '확인 중…'}
                {workspaceState.status === 'valid' && <><Icon name="check" size={16} /> 확인됨</>}
                {workspaceState.status === 'invalid' && '확인 필요'}
              </span>
              <Button variant="secondary" className="is-compact" onClick={handleChooseWorkspace}>폴더 바꾸기</Button>
            </div>
            {workspaceState.status === 'invalid' && <p className="danger-text">{workspaceState.message}</p>}
            {pickerMessage && <p className="faint-note">{pickerMessage}</p>}
            {recovery?.required && (
              <div className="glass-notice is-warning">
                <div>
                  <strong>정리되지 않은 이전 실행이 있어요</strong>
                  <p>#{recovery.session_id?.slice(0, 8)}{recovery.status ? ` · ${recovery.status}` : ''} · 이전 AIA·Codex가 완전히 종료됐는지 확인한 뒤 정리하세요.</p>
                  {reconcileError && <p className="danger-text">{reconcileError}</p>}
                </div>
                <Button variant="cta" className="is-compact" disabled={reconciling} onClick={handleReconcile}>{reconciling ? '정리하는 중…' : '정리하고 계속'}</Button>
              </div>
            )}
          </section>

          <section className="newrun-section" aria-labelledby="newrun-policy">
            <h3 id="newrun-policy"><span className="newrun-step">2</span>보호 정책</h3>
            <div className="newrun-policies">
              {profiles.map((profile, index) => {
                const selected = profile.value === policyProfile
                return (
                  <button key={profile.value} type="button" className={`glass-card newrun-policy${selected ? ' is-selected' : ''}`} aria-pressed={selected} onClick={() => setChosenProfile(profile.value)}>
                    <GlossyIcon tone={CARD_TONES[index % CARD_TONES.length]} icon="shieldPlain" size="sm" />
                    <strong>{profile.display_name}</strong>
                    <span>{profile.description}</span>
                    {selected && <span className="badge is-ok newrun-policy-mark"><Icon name="check" size={14} />선택됨</span>}
                  </button>
                )
              })}
              {profiles.length === 0 && <p className="faint-note">정책 목록을 불러오는 중…</p>}
            </div>
            {policyProfile === 'CUSTOM' && <p className="faint-note">{customPolicy ? '저장한 사용자 지정 규칙을 실행 시작 시 다시 검증해요.' : '정책 화면에서 사용자 지정 규칙을 먼저 검증하고 저장해 주세요.'}</p>}
          </section>

          <section className="newrun-section" aria-labelledby="newrun-connection">
            <h3 id="newrun-connection"><span className="newrun-step">3</span>연결 상태</h3>
            <div className="newrun-pills">
              {CONNECTION_CHECKS.map(([name, label]) => {
                const check = preflight?.checks?.find(item => item.name === name)
                return <span key={name} className="chip" title={check?.detail}><StatusDot tone={!check ? 'neutral' : check.ok ? 'ok' : 'warn'} />{label}</span>
              })}
              <span className="chip"><StatusDot tone="neutral" />센서 3개 · 실행하면 시작</span>
            </div>
            {!hookReady && <HookStatusControl />}
          </section>

          {submitError && <div className="glass-notice is-danger" role="alert"><strong>시작하지 못했어요</strong><p>{submitError}</p></div>}

          <footer className="newrun-foot">
            <p className="faint-note">{!hookReady ? '연결 상태가 준비되면 시작할 수 있어요.' : workspaceState.status !== 'valid' ? '작업 폴더를 확인하면 시작할 수 있어요.' : '시작하면 기준점을 저장하고 감시를 켜요.'}</p>
            <div className="newrun-actions">
              <Button variant="secondary" onClick={closeNewRun} disabled={submitting}>취소</Button>
              <RoundAction small onClick={handleSubmit} disabled={!canSubmit}>{submitting ? '시작 중…' : '보호 시작'}</RoundAction>
            </div>
          </footer>
        </div>
      </div>
    </>
  )
}
