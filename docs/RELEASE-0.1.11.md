# AIA 0.1.11 Release Readiness

0.1.11은 Hook Trust 상태를 사용자가 보는 값과 CLI JSON 계약에서 일치시키는
유지보수 릴리스다. `aia hook status`가 실제 Codex PreToolUse 상태를
`TRUSTED`·`MANAGED`·`MANUAL_REVIEW_REQUIRED` 중 올바르게 표시한다.

## 보안 경계

이 릴리스는 정책 판정, PreToolUse 집행, Hook 검증, Workspace 보호 범위를
확장하지 않는다. 기존과 동일하게 Windows 11, Python 3.13, Codex CLI,
AIA Protected Run, 명시된 PreToolUse 의미 해석 범위만 지원한다.

Codex Hook Trust는 사용자가 Codex `/hooks` 화면에서 직접 검토해야 한다.
Trust가 `TRUSTED` 또는 `MANAGED`가 아니면 AIA는 보호 실행을 시작하지 않는다.

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
uv run aia --version
uv run aia self-test --json
uv run aia capabilities --json
powershell -ExecutionPolicy Bypass -File .\scripts\package-release.ps1 -Force
powershell -ExecutionPolicy Bypass -File .\scripts\verify-release.ps1 -BundlePath .\dist\release\aia-0.1.11
```

실제 Codex 차단 증거와 일반 사용자 Hook Trust 절차는
[현재 재검증 기록](validation/CURRENT-REVALIDATION.md)에서 확인한다.
