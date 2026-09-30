# AIA 0.1.20 Release Readiness

0.1.20은 첫 실행 온보딩 상태를 보강한 유지보수 릴리스다. `aia setup`이 Hook을
설치했다는 사실과 실제 Protected Run을 시작할 준비가 끝났다는 사실을 분리해
표시한다.

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
powershell -ExecutionPolicy Bypass -File .\scripts\release-gate.ps1
```

## 준비 상태 해석

`aia setup --json`과 일반 출력의 `readiness_code`는 다음처럼 해석한다.

| 코드 | 의미 |
|---|---|
| `READY` | Hook Trust·실제 Hook 검증·Control Root 준비가 모두 확인됨 |
| `CODEX_HOOK_TRUST_REQUIRED` | Codex `/hooks`에서 AIA Hook을 사용자가 검토·신뢰해야 함 |
| `HOOK_VERIFICATION_REQUIRED` | Trust는 확인됐지만 Session-bound 실제 Hook Probe가 필요함 |
| `CODEX_EXECUTABLE_UNAVAILABLE` | Codex CLI를 찾을 수 없음 |
| `CONTROL_ROOT_NOT_WRITABLE` | AIA Control Root에 쓸 수 없음 |

`configured=true`는 Hook 설정을 기록했다는 뜻이고, `ready=true`일 때만 보호
실행을 시작할 준비가 끝났다는 뜻이다. AIA는 Codex Hook Trust를 자동으로
승인하지 않는다.

## 회귀 결과

- 전체 pytest: **578 passed, 3 skipped, 2 warnings**
- 기존 Core·Actual Codex 증거·배포 검증 계약 유지
- 새 `aia setup` 준비 상태 코드 회귀 테스트 추가

실제 Codex 보호 증명은 사용자가 Codex `/hooks`에서 AIA Hook을 검토·신뢰한 뒤
다음 순서로 별도 수행한다.

```powershell
aia hook verify
aia doctor
aia proof
```
