# AIA 0.1.9 Release Readiness

0.1.9는 보호 실행 중 지원 목록 밖의 Codex 로컬 도구가 조용히 matcher를 빠져나가던
제품 표면을 보강한 릴리스다.

## 사용자에게 보이는 변경

- AIA Codex Hook은 PreToolUse/PostToolUse에서 `matcher = "*"`로 설치된다.
- AIA가 의미를 해석하는 도구 목록은 Bash, apply_patch/Edit/Write 계열, 등록된
  파일 읽기 MCP로 명시적으로 유지된다.
- 목록 밖 도구가 Hook 경로로 도착하면 `UNSUPPORTED_TOOL_PATH` deny를 반환한다.
- 이런 실행은 정상적인 Protected Run 성공으로 표시하지 않고 degraded 결과와
  제한사항으로 남긴다.

## 보안 경계

`matcher = "*"`는 Codex가 로컬 Hook 경로로 전달하는 도구를 수신하기 위한 설정이다.
Codex가 Hook 경로로 보내지 않는 특수·Hosted 도구, Hook 비활성화·불신뢰, 외부
Agent와 사용자의 수동 실행은 보호 범위 밖이다. 따라서 이 릴리스도 모든 Agent와
모든 OS 작업을 완전히 통제한다고 주장하지 않는다.

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
uv run aia self-test --json
uv run aia capabilities --json
powershell -ExecutionPolicy Bypass -File .\scripts\package-release.ps1 -Force
powershell -ExecutionPolicy Bypass -File .\scripts\verify-release.ps1 -BundlePath .\dist\release\aia-0.1.9
```

실제 Codex Hook Trust는 사용자가 Codex `/hooks` 화면에서 직접 검토해야 하며,
현재 실행 환경의 Hook 신뢰 상태는 `aia doctor`로 확인한다.
