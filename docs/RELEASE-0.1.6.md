# AIA 0.1.6 Release Readiness

0.1.6은 보호 실행 결과를 사용자가 정확히 해석할 수 있도록 결과 계약과 화면을
보강한 릴리스다. 정책 판정, 정책 효과, Enforcement 결정, 실제 Action, 실행 결과를
서로 다른 축으로 표시하고, Recovery와 Integrity를 독립 상태로 계속 보존한다.

## 추가된 동작

- Result Bundle의 행위 결과에 `operation_effect`를 보존한다.
- `COMPLIANT / VIOLATION / INDETERMINATE` 정책 판정과
  `ALLOW / AUDIT / DENY` 정책 효과를 구분한다.
- CLI와 로컬 콘솔에 전체 행위·차단·실행 성공·실패 집계를 표시한다.
- `RESTORED + VERIFIED`만 검증된 복구 성공으로 설명한다.

```powershell
uv run aia self-test
uv run aia doctor
uv run aia protect C:\workspace\my-project
```

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
전체 pytest: 554 passed, 3 skipped, 2 warnings
uv lock --check: PASS
정적 compileall: PASS
릴리스 SHA-256: PASS
clean wheel 설치: PASS
로컬 콘솔 assets: PASS
```

## 제한

- 모든 Codex 도구·MCP·외부 Agent·수동 실행을 보호한다고 주장하지 않는다.
- Hook Trust는 사용자가 Codex `/hooks`에서 직접 검토·신뢰해야 한다.
- 정책 위반에 따른 Actual Codex destructive Process 자동 집행은 보편적으로 검증하지 않았다.
- Network Security, Database state, ACL/ADS와 대규모 Workspace SLA는 지원 범위 밖이다.
