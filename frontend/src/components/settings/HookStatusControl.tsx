import { Button } from '../common/Button'
import { Icon } from '../common/Icon'
import { useEffect, useState } from 'react'
import { usePreflight } from '../../hooks/usePreflight'
import { installHook, verifyHook, consoleInfo, type ConsoleInfo } from '../../api/endpoints'

const FAST_POLL_MS = 5_000
const SLOW_POLL_MS = 30_000

type Phase = 'checking' | 'not_installed' | 'trust_required' | 'verify_required' | 'not_writable' | 'unavailable' | 'ready'

function phaseFor(readinessCode: string | undefined, hasData: boolean, checks?: Array<{ name: string; ok: boolean }>): Phase {
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
    default: {
      // Generic NOT_READY (servers that skip Hook verification): place the step from the checks.
      const hook = checks?.find(check => check.name === 'pretool_hook')
      if (hook && !hook.ok) return 'not_installed'
      const trust = checks?.find(check => check.name === 'codex_hook_trust')
      if (trust && !trust.ok) return 'trust_required'
      return 'verify_required'
    }
  }
}

/** Three-step Hook setup (install → trust in Codex → verify). Trust is always the user's decision inside Codex. */
export function HookStatusControl({ onReadyChange }: { onReadyChange?: (ready: boolean) => void }) {
  const [pollIntervalMs, setPollIntervalMs] = useState(SLOW_POLL_MS)
  const { data: preflight, error, refetch } = usePreflight(pollIntervalMs)
  const phase = phaseFor(preflight?.readiness_code, Boolean(preflight), preflight?.checks)

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
  const [verifyMessageTone, setVerifyMessageTone] = useState<'warning' | 'danger'>('warning')

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
        setVerifyMessageTone('warning')
        setVerifyMessage('검증이 예상보다 오래 걸립니다. Codex 실행 환경을 확인한 뒤 다시 시도하세요.')
      } else if (result.reason === 'CODEX_HOOK_TRUST_REQUIRED' || result.reason === 'PRETOOL_HOOK_NOT_INSTALLED') {
        // Preflight will re-derive the correct earlier phase on refetch;
        // not a user-facing error, just a stale click.
        setVerifyMessage(null)
      } else {
        setVerifyMessageTone('danger')
        setVerifyMessage(result.next_step || result.reason || '검증에 실패했습니다.')
      }
      await refetch()
    } catch (err) {
      setVerifyMessageTone('danger')
      setVerifyMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setVerifying(false)
    }
  }

  const lastVerifiedAt = preflight?.hook_activation?.status === 'OBSERVED_IN_PAST'
  const installed = !['checking', 'unavailable', 'not_installed'].includes(phase)
  const trusted = ['verify_required', 'ready', 'not_writable'].includes(phase)
  const verified = ['ready', 'not_writable'].includes(phase)
  const steps: Array<[boolean, string, string]> = [
    [installed, phase === 'unavailable' ? 'Codex 설치 필요' : 'Hook 설치', installed ? '완료' : phase === 'unavailable' ? 'Codex 경로 확인' : 'AIA에서 설치'],
    [trusted, 'Codex에서 신뢰', trusted ? '완료' : '/hooks에서 Trust'],
    [verified, '연결 검증', verified ? '완료' : 'AIA에서 확인'],
  ]

  return (
    <div className="hook-setup">
      <ol className="hook-steps" aria-label="AIA Hook 연결 단계">
        {steps.map(([done, title, note], index) => (
          <li key={title} className={done ? 'is-done' : undefined}>
            <span className="hook-step-mark">{done ? <Icon name="check" size={16} /> : index + 1}</span>
            <span><b>{title}</b><small>{note}</small></span>
          </li>
        ))}
      </ol>

      {error && <div role="alert" className="glass-notice is-warning"><strong>연결 상태를 가져오지 못했어요</strong><Button variant="text" onClick={refetch}>다시 확인</Button></div>}
      {phase === 'checking' && !error && <p className="faint-note">연결 상태를 확인하는 중…</p>}

      {phase === 'unavailable' && (
        <div className="glass-notice is-warning"><div><strong>Codex 설치 또는 경로 확인이 필요해요</strong><p>{preflight?.next_step}</p></div></div>
      )}

      {phase === 'not_installed' && (
        <div className="glass-notice is-warning hook-phase">
          <div><strong>AIA Hook을 설치하세요</strong><p>설치 후에는 Codex에서 이 Hook을 직접 검토하고 신뢰하게 돼요.</p>{installError && <p className="danger-text">{installError}</p>}</div>
          <Button variant="cta" className="is-compact" disabled={installing} onClick={handleInstall}>{installing ? '설치하는 중…' : 'Hook 설치'}</Button>
        </div>
      )}

      {phase === 'trust_required' && (
        <div className="glass-notice is-warning hook-phase">
          <div>
            <strong>Codex에서 AIA Hook을 신뢰하세요</strong>
            <p>새 터미널에서 <code className="mono">codex</code>를 실행하고 <code className="mono">/hooks</code>에서 AIA Hook을 검토한 뒤 Trust를 고르세요. 끝나면 몇 초 안에 자동으로 감지돼요.</p>
          </div>
        </div>
      )}

      {phase === 'verify_required' && (
        <div className="glass-notice hook-phase">
          <div>
            <strong>AIA에서 연결을 검증하세요</strong>
            <p>Hook이 실제 실행 전 요청을 AIA에 전달하는지 확인해요.{lastVerifiedAt ? ' 이전 실행에서 검증된 적이 있어요. 다시 검증하면 최신 상태로 바뀌어요.' : ''}</p>
            {verifyMessage && <p className={verifyMessageTone === 'danger' ? 'danger-text' : 'warning-text'}>{verifyMessage}</p>}
          </div>
          <Button variant="cta" className="is-compact" disabled={verifying} onClick={handleVerify}>{verifying ? '검증하는 중… (최대 4분)' : '연결 검증'}</Button>
        </div>
      )}

      {phase === 'not_writable' && (
        <div className="glass-notice is-warning"><div><strong>로컬 기록 폴더 권한을 확인하세요</strong><p>{preflight?.next_step}</p></div></div>
      )}

      {cli && (
        <details className="hook-advanced">
          <summary>터미널에서 직접 검증하기</summary>
          <div className="hook-command">
            <code className="mono">{cli.cli_prefix} hook verify</code>
            <Button variant="iconText" onClick={() => { navigator.clipboard?.writeText(`${cli.cli_prefix} hook verify`).catch(() => {}) }} title="명령 복사">복사</Button>
          </div>
        </details>
      )}
    </div>
  )
}
