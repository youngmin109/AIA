# AIA 0.1.8 Release Readiness

0.1.8은 0.1.7의 지원 계약과 보안 판정을 유지하면서, 사용자가 이해하기 쉬운
보호 세션 진입점을 제품 CLI에 추가한 릴리스다.

## 사용자에게 보이는 변경

- `aia start <workspace>`를 실행하면 AIA가 먼저 Protected Run을 준비한 뒤
  Codex 대화형 세션을 연다.
- 사용자는 Codex가 열린 뒤 그 세션 안에서 작업 문장을 입력한다.
- 기존 `aia protect` 명령은 호환성을 위해 유지되며 같은 보안 경로를 사용한다.
- 설치 가이드와 빠른 시작 문서가 세션 우선 사용 흐름을 설명한다.

## 보안 계약

- Workspace 검증, Active Policy Freeze, Workspace Lease, Safe Checkpoint,
  Hook/File/Process Sensor 준비와 Readiness Barrier를 기존과 동일하게 적용한다.
- Codex Hook Trust와 Session-bound Hook 검증이 완료되지 않으면 Protected Run을
  시작하지 않는다.
- 지원 범위 밖의 도구·MCP·Hook 우회 실행을 보호 성공으로 주장하지 않는다.

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
uv run aia self-test --json
uv run aia start --help
powershell -ExecutionPolicy Bypass -File .\scripts\package-release.ps1 -Force
powershell -ExecutionPolicy Bypass -File .\scripts\verify-release.ps1 -BundlePath .\dist\release\aia-0.1.8
```

Actual Codex 보안 증거와 지원 범위는 [현재 재검증 기록](../validation/CURRENT-REVALIDATION.md)과
제품 지원 문서를 함께 확인한다. 이 릴리스도 모든 Agent·도구·MCP·OS 전체 Writer를
보호한다고 주장하지 않는다.
