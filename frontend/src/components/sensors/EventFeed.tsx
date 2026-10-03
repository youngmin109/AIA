import { Badge } from '../common/Badge'
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
  limit,
}: {
  runId: string | null
  events?: SecurityEvent[]
  evidenceChains?: EvidenceChain[]
  /** Caps how many of the most-recent events render -- used by the
   * dashboard's condensed "최근 활동" card; the right panel's full feed
   * leaves this unset. */
  limit?: number
}) {
  if (!runId) {
    return <p className="empty-hint">실행을 선택하면 요청·파일·프로세스의 정규화된 활동을 확인할 수 있습니다.</p>
  }
  const list = events ?? []
  if (list.length === 0) {
    return <p className="empty-hint">표시할 정규화된 활동이 없습니다. 파일·프로세스 관찰은 보호 현황에서 확인하세요.</p>
  }
  const reversed = list.slice().reverse()
  const visible = limit ? reversed.slice(0, limit) : reversed

  return (
    <div className="event-list">
      {visible.map((event, index) => (
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
        className={`row-toggle${expandable ? '' : ' is-static'}`}
        onClick={() => expandable && setExpanded((value) => !value)}
      >
        <div className="event-row-top">
          <span className="event-row-sensor">{event.sensor ?? event.origin_label ?? '센서'}</span>
          <span className="event-row-badges">
            <Badge tone={toneFor(event.display_decision ?? event.decision)}>
              {event.display_decision ?? event.decision ?? '확인 필요'}
            </Badge>
            {showExecutionResult && <Badge tone="warn">{event.execution_result}</Badge>}
          </span>
        </div>
        <span>{event.display_summary ?? event.summary}</span>
        {(meta || event.observed_at) && (
          <div className="event-row-meta">
            <span className="event-row-meta-text">{meta}</span>
            <span className="event-row-meta-time">{formatTime(event.observed_at)}</span>
          </div>
        )}
      </button>
      {expanded && chain && (
        <div className="chain-details">
          <div className="chain-badges">
            {(chain.sensor_links ?? []).map((link, index) => (
              <Badge tone={linkTone(link.status)} key={index}>
                {link.sensor}: {link.status}
                {typeof link.evidence_count === 'number' ? ` (${link.evidence_count})` : ''}
              </Badge>
            ))}
          </div>
          <div className="chain-badges is-muted">
            {(chain.stages ?? []).map((stage, index) => (
              <Badge tone={toneFor(stage.status)} key={index} title={stage.label}>
                {stage.label ?? stage.stage}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
