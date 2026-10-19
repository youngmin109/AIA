import { useEffect, useMemo, useState } from 'react'
import { Button } from '../common/Button'
import { StatusPill } from '../common/Badge'
import { Icon } from '../common/Icon'
import { GlossyIcon, RoundAction, StatTile, TileCorner } from '../common/Glass'
import { MiniBars } from '../common/Charts'
import { GuardianFigure } from '../common/GuardianAvatar'
import { GUARDIAN_ALT } from '../common/guardianImages'
import { displayStatus, isSessionRunning, readinessNextStep } from '../../api/display'
import { observedCountLabel } from '../../api/activityDisplay'
import { TIMELINE_LIMIT, activityBuckets } from '../../api/chartMath'
import { blockingPillar, recoveryPillar } from '../../api/homeStatus'
import { readDefaultPolicyProfile } from '../policy/policyStorage'
import { sessionCreatedLabel, workspaceShortName } from '../shell/sessionLabel'
import { useShellStore } from '../../state/shellStore'
import { usePreflight } from '../../hooks/usePreflight'
import { useRunStatus } from '../../hooks/useRunStatus'
import { useRunList, isRunActive } from '../../hooks/useRunList'
import { sessionStateLabel } from '../../api/sessionNavigation'
import { useGuardianState } from '../../hooks/useGuardianState'
import { useProfiles } from '../../hooks/useProfiles'
import { blockDecisionCount, useRunActions } from '../../hooks/useRunActions'
import { elapsedLabel, useNow } from '../../hooks/useElapsed'
import type { RunStatus } from '../../api/types'
import { startupView } from '../../api/startupStatus'
import { UI_PREFERENCE_RESTORED_EVENT } from '../../api/preferenceSync'

/** ① before a run and ② while the selected run is live. */
export function HomeView() {
  const { activeRunId } = useShellStore()
  const { data: status, error } = useRunStatus(activeRunId, { enabled: Boolean(activeRunId) })
  const live = isSessionRunning(status?.session?.status, status?.runtime_reconciliation?.orphaned)
  return live && status ? <HomeLive status={status} stale={Boolean(error)} /> : <HomeIdle />
}

