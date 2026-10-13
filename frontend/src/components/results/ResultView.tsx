import { grantSummary, widensBeyondProtection } from '../../api/permissionGrants'
import { useRef, useState } from 'react'
import { Button } from '../common/Button'
import { Badge } from '../common/Badge'
import { Icon } from '../common/Icon'
import { StatTile } from '../common/Glass'
import { BarList, ChartLegend, DonutChart } from '../common/Charts'
import { GuardianFigure } from '../common/GuardianAvatar'
import type { GuardianState } from '../../api/guardianStatus'
import { useResult } from '../../hooks/useResult'
import { useRecoveryStatus } from '../../hooks/useRecoveryStatus'
import { useRunSnapshot } from '../../hooks/useRunSnapshot'
import { displayStatus, statusTone } from '../../api/display'
import type { IncidentView, RecoveryStatusView, ResultView as ResultData } from '../../api/resultTypes'
import { deriveVerdict } from '../../api/resultVerdict'
import { verdictSlices } from '../../api/chartMath'
import { fileBreakdown, resultHeadline } from '../../api/resultSummary'
import { useShellStore } from '../../state/shellStore'
import { sessionCreatedLabel, workspaceShortName } from '../shell/sessionLabel'
import { EvidenceLogView } from './EvidenceLogView'
import { RestoreComplete, RestoreDialog, type RestoreOutcome } from './WorkspaceRestoreControl'

function toneFor(value: string | undefined): 'ok' | 'warn' | 'bad' {
  const upper = String(value || '').toUpperCase()
  if (['VALID', 'VERIFIED', 'RESTORED', 'COMPLETED', 'TRUSTED'].includes(upper)) return 'ok'
  if (['INVALID', 'FAILED', 'VIOLATION', 'MISSING'].includes(upper)) return 'bad'
  return 'warn'
}

function guardianFor(data: ResultData, tone: 'ok' | 'warn' | 'bad'): GuardianState {
  if (tone === 'bad') return 'review'
  if (data.recovery_status === 'RESTORED' && data.integrity_status === 'VERIFIED') return 'recovery'
  if ((data.incidents?.length ?? 0) > 0) return 'blocked'
  return tone === 'ok' ? 'normal' : 'review'
}

function durationLabel(start?: unknown, end?: unknown): string | null {
  const ms = Date.parse(String(end ?? '')) - Date.parse(String(start ?? ''))
  if (!(ms >= 0)) return null
  const minutes = Math.round(ms / 60_000)
  if (minutes < 1) return '1분 미만'
  if (minutes < 60) return `${minutes}분`
  const hours = Math.floor(minutes / 60)
  return hours < 24 ? `${hours}시간 ${minutes % 60}분` : `${Math.floor(hours / 24)}일 이상`
}

function restoreTile(recovery: RecoveryStatusView | null, data: ResultData): { value: string; note: string; tone?: 'success' | 'warning' } {
  if (recovery?.manual_recovery && recovery.recovery_status === 'RESTORED' && recovery.integrity_status === 'VERIFIED') return { value: '완료', note: '되돌리고 검증함', tone: 'success' }
  if (data.recovery_status === 'RESTORED' && data.integrity_status === 'VERIFIED') return { value: '자동 복구', note: '복구·검증 완료', tone: 'success' }
  if (!recovery) return { value: '확인 중', note: '기준점 확인 중' }
  if (recovery.workspace_matches) return { value: '변경 없음', note: '기준점과 같아요' }
  if (recovery.available) return { value: '가능', note: `바뀐 항목 ${recovery.change_count ?? 0}개` }
  const note = recovery.reason === 'RUN_IS_ACTIVE' ? '실행이 끝나면 가능' : recovery.reason === 'SNAPSHOT_PRUNED' ? '저장 공간 정리로 사본을 지웠어요' : '기준점이 없어요'
  return { value: '불가', note, tone: 'warning' }
}

