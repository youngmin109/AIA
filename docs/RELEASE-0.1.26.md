# AIA 0.1.26 Release Readiness

0.1.26은 현재 MVP 지원 범위를 고정하고, 제품 실행 경로에서 MCP 실험 코드를
제거한 정합성 릴리스다.

## 변경 내용

- 현재 Codex PreToolUse 의미 해석 지원을 `Bash`와 `apply_patch`로 고정했다.
- MCP 서버 등록·호출과 MCP 도구의 정책 의미 해석을 제품 실행 경로에서 제거했다.
- Hook으로 도착한 MCP 요청은 `UNSUPPORTED_TOOL_PATH`로 거부한다.
- 과거 MCP direct smoke와 산출물은 개발 이력으로 보존하지만 현재 제품 지원이나
  MVP 완료 주장에 포함하지 않는다.
- README, 제품 지원 범위, 제한사항, Actual Codex 검증 문서를 현재 계약에 맞췄다.

## 현재 지원 범위

```text
Windows 11
Python 3.13
Codex CLI
AIA Protected Run
Codex PreToolUse: Bash, apply_patch
```

`Edit`와 `Write`는 Codex Hook에서 canonical `apply_patch` 별칭으로 처리한다.
MCP와 목록 밖 도구는 지원하지 않으며 `UNSUPPORTED_TOOL_PATH`로 거부한다.

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
uv run aia self-test
uv run aia doctor
uv run aia capabilities --json
```

실제 Codex 증명은 사용자가 Codex `/hooks`에서 AIA Hook을 검토·신뢰한 뒤 다음을
실행한다.

```powershell
uv run aia proof --scenario block-canary
uv run aia proof --scenario block-env
uv run aia proof --scenario block-apply-patch
uv run aia proof --scenario block-windows-delete
uv run aia proof --scenario normal
```

각 증명은 실제 Hook Event, `permissionDecision=deny` 또는 정상 실행, 부작용 부재,
Result Bundle 상태를 함께 확인해야 PASS로 해석한다.
