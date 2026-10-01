import { useEffect, useState } from 'react'
import { usePreflight } from '../../hooks/usePreflight'
import { installHook, verifyHook, consoleInfo, type ConsoleInfo } from '../../api/endpoints'

const FAST_POLL_MS = 5_000
const SLOW_POLL_MS = 30_000

type Phase = 'checking' | 'not_installed' | 'trust_required' | 'verify_required' | 'not_writable' | 'unavailable' | 'ready'

function phaseFor(readinessCode: string | undefined, hasData: boolean): Phase {
  if (!hasData) return 'checking'
  switch (readinessCode) {
    case 'CODEX_EXECUTABLE_UNAVAILABLE':
      return 'unavailable'
    case 'CODEX_HOOK_NOT_INSTALLED':
      return 'not_installed'
    case 'CODEX_HOOK_TRUST_REQUIRED':
      return 'trust_required'
    case 'HOOK_VERIFICATION_REQUIRED':
      return 'verify_required'
    case 'CONTROL_ROOT_NOT_WRITABLE':
      return 'not_writable'
    case 'READY':
      return 'ready'
    default:
      return 'verify_required'
  }
}

export function HookStatusControl({ onReadyChange }: { onReadyChange?: (ready: boolean) => void }) {
  const [pollIntervalMs, setPollIntervalMs] = useState(SLOW_POLL_MS)
  const { data: preflight, refetch } = usePreflight(pollIntervalMs)
  const phase = phaseFor(preflight?.readiness_code, Boolean(preflight))

  // Fast-poll only while waiting on the one step AIA can't do for the user
  // (trusting the Hook inside Codex's own /hooks review) -- this is the
  // one moment where the answer can change at any time from outside AIA.
  useEffect(() => {
    setPollIntervalMs(phase === 'trust_required' ? FAST_POLL_MS : SLOW_POLL_MS)
  }, [phase])

  useEffect(() => {
    onReadyChange?.(phase === 'ready')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase])

  const [installing, setInstalling] = useState(false)
  const [installError, setInstallError] = useState<string | null>(null)
  const [verifying, setVerifying] = useState(false)
  const [verifyMessage, setVerifyMessage] = useState<string | null>(null)
  const [verifyMessageTone, setVerifyMessageTone] = useState<'warn' | 'bad'>('warn')

  const [cli, setCli] = useState<ConsoleInfo | null>(null)
  useEffect(() => {
    consoleInfo().then(setCli).catch(() => setCli(null))
  }, [])

  async function handleInstall() {
    setInstalling(true)
    setInstallError(null)
    try {
      const result = await installHook()
      if (!result.installed) setInstallError(result.error ?? 'Hook 설치에 실패했습니다.')
      await refetch()
    } catch (err) {
      setInstallError(err instanceof Error ? err.message : String(err))
    } finally {
      setInstalling(false)
    }
  }

  async function handleVerify() {
    setVerifying(true)
    setVerifyMessage(null)
    try {
      const result = await verifyHook()
      if (result.verified) {
        setVerifyMessage(null)
      } else if (result.reason === 'HOOK_VERIFICATION_TIMEOUT') {
        setVerifyMessageTone('warn')
        setVerifyMessage('검증이 예상보다 오래 걸립니다. Codex 실행 환경을 확인한 뒤 다시 시도하세요.')
      } else if (result.reason === 'CODEX_HOOK_TRUST_REQUIRED' || result.reason === 'PRETOOL_HOOK_NOT_INSTALLED') {
        // Preflight will re-derive the correct earlier phase on refetch;
        // not a user-facing error, just a stale click.
        setVerifyMessage(null)
      } else {
        setVerifyMessageTone('bad')
        setVerifyMessage(result.next_step || result.reason || '검증에 실패했습니다.')
      }
      await refetch()
    } catch (err) {
      setVerifyMessageTone('bad')
      setVerifyMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setVerifying(false)
    }
  }

  const trustDetail = preflight?.codex_hook_trust?.hooks?.find((hook) => hook.event === 'preToolUse')?.trust_status
  const lastVerifiedAt = preflight?.hook_activation?.status === 'OBSERVED_IN_PAST'
  const installed = !['checking', 'unavailable', 'not_installed'].includes(phase)
  const trusted = ['verify_required', 'ready', 'not_writable'].includes(phase)
  const verified = ['ready', 'not_writable'].includes(phase)
  const firstStepLabel = phase === 'unavailable' ? 'Codex 설치 필요' : 'Hook 설치'

  return (
    <div className="panel-section">
      <p className="panel-section-title">AIA Hook 연결</p>
      <div className="hook-setup-intro">
        <b>처음 한 번만, 아래 순서대로 연결하세요.</b>
        <p>Hook은 Codex가 도구를 실행하기 직전 AIA에 알려 주는 연결 지점입니다. <strong>Trust는 Codex 안에서 사용자가 직접 승인</strong>해야 해요.</p>
        <ol className="hook-setup-steps" aria-label="AIA Hook 연결 단계">
          <li className={installed ? 'is-done' : ''}><span>1</span><b>{firstStepLabel}</b><small>{installed ? '완료' : phase === 'unavailable' ? 'Codex 경로 확인' : 'AIA에서 설치'}</small></li>
          <li className={trusted ? 'is-done' : ''}><span>2</span><b>Codex에서 신뢰</b><small>{trusted ? '완료' : '/hooks에서 Trust'}</small></li>
          <li className={verified ? 'is-done' : ''}><span>3</span><b>연결 검증</b><small>{verified ? '완료' : 'AIA에서 확인'}</small></li>
        </ol>
      </div>

      {phase === 'checking' && <div className="stat-card"><div className="stat-card-value">확인하는 중…</div></div>}

      {phase === 'unavailable' && (
        <div className="stat-card">
          <div className="stat-card-value is-warn">1. Codex 설치 또는 경로 확인이 필요합니다</div>
          <div className="stat-card-label">{preflight?.next_step}</div>
        </div>
      )}

      {phase === 'not_installed' && (
        <div className="stat-card">
          <div className="stat-card-value is-warn">1. AIA Hook을 설치하세요</div>
          <div className="stat-card-label">설치 후에는 Codex에서 이 Hook을 직접 검토하고 신뢰하게 됩니다.</div>
          {installError && <div style={{ color: 'var(--danger)', fontSize: 11, marginTop: 4 }}>{installError}</div>}
          <button type="button" className="cta-button" style={{ marginTop: 10 }} disabled={installing} onClick={handleInstall}>
            {installing ? '설치하는 중…' : '1. Hook 설치'}
          </button>
        </div>
      )}

      {phase === 'trust_required' && (
        <div className="stat-card">
          <div className="stat-card-value is-warn">2. Codex에서 AIA Hook을 신뢰하세요</div>
          {trustDetail && <div className="badge is-warn" style={{ marginTop: 4 }}>preToolUse: {trustDetail}</div>}
          <ol style={{ margin: '10px 0 0', paddingLeft: 18, fontSize: 12, color: 'var(--text-muted)', display: 'grid', gap: 4 }}>
            <li>새 터미널에서 <code className="mono">codex</code>를 실행합니다.</li>
            <li><code className="mono">/hooks</code>를 입력하고 AIA Hook을 검토한 뒤 <b>Trust</b>를 선택합니다.</li>
          </ol>
          <div style={{ fontSize: 11, color: 'var(--text-faint)', marginTop: 8 }}>신뢰가 끝나면 자동으로 감지됩니다 (몇 초 내).</div>
        </div>
      )}

      {phase === 'verify_required' && (
        <div className="stat-card">
          <div className="stat-card-value is-ok">3. AIA에서 연결을 검증하세요</div>
          <div className="stat-card-label">검증은 Hook이 실제 사전 실행 이벤트를 AIA에 전달할 수 있는지 확인합니다.</div>
          {lastVerifiedAt && (
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
              이전 실행에서 한 번 검증된 적이 있습니다 — 다시 검증하면 최신 상태로 갱신됩니다.
            </div>
          )}
          {verifyMessage && (
            <div style={{ color: verifyMessageTone === 'bad' ? 'var(--danger)' : 'var(--warning)', fontSize: 11, marginTop: 4 }}>
              {verifyMessage}
            </div>
          )}
          <button type="button" className="cta-button" style={{ marginTop: 10 }} disabled={verifying} onClick={handleVerify}>
            {verifying ? '검증하는 중… (최대 4분)' : '3. 연결 검증'}
          </button>
        </div>
      )}

      {phase === 'not_writable' && (
        <div className="stat-card">
          <div className="stat-card-value is-warn">AIA Control Root 권한 문제</div>
          <div className="stat-card-label">{preflight?.next_step}</div>
        </div>
      )}

      {phase === 'ready' && (
        <div className="stat-card">
          <div className="stat-card-value is-ok">보호 실행 준비 완료</div>
          <div className="stat-card-label">이제 Workspace와 정책을 고르고 보호 실행을 시작할 수 있습니다.</div>
        </div>
      )}

      {cli && (
        <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 8, fontSize: 11 }}>
          <code className="mono" style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-muted)' }}>
            {cli.cli_prefix} hook verify
          </code>
          <button
            type="button"
            className="icon-button-text"
            onClick={() => {
              if (!navigator.clipboard) return
              navigator.clipboard.writeText(`${cli.cli_prefix} hook verify`).catch(() => {})
            }}
            title="명령 복사"
          >
            복사
          </button>
        </div>
      )}
    </div>
  )
}
