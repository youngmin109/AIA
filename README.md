# AIA MVP

AIA는 Codex와 같은 Agent의 보호 실행을 위한 독립적인 제품형 MVP Repository다. MVP는 실행 증거를 수집하고, 정규화·귀속·정책 평가·집행·복구·무결성 검증·감사를 연결한다.

EPIC-018 평가 결과는 [MVP 최종 판정](docs/validation/MVP-FINAL-VERDICT.md)과 [제한사항](docs/LIMITATIONS.md)에 기록되어 있다. 이 릴리스 후보는 결정론적 핵심 흐름을 검증했으며, Actual Codex의 구조화된 READ 차단과 파괴적 PROCESS 시나리오는 외부 인터페이스 제약으로 제한된다.

제품 정의와 개발 규칙은 [PROJECT.md](PROJECT.md), [ARCHITECTURE.md](ARCHITECTURE.md), [AGENTS.md](AGENTS.md)를 참조한다.

시스템 전체 구성은 [AIA 시스템 구성도](docs/SYSTEM-OVERVIEW.md)에서 확인할 수 있다.

## 개발 환경

```powershell
uv sync
uv run pytest
```

평가 산출물은 `evaluation/mvp-1.0/<evaluation-id>/` 아래에 보존한다. 평가 기준, 허용된 주장, 제한사항, 위협 모델은 `docs/validation/`과 `docs/`에 함께 고정한다.

## 로컬 보안 콘솔 (EPIC-019)

선택적으로 로컬 콘솔을 실행할 수 있다.

```powershell
uv run aia-web
```

기본 주소는 [http://127.0.0.1:8787](http://127.0.0.1:8787)이다. 화면에서 Workspace, Codex task, Policy Profile, ENFORCE/AUDIT 모드를 입력하면 AIA Core의 보호 실행 흐름을 시작하고, Live Run과 Result Bundle을 확인할 수 있다. 기본 Control Root는 `%USERPROFILE%\.aia\control`이며 `AIA_CONTROL_ROOT` 환경 변수로 바꿀 수 있다.

콘솔은 로컬 단일 사용자 P1 도구다. 외부 bind/로그인/원격 접근/Database를 제공하지 않으며, Core의 보안 판정과 Result Bundle을 화면에 표시하는 역할만 한다. 화면에는 raw command와 evidence payload 값이 노출되지 않는다. 자세한 범위와 HTTP 계약은 [EPIC-019 문서](docs/epics/EPIC-019-LOCAL-SECURITY-CONSOLE.md)를 참조한다.

외부 Network에 노출하지 마십시오.

## 실제 Codex 보호 실행

```powershell
uv run aia hook install
uv run aia protect C:\workspace\my-project --task "작업 내용을 입력"
```

Hook을 Codex에서 검토·신뢰한 뒤 보호 실행을 시작한다. 실제 사전 차단 증명은 [docs/ACTUAL-CODEX-PROOF.md](docs/ACTUAL-CODEX-PROOF.md)를 참고한다.
