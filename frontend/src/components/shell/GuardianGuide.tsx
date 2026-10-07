import { useState } from 'react'
import { createPortal } from 'react-dom'
import { Button } from '../common/Button'
import { Icon } from '../common/Icon'
import { GuardianAvatar } from '../common/GuardianAvatar'
import { useDialog } from '../common/useDialog'
import { errorReportTemplate } from '../../api/errorReport'
import type { GuardianStatus } from '../../api/guardianStatus'
import { useShellStore, type ShellView } from '../../state/shellStore'

export type GuideTopic = 'start' | 'hook' | 'safety' | 'recovery' | 'report'

const TOPICS: Array<[GuideTopic, string]> = [
  ['start', '시작하기'], ['hook', 'Hook 연결'], ['safety', '위험 알림'], ['recovery', '복구·감사'], ['report', '오류 신고'],
]

const CONTENT: Record<GuideTopic, { title: string; text: string; steps: string[] }> = {
  start: {
    title: '보호 실행을 시작할까요?',
    text: '작업 폴더와 정책을 고른 뒤 시작하면, 아이아가 Codex의 요청과 실제 파일·프로세스 변화를 함께 관찰해요.',
    steps: ['홈에서 보호 시작을 누릅니다.', '작업할 폴더와 보호 정책을 고릅니다.', '연결 상태를 확인하고 시작한 뒤 작업창에 요청을 입력해요.'],
  },
  hook: {
    title: 'Hook 연결은 왜 필요한가요?',
    text: 'Hook은 Codex가 도구를 실행하기 직전 AIA에 알려 주는 연결 지점이에요. 신뢰 여부는 Codex 안에서 사용자가 직접 결정합니다.',
    steps: ['AIA에서 Hook 설치를 누릅니다.', '새 터미널에서 codex를 실행한 뒤 /hooks를 엽니다.', 'AIA Hook을 검토하고 Trust한 다음, AIA에서 연결 검증을 누릅니다.'],
  },
  safety: {
    title: '위험 알림이 뜨면 이렇게 보세요',
    text: '명령, 대상 경로, 위험 이유를 먼저 확인하세요. AIA가 의미를 해석하지 못하는 지원 범위 밖 도구만 사용자 확인을 요청할 수 있고, 정책상 금지된 행위는 사용자가 허용할 수 없습니다.',
    steps: ['요청된 명령과 대상 파일 경로를 확인합니다.', '위험 이유와 적용된 정책을 읽습니다.', '지원 범위 밖 도구라면 이번만 허용하거나 거절한 뒤, 결과를 기록에서 확인합니다.'],
  },
  recovery: {
    title: '복구와 감사 기록은 어떻게 보나요?',
    text: '복구가 필요한 경우 AIA는 실행 전 기준점을 바탕으로 처리하고, 파일 경로와 SHA-256 무결성 검증 결과를 감사 기록에 남깁니다.',
    steps: ['기록에서 끝난 실행을 선택합니다.', '결과 요약과 증거, 정책 판단을 차례로 확인합니다.', '복구·무결성 검증 결과가 확정된 뒤 결과 번들을 확인합니다.'],
  },
  report: {
    title: '문제가 생겼나요?',
    text: '오류를 보내기 전에 실행 중인 작업이 있다면 먼저 중지 또는 결과 확정을 확인하세요. 아래 버튼은 내용을 자동 전송하지 않고, 신고 초안만 복사하거나 GitHub 이슈 작성 화면을 엽니다.',
    steps: ['무엇을 하려 했는지와 실제로 보인 현상을 적습니다.', '오류가 난 시각, 화면 캡처, 실행 상태를 함께 남깁니다.', '비밀값·API 키·개인 경로는 신고 내용에서 지웁니다.'],
  },
}

