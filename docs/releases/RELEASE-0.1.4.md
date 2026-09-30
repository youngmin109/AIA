# AIA 0.1.4 Release Readiness

0.1.4는 0.1.3의 보호 범위와 보안 주장을 유지하면서 AIA가 비정상 종료된 뒤에도
이전 Protected Run의 상태를 숨기지 않고 확인할 수 있게 한 안정성 보강 릴리스다.

## 추가된 동작

- Protected Run 상태에 AIA 조정 프로세스의 PID와 프로세스 생성 시각을 기록한다.
- AIA가 사라진 non-terminal 실행은 `ORPHANED_DEGRADED`로 표시한다.
- 실행 중 기록된 Agent Root가 있으면 PID와 생성 시각을 다시 확인한다.
- Agent Root가 실제로 사라진 경우에만 다음 명령으로 정리 확인을 남긴다.

```powershell
uv run aia status <SESSION_ID>
uv run aia reconcile <SESSION_ID>
```

`reconcile`은 Evidence와 Result Bundle을 삭제하지 않고, 고아 실행을 성공한 보호
실행으로 바꾸지 않는다. Agent Root가 살아 있거나 신원을 확인할 수 없으면 정리를
거부한다.

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

## 검증 기준

```text
전체 pytest: 550 passed, 3 skipped, 2 warnings
uv lock --check: PASS
정적 compileall: PASS
```

Symlink 관련 통합 테스트와 Windows 테스트 실행기의 Job Object 영향을 받는 Process
Manager 통합 테스트는 기존 조건에 따라 환경에서 skip될 수 있다. 환경 독립적인
거부 Unit Test는 항상 실행한다.

## 제한

- 모든 Codex 도구·MCP·외부 Agent·수동 실행을 보호한다고 주장하지 않는다.
- Hook Trust는 사용자가 Codex `/hooks`에서 직접 검토·신뢰해야 한다.
- 정책 위반에 따른 Actual Codex destructive Process 자동 집행은 정상 제품 경로의
  보편적인 완료 보장으로 주장하지 않는다.
- Network Security, Database state, ACL/ADS와 대규모 Workspace SLA는 지원 범위 밖이다.
