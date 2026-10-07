import { useMemo } from 'react'
import { GlossyIcon, StatusDot } from '../common/Glass'
import { MiniBars } from '../common/Charts'
import { TIMELINE_LIMIT, activityBuckets } from '../../api/chartMath'
import { displayStatus, statusTone } from '../../api/display'
import type { RunStatus } from '../../api/types'
import { blockDecisionCount, useRunActions } from '../../hooks/useRunActions'
import { useNow } from '../../hooks/useElapsed'

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
  const recent = useMemo(() => activityBuckets(status?.evidence_timeline, now), [status?.evidence_timeline, now])
  const processes = processDepths(activity?.processes ?? []).slice(0, 8)
  const files = (activity?.files ?? []).slice(-6).reverse()
  const checkpoint = typeof status?.checkpoint === 'string' ? status.checkpoint : null

  const rows: Array<{ key: string; tone: Parameters<typeof GlossyIcon>[0]['tone']; icon: Parameters<typeof GlossyIcon>[0]['icon']; label: string; value: string; alert?: boolean }> = [
    { key: 'pretool', tone: 'hook', icon: 'shieldPlain', label: '실행 전 검사', value: `${summary?.pretool_events ?? 0}건` },
    { key: 'block', tone: 'danger', icon: 'block', label: '차단 판정', value: `${blocks}건`, alert: blocks > 0 },
    { key: 'process', tone: 'process', icon: 'pulse', label: '감시 중 프로세스', value: `${activity?.current_alive_count ?? activity?.process_identity_count ?? 0}개` },
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

      <section className="work-panel-section">
        <h3 className="work-panel-head">최근 5분 활동<span>이번 1분 {recent.current}건</span></h3>
        <MiniBars values={recent.counts} showValues label={`1분 단위 실행 요청·프로세스·파일 변화 ${recent.counts.join(', ')}건`} />
        <p className="faint-note">실행 요청·프로세스·파일 변화만 세요.{recent.partial && ` 최근 기록 ${TIMELINE_LIMIT}건까지만 반영돼요.`}</p>
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
