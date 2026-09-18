# AIA Protected Run 실행 흐름과 용어 설명

## Protected Run 실행 흐름

1. 사용자가 Workspace 경로를 지정하면 AIA가 보호 실행의 독립적인 `Protected Run Session`을 생성한다.
2. AIA는 Workspace를 정규화하고 정책·Agent·실행 모드를 Session에 연결한다.
3. 정책은 Strict Validation 후 immutable Resolved Policy로 변환되어 실행 중 변경되지 않는다.
4. Workspace Lease는 동일 Workspace에 중복 보호 Session이 생성되지 않도록 소유권을 기록한다.
5. Checkpoint Manager는 실행 전 파일 경로·존재 여부·SHA-256 Manifest를 저장해 복구 기준점을 만든다.
6. File Sensor는 Workspace의 생성·수정·삭제·이동을 파일 시스템 Evidence로 수집한다.
7. 보호 준비가 완료되면 AIA가 `subprocess`로 Codex를 생성하고 PID와 `create_time`을 Root Identity로 등록한다.
8. Process Sensor는 등록된 Codex Root와 자식 프로세스 트리만 PID·생존 상태·생성 시각으로 관찰한다.
9. Codex의 PreTool 요청은 Hook을 통해 AIA로 전달되고, AIA는 명령·경로·도구 정보만 Raw Evidence로 보존한다.
10. Normalizer는 Hook·File·Process Evidence를 `Canonical Action`으로 통합한 뒤 Policy Evaluation과 Attribution을 독립적으로 수행한다.
11. Enforcement Gate는 정책 결과·귀속 수준·Session·Lease·Sensor 상태를 검증해 `CONTINUE`, `CONTAIN`, `REFUSE`를 결정한다.
12. 실제 차단·프로세스 종료·복구는 별도 실행기가 수행하고, AIA는 실제 성공 여부를 확인한 뒤 Enforcement·Recovery·Integrity·Audit 결과를 확정한다.

## 용어 주석

Protected Run Session[보호 실행 세션]: AIA가 하나의 Workspace를 보호하는 전체 보안 책임 단위.

Session[세션]: 보호 실행의 생성부터 종료까지를 식별하는 실행 단위.

Strict Validation[엄격한 검증]: 정책의 Key, 값, 구조를 모두 검사하고 오류를 허용하지 않는 과정.

immutable Resolved Policy[변경 불가능한 확정 정책]: 검증된 정책을 내부 객체로 변환해 실행 중 변경되지 않도록 고정한 정책.

Workspace Lease[Workspace 점유권]: 특정 AIA Session이 Workspace를 사용 중임을 기록해 중복 보호 실행을 방지하는 장치.

Checkpoint Manager[체크포인트 관리자]: 실행 전 Workspace 상태를 저장하고 이후 복구에 사용할 기준점을 관리하는 컴포넌트.

SHA-256 Manifest[SHA-256 파일 목록]: 파일별 경로, 존재 여부, 크기, SHA-256 해시를 기록한 기준 목록.

File Sensor[파일 센서]: Workspace의 파일 생성·수정·삭제·이동을 관찰하는 센서.

Evidence[증거]: AIA가 관찰한 실행 요청, 파일 변화, 프로세스 상태 등의 사실 기록.

subprocess[하위 프로세스 실행]: AIA가 운영체제 기능을 통해 Codex를 별도 프로세스로 생성하는 방식.

create_time[프로세스 생성 시각]: PID가 재사용되어도 원래 프로세스인지 구분하기 위한 생성 시각 정보.

Root Identity[루트 프로세스 식별자]: 관리 대상 Root Process를 식별하는 PID와 create_time의 조합.

Process Sensor[프로세스 센서]: Codex Root와 그 자식 프로세스의 생존 상태와 프로세스 트리를 관찰하는 센서.

Raw Evidence[원시 증거]: 변환이나 해석 전의 Hook·File·Process 관찰 기록.

Normalizer[정규화기]: 서로 다른 센서의 Raw Evidence를 공통된 행위 표현으로 변환하는 컴포넌트.

Hook·File·Process Evidence[Hook·파일·프로세스 증거]: 실행 직전 요청, 실제 파일 변화, 프로세스 상태를 각각 기록한 관찰 데이터.

Canonical Action[표준 행위]: 여러 Evidence를 통합해 표현한 `READ`, `MODIFY`, `DELETE`, `EXECUTE` 등의 공통 행위 모델.

Policy Evaluation[정책 평가]: Canonical Action이 현재 정책을 위반했는지 판단하는 과정.

Attribution[행위 귀속]: 관찰된 행위를 AIA가 관리하는 특정 Agent·Session에 어느 수준까지 연결할 수 있는지 판단하는 과정.

Enforcement Gate[강제조치 관문]: 정책 결과, 행위 귀속, Session, Lease, Sensor 상태를 확인해 실제 조치 가능 여부를 결정하는 컴포넌트.

Session·Lease·Sensor[세션·점유권·센서 상태]: 현재 실행이 올바른 Session인지, Workspace 사용권이 유효한지, 관찰 센서가 정상인지 확인하는 조건.

CONTINUE[계속]: 정책상 허용되며 실행을 계속하는 결정.

CONTAIN[격리·통제]: 실행을 제한하거나 도구 차단 또는 프로세스 종료를 시도하는 결정.

REFUSE[거부]: 필요한 보안 조건이 충족되지 않아 자동 조치를 승인하지 않고 사용자 검토로 넘기는 결정.

Enforcement[강제조치]: 실제 Hook 차단이나 관리 대상 프로세스 종료를 수행하는 실행 단계.

Recovery[복구]: 문제가 발생한 Workspace를 유효한 Checkpoint 상태로 되돌리는 단계.

Integrity[무결성 검증]: 복구 후 파일 경로, 존재 여부, SHA-256이 기준 Manifest와 일치하는지 확인하는 단계.

Audit[감사 기록]: 전체 실행의 Evidence, 정책 판정, 조치 결과, 복구 결과를 나중에 검토할 수 있도록 보존하는 단계.
