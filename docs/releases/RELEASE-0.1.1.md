# AIA 0.1.1 Release Readiness

0.1.1은 0.1.0의 지원 범위와 보안 주장을 유지하면서 보호 실행의 운영 상태와
시작·중지 경계를 보강한 하드닝 릴리스다. AIA를 모든 Agent와 모든 운영체제를
보호하는 범용 보안 제품으로 해석하지 않는다.

## 지원 계약

| 항목 | 현재 계약 |
|---|---|
| 운영체제 | Windows 11 |
| Agent | Codex CLI |
| 시작 방식 | AIA Protected Run에서 AIA가 실행한 Codex |
| 사전 통제 지점 | Codex `PreToolUse` Hook |
| 지원 matcher | Bash, `apply_patch`, Edit, Write 계열, 등록된 파일 읽기 MCP matcher |
| 저장 위치 | Workspace 밖의 사용자별 AIA Control Root |
| 결과 | 검증된 Evidence Bundle과 보안 결과 |

## 이번 릴리스의 보강

- 보호 준비 이후 Codex 프로세스·Hook Broker·Process Sensor를 등록하는 동안
  `LAUNCHING` 상태를 CLI와 로컬 콘솔에 표시한다.
- `LAUNCHING` 상태는 Control Root 스냅샷에도 저장되어 별도 터미널의 `aia status`가
  실제 진행 상태를 보여준다.
- `LAUNCHING` 중 사용자 중지가 들어오면 이미 확인된 Process Identity가 있는
  관리 Root만 identity 검증 절차로 종료한다. PID만으로 종료하지 않는다.
- 실행 중 Hook Broker가 손실되면 `HOOK_BROKER_LOST`와 별도 보호 실패 종료 결과를
  기록하고, 보호 성공으로 해석할 수 없는 `FAILED_DEGRADED`로 종료한다.

## 검증

```text
pytest: 540 passed, 3 skipped, 2 warnings
AIA Core self-test: PASS
Release SHA-256: PASS
Clean wheel install: PASS
Local console assets: PASS
```

Symlink 통합 테스트 2건은 Windows 권한이 없으면 skip될 수 있으며, 환경 독립적인
Symlink/Junction/Reparse 거부 Unit Test는 항상 실행한다. Process Manager 통합
테스트 1건은 Windows 테스트 실행기의 Job Object 영향으로 skip될 수 있다.

## 사용 시작

```powershell
uv sync
uv run aia self-test
uv run aia setup
```

Codex에서 `/hooks`를 열어 AIA Hook을 직접 검토·신뢰한 뒤 다음을 실행한다.

```powershell
uv run aia hook verify
uv run aia doctor
uv run aia proof
```

`doctor`가 `ready=true`를 보고한 뒤에만 일반 Protected Run을 시작한다.

```powershell
uv run aia protect C:\workspace\my-project
```

## 제한

- 모든 Codex 도구·MCP·외부 Agent·수동 실행을 보호한다고 주장하지 않는다.
- Hook Trust는 사용자가 Codex `/hooks`에서 직접 검토·신뢰해야 한다.
- 정책 위반에 따른 Actual Codex destructive Process 자동 집행은 정상 제품 경로의
  보편적인 완료 보장으로 주장하지 않는다.
- Network Security, Database state, ACL/ADS와 대규모 Workspace SLA는 지원 범위 밖이다.

상세한 최신 검증 결과는 [현재 재검증 기록](../validation/CURRENT-REVALIDATION.md),
보안 주장 범위는 [제품 지원 범위](../PRODUCT-SUPPORT.md)와
[제한사항](../LIMITATIONS.md)에서 확인한다.
