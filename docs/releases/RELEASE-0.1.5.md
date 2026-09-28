# AIA 0.1.5 Release Readiness

0.1.5는 0.1.4의 고아 실행 확인 기능을 확장해, AIA가 비정상 종료된 뒤 이전
Protected Run의 Agent Root가 정리되지 않은 Workspace를 새 실행이 자동으로
재사용하지 못하게 하는 안전성 보강 릴리스다.

## 추가된 동작

- 새 Protected Run을 만들기 전에 같은 Workspace의 이전 실행 상태를 확인한다.
- AIA 조정 프로세스가 사라졌고 기록된 Agent Root가 아직 살아 있거나 신원을
  확인할 수 없으면 새 실행을 거부한다.
- Agent Root가 사라진 경우에도 `aia reconcile <SESSION_ID>`가 먼저 완료되어야
  같은 Workspace를 다시 사용할 수 있다.
- 이미 정리 확인된 실행은 Evidence와 Result Bundle을 보존한 채 새 실행을 허용한다.

```powershell
uv run aia status <SESSION_ID>
uv run aia reconcile <SESSION_ID>
uv run aia protect C:\workspace\my-project
```

이 보호는 두 Codex 실행이 같은 Workspace에서 동시에 변경을 일으키는 상황을
자동으로 허용하지 않기 위한 것이다. AIA는 확인되지 않은 이전 Agent를 자동으로
종료하지 않으며, 이전 실행을 성공으로 바꾸지도 않는다.

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
전체 pytest: 552 passed, 3 skipped, 2 warnings
uv lock --check: PASS
정적 compileall: PASS
```

## 제한

- 모든 Codex 도구·MCP·외부 Agent·수동 실행을 보호한다고 주장하지 않는다.
- Hook Trust는 사용자가 Codex `/hooks`에서 직접 검토·신뢰해야 한다.
- 이전 AIA 상태에 Coordinator 또는 Agent Root 신원이 없으면 자동으로 안전하다고
  결론 내리지 않는다.
- 정책 위반에 따른 Actual Codex destructive Process 자동 집행은 정상 제품 경로의
  보편적인 완료 보장으로 주장하지 않는다.
- Network Security, Database state, ACL/ADS와 대규모 Workspace SLA는 지원 범위 밖이다.
