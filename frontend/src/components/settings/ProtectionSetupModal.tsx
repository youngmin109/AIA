import { useResumableConversations } from '../../hooks/useResumableConversations'
import type { ResumableConversation } from '../../api/endpoints'
import { sessionCreatedLabel } from '../shell/sessionLabel'
import { useCodexModels } from '../../hooks/useCodexModels'
import { effortLabel, effortsFor } from '../../api/modelView'
import { largeFolderNotice } from '../../api/startupStatus'
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
import { absoluteInWorkspace, addProtectedPaths, insideWorkspace, MAX_PROTECTED_PATHS } from '../../api/protectedPaths'
import { PERMISSION_DEFAULT, permissionAllowed, permissionOption, type PermissionMode } from '../../api/permissionMode'
import { PermissionMenu } from '../terminal/PermissionChip'
import { usePermissionProfiles } from '../../hooks/usePermissionProfiles'
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
  const [sizeNotice, setSizeNotice] = useState<string | null>(null)
  const models = useCodexModels()
  const [model, setModel] = useState('')
  const { newRunResume } = useShellStore()
  const [resumeMode, setResumeMode] = useState(newRunResume)
  const [resumeThread, setResumeThread] = useState<ResumableConversation | null>(null)
  const conversations = useResumableConversations(resumeMode)
  const [effort, setEffort] = useState('')
  const [protectedPaths, setProtectedPaths] = useState<string[]>([])
  const [protectEntry, setProtectEntry] = useState('')
  const [protectMessage, setProtectMessage] = useState<string | null>(null)
  const [chosenPermission, setPermission] = useState<PermissionMode>(PERMISSION_DEFAULT)
  const permissionProfiles = usePermissionProfiles()
  // A choice Codex's config forbids falls back to asking the user.
  const chosenOption = permissionOption(chosenPermission)
  const permission: PermissionMode = chosenOption && permissionAllowed(chosenOption, permissionProfiles) ? chosenPermission : 'workspace'

  const dialogRef = useDialog(true, () => { if (!submitting) closeNewRun() })
  const storedDefault = readDefaultPolicyProfile()
  const policyProfile = chosenProfile ?? (profiles.some(profile => profile.value === storedDefault) ? storedDefault : profiles[0]?.value) ?? ''

  function changeWorkspace(value: string) {
    setWorkspace(value)
    // Protected paths belong to one work folder; a new folder starts with none.
    setProtectedPaths([])
    setProtectMessage(null)
    setRecovery(null)
    setReconcileError(null)
    setSizeNotice(null)
    setWorkspaceState({ status: value.trim() ? 'checking' : 'idle' })
  }

  useEffect(() => {
    if (!workspace.trim()) return
    let cancelled = false
    const timer = setTimeout(() => {
      validateWorkspace(workspace.trim())
        .then((result) => {
          if (cancelled) return
          if (result.valid && result.busy) {
            setWorkspaceState({ status: 'invalid', message: `이 폴더는 다른 대화(${workspaceShortName(result.busy.workspace)})에서 보호 중이에요. 같은 폴더나 그 안팎의 폴더는 한 대화에서만 보호할 수 있어요.` })
          } else if (result.valid) {
            setWorkspaceState({ status: 'valid' })
            setRecovery(result.recovery?.required ? result.recovery : null)
            setSizeNotice(largeFolderNotice(result.size_estimate))
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
        model: model || undefined,
        reasoning_effort: effort || undefined,
        resume_thread_id: resumeMode && resumeThread ? resumeThread.thread_id : undefined,
        protected_paths: protectedPaths.length > 0 ? protectedPaths : undefined,
        permission_mode: permission,
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

  function addProtected(additions: string[]) {
    const result = addProtectedPaths(protectedPaths, additions, workspace)
    setProtectedPaths(result.paths)
    setProtectMessage(result.outside > 0
      ? `작업 폴더 밖의 경로 ${result.outside}개는 넣지 않았어요. 작업 폴더 안의 파일·폴더만 지정할 수 있어요.`
      : result.overLimit > 0 ? `최대 ${MAX_PROTECTED_PATHS}개까지 지정할 수 있어요.` : null)
  }

  async function pickProtected(kind: 'files' | 'folder') {
    const api = window.pywebview?.api
    try {
      if (kind === 'files') addProtected((await api?.choose_files?.())?.paths ?? [])
      else {
        const folder = (await api?.choose_directory?.())?.path
        if (folder) addProtected([folder])
      }
    } catch (error) {
      setProtectMessage(error instanceof Error ? `선택창을 열지 못했어요: ${error.message}` : '선택창을 열지 못했어요.')
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

          <section className="newrun-section" aria-labelledby="newrun-conversation">
            <h3 id="newrun-conversation">대화</h3>
            <div className="segmented" role="group" aria-label="대화 시작 방식">
              <button type="button" aria-pressed={!resumeMode} onClick={() => { setResumeMode(false); setResumeThread(null) }}>새 대화</button>
              <button type="button" aria-pressed={resumeMode} onClick={() => setResumeMode(true)}>이전 대화 이어하기</button>
            </div>
            {resumeMode && (
              <div className="newrun-resume">
                {conversations === null && <p className="muted">AIA로 연 대화를 불러오는 중…</p>}
                {conversations?.length === 0 && <p className="muted">이어할 수 있는 대화가 없어요. AIA로 연 대화만 보여요.</p>}
                {conversations?.map(item => (
                  <button
                    key={item.thread_id}
                    type="button"
                    className={`glass-row newrun-resume-item${resumeThread?.thread_id === item.thread_id ? ' is-selected' : ''}`}
                    aria-pressed={resumeThread?.thread_id === item.thread_id}
                    disabled={item.missing === true}
                    onClick={() => { setResumeThread(item); changeWorkspace(item.workspace) }}
                  >
                    <strong>{item.name || item.preview || '이름 없는 대화'}</strong>
                    <span className="muted">{workspaceShortName(item.workspace)} · {sessionCreatedLabel(item.created_at ?? undefined)}{item.missing ? ' · Codex에서 찾을 수 없어요' : ''}</span>
                  </button>
                ))}
                <p className="faint-note">이전 대화에서 일어난 일은 이번 보호 기록 범위 밖이에요. 고른 대화의 작업 폴더로 시작해요.</p>
              </div>
            )}
          </section>

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
            {workspaceState.status === 'valid' && sizeNotice && <p className="glass-notice is-warning newrun-size" role="note">{sizeNotice}</p>}
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
                  <button key={profile.value} type="button" className={`glass-card newrun-policy${selected ? ' is-selected' : ''}`} aria-pressed={selected} title={profile.description} onClick={() => setChosenProfile(profile.value)}>
                    <GlossyIcon tone={CARD_TONES[index % CARD_TONES.length]} icon="shieldPlain" size="sm" />
                    <strong>{profile.display_name}</strong>
                    <span className="newrun-policy-text">{profile.description}</span>
                    {selected && <span className="badge is-ok newrun-policy-mark"><Icon name="check" size={14} />선택됨</span>}
                  </button>
                )
              })}
              {profiles.length === 0 && <p className="faint-note">정책 목록을 불러오는 중…</p>}
            </div>
            {policyProfile === 'CUSTOM' && <p className="faint-note">{customPolicy ? '저장한 사용자 지정 규칙을 실행 시작 시 다시 검증해요.' : '정책 화면에서 사용자 지정 규칙을 먼저 검증하고 저장해 주세요.'}</p>}
          </section>

          <section className="newrun-section" aria-labelledby="newrun-permission">
            <h3 id="newrun-permission"><span className="newrun-step">3</span>권한</h3>
            <div className="glass-card newrun-permissions">
              <PermissionMenu mode={permission} profiles={permissionProfiles} disabled={false} onChoose={setPermission} />
            </div>
            <p className="faint-note">Codex 앱과 같은 권한 설정이에요. 작업창에서도 바꿀 수 있어요. 어떤 권한이든 AIA가 모든 명령을 실행 전에 검사해요. 전체 권한에서는 작업 폴더 밖 변경과 인터넷 사용을 Codex가 막지 않고, 작업 폴더 밖 변경은 되돌리기 범위 밖이에요.</p>
          </section>

          <section className="newrun-section" aria-labelledby="newrun-protect">
            <h3 id="newrun-protect"><span className="newrun-step">4</span>꼭 지킬 파일·폴더<small className="newrun-optional">선택</small></h3>
            <p className="faint-note">고른 파일과 폴더는 정책에 더해 지우기·옮기기·이름 바꾸기·덮어쓰기를 실행 전에 막아요. 셸 명령은 그 파일 이름이 명령에 보일 때 막고, 그 밖의 변경은 감시해 되돌릴 수 있어요. 읽기와 복사는 막지 않아요.</p>
            <div className="protect-actions">
              {hasNativeWorkspacePicker() ? (
                <>
                  <Button variant="secondary" className="is-compact" disabled={workspaceState.status !== 'valid'} onClick={() => pickProtected('files')}><Icon name="file" size={16} />파일 추가</Button>
                  <Button variant="secondary" className="is-compact" disabled={workspaceState.status !== 'valid'} onClick={() => pickProtected('folder')}><Icon name="folder" size={16} />폴더 추가</Button>
                </>
              ) : (
                <form className="protect-entry" onSubmit={(event) => { event.preventDefault(); if (protectEntry.trim()) { addProtected([absoluteInWorkspace(workspace, protectEntry)]); setProtectEntry('') } }}>
                  <input className="glass-input" value={protectEntry} disabled={workspaceState.status !== 'valid'} onChange={(event) => setProtectEntry(event.target.value)} placeholder="작업 폴더 안의 경로 (예: data\고객정보.db)" aria-label="보호할 파일·폴더 경로" />
                  <Button type="submit" variant="secondary" className="is-compact" disabled={workspaceState.status !== 'valid' || !protectEntry.trim()}>추가</Button>
                </form>
              )}
              {workspaceState.status !== 'valid' && <span className="faint-note">작업 폴더를 먼저 고르세요.</span>}
            </div>
            {protectedPaths.length > 0 && (
              <ul className="protect-list" aria-label="꼭 지킬 파일·폴더">
                {protectedPaths.map(path => (
                  <li key={path}>
                    <Icon name="shieldPlain" size={14} />
                    <span className="mono" title={path}>{insideWorkspace(workspace, path) ?? path}</span>
                    <Button variant="icon" className="protect-remove" aria-label={`${insideWorkspace(workspace, path) ?? path} 보호 해제`} onClick={() => setProtectedPaths(protectedPaths.filter(item => item !== path))}><Icon name="close" size={12} /></Button>
                  </li>
                ))}
              </ul>
            )}
            {protectMessage && <p className="warning-text" role="status">{protectMessage}</p>}
          </section>

          {models.length > 0 && (
            <section className="newrun-section" aria-labelledby="newrun-model">
              <h3 id="newrun-model"><span className="newrun-step">5</span>모델과 생각 깊이</h3>
              <div className="newrun-model">
                <label className="model-field">
                  <span>모델</span>
                  <select className="glass-input" value={model} onChange={(event) => { setModel(event.target.value); setEffort('') }}>
                    <option value="">Codex 기본값</option>
                    {models.map(item => <option key={item.model} value={item.model}>{item.display_name}</option>)}
                  </select>
                </label>
                <label className="model-field">
                  <span>생각 깊이</span>
                  <select className="glass-input" value={effort} onChange={(event) => setEffort(event.target.value)}>
                    <option value="">모델 기본값</option>
                    {effortsFor(models, model || null).map(item => <option key={item.effort} value={item.effort}>{effortLabel(item.effort)}</option>)}
                  </select>
                </label>
              </div>
              <p className="faint-note">작업창에서도 바꿀 수 있어요. 보호 설정은 모델과 상관없이 같아요.</p>
            </section>
          )}

          <section className="newrun-section" aria-labelledby="newrun-connection">
            <h3 id="newrun-connection"><span className="newrun-step">{models.length > 0 ? 6 : 5}</span>연결 상태</h3>
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
