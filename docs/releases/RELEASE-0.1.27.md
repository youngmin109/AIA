# AIA 0.1.27 Release Readiness

0.1.27은 Codex CLI 전용 MVP에서 Hook·File·Process Sensor의 검증 상태와
Evidence 가시성을 보강한 유지보수 릴리스다.

## 변경 내용

- 세 센서(`AGENT_HOOK`, `FILESYSTEM_WATCHER`, `PROCESS_RUNTIME`)가 모두 실행 중
  `HEALTHY`, 종료 후 `STOPPED`인 경우에만 `COMPLETED_VERIFIED` 또는
  `ABORTED_VERIFIED`를 표시한다.
- 센서가 누락되거나 실패한 실행은 `*_DEGRADED`로 남긴다.
- Result 화면에서 센서별 실행 중 상태·종료 상태·판정을 확인할 수 있다.
- Live Run과 Result 화면에서 File·Hook·Process Evidence 건수를 확인할 수 있다.
- MCP와 지원 목록 밖 도구는 계속 제품 범위에서 제외한다.

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
세 센서가 모두 `HEALTHY → STOPPED`로 기록된 경우에만 주장한다.
