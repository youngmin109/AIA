# AIA 0.1.13 Release Readiness

0.1.13은 첫 실행 제품 흐름을 보강한 릴리스다. 실제 Workspace와 Codex를
건드리지 않는 `aia demo`와 disposable Workspace에서 실제 Codex 증명을 선택하는
`aia demo --live`를 제공한다.

## 사용 흐름

```powershell
aia demo
aia setup
# Codex /hooks에서 AIA Hook을 검토·신뢰
aia hook verify
aia demo --live
```

`aia demo`는 AIA Core만 점검하며 실제 Codex를 시작하지 않는다. `--live`는
기존 `aia proof`와 동일한 실제 Codex 증명 경로를 사용하고, Hook Trust가 확인되지
않으면 Codex 도구를 실행하지 않는다.

Codex matcher의 `Edit`·`Write` 별칭은 실제 Hook 입력의 canonical
`apply_patch` 경로로 처리되며, `aia capabilities --json`의 alias metadata에서
확인할 수 있다.

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
uv run aia --version
uv run aia demo
uv run aia self-test --json
uv run aia capabilities --json
powershell -ExecutionPolicy Bypass -File .\scripts\package-release.ps1 -Force
```

실제 Codex 차단 결과와 지원 범위는 [현재 재검증 기록](validation/CURRENT-REVALIDATION.md),
[제품 지원 범위](PRODUCT-SUPPORT.md), [제한사항](LIMITATIONS.md)을 함께 확인한다.
현재 0.1.13의 disposable Actual Codex 차단 요약은
[Actual Codex 증명 기록](validation/evidence/actual-codex-pretool-20260911-0.1.13.json)에서
확인할 수 있다.
