const STEPS = [
  { title: '1. 사용자 요청', text: '사용자가 Codex에게 자연어로 작업을 지시합니다.' },
  { title: '2. Codex 실행 요청', text: 'Codex가 도구·명령을 실제로 실행하려는 순간 Hook이 요청을 받습니다.' },
  { title: '3. AIA 정책 확인', text: '경로·명령·세션 상태를 확인해 허용, 확인 요청, 차단을 결정합니다.' },
  { title: '4. 실제 결과 검증', text: '프로세스와 파일 변화까지 관찰해 감사 기록으로 남깁니다.' },
]

export function StepsExplainer() {
  return (
    <aside className="card explainer">
      <div className="explainer-overline">HOW IT WORKS</div>
      <h2 className="explainer-title">명령은 이렇게 보호돼요</h2>
      <div className="explainer-flow">
        {STEPS.map((step) => (
          <div key={step.title} className="explainer-step">
            <b>{step.title}</b>
            <p>{step.text}</p>
          </div>
        ))}
      </div>
    </aside>
  )
}
