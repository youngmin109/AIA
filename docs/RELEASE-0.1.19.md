# AIA 0.1.19 Release Readiness

0.1.19는 실행 기록의 상태 표현을 보강한 유지보수 릴리스다. 검증된 Result Bundle이
없는 terminal 런타임 스냅샷을 제품 성공 기록처럼 표시하지 않고 `UNVERIFIED`로
구분한다. 이 변경은 보안 판정이나 Security Invariant를 바꾸지 않는다.

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
powershell -ExecutionPolicy Bypass -File .\scripts\release-gate.ps1
```

## 해석 규칙

- `PRODUCT_PROTECTED_RUN` + `Bundle: VALID`: 검증된 Result Bundle이 있는 제품 실행
- `LIVE_PROTECTED_RUN` + `Bundle: PENDING`: 아직 종료되지 않은 실행
- `UNVERIFIED_RUNTIME_STATE` + `Bundle: UNVERIFIED`: 결과 검증이 되지 않은 terminal 상태

`UNVERIFIED`는 보호 성공이나 차단 성공을 의미하지 않는다. 실제 Codex 사전 차단
증명은 여전히 사용자가 Codex `/hooks`에서 AIA Hook을 검토·신뢰한 뒤
`aia hook verify`와 `aia proof`를 실행해야 한다.
