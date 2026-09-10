# AIA 제품 사용 전후 정량 평가

이 평가는 AIA 없이 수행한 개발 작업과 AIA Protected Run 안에서 수행한 동일 작업을 비교한다. 기존 EPIC-018 Acceptance와 Performance 결과를 대체하지 않으며, 제품 사용 효과를 별도 평가한다.

## 평가 영역

- 보안 효과: 위험 행위 부작용률, 사전 차단 성공률, 오차단률, unrelated 프로세스 영향
- 정상 작업 보존: 정상 작업 성공률, 작업 실패율, 재시도 횟수
- 성능 비용: 보호 준비, Checkpoint, 작업, Recovery, Integrity, 결과 확정 시간
- 증거 품질: Evidence Coverage, Lineage 완전성, 판정 일관성, 결과 재구성 시간

## 비교 원칙

각 시나리오는 새 Disposable Workspace에서 AIA OFF와 AIA ON으로 반복한다. Workspace 초기 상태, 작업 입력, 정책, Windows·Python·uv·Codex 환경을 고정하고 실행 순서는 무작위화한다. 결정론적 Fixture와 Actual Codex 결과는 서로 섞지 않는다.

Actual Codex가 구조화된 READ나 파괴적 PROCESS 경로를 실현하지 못하면 PASS로 변경하지 않고 `LIMITATION` 또는 `SCENARIO_NOT_REALIZED`로 기록한다.

## 고정 시나리오

시나리오 정의는 `scripts/product_evaluation/scenarios.py`에 보존한다. 정상 작업, 정책 위반, 불확실한 Evidence, Recovery·Integrity를 포함한다.

## 보고서

`scripts/product_evaluation/build_report.py`는 JSONL 원본을 검증하고 `summary.json`과 자체 실행 가능한 Plotly HTML을 만든다. Plotly는 평가 도구 전용 의존성이며 AIA 보안 실행 경로에는 포함하지 않는다.

보고서에는 다음이 포함된다.

- AIA OFF/AIA ON 핵심 지표 비교
- 시나리오별 부작용 비교
- 작업·Checkpoint·Recovery·Integrity 시간 분포
- 각 시간 지표의 최소값·중앙값·P95·최대값과 AIA OFF 대비 중앙값·P95 변화량
- Evidence 흐름 Funnel
- 판정 일관성과 과도한 귀속률(원본 필드가 기록된 경우)
- Actual Codex와 외부 인터페이스 제한사항

보고서는 하나의 종합점수를 만들지 않고 원본 지표와 변화량을 함께 표시한다.
