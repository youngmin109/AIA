import { useState } from 'react'
import type { EvidenceChain, SecurityEvent } from '../../api/types'

function toneFor(decision: string | undefined): 'ok' | 'warn' | 'bad' {
  const upper = String(decision || '').toUpperCase()
  if (['VIOLATION', 'DENY', 'REFUSE'].includes(upper)) return 'bad'
  if (['VALID', 'ALLOW', 'NONE', ''].includes(upper)) return 'ok'
  return 'warn'
}

function linkTone(status: string | undefined): 'ok' | 'warn' | 'bad' {
  const upper = String(status || '').toUpperCase()
  if (upper === 'LINKED') return 'ok'
  if (upper === 'RUN_OBSERVED') return 'warn'
  return 'bad'
}

function formatTime(value: string | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function EventFeed({
  runId,
  events,
  evidenceChains,
}: {
  runId: string | null
  events?: SecurityEvent[]
  evidenceChains?: EvidenceChain[]
}) {
  if (!runId) {
    return <p className="empty-hint">열린 실행을 선택하면 Hook·File·Process 센서 기록이 여기에 표시됩니다.</p>
  }
  const list = events ?? []
  if (list.length === 0) {
    return <p className="empty-hint">아직 관찰된 센서 이벤트가 없습니다.</p>
  }

  return (
    <div className="event-list">
      {list
        .slice()
        .reverse()
        .map((event, index) => (
          <EventRow key={event.event_id ?? index} event={event} chain={findChain(evidenceChains, event.chain_action_id)} />
        ))}
    </div>
  )
}

function findChain(chains: EvidenceChain[] | undefined, actionId: string | undefined): EvidenceChain | undefined {
  if (!chains || !actionId) return undefined
  return chains.find((chain) => chain.action_id === actionId)
}

function EventRow({ event, chain }: { event: SecurityEvent; chain?: EvidenceChain }) {
  const [expanded, setExpanded] = useState(false)
  const expandable = Boolean(chain)
  const meta = [event.tool_name, event.target_label].filter(Boolean).join(' · ')
  const showExecutionResult = event.execution_result && event.execution_result !== 'NOT_REPORTED'

  return (
    <div className="event-row">
      <button
        type="button"
        style={{ all: 'unset', cursor: expandable ? 'pointer' : 'default', display: 'block', width: '100%' }}
        onClick={() => expandable && setExpanded((value) => !value)}
      >
        <div className="event-row-top">
          <span className="event-row-sensor">{event.sensor ?? event.origin_label ?? '센서'}</span>
          <span style={{ display: 'flex', gap: 4 }}>
            <span className={`badge is-${toneFor(event.display_decision ?? event.decision)}`}>
              {event.display_decision ?? event.decision ?? '확인 필요'}
            </span>
            {showExecutionResult && <span className="badge is-warn">{event.execution_result}</span>}
          </span>
        </div>
        <span>{event.display_summary ?? event.summary}</span>
        {(meta || event.observed_at) && (
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginTop: 3, fontSize: 10, color: 'var(--text-faint)' }}>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{meta}</span>
            <span style={{ flex: '0 0 auto' }}>{formatTime(event.observed_at)}</span>
          </div>
        )}
      </button>
      {expanded && chain && (
        <div style={{ marginTop: 8, display: 'grid', gap: 6, fontSize: 11 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {(chain.sensor_links ?? []).map((link, index) => (
              <span key={index} className={`badge is-${linkTone(link.status)}`}>
                {link.sensor}: {link.status}
                {typeof link.evidence_count === 'number' ? ` (${link.evidence_count})` : ''}
              </span>
            ))}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, color: 'var(--text-muted)' }}>
            {(chain.stages ?? []).map((stage, index) => (
              <span key={index} className={`badge is-${toneFor(stage.status)}`} title={stage.label}>
                {stage.label ?? stage.stage}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
