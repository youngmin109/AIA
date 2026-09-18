# AIA 0.1.18 Release Readiness

0.1.18은 설치 이후의 제거 경계를 보강한 유지보수 릴리스다. 릴리스 번들에
`uninstall.ps1`을 포함하며, 기본 동작은 AIA가 설치한 Codex Hook만 제거한다.

사용자 수준 AIA 도구까지 제거하려면 `-RemoveTool`을 명시해야 한다. Protected Run
결과와 AIA Control Root는 제거 스크립트가 삭제하지 않는다.

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
uv run aia --version
uv run aia self-test
uv run aia hook explain --json
powershell -ExecutionPolicy Bypass -File .\scripts\package-release.ps1 -Force
```

실제 Codex 보호 증거와 현재 제한사항은 [제품 상태](PRODUCT-STATUS.md),
[현재 재검증 기록](validation/CURRENT-REVALIDATION.md),
[제한사항](LIMITATIONS.md)을 함께 확인한다.
