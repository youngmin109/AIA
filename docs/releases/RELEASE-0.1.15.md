# AIA 0.1.15 Release Readiness

0.1.15는 로컬 콘솔의 기본 진입 경험을 제품 흐름에 맞게 정리한 릴리스다.
콘솔을 열면 먼저 현재 보호 준비 상태와 지원 범위를 확인하고, 사용자가 명시적으로
`새 보호 실행` 화면으로 이동해 Workspace와 정책을 선택한다.

## 화면 경로

```text
/          → 제품 대시보드
/new       → 새 보호 실행
/dashboard → 대시보드 호환 별칭
/runs      → 실행 기록
```

대시보드는 실행을 자동으로 시작하지 않는다. `READY`가 아닌 경우 Codex Hook Trust,
실시간 Hook 검증 등 해결해야 할 다음 단계를 표시한다.

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
uv run aia --version
uv run aia demo
powershell -ExecutionPolicy Bypass -File .\\scripts\\package-release.ps1 -Force
```

Actual Codex 보호 증거와 지원 범위는 [제품 상태](../PRODUCT-STATUS.md),
[현재 재검증 기록](../validation/CURRENT-REVALIDATION.md), [제한사항](../LIMITATIONS.md)을
함께 확인한다.
