# AIA 0.1.28 Release Readiness

0.1.28은 Codex CLI 전용 MVP의 Process Sensor 실패 처리를 보수적으로 보강한
유지보수 릴리스다.

## 변경 내용

- 관리 대상 프로세스의 자식 트리 조회가 `AccessDenied`, `PermissionError` 또는 OS
  오류로 실패하면 빈 자식 목록으로 삼지 않는다.
- 해당 상황은 `OWNER_UNVERIFIABLE` 및 `FAILED`로 기록하고 Process Sensor가
  `HEALTHY`라고 주장하지 않는다.
- 조회 실패 시 Process Evidence를 생성하지 않는 결정론적 Unit Test를 추가했다.
- Hook·File·Process Sensor, Codex CLI 전용 지원 범위, MCP 제외 계약은 변경하지 않는다.

## 지원 범위

```text
Windows 11
Python 3.13
Codex CLI
AIA Protected Run
Codex PreToolUse: Bash, apply_patch
Runtime Sensors: Hook, File, Process
```

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
uv run aia self-test
uv run aia doctor
uv run aia proof --scenario normal
uv run aia proof --scenario block-canary
uv run aia proof --scenario block-apply-patch
uv run aia proof --scenario block-env
```

실제 보호 성공은 Hook Trust를 검토·신뢰하고, 결과 Bundle이 `VALID`이며,
세 센서가 모두 실행 중 `HEALTHY`, 종료 후 `STOPPED`로 기록된 경우에만 주장한다.
Process 트리 조회가 신뢰할 수 없는 경우에는 `OWNER_UNVERIFIABLE`을 성공으로
해석하지 않는다.
