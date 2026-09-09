# AIA MVP

AIA는 Codex와 같은 Agent의 보호 실행을 위한 독립적인 제품형 MVP Repository다. MVP는 실행 증거를 수집하고, 정규화·귀속·정책 평가·집행·복구·무결성 검증·감사를 연결한다.

EPIC-018 평가 결과는 [MVP 최종 판정](docs/validation/MVP-FINAL-VERDICT.md)과 [제한사항](docs/LIMITATIONS.md)에 기록되어 있다. 이 릴리스 후보는 결정론적 핵심 흐름을 검증했으며, Actual Codex의 구조화된 READ 차단과 파괴적 PROCESS 시나리오는 외부 인터페이스 제약으로 제한된다.

제품 정의와 개발 규칙은 [PROJECT.md](PROJECT.md), [ARCHITECTURE.md](ARCHITECTURE.md), [AGENTS.md](AGENTS.md)를 참조한다.

## 개발 환경

```powershell
uv sync
uv run pytest
```

평가 산출물은 `evaluation/mvp-1.0/<evaluation-id>/` 아래에 보존한다. 평가 기준, 허용된 주장, 제한사항, 위협 모델은 `docs/validation/`과 `docs/`에 함께 고정한다.