function HomeIdle() {
  const { setView, openNewRun, setActiveRun, openResult } = useShellStore()
  const { data: preflight, error: preflightError } = usePreflight()
  const { data: runs } = useRunList()
  const { profiles } = useProfiles()
  const guardian = useGuardianState()
  const [policyValue, setPolicyValue] = useState(readDefaultPolicyProfile)
  useEffect(() => {
    const restoreDefault = (event: Event) => {
      if ((event as CustomEvent<string>).detail === 'aia.defaultPolicyProfile') setPolicyValue(readDefaultPolicyProfile())
    }
    window.addEventListener(UI_PREFERENCE_RESTORED_EVENT, restoreDefault)
    return () => window.removeEventListener(UI_PREFERENCE_RESTORED_EVENT, restoreDefault)
  }, [])
  const ready = preflight?.readiness_code === 'READY'
  const checks = preflight?.checks
  const blocking = blockingPillar(checks)
  const recovery = recoveryPillar(checks)
  const lastRun = runs?.[0]
  const liveRun = (runs ?? []).find(isRunActive)
  const policyName = profiles.find(profile => profile.value === policyValue)?.display_name ?? profiles[0]?.display_name ?? '기본 정책'

  function openLastRun() {
    if (!lastRun) return
    if (isRunActive(lastRun)) {
      setActiveRun(lastRun.session_id)
      setView('work')
    } else {
      openResult(lastRun.session_id)
    }
  }

  return (
    <div className="page-stack home-page view-enter">
      <header className="home-head">
        <span className="home-head-title">보호 현황</span>
        <StatusPill tone={preflightError ? 'bad' : ready ? 'good' : preflight ? 'warning' : 'neutral'}>
          {preflightError ? '연결 확인 필요' : ready ? '보호 연결 정상' : preflight ? displayStatus(preflight.readiness_code).replace('상세 확인 필요', '연결 확인 필요') : '연결 확인 중'}
        </StatusPill>
      </header>

      <div className="lens-anchor home-hero-wrap">
      <span className="lens-orb at-home" aria-hidden="true" />
      <section className="glass is-hero lens-hero home-hero" aria-label="보호 준비">
        <div className="home-hero-copy">
          <span className="eyebrow">AI AGENT GUARD</span>
          <h1>{ready ? <>에이전트 작업을<br />지켜볼 준비가 됐어요</> : <>보호 연결을<br />먼저 확인해 주세요</>}</h1>
          {!ready && preflight && <p className="home-hero-next">{readinessNextStep(preflight.readiness_code)}</p>}
          <div className="home-hero-chips">
            <span className="chip"><Icon name="folder" size={16} />{lastRun?.workspace ? workspaceShortName(lastRun.workspace) : '작업 폴더 선택 전'}</span>
            <span className="chip"><Icon name="shieldPlain" size={16} />{policyName}</span>
            {!ready && <Button variant="secondary" className="is-compact" onClick={() => setView('settings')}>연결 상태 보기</Button>}
          </div>
        </div>
        <GuardianFigure state={guardian.state} alt={GUARDIAN_ALT[guardian.state]} className="home-hero-guardian" />
      </section>
      </div>

      <section className="home-tiles" aria-label="보호 단계">
        <article className="glass-card home-tile">
          <TileCorner tone="hook" icon="shieldPlain" />
          <span className="home-tile-label">실행 전 차단</span>
          <strong className="home-tile-value">{blocking === 'ready' ? '준비됨' : blocking === 'setup' ? '설정 필요' : '확인 중'}</strong>
          <span className="home-tile-note">실행 전에 위험 요청을 검사해요</span>
        </article>
        <article className="glass-card home-tile">
          <TileCorner tone="process" icon="pulse" />
          <span className="home-tile-label">실행 중 감시</span>
          <strong className="home-tile-value">자동 시작</strong>
          <span className="home-tile-note">실행하면 프로세스·파일 변화를 관찰해요</span>
        </article>
        <article className="glass-card home-tile">
          <TileCorner tone="file" icon="restore" />
          <span className="home-tile-label">실행 후 복구</span>
          <strong className="home-tile-value">{recovery === 'checking' ? '확인 중' : recovery === 'setup' ? '설정 필요' : '실행 전 저장'}</strong>
          <span className="home-tile-note">실행하면 시작 시점을 저장해요</span>
        </article>
        <button type="button" className="glass-card home-tile is-button" onClick={openLastRun} disabled={!lastRun}>
          <TileCorner tone="amber" icon="clock" />
          <span className="home-tile-label">최근 실행{lastRun ? ` · ${sessionCreatedLabel(lastRun.created_at)}` : ''}</span>
          <strong className="home-tile-value">{!lastRun ? '없음' : (lastRun.incident_count ?? 0) > 0 ? `사건 ${lastRun.incident_count}건` : (lastRun.unevaluated_observation_count ?? 0) > 0 ? `판정 불가 관찰 ${lastRun.unevaluated_observation_count}건` : sessionStateLabel(lastRun)}</strong>
          <span className="home-tile-note home-tile-link">{lastRun ? <>{(lastRun.incident_count ?? 0) > 0 && (lastRun.unevaluated_observation_count ?? 0) > 0 ? `판정 불가 관찰 ${lastRun.unevaluated_observation_count}건 · ` : ''}결과 보기 <Icon name="arrowRight" size={14} /></> : '보호 실행을 시작해 보세요'}</span>
        </button>
      </section>

      <div className="home-action">
        {liveRun ? (
          <>
            <RoundAction onClick={() => { setActiveRun(liveRun.session_id); setView('work') }}>작업 열기</RoundAction>
            <Button variant="text" onClick={openNewRun}><Icon name="plus" size={14} />다른 폴더에서 새 대화</Button>
          </>
        ) : (
          <RoundAction onClick={openNewRun}>보호 시작</RoundAction>
        )}
      </div>
    </div>
  )
}

