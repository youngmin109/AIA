# AIA 0.1.24 Release Readiness

0.1.24는 로컬 콘솔의 첫 실행 흐름을 보강한 유지보수 릴리스다.

`새 보호 실행` 화면의 `실제 Hook 연결 검증` 버튼은 기존 `aia hook verify` CLI를
동일하게 실행한다. 사용자가 Codex `/hooks`에서 직접 Trust를 완료한 뒤 버튼을
누르면, AIA는 disposable Workspace에서 Session-bound Hook Event를 확인하고
화면의 준비 상태를 다시 표시한다.

AIA는 이 버튼으로 Codex Trust를 자동 변경하지 않는다. Trust가 없으면 검증은
실행되지 않거나 `CODEX_HOOK_TRUST_REQUIRED` 결과를 반환하며, 보호 실행도 열리지
않는다.

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
powershell -ExecutionPolicy Bypass -File .\scripts\release-gate.ps1
```

현재 전체 테스트 결과는 `583 passed, 3 skipped, 2 warnings`다.
