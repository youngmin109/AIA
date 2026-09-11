# AIA 0.1.22 Release Readiness

0.1.22는 첫 실행 진입점을 단순화한 유지보수 릴리스다.

`aia start` 또는 `aia protect`에서 Workspace 경로를 생략하면 현재 PowerShell
디렉터리를 보호 대상으로 사용한다. 실행이 시작되면 AIA가 실제로 선택한 Workspace
절대 경로를 표시하므로, 사용자가 다른 폴더를 보호하고 있다고 오해하지 않게 한다.

예:

```powershell
cd C:\workspace\my-project
aia start
```

명시적 경로도 계속 사용할 수 있다.

```powershell
aia start C:\workspace\my-project
aia protect C:\workspace\my-project --task "테스트를 실행해줘"
```

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
powershell -ExecutionPolicy Bypass -File .\scripts\release-gate.ps1
```

현재 기준 전체 테스트 결과는 `580 passed, 3 skipped, 2 warnings`다.

## 범위

이번 변경은 CLI 진입점의 기본 Workspace만 개선한다. 정책 판정, Hook Trust,
Evidence, Enforcement, Recovery, Integrity 계약은 변경하지 않는다.
