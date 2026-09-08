# EPIC-002 보호 실행 세션

## 정의

AIA Session은 프로젝트 자체나 Agent 대화 세션이 아니라, 하나의 Workspace에 대해
AIA Protected Run을 시작한 시점부터 해당 보호 실행이 종료될 때까지의 보안 책임
단위다.

Workspace와 Session은 다르다. 동일 Workspace에서 여러 AIA Session이 반복될 수
있으며, Agent Native Session ID는 AIA Session ID와 별도로 보존한다.

## Session lifecycle

| 상태 | 다음 상태 |
|---|---|
| CREATED | PREPARING |
| PREPARING | READY, FAILED |
| READY | RUNNING, ABORTED, FAILED |
| RUNNING | COMPLETED, ABORTED, FAILED |
| COMPLETED | 없음 |
| ABORTED | 없음 |
| FAILED | 없음 |

Session Start는 AIA Protected Run 시작, Session ID 생성, Workspace 확정, Active
Policy 고정, Sensor 초기화, Checkpoint 준비, Agent identity 등록으로 구성된다.

Session End는 사용자 명시적 종료, Agent 보호 실행 정상 종료, AIA 강제 종료,
보호 보증을 지속할 수 없는 치명적 실행 실패다.

이번 EPIC에서는 Agent 실행, Policy Engine, Sensor, Enforcement, Recovery, Integrity,
API, GUI를 연결하지 않는다.