/** Help popover opened from the guardian pet or settings. It explains; it never approves, blocks, or restores. */
export function GuardianGuide({ guardian, initialTopic, side = 'left', onClose }: { guardian: GuardianStatus; initialTopic: GuideTopic; side?: 'left' | 'right'; onClose: () => void }) {
  const { activeRunId, setView, openNewRun } = useShellStore()
  const [topic, setTopic] = useState<GuideTopic>(initialTopic)
  const [reportCopied, setReportCopied] = useState(false)
  const ref = useDialog(true, onClose)
  const content = CONTENT[topic]
  const needsApproval = guardian.label === '사용자 확인'

  function go(view: ShellView) {
    onClose()
    setView(view)
  }

  function startRun() {
    onClose()
    openNewRun()
  }

  async function copyErrorReport() {
    try {
      if (!navigator.clipboard) throw new Error('클립보드를 사용할 수 없습니다.')
      await navigator.clipboard.writeText(errorReportTemplate())
      setReportCopied(true)
    } catch {
      setReportCopied(false)
    }
  }

  function openIssueDraft() {
    const params = new URLSearchParams({ title: '[오류 신고] ', body: errorReportTemplate() })
    window.open(`https://github.com/youngmin109/AIA/issues/new?${params.toString()}`, '_blank', 'noopener,noreferrer')
  }

  return createPortal(
    <>
      <div className="guide-scrim" aria-hidden="true" onClick={onClose} />
      <div ref={ref} tabIndex={-1} className={`guide-popover is-${side}`} role="dialog" aria-modal="true" aria-label="아이아 가디언 도움말">
        <Button variant="icon" className="guide-close" onClick={onClose} aria-label="도움말 닫기"><Icon name="close" size={14} /></Button>
        <div className="guide-hero">
          <GuardianAvatar state={guardian.state} alt={`아이아 가디언 · ${guardian.label}`} size="guide" />
          <div><strong>안녕하세요, 아이아 가디언이에요.</strong><p>궁금한 주제를 골라보세요. 저는 Codex의 실제 실행과 AIA의 보호 상태를 설명하는 안내자예요.</p></div>
        </div>
        <div className={`guide-state is-${guardian.state}`}><span>현재 상태 · {guardian.label}</span><strong>{guardian.headline}</strong><p>{guardian.detail}</p></div>
        <div className="segmented guide-topics" role="group" aria-label="도움 주제">
          {TOPICS.map(([value, label]) => (
            <button key={value} type="button" aria-pressed={topic === value} onClick={() => { setTopic(value); setReportCopied(false) }}>{label}</button>
          ))}
        </div>
        <section key={topic} className="guide-answer" aria-live="polite">
          <b>{content.title}</b>
          <p>{content.text}</p>
          <ol>{content.steps.map(step => <li key={step}>{step}</li>)}</ol>
          <div className="dialog-actions">
            {topic === 'report' && <>
              <Button variant="outline" onClick={copyErrorReport}>{reportCopied ? '신고 초안을 복사했어요' : '신고 초안 복사'}</Button>
              <Button variant="cta" onClick={openIssueDraft}>GitHub 이슈 작성</Button>
            </>}
            {topic === 'start' && <Button variant="cta" onClick={startRun}>새 보호 실행</Button>}
            {topic === 'hook' && <Button variant="cta" onClick={() => go('settings')}>연결 상태 확인</Button>}
            {topic === 'safety' && <Button variant="cta" onClick={() => go(needsApproval ? 'work' : 'history')}>{needsApproval ? '확인 요청 열기' : '기록에서 확인'}</Button>}
            {topic === 'recovery' && <Button variant="cta" onClick={() => go('history')}>{activeRunId ? '실행 결과·복구 열기' : '복구할 실행 고르기'}</Button>}
          </div>
        </section>
        <p className="faint-note">가디언은 안내자예요. 여기서 실행을 허용·차단하거나 자동 복구하지 않습니다.</p>
      </div>
    </>,
    document.body,
  )
}
