# AIA 0.1.16 Release Readiness

0.1.16은 로컬 콘솔의 실행 완료 후 탐색 경로를 수정한 유지보수 릴리스다.
대시보드를 기본 화면으로 사용하면서도 실행 중 화면과 결과 화면의 `새 보호 실행`
링크가 `/new` 실행 폼으로 직접 이동한다.

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
uv run aia --version
uv run aia demo
powershell -ExecutionPolicy Bypass -File .\\scripts\\package-release.ps1 -Force
```

보호 범위와 Actual Codex 증거는 [제품 상태](../PRODUCT-STATUS.md),
[현재 재검증 기록](../validation/CURRENT-REVALIDATION.md), [제한사항](../LIMITATIONS.md)을
함께 확인한다.
