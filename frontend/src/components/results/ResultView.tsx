import { useState } from 'react'
import { useResult } from '../../hooks/useResult'
import type { IncidentView } from '../../api/resultTypes'
import { deriveVerdict } from '../../api/resultVerdict'
import { EvidenceLogView } from './EvidenceLogView'

function toneFor(value: string | undefined): 'ok' | 'warn' | 'bad' {
  const upper = String(value || '').toUpperCase()
  if (['VALID', 'VERIFIED', 'RESTORED', 'COMPLETED', 'TRUSTED'].includes(upper)) return 'ok'
  if (['INVALID', 'FAILED', 'VIOLATION', 'MISSING'].includes(upper)) return 'bad'
  return 'warn'
}

export function ResultView({ runId, showEvidenceLog = false }: { runId: string; showEvidenceLog?: boolean }) {
  const { data, error, isLoading } = useResult(runId)

  if (isLoading) {
    return (
      <div className="center-empty-state">
        <strong>결과를 불러오는 중입니다…</strong>
      </div>
    )
  }
  if (error || !data) {
    return (
      <div className="center-empty-state">
        <strong>결과를 표시할 수 없습니다</strong>
        <p>{error || '실행 기록을 확인할 수 없습니다.'}</p>
      </div>
    )
  }

  const incidents = data.incidents ?? []
  const verdict = deriveVerdict(data)

  return (
    <div style={{ padding: 16, overflowY: 'auto', height: '100%' }}>
      <div className={`result-verdict is-${verdict.tone}`}>
        <span className="result-verdict-mark" aria-hidden="true">
          {verdict.tone === 'ok' ? '✓' : verdict.tone === 'bad' ? '!' : '·'}
        </span>
        <div className="result-verdict-copy">
          <strong>{verdict.headline}</strong>
          <span>{verdict.detail}</span>
        </div>
      </div>

      {verdict.executionPolicyAttention && (
        <div className="result-alert-banner">
          <span>
            {verdict.executionPolicyStatus === 'NOT_OBSERVED'
              ? 'Codex 실행 정책이 관찰되지 않았습니다. 실제 적용 정책을 확인하기 전에는 완전한 보호 성공으로 해석하지 마세요.'
              : 'Codex 실행 정책이 저하된 상태로 관찰됐습니다. 실제 적용 정책을 확인하세요.'}
          </span>
        </div>
      )}

      <details className="result-reading-guide">
        <summary>이 결과를 어떻게 읽나요?</summary>
        <div className="result-reading-guide-body">
          <span>① 정책 판정 — 아래 정책 사건 상세에서 각 행위가 위반인지 확인</span>
          <span>② 실행 Evidence — AIA의 조치와 실제 도구 실행 결과는 별개입니다. 실행 결과 배지를 따로 확인하세요</span>
          <span>③ 보호 검증 — Bundle 유효성과 보호 상태가 함께 검증돼야 신뢰할 수 있습니다</span>
        </div>
      </details>

      <div className="panel-section">
        <p className="panel-section-title">보호 실행 결과</p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
          <span className={`badge is-${toneFor(data.bundle_status)}`}>Bundle {data.bundle_status ?? '확인 전'}</span>
          <span className={`badge is-${toneFor(data.session_status)}`}>{data.session_status ?? '상태 미확인'}</span>
          {incidents.length > 0 && <span className="badge is-warn">정책 사건 {incidents.length}건</span>}
        </div>
        <div className="run-row-path" style={{ whiteSpace: 'normal' }}>
          {data.workspace} {data.policy_id ? `· 정책 ${data.policy_id}${data.policy_version ? ` · ${data.policy_version}` : ''}` : ''}
        </div>
      </div>

      <div className="panel-section">
        <p className="panel-section-title">복구 · 무결성</p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <span className={`badge is-${toneFor(data.recovery_status)}`}>Recovery: {data.recovery_status ?? 'NOT_ATTEMPTED'}</span>
          <span className={`badge is-${toneFor(data.integrity_status)}`}>Integrity: {data.integrity_status ?? 'NOT_CHECKED'}</span>
        </div>
      </div>

      {data.result_action_chains && data.result_action_chains.length > 0 && (
        <div className="panel-section">
          <p className="panel-section-title">Evidence Chain</p>
          <div className="run-list">
            {data.result_action_chains.map((chain, index) => (
              <div className="event-row" key={chain.action_id ?? index}>
                <div className="event-row-top">
                  <span className="event-row-sensor">행위 {chain.action_id ?? index + 1}</span>
                </div>
                <div style={{ display: 'grid', gap: 5, marginTop: 6 }}>
                  {(chain.stages ?? []).map((stage, stageIndex) => (
                    <div key={stage.stage ?? stageIndex} style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                      <span>{stage.label}</span>
                      <span className={`badge is-${stage.status === 'NOT_OBSERVED' ? 'warn' : toneFor(stage.status)}`}>
                        {stage.value ?? 'not observed'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {data.sensor_summary && data.sensor_summary.length > 0 && (
        <div className="panel-section">
          <p className="panel-section-title">센서 결과</p>
          <div className="run-list">
            {data.sensor_summary.map((sensor, index) => (
              <div key={index} className="event-row">
                <div className="event-row-top">
                  <span className="event-row-sensor">{sensor.sensor}</span>
                  <span className="badge is-ok">{sensor.final_sensor_state}</span>
                </div>
                <span>관찰 전 상태: {sensor.runtime_health_before_stop}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {incidents.length > 0 && (
        <div className="panel-section">
          <p className="panel-section-title">정책 사건 상세</p>
          <div className="run-list">
            {incidents.map((incident, index) => (
              <IncidentRow key={incident.action_id ?? index} incident={incident} />
            ))}
          </div>
        </div>
      )}

      {showEvidenceLog && (
        <div className="panel-section">
          <details className="result-reading-guide">
            <summary>Raw Evidence (원시 기록 보기)</summary>
            <div style={{ marginTop: 8 }}>
              <EvidenceLogView incidents={incidents} />
            </div>
          </details>
        </div>
      )}
    </div>
  )
}

function IncidentRow({ incident }: { incident: IncidentView }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="event-row">
      <button
        type="button"
        style={{ all: 'unset', cursor: 'pointer', display: 'block', width: '100%' }}
        onClick={() => setExpanded((value) => !value)}
      >
        <div className="event-row-top">
          <span className="event-row-sensor">{incident.operation ?? '행위'}</span>
          <span className={`badge is-${toneFor(incident.policy_effect)}`}>{incident.policy_effect ?? '판정 불가'}</span>
        </div>
        <span>{incident.summary}</span>
      </button>
      {expanded && (
        <div style={{ marginTop: 8, display: 'grid', gap: 4, fontSize: 11, color: 'var(--text-muted)' }}>
          <span>대상: {incident.target?.display ?? '—'}</span>
          <span>귀속: {incident.attribution_class ?? '—'}</span>
          <span>AIA 조치: {incident.enforcement_action ?? '조치 없음'}</span>
          <span>실행 결과: {incident.execution_result ?? '실행 결과 증거 없음'}</span>
          {incident.reason && <span>사유: {incident.reason}</span>}
        </div>
      )}
    </div>
  )
}