function HomeLive({ status, stale }: { status: RunStatus; stale: boolean }) {
  const { activeRunId, activeView, setView, requestEnd, codexActivity } = useShellStore()
  // Views stay mounted; the hidden home must not poll the same list the Work view already does.
  const { data: actions } = useRunActions(activeRunId, activeView === 'home')
  const blocks = blockDecisionCount(actions)
  const summary = status.evidence_summary
  const activity = status.activity
  const now = useNow(true)
  const elapsed = elapsedLabel(status.session?.created_at, now)
  const recentActivity = useMemo(() => activityBuckets(status.evidence_timeline, now), [status.evidence_timeline, now])
  const waitingApproval = codexActivity?.runId === activeRunId && Boolean(codexActivity?.terminalAction)
  const startup = startupView(status.startup)
  const recent = (status.events ?? []).filter(event => event.category !== 'SENSOR').slice(-6).reverse()
  const processes = activity?.current_alive_count ?? activity?.process_identity_count

  const rows: Array<{ key: string; icon: Parameters<typeof GlossyIcon>[0]['icon']; tone: Parameters<typeof GlossyIcon>[0]['tone']; label: string; value: string; state: 'done' | 'live' | 'alert' }> = [
    { key: 'pretool', icon: 'shieldPlain', tone: 'hook', label: '실행 전 검사', value: `${summary?.pretool_events ?? 0}건`, state: 'done' },
    { key: 'process', icon: 'pulse', tone: 'process', label: '프로세스 감시', value: observedCountLabel(activity?.available, activity?.process_identity_count), state: 'live' },
    { key: 'file', icon: 'file', tone: 'file', label: '파일 변경 기록', value: observedCountLabel(activity?.available, activity?.unique_file_count), state: 'live' },
  ]
  if (blocks > 0) rows.push({ key: 'block', icon: 'block', tone: 'danger', label: '위험 요청 차단 판정', value: `${blocks}건`, state: 'alert' })

  return (
    <div className="page-stack home-page view-enter">
      <header className="home-head">
        <span className="home-head-title"><span className="status-dot is-ok" />보호 실행 중 · {workspaceShortName(status.session?.workspace)}</span>
        {elapsed && <span className="chip home-elapsed" aria-label={`경과 시간 ${elapsed}`}>{elapsed}</span>}
      </header>
      {stale && <div className="glass-notice is-warning" role="alert"><strong>최신 상태를 가져오지 못했어요</strong><p>연결이 돌아오기 전까지 이 화면을 현재 상태로 보지 마세요.</p></div>}

      <div className="home-live-grid lens-anchor">
        <span className="lens-orb at-live" aria-hidden="true" />
        <section className="glass is-hero lens-panel home-live-hero" aria-label="보호 진행">
          <div className="home-live-copy">
            <h1>보호 중…</h1>
            <ul className="home-live-list">
              {rows.map(row => (
                <li key={row.key} className={row.state === 'alert' ? 'is-alert' : undefined}>
                  <GlossyIcon tone={row.tone} icon={row.icon} size="sm" />
                  <span className="home-live-label">{row.label}</span>
                  <span className="home-live-value">{row.value}</span>
                  {row.state === 'done' ? <Icon name="check" size={18} /> : row.state === 'live' ? <span className="spinner" aria-hidden="true" /> : <Icon name="alert" size={18} />}
                </li>
              ))}
            </ul>
          </div>
          <GuardianFigure state={blocks > 0 ? 'blocked' : 'normal'} alt={GUARDIAN_ALT[blocks > 0 ? 'blocked' : 'normal']} className="home-live-guardian" />
        </section>

        <section className="glass is-soft home-codex" aria-label="Codex 상태">
          <div className="home-codex-head">
            <span className="muted">Codex 대화</span>
            <Button variant="text" onClick={() => setView('work')}>크게 보기 <Icon name="arrowRight" size={14} /></Button>
          </div>
          {waitingApproval ? (
            <button type="button" className="glass-notice is-warning home-codex-approval" onClick={() => setView('work')}>
              <strong>Codex가 승인을 기다리고 있어요</strong><span>확인하기 →</span>
            </button>
          ) : (
            <p className="home-codex-state">{startup ? `${startup.label}${startup.detail ? ` · ${startup.detail}` : ''}` : codexActivity?.runId !== activeRunId ? '작업창에서 Codex에게 요청을 보낼 수 있어요' : codexActivity.mode === 'WORKING' ? 'Codex가 작업하고 있어요' : codexActivity.mode === 'WAITING' ? 'Codex가 다음 요청을 기다려요' : 'Codex 연결을 준비하고 있어요'}</p>
          )}
          <span className="muted home-codex-sub">최근 관찰</span>
          {recent.length === 0 ? <p className="faint-note">아직 관찰된 요청이 없어요.</p> : (
            <ul className="home-codex-events">
              {recent.map((event, index) => <li key={event.event_id ?? index}><span className={`status-dot ${event.severity === 'HIGH' || event.category === 'ENFORCEMENT' ? 'is-bad' : 'is-ok'}`} />{event.display_summary ?? event.summary ?? '관찰 기록'}</li>)}
            </ul>
          )}
        </section>
      </div>

      <section className="home-live-tiles" aria-label="실시간 숫자">
        <StatTile label="차단 판정" value={blocks} tone={blocks > 0 ? 'danger' : undefined} note="실행 전 정책 판정" />
        <StatTile label={activity?.current_alive_count == null ? '누적 관찰 프로세스' : '현재 실행 프로세스'} value={processes ?? '—'} note={activity?.current_alive_count == null ? '세션 전체 관찰 수' : '지금 살아 있는 수'} />
        <StatTile label="파일 변경" value={observedCountLabel(activity?.available, activity?.unique_file_count)} note={activity?.available === true ? '관찰된 경로 수' : '관찰 기록을 확인할 수 없어요'} />
        <div className="glass-card stat-tile">
          <span className="stat-label">최근 5분 활동</span>
          <MiniBars values={recentActivity.counts} showValues label={`1분 단위 실행 요청·프로세스·파일 변화 ${recentActivity.counts.join(', ')}건`} />
          <span className="stat-note">이번 1분 {recentActivity.current}건 · 실행 요청·프로세스·파일 변화{recentActivity.partial && ` · 최근 ${TIMELINE_LIMIT}건 기준`}</span>
        </div>
      </section>

      <div className="home-action">
        <RoundAction small onClick={requestEnd}>종료</RoundAction>
      </div>
    </div>
  )
}
