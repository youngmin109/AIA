# MVP Claim Matrix

평가 ID: `eval-20260909T144119Z`
후보 코드 기준: `c5bd350`

| 영역 | 허용되는 주장 | 금지되는 주장 |
|---|---|---|
| Runtime Evidence | 지원 센서가 관찰한 Raw Evidence를 bounded 방식으로 보존한다 | 모든 실행을 포괄적으로 관찰한다 |
| Security Asset Policy | 검증·해결된 정책 객체에 대해 결정론적으로 평가한다 | 모든 환경의 모든 정책을 보장한다 |
| Attribution | 증거가 충분할 때만 `EXACT`를 산출한다 | `PROCESS`만으로 정확한 파일 Writer를 증명한다 |
| PreTool Blocking | 제품 계약과 결정론적 Hook bridge의 차단 결과를 표현한다 | Actual Codex의 모든 도구를 항상 fail-closed한다 |
| Post-action containment | 관리 대상 Process fixture의 실제 종료를 확인한다 | 사전 예방을 보장하거나 모든 subprocess를 종료한다 |
| PID/create_time | 등록된 managed tree에서 identity를 확인해 종료한다 | 임의 PID나 모든 시스템 프로세스를 종료한다 |
| SafeCheckpoint recovery | 유효 manifest가 있는 Workspace baseline을 복원한다 | 임의의 유효하지 않은 checkpoint나 GB 규모 성능을 보장한다 |
| SHA-256 integrity | 경로·존재·SHA-256 기준의 복원 후 검증을 수행한다 | 공격자에 대한 tamper-proof를 보장한다 |
| Evidence Bundle | staging·manifest·검증된 Result Bundle을 생성한다 | 서명되었거나 공격자가 수정할 수 없는 저장소라고 주장한다 |
| Actual Codex | Actual Codex 보호 실행의 정상 종료와 Bundle 생성은 검증했다 | Actual Codex의 `.env` 구조화 READ 차단이나 실제 Agent tree kill을 검증했다고 주장한다 |
| Fail-open limitation | Hook 실패가 계속 실행될 수 있음을 결과와 문서에 남긴다 | 모든 경로가 universally fail-closed하다고 주장한다 |
| PROCESS limitation | PROCESS 증거는 자동 종료하지 않는다고 주장한다 | Agent가 특정 파일을 작성했다고 주장한다 |

`LIMITATION`은 실패를 숨기지 않는 평가 결과다. 제한된 외부 인터페이스가 열리면 별도 평가에서 다시 검증해야 한다.
