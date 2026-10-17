import { useEffect, useRef, useState } from 'react'
import { Icon } from '../common/Icon'
import { changeLabel, massChange, newProtectedChange, type MissedViolation, type ProtectedChange, type Threat } from '../../api/threats'

const SHOW_MS = 12_000

/** Top-of-screen alert when AIA blocks a threat, the file sensor sees a burst of changes, or a protected file changes without passing the Hook. */
export function ThreatAlert({ threats, fileCount, protectedChanges, protectedCount, missedViolations }: {
  threats: Threat[]
  fileCount: number | null
  protectedChanges?: ProtectedChange[]
  protectedCount: number | null
  missedViolations: MissedViolation[] | null
}) {
  const [threat, setThreat] = useState<Threat | null>(null)
  const [burst, setBurst] = useState(0)
  const [detected, setDetected] = useState<ProtectedChange | null>(null)
  const [missed, setMissed] = useState<MissedViolation | null>(null)
  const seenThreats = useRef<number | null>(null)
  const lastFiles = useRef<number | null>(null)
  const seenProtected = useRef<number | null>(null)
  const seenMissed = useRef<number | null>(null)

  useEffect(() => {
    const change = newProtectedChange(seenProtected.current, protectedCount, protectedChanges)
    if (change) setDetected(change)
    if (protectedCount !== null) seenProtected.current = protectedCount
  }, [protectedCount, protectedChanges])

  // The first available action list is the baseline, so reopening a run does not replay old warnings.
  useEffect(() => {
    if (missedViolations === null) return
    if (seenMissed.current !== null && missedViolations.length > seenMissed.current && missedViolations.length > 0) {
      setMissed(missedViolations[missedViolations.length - 1])
    }
    seenMissed.current = missedViolations.length
  }, [missedViolations])

  useEffect(() => {
    if (!detected) return
    const timer = setTimeout(() => setDetected(null), SHOW_MS)
    return () => clearTimeout(timer)
  }, [detected])

  useEffect(() => {
    if (!missed) return
    const timer = setTimeout(() => setMissed(null), SHOW_MS)
    return () => clearTimeout(timer)
  }, [missed])

  // The first poll only sets the baseline, so reopening a run does not replay old alerts.
  useEffect(() => {
    if (seenThreats.current !== null && threats.length > seenThreats.current) setThreat(threats[threats.length - 1])
    seenThreats.current = threats.length
  }, [threats])

  useEffect(() => {
    const delta = massChange(lastFiles.current, fileCount)
    if (delta > 0) setBurst(delta)
    if (fileCount !== null) lastFiles.current = fileCount
  }, [fileCount])

  useEffect(() => {
    if (!threat) return
    const timer = setTimeout(() => setThreat(null), SHOW_MS)
    return () => clearTimeout(timer)
  }, [threat])

  useEffect(() => {
    if (!burst) return
    const timer = setTimeout(() => setBurst(0), SHOW_MS)
    return () => clearTimeout(timer)
  }, [burst])

  if (!threat && !burst && !detected && !missed) return null
  return (
    <div className="threat-alerts" role="alert" aria-live="assertive">
      {missed && (
        <div className="threat-alert is-detected">
          <span className="threat-alert-icon"><Icon name="alert" size={22} /></span>
          <div className="threat-alert-copy">
            <small>정책 위반 감지</small>
            <strong>{missed.title}</strong>
            <span>{missed.reason}</span>
            {missed.target && <span className="mono">{missed.target}</span>}
          </div>
          <span className="threat-alert-count">이번 실행 {missedViolations?.length ?? 0}건 확인</span>
          <button type="button" className="icon-button" aria-label="알림 닫기" onClick={() => setMissed(null)}><Icon name="close" size={16} /></button>
        </div>
      )}
      {detected && (
        <div className="threat-alert is-detected">
          <span className="threat-alert-icon"><Icon name="alert" size={22} /></span>
          <div className="threat-alert-copy">
            <small>보호 파일 변경 감지 · 파일 센서</small>
            <strong>보호 파일이 {changeLabel(detected.event_type)}됐어요</strong>
            <span className="mono">{detected.path}</span>
            <span>실행 전 검사를 거치지 않은 변경이에요 · 끝난 뒤 되돌릴 수 있어요</span>
          </div>
          <span className="threat-alert-count">이번 실행 {protectedCount}건 감지</span>
          <button type="button" className="icon-button" aria-label="알림 닫기" onClick={() => setDetected(null)}><Icon name="close" size={16} /></button>
        </div>
      )}
      {threat && (
        <div className="threat-alert is-blocked">
          <span className="threat-alert-icon"><Icon name="block" size={22} /></span>
          <div className="threat-alert-copy">
            <small>위협 차단 · {threat.tactic}</small>
            <strong>{threat.title}</strong>
            {threat.target && <span className="mono">{threat.target}</span>}
          </div>
          <span className="threat-alert-count">이번 실행 {threats.length}건 차단</span>
          <button type="button" className="icon-button" aria-label="알림 닫기" onClick={() => setThreat(null)}><Icon name="close" size={16} /></button>
        </div>
      )}
      {burst > 0 && (
        <div className="threat-alert is-burst">
          <span className="threat-alert-icon"><Icon name="alert" size={22} /></span>
          <div className="threat-alert-copy">
            <small>대량 변경 감지 · 파일 센서</small>
            <strong>파일 {burst}개가 한꺼번에 바뀌었어요</strong>
            <span>프로세스 트리에서 숨은 실행을 확인하세요 · 끝난 뒤 되돌릴 수 있어요</span>
          </div>
          <button type="button" className="icon-button" aria-label="알림 닫기" onClick={() => setBurst(0)}><Icon name="close" size={16} /></button>
        </div>
      )}
    </div>
  )
}
