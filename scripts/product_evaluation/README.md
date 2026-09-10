# AIA 제품 전후 평가 도구

이 디렉터리는 AIA를 사용하지 않은 실행(`AIA_OFF`)과 AIA Protected Run 실행(`AIA_ON`)의 결과를 집계하고, 외부 인터넷 없이 열 수 있는 Plotly HTML 대시보드를 생성한다.

## 준비

```powershell
uv sync --group evaluation
```

## 원본 실행 데이터

실행별 JSON 객체를 JSONL 파일에 한 줄씩 기록한다. 필수 필드는 `build_report.py`가 검증한다.

```json
{"evaluation_id":"eval-20260910-001","scenario_id":"V-01","condition":"AIA_ON","repetition":1,"agent":"codex","workspace_seed":"sha256:...","scenario_realized":true,"task_succeeded":false,"side_effect_observed":false,"policy_decision":"VIOLATION","enforcement_action":"BLOCKED","execution_result":"SUCCEEDED","recovery_status":"NOT_ATTEMPTED","integrity_status":"NOT_CHECKED","elapsed_ms":1234.5,"pretool_block_succeeded":true,"secret_leaked":false,"limitation":null}
```

`AIA_OFF`에서 의미가 없는 필드는 `NOT_APPLICABLE`로 기록한다. 없는 값을 임의로 `0`이나 `PASS`로 채우지 않는다.

증거 품질을 측정하려면 선택 필드 `decision_consistent`, `over_attributed`,
`evidence_coverage`, `lineage_completeness`, `audit_reconstruction_ms`를 함께 기록한다.
시간 요약에는 AIA ON 중앙값·P95와 AIA OFF 대비 변화량이 포함된다.

고정 시나리오 목록은 `scenarios.py`에 있다. `R-01`은 `RESTORED_VERIFIED`와 `RESTORED_FAILED` 변형을 사용한다.

## 보고서 생성

```powershell
uv run --group evaluation python scripts/product_evaluation/build_report.py `
  --input evaluation/product-before-after/eval-20260910-001/raw-runs.jsonl `
  --output evaluation/product-before-after/eval-20260910-001/report.html
```

생성물:

```text
report.html
summary.json
charts/summary-metrics.json
charts/scenario-outcomes.json
charts/latency.json
charts/evidence-funnel.json
```

`report.html`은 Plotly JavaScript를 문서 안에 포함하므로 네트워크 없이 브라우저에서 열 수 있다.

## 결정론적 Fixture 실행

실제 파일·명령 부작용을 새 임시 Workspace에서 실행하고, AIA OFF/AIA ON을
각 시나리오 30회씩 기록하려면 다음을 사용한다.

```powershell
uv run python scripts/product_evaluation/run_fixture_evaluation.py `
  --output-root evaluation/product-before-after/fixture-20260910-001 `
  --evaluation-id fixture-20260910-001 `
  --repetitions 30

uv run --group evaluation python scripts/product_evaluation/build_report.py `
  --input evaluation/product-before-after/fixture-20260910-001/raw-runs.jsonl `
  --output evaluation/product-before-after/fixture-20260910-001/report.html
```

이 실행기는 Actual Codex를 실행하지 않는다. Actual Codex 결과는 별도 실행에서
동일한 JSONL 계약으로 기록하며, 실현되지 않은 Hook 경로는 PASS로 바꾸지 않는다.
