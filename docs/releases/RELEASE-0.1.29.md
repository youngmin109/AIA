# AIA 0.1.29 Release Readiness

0.1.29는 AIA를 실제 사용자가 체감하는 로컬 Codex 보호 제품으로 정리한
사용성 릴리스다.

## 변경 내용

- 로컬 콘솔에서 기존 Workspace를 선택해 Protected Run을 시작한다.
- 대화형 실행에서 Codex를 별도 Windows 터미널로 열 수 있다.
- 실행 화면에 Hook·File·Process Sensor 상태와 raw payload 없는 이벤트 요약을
  1초 주기로 표시한다.
- 차단 사건에서 정책 판정, AIA 결정, 실제 실행 결과를 분리해 표시하고 실제
  도구 미실행이 확인된 경우에만 `BLOCKED / SUCCEEDED`를 사용한다.
- 콘솔에서 Strict Schema 기반 사용자 정책을 작성·검증·저장한다.
- 실행 기록에 Workspace·상태·보호 상태·차단 여부·날짜 필터를 제공한다.

## 지원 범위

```text
Windows 11
Python 3.13
Codex CLI
AIA Protected Run
Runtime Sensors: Hook, File, Process
MCP·Claude·외부 Agent·Network: 미지원
```

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
uv run aia self-test
uv run aia proof --scenario normal
uv run aia proof --scenario block-canary
uv run aia proof --scenario block-env
powershell -ExecutionPolicy Bypass -File .\scripts\release-gate.ps1
```

실제 보호 성공은 Hook Trust를 사용자가 검토·신뢰하고, Result Bundle이 `VALID`이며,
세 센서가 실행 중 `HEALTHY`, 종료 후 `STOPPED`로 기록된 경우에만 주장한다.
화면에 보이는 안전한 이벤트 요약은 명령 원문·비밀값·파일 내용을 포함하지 않는다.