/** ③ Result: one glance summary on top, every detailed section folded below. */
export function ResultView({ runId, showEvidenceLog = false }: { runId: string; showEvidenceLog?: boolean }) {
  const { setView } = useShellStore()
  const { data, error, isLoading } = useResult(runId)
  const { data: recovery, error: recoveryError, reload: reloadRecovery } = useRecoveryStatus(runId)
  const snapshot = useRunSnapshot(runId)
  const [restoreOpen, setRestoreOpen] = useState(false)
  const [outcome, setOutcome] = useState<RestoreOutcome | null>(null)
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const detailsRef = useRef<HTMLDivElement>(null)

  if (isLoading) {
    return <div className="glass-empty"><span className="spinner" aria-hidden="true" /><strong>결과를 불러오는 중이에요…</strong></div>
  }
  if (error || !data) {
    return <div className="glass-empty"><strong>결과를 보여줄 수 없어요</strong><span>{error || '실행 기록을 확인할 수 없습니다.'}</span></div>
  }
  if (outcome) {
    return <RestoreComplete outcome={outcome} onBack={() => setOutcome(null)} onHome={() => setView('home')} />
  }

  const incidents = data.incidents ?? []
  const verdict = deriveVerdict(data)
  const summary = data.action_summary as { total?: number; compliant?: number; audit?: number; violation?: number; indeterminate?: number; contain?: number; blocked?: number; terminated?: number } | undefined
  const slices = verdictSlices(summary)
  const activity = snapshot?.activity
  const changedFiles = activity?.available ? activity.unique_file_count ?? 0 : null
  const headline = resultHeadline({ ...data, action_summary: summary, codex_block_confirmation: data.codex_block_confirmation as string | undefined }, changedFiles)
  const breakdown = fileBreakdown(activity?.files)
  const attention = verdict.tone === 'ok' ? 0 : Math.max(1, incidents.length)
  const restore = restoreTile(recovery, data)
  const canRestore = Boolean(recovery?.available && !recovery.workspace_matches && recovery.preview_fingerprint)
  const duration = durationLabel(data.started_at, data.ended_at)
  // STOPPED at the end of a run is a normal finish; only warn/bad states count as problems.
  const sensorIssues = (data.sensor_summary ?? []).filter(sensor => ['warn', 'bad'].includes(statusTone(sensor.final_sensor_state))).length
  const blockedConfirmed = data.codex_block_confirmation === 'BLOCK_CONFIRMED' ? summary?.blocked ?? 0 : 0

  function showEvidence() {
    setEvidenceOpen(true)
    window.setTimeout(() => detailsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
  }

  return (
    <div className="page-stack result-page view-enter">
      <header className="result-head">
        <span className="home-head-title">보호 실행 결과</span>
        <span className="muted">{[workspaceShortName(data.workspace), sessionCreatedLabel(data.started_at as string | undefined), duration].filter(Boolean).join(' · ')}</span>
      </header>

      {(snapshot?.permission_grants ?? []).length > 0 && (
        <div className="glass-notice is-warning" role="note">
          <div>
            <strong>이번 실행에 권한 확대 또는 요청 기록이 있어요</strong>
            {(snapshot?.permission_grants ?? []).map((grant) => <p key={grant.granted_at}>{grantSummary(grant)}</p>)}
            {widensBeyondProtection(snapshot?.permission_grants) && <p>작업 폴더 밖 쓰기와 인터넷 사용은 AIA 기준점·복구와 감시 범위 밖이라, 이 결과가 그 부분까지 보장하지는 않아요.</p>}
          </div>
        </div>
      )}

      {verdict.executionPolicyAttention && (
        <div className="glass-notice is-warning" role="note">
          <div><strong>Codex 실행 정책을 확인해 주세요</strong><p>{verdict.executionPolicyStatus === 'NOT_OBSERVED' ? 'Codex 실행 정책이 관찰되지 않았어요. 실제 적용 정책을 확인하기 전에는 완전한 보호 성공으로 보지 마세요.' : 'Codex 실행 정책이 저하된 상태로 관찰됐어요. 실제 적용 정책을 확인하세요.'}</p></div>
        </div>
      )}

      <div className="lens-anchor">
      <span className="lens-orb at-result" aria-hidden="true" />
      <section className="glass is-hero lens-hero result-hero" aria-label="결과 요약">
        <GuardianFigure state={guardianFor(data, verdict.tone)} alt="결과를 알려주는 아이아 가디언" className="result-guardian" />
        <div className="result-hero-copy">
          <span className={`status-pill ${attention > 0 ? 'warning' : 'good'}`}>{attention > 0 ? `확인할 것 ${attention}개` : '모두 확인됐어요'}</span>
          <h1>{headline.map((line, index) => <span key={line}>{line}{index < headline.length - 1 && <br />}</span>)}</h1>
          <p className="muted">{verdict.headline}</p>
          <div className="result-actions">
            {canRestore && <Button variant="cta" onClick={() => setRestoreOpen(true)}><Icon name="restore" size={18} />작업 폴더 되돌리기</Button>}
            <Button variant="secondary" onClick={showEvidence}>증거 보기</Button>
            <Button variant="text" onClick={() => setView('home')}>홈으로</Button>
          </div>
        </div>
        <div className="result-donut">
          <DonutChart slices={slices} centerValue={summary?.total ?? 0} centerLabel="판정" label={`판정 비율: ${slices.map(slice => `${slice.label} ${slice.value}`).join(', ')}`} />
          <ChartLegend slices={slices.filter(slice => slice.value > 0)} />
        </div>
      </section>
      </div>

      <section className="stat-grid" aria-label="결과 숫자">
        <StatTile label="차단 판정" value={summary?.contain ?? 0} tone={(summary?.contain ?? 0) > 0 ? 'danger' : undefined} note={blockedConfirmed > 0 ? `막음 확인 ${blockedConfirmed}건` : '실행 전 정책 판정'} />
        <StatTile label="파일 변경" value={changedFiles ?? '—'} note={changedFiles === null ? '관찰 기록 확인 중' : '관찰된 경로 수'} />
        <StatTile label="되돌리기" value={restore.value} word tone={restore.tone} note={restore.note} />
        <StatTile label="감사 기록" value={data.bundle_status === 'VALID' ? '확인됨' : displayStatus(data.bundle_status)} word tone={data.bundle_status === 'VALID' ? 'success' : 'warning'} note={data.bundle_status === 'VALID' ? '해시 체인 검증' : '검증 상태 확인 필요'} />
      </section>

      <div className="result-lower">
        <section className="glass-card result-files" aria-label="바뀐 파일">
          <h2>바뀐 파일</h2>
          {changedFiles === null ? <p className="faint-note">관찰 기록을 불러오는 중이에요.</p> : (
            <BarList rows={[
              { key: 'created', label: '생성', value: breakdown.created, tone: 'success' },
              { key: 'modified', label: '수정', value: breakdown.modified, tone: 'accent' },
              { key: 'deleted', label: '삭제', value: breakdown.deleted, tone: 'danger' },
              { key: 'moved', label: '이동', value: breakdown.moved, tone: 'warning' },
            ]} />
          )}
          <p className="faint-note">{activity?.truncated ? '관찰 목록은 200개까지라 일부만 셌어요.' : '관찰된 변경 기준이에요. 누가 바꿨는지 확정하지 않아요.'}</p>
        </section>

        <div ref={detailsRef} className="glass-card result-details" aria-label="자세한 결과">
          <details open={evidenceOpen || undefined} onToggle={event => setEvidenceOpen(event.currentTarget.open)}>
            <summary>정책 사건 {incidents.length}건</summary>
            {incidents.length === 0 ? <p className="faint-note">기록된 정책 사건이 없어요.</p> : (
              <div className="result-incidents">{incidents.map((incident, index) => <IncidentRow key={incident.action_id ?? index} incident={incident} />)}</div>
            )}
            {(showEvidenceLog || evidenceOpen) && incidents.length > 0 && (
              <details className="result-sub"><summary>원시 증거 메타데이터</summary><EvidenceLogView incidents={incidents} /></details>
            )}
          </details>

          <details>
            <summary>행위 귀속 · 자동 통제</summary>
            <div className="badge-wrap">
              {(['EXACT', 'PROCESS', 'TEMPORAL', 'UNKNOWN'] as const).map(grade => (
                <Badge tone="neutral" key={grade}>{displayStatus(grade)} {data.attribution_summary?.counts?.[grade] ?? 0}건</Badge>
              ))}
            </div>
            <p className="faint-note">자동 통제: {data.attribution_summary?.automatic_control_happened ? `발생 (${data.attribution_summary.automatic_control_grades?.join(', ') || '귀속 등급 미확인'})` : '기록되지 않음'} · 정책 위반만으로는 에이전트를 중지하지 않아요.</p>
          </details>

          <details>
            <summary>센서 {data.sensor_summary?.length ?? 0}개 · 이상 {sensorIssues}개</summary>
            <ul className="result-list">
              {(data.sensor_summary ?? []).map((sensor, index) => (
                <li key={index}><span>{sensor.sensor}</span><Badge tone={statusTone(sensor.final_sensor_state)}>{displayStatus(sensor.final_sensor_state)}</Badge><small>관찰 중 상태 {displayStatus(sensor.runtime_health_before_stop)}</small></li>
              ))}
            </ul>
          </details>

          <details>
            <summary>복구 · 무결성</summary>
            <div className="badge-wrap">
              <Badge tone={toneFor(recovery?.recovery_status ?? data.recovery_status)}>복구 {displayStatus(recovery?.recovery_status ?? data.recovery_status ?? 'NOT_ATTEMPTED')}</Badge>
              <Badge tone={toneFor(recovery?.integrity_status ?? data.integrity_status)}>무결성 {displayStatus(recovery?.integrity_status ?? data.integrity_status ?? 'NOT_CHECKED')}</Badge>
              <Badge tone="neutral">불일치 파일 {recovery?.mismatched_file_count ?? '확인 불가'}</Badge>
            </div>
            {recovery?.record_verification && recovery.record_verification !== 'VALID' && <p className="warning-text">이전 수동 복구 기록이 미검증 또는 손상 상태예요. 원래 실행의 감사 검증과 따로 확인해야 해요.</p>}
            {recoveryError && <p className="warning-text">복구 상태를 확인하지 못했어요: {recoveryError} <Button variant="text" onClick={reloadRecovery}>다시 확인</Button></p>}
          </details>

          {(data.result_action_chains?.length ?? 0) > 0 && (
            <details>
              <summary>증거 연결 흐름 {data.result_action_chains?.length}건</summary>
              {data.result_action_chains?.map((chain, index) => (
                <div className="result-chain" key={chain.action_id ?? index}>
                  <span className="muted">행위 {chain.action_id ?? index + 1}</span>
                  <div className="badge-wrap">{(chain.stages ?? []).map((stage, stageIndex) => <Badge key={stage.stage ?? stageIndex} tone={stage.status === 'NOT_OBSERVED' ? 'warn' : toneFor(stage.status)}>{stage.label} · {displayStatus(stage.value)}</Badge>)}</div>
                </div>
              ))}
            </details>
          )}

          {(data.unsupported_tool_review_decisions?.length ?? 0) > 0 && (
            <details>
              <summary>지원 범위 밖 도구 검토 {data.unsupported_tool_review_decisions?.length}건</summary>
              <ul className="result-list">{data.unsupported_tool_review_decisions?.map(decision => <li key={decision}>{unsupportedToolReviewDecisionLabel(decision)}</li>)}</ul>
              {data.limitations?.includes('UNSUPPORTED_TOOL_USER_APPROVED') && <p className="faint-note">승인된 도구는 AIA가 의미를 해석하지 못해 정책 판정과 보호 대상에서 빠져요.</p>}
            </details>
          )}

          {data.limitations?.includes('CODEX_FULL_ACCESS_USER_SELECTED') && (
            <p className="faint-note">
              전체 권한으로 실행했어요. 모든 명령은 AIA가 실행 전에 검사했고 작업 폴더는 되돌릴 수 있어요. 작업 폴더 밖 변경과 인터넷 사용은 Codex 샌드박스가 막지 않았고 되돌리기 범위 밖이에요.
            </p>
          )}
          {data.limitations?.includes('CODEX_AUTO_REVIEW_USER_SELECTED') && (
            <p className="faint-note">
              "나 대신 승인"으로 실행해 Codex가 승인 요청을 대신 검토했어요. 그렇게 승인된 권한 확대는 AIA 기록에 따로 남지 않을 수 있어요.
            </p>
          )}

          <details>
            <summary>이 결과를 읽는 법 · 제한 사항</summary>
            <ol className="result-guide">
              <li>정책 판정 — 정책 사건에서 각 행위가 위반인지 확인해요.</li>
              <li>실행 증거 — AIA의 조치와 실제 도구 실행 결과는 따로예요. 실행 결과를 따로 확인하세요.</li>
              <li>보호 검증 — 감사 기록과 보호 상태가 함께 검증돼야 믿을 수 있어요.</li>
            </ol>
            <div className="badge-wrap">
              <Badge tone={toneFor(data.bundle_status)}>감사 기록 {displayStatus(data.bundle_status)}</Badge>
              <Badge tone={toneFor(data.session_status)}>{displayStatus(data.session_status)}</Badge>
              <Badge tone="neutral">{displayStatus(data.protection_state)}</Badge>
            </div>
            <ul className="result-limitations">{(data.limitations ?? []).map(item => <li key={item}>{item}</li>)}</ul>
            <p className="faint-note mono">{data.workspace}{data.policy_id ? ` · 정책 ${data.policy_id}${data.policy_version ? ` ${data.policy_version}` : ''}` : ''}</p>
          </details>
        </div>
      </div>

      <p className="faint-note"><Icon name="info" size={15} />판정은 AIA가 관찰한 범위 안의 결과예요.</p>

      {restoreOpen && recovery && (
        <RestoreDialog runId={runId} recovery={recovery} onClose={() => setRestoreOpen(false)} onDone={(result) => { setRestoreOpen(false); setOutcome(result); reloadRecovery() }} />
      )}
    </div>
  )
}

function unsupportedToolReviewDecisionLabel(decision: string): string {
  switch (decision) {
    case 'UNSUPPORTED_TOOL_REVIEW_APPROVED':
      return '사용자가 검토 후 승인함'
    case 'UNSUPPORTED_TOOL_REVIEW_DECLINED':
      return '사용자가 검토 후 거절함'
    case 'UNSUPPORTED_TOOL_REVIEW_TIMED_OUT':
      return '검토 시간 초과로 거절됨'
    default:
      return '검토 결정 기록'
  }
}

function IncidentRow({ incident }: { incident: IncidentView }) {
  return (
    <details className="incident-row">
      <summary>
        <span className="incident-op">{displayStatus(incident.operation)}</span>
        <span className="incident-summary">{incident.summary}</span>
        <Badge tone={toneFor(incident.policy_effect)}>{displayStatus(incident.policy_effect)}</Badge>
      </summary>
      <dl className="incident-facts">
        <dt>대상</dt><dd>{incident.target?.display ?? '—'}</dd>
        <dt>귀속</dt><dd>{displayStatus(incident.attribution_class)}</dd>
        <dt>AIA 조치</dt><dd>{displayStatus(incident.enforcement_action)}</dd>
        <dt>실행 결과</dt><dd>{displayStatus(incident.execution_result)}</dd>
        {incident.reason && <><dt>사유</dt><dd>{incident.reason}</dd></>}
      </dl>
    </details>
  )
}
