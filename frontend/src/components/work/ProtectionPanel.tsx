import { grantSummary, widensBeyondProtection } from '../../api/permissionGrants'
import { useMemo } from 'react'
import { GlossyIcon, StatusDot } from '../common/Glass'
import { ActivityStrip } from './ActivityStrip'
import { TIMELINE_LIMIT, activityStrip } from '../../api/chartMath'
import { displayStatus, statusTone } from '../../api/display'
import type { RunStatus } from '../../api/types'
import { blockDecisionCount, useRunActions } from '../../hooks/useRunActions'
import { useNow } from '../../hooks/useElapsed'
import { useCodexConnectors } from '../../hooks/useCodexConnectors'
import { connectorsOnFirst, connectorSummary } from '../../api/connectorView'

const FILE_LABELS: Record<string, string> = { created: '생성', modified: '수정', deleted: '삭제', moved: '이동' }
const SENSORS: Array<[string, string]> = [['AGENT_HOOK', '실행 요청'], ['FILESYSTEM_WATCHER', '파일 변화'], ['PROCESS_RUNTIME', '프로세스']]

type Process = NonNullable<NonNullable<RunStatus['activity']>['processes']>[number]

/** Parent links only when PID and creation time both match (same rule as before). */
function processDepths(processes: Process[]): Array<{ process: Process; depth: number }> {
  const key = (pid?: number, created?: number) => `${pid}:${created}`
  const byKey = new Map(processes.map(process => [key(process.pid, process.create_time), process]))
  const depthOf = (process: Process, guard = 0): number => {
    const parent = byKey.get(key(process.parent_pid, process.parent_create_time))
    return parent && guard < 8 ? depthOf(parent, guard + 1) + 1 : 0
  }
  return processes.map(process => ({ process, depth: Math.min(3, depthOf(process)) }))
}

