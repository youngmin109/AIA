import { Button } from '../common/Button'
import { useState } from 'react'
import type { RunStatus } from '../../api/types'
import { useShellStore } from '../../state/shellStore'
import { Icon } from '../common/Icon'

const FILE_LABELS: Record<string, string> = { created: '생성', modified: '수정', deleted: '삭제', moved: '이동' }
const PROCESS_LABELS: Record<string, string> = { LIVE_MATCH: '현재 생존 확인', EXIT_OBSERVED: '종료 관찰', GONE_AT_REFRESH: '현재 없음', LAST_OBSERVED: '당시 관찰', UNVERIFIABLE: '확인 어려움' }
export function WorkspaceActivity({ status }: { status: RunStatus | null }) {
  const [expert, setExpert] = useState(false)
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const { setView } = useShellStore()
  const activity = status?.activity
  const files = activity?.files ?? []
  const selected = files.find(file => file.path === selectedPath)
  const processes = activity?.processes ?? []
  return <section className="soft-card data-section workspace-activity">
    <div className="section-title-row"><div><h3>작업공간 관찰</h3><p>실제 파일 변화와 등록된 프로세스의 관찰 기록입니다.</p></div><Button variant="secondary" aria-pressed={expert} onClick={() => setExpert(value => !value)}>{expert ? '사용자 보기' : '전문가 보기'}</Button></div>
    {!activity?.available ? <p className="empty-copy">실행을 시작하면 관찰 기록이 연결됩니다. 검증할 수 없는 기록은 표시하지 않습니다.</p> : <>
      <div className="workspace-file-list" aria-label="관찰된 파일 변화">
        {files.length === 0 && <p className="empty-copy">아직 관찰된 파일 변경이 없습니다.</p>}
        {files.map(file => <button type="button" className={`activity-file-row${selectedPath === file.path ? ' is-selected' : ''}`} key={`${file.path}:${file.evidence_id}`} onClick={() => setSelectedPath(file.path)}><Icon name="report" size={16} /><span>{file.path}</span><b className={`file-event-${file.event_type}`}>{FILE_LABELS[file.event_type] ?? '변경'}</b></button>)}
      </div>
      {selected && <div className="activity-file-detail" aria-live="polite"><b>{selected.path}</b><span>{new Date(selected.observed_at).toLocaleString('ko-KR')} · {selected.event_count}건 관찰</span><p>세션 중 관찰된 변경입니다. 파일을 바꾼 프로세스를 확정하지 않습니다. 파일 내용은 읽거나 표시하지 않습니다.</p><Button variant="text" onClick={() => { setView('history') }}>이 세션의 증거 확인</Button></div>}
      {expert && <div className="process-tree"><h4>관리 프로세스 트리 · 누적 {activity.process_identity_count ?? 0}개</h4><p>부모 연결은 PID와 생성 시각이 일치하는 경우에만 표시합니다.</p>{processes.length === 0 && <p>프로세스 관찰 기록이 없습니다.</p>}{processes.map(process => {
        const parent = processes.find(item => item.pid === process.parent_pid && item.create_time === process.parent_create_time)
        return <div className={`process-tree-row${parent ? ' is-child' : ''}`} key={`${process.pid}:${process.create_time}`}><span>{parent ? '└' : '●'} {process.name}</span><small>PID {process.pid}{parent ? ` · 부모 ${parent.pid}` : process.role === 'ROOT' ? ' · 시작 프로세스' : ' · 부모 연결 미확인'}</small><b>{PROCESS_LABELS[process.state] ?? '확인 어려움'}</b></div>
      })}</div>}
      {activity.truncated && <p className="validation-note">목록은 최대 200개로 제한됩니다. 표시 일부가 생략되었으며 감사 원본은 유지됩니다.</p>}
    </>}
  </section>
}
