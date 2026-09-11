# AIA 0.1.12 Release Readiness

0.1.12는 Codex 도구 지원 주장을 실제 입력 계약과 일치시키는 유지보수
릴리스다. AIA가 의미를 해석하고 실제로 검증한 지원 도구는 `Bash`,
`apply_patch`, 명시적으로 등록된 파일 읽기 MCP다.

`Edit`·`Write`는 현재 공식 Codex 입력 계약이 확인되지 않아 지원 목록에서
제외했다. 해당 이름의 Hook 이벤트가 들어오면 AIA는 보호 성공으로 해석하지
않고 `UNSUPPORTED_TOOL_PATH` 경계로 처리한다.

## 보안 경계

이 릴리스는 정책 판정, PreToolUse 집행, Hook 검증, Workspace 보호 범위를
확장하지 않는다. 기존과 동일하게 Windows 11, Python 3.13, Codex CLI,
AIA Protected Run, 명시된 PreToolUse 의미 해석 범위만 지원한다.

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
uv run aia --version
uv run aia self-test --json
uv run aia capabilities --json
powershell -ExecutionPolicy Bypass -File .\scripts\package-release.ps1 -Force
powershell -ExecutionPolicy Bypass -File .\scripts\verify-release.ps1 -BundlePath .\dist\release\aia-0.1.12
```

실제 Codex 차단 증거와 일반 사용자 Hook Trust 절차는
[현재 재검증 기록](validation/CURRENT-REVALIDATION.md)에서 확인한다.