/** ⑤ Right-hand protection panel of the work view. Observation only; never an authority. */
export function ProtectionPanel({ runId, status, live }: { runId: string; status: RunStatus | null; live: boolean }) {
  const { data: actions } = useRunActions(runId, live)
  const blocks = blockDecisionCount(actions)
  const summary = status?.evidence_summary
  const activity = status?.activity
  const now = useNow(live)
  const recent = useMemo(() => activityStrip(status?.evidence_timeline, actions, now), [status?.evidence_timeline, actions, now])
  const processes = processDepths(activity?.processes ?? []).slice(0, 8)
  const files = (activity?.files ?? []).slice(-6).reverse()
  const checkpoint = typeof status?.checkpoint === 'string' ? status.checkpoint : null
  // The conversation id appears once Codex's conversation is open; connectors exist from then on.
  const { connectors } = useCodexConnectors(runId, live && Boolean(status?.codex_thread_id))
  const connectorsOff = connectors?.filter(connector => connector.turned_off_by_aia).length ?? 0
  const connectorsUsable = connectors?.filter(connector => !connector.turned_off_by_aia && connector.tool_count > 0).length ?? 0

  const rows: Array<{ key: string; tone: Parameters<typeof GlossyIcon>[0]['tone']; icon: Parameters<typeof GlossyIcon>[0]['icon']; label: string; value: string; alert?: boolean }> = [
    { key: 'pretool', tone: 'hook', icon: 'shieldPlain', label: '실행 전 검사', value: `${summary?.pretool_events ?? 0}건` },
    { key: 'block', tone: 'danger', icon: 'block', label: '차단 판정', value: `${blocks}건`, alert: blocks > 0 },
    { key: 'process', tone: 'process', icon: 'pulse', label: activity?.current_alive_count == null ? '누적 관찰 프로세스' : '현재 실행 프로세스', value: activity?.current_alive_count != null || activity?.process_identity_count != null ? `${activity.current_alive_count ?? activity.process_identity_count}개` : '—' },
    { key: 'file', tone: 'file', icon: 'file', label: '파일 변경', value: `${activity?.unique_file_count ?? 0}개` },
  ]

  return (
    <aside className="glass is-soft work-panel" aria-label="보호 패널">
      <h2 className="work-panel-title">보호 패널</h2>
      <ul className="work-panel-rows">
        {rows.map(row => (
          <li key={row.key} className={row.alert ? 'is-alert' : undefined}>
            <GlossyIcon tone={row.tone} icon={row.icon} size="sm" />
            <span>{row.label}</span>
            <strong>{row.value}</strong>
          </li>
        ))}
      </ul>

      {(status?.permission_grants ?? []).length > 0 && (
        <section className="work-panel-section">
          <h3>이번 실행에서 넓힌 권한</h3>
          <ul className="work-grants">
            {(status?.permission_grants ?? []).map((grant) => <li key={grant.granted_at}>{grantSummary(grant)}</li>)}
          </ul>
          {widensBeyondProtection(status?.permission_grants) && <p className="faint-note">작업 폴더 밖 쓰기와 인터넷은 AIA 기준점·복구와 감시 범위 밖이에요.</p>}
        </section>
      )}

      {connectors && connectors.length > 0 && (
        <section className="work-panel-section">
          <h3>외부 도구 {connectors.length}개{connectorsOff > 0 && ` · ${connectorsOff}개 꺼 둠`}</h3>
          <ul className="work-connectors">
            {connectorsOnFirst(connectors).map(connector => <li key={connector.name}><span className="mono">{connector.name}</span><small className="muted">{connectorSummary(connector)}</small></li>)}
          </ul>
          <p className="faint-note">{connectorsUsable === 0 ? 'Hook 밖에서 움직일 수 있는 도구를 이번 실행에서 껐어요.' : '켜진 도구는 AIA 보호 범위 밖이에요.'} 설정 › 외부 도구에서 바꿀 수 있어요.</p>
        </section>
      )}

      <section className="work-panel-section">
        <h3 className="work-panel-head">최근 5분 활동<span>이번 1분 {recent.current}건</span></h3>
        <ActivityStrip data={recent} live={live} />
        <p className="faint-note">점 하나가 기록 하나예요. 빨간 마름모는 차단 판정, 아래 선은 AIA가 지켜보는 심박이에요.{recent.partial && ` 최근 기록 ${TIMELINE_LIMIT}건까지만 반영돼요.`}</p>
      </section>

      <section className="work-panel-section">
        <h3>프로세스 트리</h3>
        {processes.length === 0 ? <p className="faint-note">관찰된 프로세스가 아직 없어요.</p> : (
          <ul className="process-tree">
            {processes.map(({ process, depth }) => (
              <li key={`${process.pid}:${process.create_time}`} className={`depth-${depth}`}>
                <span className="mono">{depth > 0 ? '└ ' : ''}{process.name}</span>
                <small>PID {process.pid}</small>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="work-panel-section">
        <h3>바뀐 파일</h3>
        {files.length === 0 ? <p className="faint-note">관찰된 파일 변경이 아직 없어요.</p> : (
          <ul className="work-files">
            {files.map(file => (
              <li key={`${file.path}:${file.evidence_id}`}>
                <span className="mono">{file.path}</span>
                <span className={`badge is-${file.event_type === 'deleted' ? 'bad' : file.event_type === 'created' ? 'ok' : 'neutral'}`}>{FILE_LABELS[file.event_type] ?? '변경'}</span>
              </li>
            ))}
          </ul>
        )}
        <p className="faint-note">관찰된 변경이에요. 누가 바꿨는지 확정하지 않아요.</p>
      </section>

      <section className="work-panel-section">
        <h3>센서</h3>
        <ul className="work-sensors">
          {SENSORS.map(([key, label]) => {
            const health = status?.sensor_health?.[key]
            const tone = statusTone(health)
            return <li key={key}><StatusDot tone={tone === 'neutral' ? 'neutral' : tone} />{label}<span>{displayStatus(health)}</span></li>
          })}
        </ul>
      </section>

      <p className="work-checkpoint">
        <StatusDot tone={checkpoint === 'READY' ? 'ok' : 'neutral'} />
        {checkpoint === 'READY' ? '기준점 준비됨 · 끝난 뒤 되돌릴 수 있어요' : '기준점 확인 중'}
      </p>
    </aside>
  )
}
