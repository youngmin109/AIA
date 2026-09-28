# AIA 0.1.10 Release Readiness

0.1.10은 0.1.9 이후 Hook 실시간 검증의 부트스트랩 경계를 보강하고, 사용자가
실제 Codex Hook Trust 상태를 정확히 확인할 수 있도록 한 유지보수 릴리스다.

## 사용자에게 보이는 변경

- CLI와 로컬 콘솔이 `TRUSTED`, `MANAGED`, `MODIFIED`, `UNTRUSTED` 상태를 실제
  Codex가 보고한 값으로 표시한다.
- 신뢰된 Hook을 수동 검토 필요 상태로 잘못 표시하지 않는다.
- Hook 검증 Probe에 사용하는 내부 경로는 일반 Protected Run의 실행 경로와
  구분된다.

## 보안 경계

Hook 검증 Probe는 Codex `/hooks`에서 사용자가 AIA Hook을 검토·신뢰한 뒤에만
시작된다. 검증 명령이 발급한 일회성 Probe 권한이 없으면 내부 Probe 플래그를
사용할 수 없다. 일반 `aia start`와 `aia protect`는 여전히 현재 Hook Trust와
Session-bound Hook 검증을 요구한다.

이 릴리스도 Windows 11, Python 3.13, Codex CLI, AIA Protected Run과 명시된
PreToolUse 의미 해석 범위만 지원한다. 모든 Agent와 모든 Codex 도구를 보편적으로
보호한다고 주장하지 않는다.

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
uv run aia self-test --json
uv run aia capabilities --json
powershell -ExecutionPolicy Bypass -File .\scripts\package-release.ps1 -Force
powershell -ExecutionPolicy Bypass -File .\scripts\verify-release.ps1 -BundlePath .\dist\release\aia-0.1.10
```

실제 Codex Hook Trust는 사용자가 Codex `/hooks` 화면에서 직접 검토해야 하며,
현재 실행 환경의 Hook 신뢰 상태는 `aia doctor`로 확인한다.
