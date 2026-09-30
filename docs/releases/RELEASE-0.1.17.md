# AIA 0.1.17 Release Readiness

0.1.17은 첫 사용자의 Hook 온보딩을 보강한 유지보수 릴리스다. `aia hook explain`은
Codex `/hooks`에서 검토해야 할 AIA Hook의 matcher와 command, 현재 Trust 상태,
실시간 검증 순서를 읽기 전용으로 보여준다.

이 명령은 Codex 설정을 수정하거나 Hook을 자동으로 Trust하지 않는다. 사용자가
검토·Trust한 뒤 `aia hook verify`를 실행해야 일반 Protected Run을 시작할 수 있다.

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
uv run aia --version
uv run aia self-test
uv run aia hook explain --json
powershell -ExecutionPolicy Bypass -File .\scripts\package-release.ps1 -Force
```

실제 Codex 보호 증거와 현재 제한사항은 [제품 상태](../PRODUCT-STATUS.md),
[현재 재검증 기록](../validation/CURRENT-REVALIDATION.md),
[제한사항](../LIMITATIONS.md)을 함께 확인한다.
