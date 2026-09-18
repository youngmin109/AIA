# AIA 0.1.7 Release Readiness

0.1.7은 보안 판정·집행 계약을 변경하지 않고, 설치 후 사용자가 현재 보호 범위를
확인할 수 있는 제품 표면을 보강한 릴리스다.

## 사용자에게 보이는 변경

- `aia capabilities`로 Windows 11·Python 3.13·Codex CLI와 지원 PreToolUse matcher를 조회할 수 있다.
- `aia capabilities --json`은 자동화와 지원 진단이 사용할 수 있는
  `aia-capabilities-v1` 계약을 제공한다.
- 로컬 콘솔의 새 보호 실행 화면에 지원 범위, 필수 사용자 단계, 지원하지 않는
  범위를 표시한다.
- 릴리스 검증은 clean wheel에서 Core self-test뿐 아니라 capabilities 계약과
  로컬 콘솔 asset을 확인한다.

## 유지되는 보호 계약

- 실제 보호 실행은 Codex `/hooks`에서 사용자가 AIA Hook을 검토·신뢰하고,
  `aia hook verify`가 현재 Session-bound Hook Event를 확인한 뒤에만 시작한다.
- 검증된 PreToolUse 범위는 `Bash`, `apply_patch`, `Edit`, `Write`,
  명시적으로 등록된 `mcp__filesystem__read_file`, `mcp__fs__read`다.
- 지원되지 않는 도구와 Hook 우회 실행은 보호 성공으로 표시하지 않는다.
- 정책 판정, Attribution, Enforcement, Recovery, Integrity의 독립 상태 축은
  변경하지 않는다.

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
uv run aia self-test --json
uv run aia capabilities --json
powershell -ExecutionPolicy Bypass -File .\scripts\package-release.ps1 -Force
powershell -ExecutionPolicy Bypass -File .\scripts\verify-release.ps1 -BundlePath .\dist\release\aia-0.1.7
```

Actual Codex의 보안 증거는 [현재 재검증 기록](validation/CURRENT-REVALIDATION.md)과
각 증거 JSON을 함께 확인한다. 0.1.7은 해당 검증된 보안 경로의 사용자 표면만
확장하며, 모든 Codex 도구·모든 MCP·OS 전체 Writer를 보호한다고 주장하지 않는다.
