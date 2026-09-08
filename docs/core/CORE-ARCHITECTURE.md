# AIA 제품 핵심 아키텍처 기준선

## 문서 목적

이 문서는 EPIC-001에서 확정하는 제품 핵심 책임, 공식 상태 모델, Security Authority
흐름을 기록한다. P0 코드를 제품 Repository로 복사하거나 이 책임에 맞춘 Python
package/class를 이번 EPIC에서 생성하지 않는다. 현재 산출물은 구조 이해와 책임
계약이며, 구현은 후속 EPIC에서 각 계약과 테스트를 확정한 뒤 진행한다.

## 제품 상위 흐름

제품의 권위 있는 흐름은 다음과 같다.

Raw Evidence
→ Normalization
→ Canonical Action
├→ Policy Evaluation
└→ Attribution
↓
Enforcement Gate
↓
Enforcement Execution
↓
Recovery
↓
Integrity
↓
Audit

Policy Evaluation과 Attribution은 Canonical Action에서 독립적으로 분기한다. Policy는
“관찰된 행위가 정책을 위반했는가?”를 판단하고, Attribution은 “그 행위를 Agent에게
어느 수준까지 귀속할 수 있는가?”를 판단한다. 어느 한쪽이 다른 쪽의 결과를
덮어쓰지 않는다.

실행 session은 이 흐름 전체를 묶지만, 각 단계가 다른 단계의 책임을 대신하지
않는다. 특히 Evidence 수집이 Enforcement 권한을 만들지 않고, Policy Violation이
그 자체로 process termination을 의미하지 않는다.

## 보호 실행 세션 (Protected Run Session)

AIA 세션은 프로젝트 자체나 Agent 대화 세션이 아니라, 사용자가 하나의 Workspace에
대해 AIA 보호 실행을 시작한 시점부터 해당 보호 실행이 종료될 때까지의 보안 책임
단위이다.

Workspace != Session

동일 Workspace에서 여러 AIA Session이 반복될 수 있다. 보호 실행을 종료하지 않고
계속 유지하는 경우 장시간 작업도 하나의 Session일 수 있다. Agent Native Session과
AIA Session ID는 별도로 관리한다.

### Session Start

- AIA Protected Run 시작
- Session ID 생성
- Workspace 확정
- Active Policy 고정
- Sensor 초기화
- Checkpoint 준비
- Agent identity 등록

### Session End

- 사용자 명시적 종료
- Agent 보호 실행 정상 종료
- AIA 강제 종료
- 보호 보증을 지속할 수 없는 치명적 실행 실패

프로젝트 기간이나 파일 수·용량 자체는 Session 경계를 결정하지 않는다. 대규모
Workspace의 Snapshot/Checkpoint 성능 문제는 Session 정의가 아니라 Scalability
문제로 분리한다.

## Network Observation Scope

Network Security는 현재 MVP Out of Scope이다. P0에 network telemetry가 존재한다는
사실은 Inventory에 보존하지만, Network Evidence를 새 Product Core의 Security
Authority나 MVP 보호 범위로 정의하지 않는다.

필요한 network observation은 Legacy / Optional Telemetry / Future Scope로 취급한다.
Network Evidence만으로 제품의 보안 Claim을 만들지 않으며, Network Evidence만으로
Policy Violation, Enforcement, Recovery 권한을 만들지 않는다.

## 핵심 구성요소와 책임

### 1. 실행 세션 관리자 (Session Manager)

- **책임**: 하나의 보호 실행에 session ID와 turn 경계를 부여하고, workspace·Agent·mode·정책·lease·센서·결과의 lifecycle을 조정한다. 실행 중단과 실패도 정상적으로 기록한다.
- **주요 입력**: 사용자 실행 요청, Agent 선택, workspace, prompt, mode, policy reference, resume/session 정보.
- **주요 출력**: session context, turn context, lifecycle transition, durable run state, 최종 evidence/result bundle.
- **앞/뒤 관계**: 모든 구성요소의 앞에서 공통 식별자와 실행 경계를 제공한다. 마지막에는 Recovery·Integrity·Report 결과를 받아 하나의 session 결과로 확정한다. Session Manager 자체는 Policy 판정을 하지 않는다.

### 2. 증거 수집기 (Evidence Collector)

- **책임**: Hook/PreTool 요청·응답, command telemetry, process observation, filesystem watcher, snapshot 차이 등 관찰 가능한 사실을 원시 형태로 보존한다. Network telemetry는 선택적 미래 관찰로만 보존할 수 있다.
- **주요 입력**: Agent Hook stream, Agent output/JSONL, OS process observation, workspace filesystem event, snapshot manifest. Network telemetry는 선택적 미래 입력이다.
- **주요 출력**: append-only raw evidence records, source metadata, capture timestamp, session/turn correlation, sensor health/error record.
- **앞/뒤 관계**: Session Manager가 수집 범위와 ID를 제공하고, Collector는 Normalizer로 전달한다. Collector는 evidence를 저장할 뿐 policy decision이나 kill 권한을 만들지 않는다.

### 3. 행위 정규화기 (Normalizer)

- **책임**: 서로 다른 센서 기록을 canonical action으로 변환한다. operation, target, path, command, session, turn, evidence source, stage, timestamp를 동일한 표현으로 맞춘다.
- **주요 입력**: raw Hook record, FileEvent, process evidence, snapshot diff, command telemetry. Network telemetry는 MVP Security Authority 입력이 아니다.
- **주요 출력**: NormalizedAction, canonical path, operation type, evidence source set, completeness indicator, 원시 record 참조.
- **앞/뒤 관계**: Evidence Collector 뒤에서 동작하고 Canonical Action을 Policy Evaluation과 Attribution에 병렬로 전달한다. 정규화는 의미론적 효과나 행위자 권한을 추론하지 않는다.

### 4. 행위 귀속 엔진 (Attribution Engine)

- **책임**: action이 Agent의 어떤 session/turn/tool과 관련되는지 증거 강도에 따라 보수적으로 귀속한다.
- **주요 입력**: normalized action, Hook supplied session/turn/tool_use ID, turn windows, process identity/lifetime, watcher event timestamp.
- **주요 출력**: attribution grade EXACT, PROCESS, TEMPORAL, UNKNOWN, attribution reason, process identity facts, competing candidate information.
- **앞/뒤 관계**: Normalizer 뒤에서 Policy Evaluation과 병렬로 동작하고, 결과를 Enforcement Gate에 전달한다. 정확한 Hook identifier가 있으면 EXACT 후보가 되지만, process 생존 구간이나 시간 겹침만으로 EXACT를 만들지 않는다. 여러 후보나 불일치는 UNKNOWN으로 남긴다.

### 5. 정책 관리자 / 정책 판정 엔진 (Policy Manager / Policy Engine)

- **책임**: validated v1 Security Asset Policy를 로드하고 asset, operation, path/command evidence, evidence completeness, stage를 기준으로 정책 적합성을 판정한다.
- **주요 입력**: 정책 문서와 schema, Canonical Action, evidence source/complete 상태, PreTool 또는 post-execution stage.
- **주요 출력**: policy decision COMPLIANT/VIOLATION/INDETERMINATE, matched rule IDs, asset type, operation effect, limitation, audit record flag.
- **앞/뒤 관계**: Attribution과 독립적으로 정책만 평가하고 결과를 Enforcement Gate로 전달한다. 같은 validated policy를 PreTool과 Runtime에 사용한다. 필수 evidence가 없으면 INDETERMINATE이며, Attribution 등급 때문에 이미 관찰된 VIOLATION을 COMPLIANT로 낮추지 않는다. Intent/Risk advisory는 이 판정을 대체하지 않는다.

### 6. 강제조치 안전문 (Enforcement Gate)

- **책임**: Policy 결과를 실제 조치 승인으로 변환하기 전에 attribution, owned process identity, session verification, sensor health, lease와 evidence stage를 독립적으로 확인한다. Gate 자체는 실제 process를 종료하지 않는다.
- **주요 입력**: PolicyEvaluation, attribution grade, process identity, session/turn verification, sensor health, workspace lease, evidence stage, optional checkpoint availability.
- **주요 출력**: enforcement decision CONTINUE/CONTAIN/REFUSE, 실행 경로와 승인 근거, 실패한 gate check와 사용자 검토 사유. BLOCKED/TERMINATED는 실제 실행 확인 뒤에만 기록한다.
- **앞/뒤 관계**: Policy Evaluation과 Attribution 뒤에 있고 PreTool Adapter 또는 Process Manager 앞에 선다. Gate가 승인한 뒤 실행 경로가 실제 조치를 수행한다. Checkpoint는 containment의 필수 전제가 아니며 Recovery 가능성을 별도로 결정한다.

#### Gate 이후의 Enforcement Execution 책임

Enforcement Execution은 Gate의 결정을 실제 adapter 또는 manager 결과로 확정하는
책임이다. 실행 전 조치는 PreTool Adapter가 실제 deny를 확인해야 BLOCKED로 기록하고,
실행 후 조치는 Process Manager가 managed process termination을 확인해야 TERMINATED로
기록한다. Gate의 CONTAIN 승인만으로 어느 action도 기록하지 않는다.

Process termination에는 실패할 수 있으므로 별도의 execution result를 보존한다.
최소 결과는 NOT_ATTEMPTED, SUCCEEDED, FAILED이며, FAILED인 경우 failure reason과
대상 process 결과를 남긴다. 예를 들어 Gate가 CONTAIN을 승인했지만 종료에 실패하면
TERMINATED를 주장하지 않고 Enforcement Decision은 CONTAIN, Action은 NONE, Execution
Result는 FAILED가 될 수 있다.

### 7. 프로세스 관리자 (Process Manager)

- **책임**: AIA가 시작한 process와 그 자식 tree의 lifecycle을 관리하고, 등록된 process identity에 대해서만 종료를 수행한다.
- **주요 입력**: Agent command, session ID, cwd, stdout/stderr 경로, Enforcement Gate의 terminate request.
- **주요 출력**: managed process identity (pid, create_time), process status, termination result, terminated/already-exited/failed PID 목록.
- **앞/뒤 관계**: Session Manager가 시작을 요청하고 Evidence Collector가 process 상태를 관찰한다. Enforcement Gate의 승인 뒤에만 종료한다. PID 숫자만으로 Process Identity를 확정하지 않는다.

### 8. 체크포인트 관리자 (Checkpoint Manager)

- **책임**: 복구에 사용할 workspace baseline을 안전하게 만들고 valid checkpoint와 trusted manifest를 관리한다.
- **주요 입력**: project root, protected workspace, session ID, 포함·제외 경로 정책.
- **주요 출력**: immutable checkpoint path, fixed file manifest, checkpoint validity와 생성 상태.
- **앞/뒤 관계**: Session Manager가 실행 전 또는 정책이 정한 시점에 요청한다. Recovery Coordinator가 valid checkpoint 여부를 확인한다. Checkpoint 생성 여부는 Containment 승인 조건이 아니며, valid checkpoint가 없으면 Rollback만 RECOVERY_UNAVAILABLE이 된다.

### 9. 복구 조정기 (Recovery Coordinator)

- **책임**: 성공적으로 종료된 managed process와 valid checkpoint를 기준으로 workspace 복구를 조정하고, 복구 가능·거부·실패를 분리한다.
- **주요 입력**: Enforcement Action, KillResult, valid checkpoint, trusted manifest, workspace lease.
- **주요 출력**: Recovery status NOT_REQUIRED/RESTORED/REFUSED/FAILED/RECOVERY_UNAVAILABLE, restored paths, recovery reason.
- **앞/뒤 관계**: Enforcement Execution과 Process Manager 뒤에서 동작한다. valid checkpoint를 이용한 복원 실행이 완료되면 RESTORED를 기록하고, Integrity Verifier 결과는 별도 Integrity 축으로 기록한다.

### 10. 무결성 검증기 (Integrity Verifier)

- **책임**: checkpoint와 현재 또는 복구 후 workspace의 path set과 SHA-256을 비교해 복구 결과를 독립적으로 검증한다.
- **주요 입력**: fixed checkpoint manifest, current workspace manifest, snapshot layout, path safety result.
- **주요 출력**: integrity status NOT_CHECKED/VERIFIED/FAILED, missing/unexpected/changed paths, hash comparison details.
- **앞/뒤 관계**: Checkpoint Manager의 trusted manifest와 Recovery Coordinator의 restored workspace를 받는다. 결과는 Recovery Coordinator와 Report Generator로 돌아간다. Rollback 실행 완료만으로 VERIFIED를 선언하지 않는다.

### 11. 결과 보고기 (Report Generator)

- **책임**: 원시 evidence의 위치와 요약, policy decision, attribution, enforcement, recovery, integrity, sensor limitation을 사용자와 audit이 읽을 수 있는 결과로 만든다.
- **주요 입력**: session lifecycle, canonical actions, raw evidence references, PolicyEvaluation, EnforcementResult, Recovery status, Integrity result, advisory findings.
- **주요 출력**: durable JSON report, human-readable Markdown report, next steps와 limitation, evidence bundle location.
- **앞/뒤 관계**: 모든 단계 뒤에서 최종 결과를 소비한다. 보고는 권한을 만들지 않으며, Agent self-report는 Security Evidence로 승격하지 않는다.

## 공식 상태 모델

코드에서 사용하는 상태값은 영어를 유지하고, 설명과 해석은 한국어를 우선한다.
서로 다른 상태 축을 하나의 verdict 문자열에 겹쳐 쓰지 않는다.

### 정책 판정 (Policy Decision)

| 상태값 | 의미 |
|---|---|
| COMPLIANT | 관찰된 operation이 적용 정책을 준수한다. 필수 evidence가 충분할 때만 사용한다. |
| VIOLATION | 적용 정책의 금지 또는 위반 rule과 일치한다. 이 상태만으로 종료 권한이 생기지 않는다. |
| INDETERMINATE | 필수 evidence가 부족하거나 증거가 불완전해 정책 준수 여부를 판정할 수 없다. COMPLIANT로 낮추지 않는다. |

### 강제조치 결정 (Enforcement Decision)

| 상태값 | 의미 |
|---|---|
| CONTINUE | 계속 실행한다. |
| CONTAIN | 현재 evidence와 identity 조건으로 자동 통제를 승인한다. |
| REFUSE | 자동 통제를 거부하고 evidence 보존과 사용자 검토로 넘긴다. |

### 강제조치 (Enforcement Action)

| 상태값 | 의미 |
|---|---|
| NONE | 실제 차단·종료 조치가 확인되지 않았다. |
| BLOCKED | PreTool Adapter의 실제 deny가 확인되었다. |
| TERMINATED | Process Manager가 managed process termination을 실제로 확인했다. |

### 강제조치 실행 결과 (Enforcement Execution Result)

Enforcement Execution Result는 Gate Decision과 Enforcement Action에서 독립된 상태
축이다. Gate 승인만으로 실제 Action을 기록하지 않는다.

| 상태값 | 의미 |
|---|---|
| NOT_ATTEMPTED | 승인된 실행 경로가 아직 실제 조치를 시도하지 않았다. |
| SUCCEEDED | 승인된 실행 경로가 요청된 조치를 성공적으로 수행했다. 이때 실행 유형에 따라 BLOCKED 또는 TERMINATED를 기록할 수 있다. |
| FAILED | 승인된 실행 경로가 조치를 시도했지만 실패했다. failure reason과 대상 결과를 보존한다. |

예를 들어 다음 조합은 유효하다.

Enforcement Decision = CONTAIN
Execution Result = FAILED
Enforcement Action = NONE

### 복구 상태

| 상태값 | 의미 |
|---|---|
| NOT_REQUIRED | 조치가 없거나 복구가 필요하지 않다. |
| RESTORED | valid checkpoint를 이용한 복원 실행 자체가 완료되었다. Integrity 성공을 의미하지 않는다. |
| REFUSED | 자동 복구 조건 또는 사용자 승인 조건이 부족해 복구하지 않았다. |
| FAILED | 복원 작업 자체를 시도했으나 완료하지 못했다. 예: 파일 복사 실패, 경로 복원 실패, 권한 오류, 복원 작업 실행 오류. |
| RECOVERY_UNAVAILABLE | valid checkpoint가 없거나 checkpoint 자체가 신뢰되지 않아 복구할 수 없다. |

### 무결성 상태

| 상태값 | 의미 |
|---|---|
| NOT_CHECKED | 아직 검증하지 않았거나 검증을 수행할 조건이 없었다. |
| VERIFIED | expected path set과 SHA-256이 일치한다. |
| FAILED | missing, unexpected, changed path 또는 검증 오류가 있다. |

Recovery와 Integrity는 독립된 상태 축이므로 다음 조합을 표현할 수 있다.

| Recovery | Integrity | 의미 |
|---|---|---|
| RESTORED | VERIFIED | valid checkpoint 복원 실행과 expected path/existence/SHA-256 검증이 모두 성공했다. 제품 전체의 “검증된 복구 성공”은 이 조합에서만 사용한다. |
| RESTORED | FAILED | valid checkpoint 복원 실행은 완료되었지만 복원 후 expected path/existence/SHA-256 검증에 실패했다. 검증된 복구 성공으로 보고하지 않는다. |

### 정상적인 상태 조합

다음 조합은 실제 실행 결과까지 확인된 정상적인 fail-closed 결과다. Gate의 CONTAIN
승인만으로 BLOCKED 또는 TERMINATED를 기록하지 않는다.

| Policy Decision | Attribution | Enforcement Decision | Enforcement Action | 의미 |
|---|---|---|---|---|
| VIOLATION | PROCESS | REFUSE | NONE | 정책 위반은 확인했지만 Agent 행위라고 자동 종료할 만큼 충분히 귀속되지 않았다. 자동 통제는 수행하지 않고 evidence를 보존하며 사용자 검토를 요청한다. |
| VIOLATION | EXACT | CONTAIN | TERMINATED | 정책 위반과 Agent 행위가 충분히 확인되었고, Gate 승인 후 실제 managed process termination이 확인되었다. 이후 valid checkpoint가 있으면 복구와 Integrity Verification을 별도로 진행한다. |

실행 전 EXACT 위반은 VIOLATION → CONTAIN → BLOCKED가 될 수 있다. COMPLIANT이면
CONTINUE → NONE이 정상이며, INDETERMINATE는 evidence 부족을 기록하고 자동 종료하지
않는다.

## Security Authority 흐름

1. Agent Hook, workspace watcher, process observer, command telemetry는 사실을 수집한다. Network telemetry는 선택적 미래 관찰이며 MVP Security Authority가 아니다. Raw evidence와 Agent self-report는 Security Authority가 아니다.
2. Normalizer는 서로 다른 source를 Canonical Action으로 묶는다. 이 단계는 증거 표현만 통일하고 위반·종료를 결정하지 않는다.
3. Canonical Action에서 Policy Evaluation과 Attribution이 독립적으로 분기한다.
4. Policy Evaluation은 “관찰된 행위가 정책을 위반했는가?”를 판단한다. 필수 Evidence가 부족한 경우에만 INDETERMINATE이며, 충분히 관찰된 VIOLATION을 Attribution 등급 때문에 COMPLIANT로 낮추지 않는다.
5. Attribution은 “그 행위를 Agent에게 어느 수준까지 귀속할 수 있는가?”를 EXACT, PROCESS, TEMPORAL, UNKNOWN으로 판단한다. PID 하나나 시간 겹침 하나만으로 EXACT를 만들지 않는다.
6. Enforcement Gate는 Policy 결과와 Attribution 결과를 함께 받아 identity/session/sensor/lease/stage를 대조한다. VIOLATION만으로는 CONTAIN하지 않는다.
7. Gate가 CONTAIN을 승인해도 실제 Action은 기록하지 않는다. PreTool Adapter의 실제 deny가 확인될 때 BLOCKED, Process Manager의 실제 managed process termination이 확인될 때 TERMINATED를 기록한다.
8. PROCESS, TEMPORAL, UNKNOWN은 자동 termination 권한을 갖지 않는다. 위반이면 REFUSE/NONE으로 기록하고 raw evidence, 귀속 이유, 사용자 검토 사유를 보존한다.
9. Policy Violation alone != Kill을 모든 구현과 보고서에 적용한다.
10. Checkpoint는 Containment의 필수 전제조건이 아니다. valid checkpoint가 있을 때만 Rollback을 수행한다.
11. Rollback 이후 Integrity Verification은 필수다. 복원 실행 완료는 RESTORED로 기록할 수 있지만, 제품 전체의 검증된 복구 성공은 RESTORED + VERIFIED일 때만 보고한다.

이를 상태 흐름으로 쓰면 다음과 같다.

Raw Evidence
→ Normalization
→ Canonical Action
├→ Policy Evaluation
└→ Attribution
↓
Enforcement Gate
↓
Enforcement Execution
↓
Recovery
↓
Integrity
↓
Audit

여기서 Recovery Status와 Integrity Status는 Enforcement Action과 별도 축이다. 예를
들어 TERMINATED + RECOVERY_UNAVAILABLE + NOT_CHECKED는 유효한 상태이며, checkpoint가
없다는 이유로 containment 승인을 소급해 취소하지 않는다.

## 변경하지 않는 Security Invariant

- EXACT → automatic containment authority 가능
- PROCESS / TEMPORAL / UNKNOWN → automatic termination 금지, evidence 보존 및 사용자 검토
- Policy Violation alone != Kill
- PID 단독으로 Process Identity를 확정하지 않는다.
- Checkpoint는 Containment의 필수 전제조건이 아니다.
- Rollback은 valid checkpoint가 있을 때만 수행한다.
- Rollback 이후 Integrity Verification은 필수다.
- 필수 Evidence가 부족하면 COMPLIANT로 판정하지 않는다.
- Agent Self-report는 Security Evidence가 아니다.

## Intent / Risk Layer의 제품 위치

P0의 Intent/Risk Layer는 raw prompt와 행동 pattern을 이용해 사용자의 의도 범위,
금지 operation, shell effect, sensitive target, sequence risk를 추정한다. 이 정보는
사용자에게 “왜 검토가 필요한가”를 설명하고, action을 정렬하고, advisory 경고를
만드는 데 유용하다.

그러나 prompt 해석은 heuristic이고 Agent가 실제로 무엇을 했는지의 Security Evidence가
아니다. 따라서 새 제품에서는 다음 경계를 고정한다.

- Intent/Risk 결과는 Advisory Finding으로 저장할 수 있다.
- v1 Security Asset Policy가 COMPLIANT이면 Legacy Risk 결과만으로 BLOCKED 또는 TERMINATED를 만들지 않는다.
- Legacy Risk가 위험 신호를 내더라도 v1 Policy, Attribution, Enforcement Gate가 별도로 승인하지 않으면 자동 통제를 수행하지 않는다.
- Policy가 VIOLATION이어도 attribution이 PROCESS/TEMPORAL/UNKNOWN이면 자동 종료하지 않는다.
- 기존 ALLOW/FLAG/KILL 상태는 제품 공식 COMPLIANT/VIOLATION/INDETERMINATE 및 CONTINUE/CONTAIN/REFUSE와 직접 같은 값으로 취급하지 않는다. 필요한 mapping은 후속 구현 EPIC에서 명시한다.

## 구현 경계

이번 EPIC에서 생성하거나 수정한 것은 공식 문서뿐이다. 다음을 생성하지 않는다.

- 새로운 Python package/class
- Policy Engine, Watchdog, Hook, Attribution Engine, Process Monitoring
- Enforcement, Checkpoint, Rollback, Recovery 구현
- API, GUI, Claude Adapter
- 새로운 dependency
- 기존 P0 코드 복사본

세부 module boundary, persistence schema, API contract, concurrency policy는 이 문서를
바탕으로 향후 EPIC에서 테스트 가능한 요구사항을 확정한 뒤 결정한다.

## 기준선에서 확인한 구조적 문제

1. P0 Repository 하나에 제품 실행 코드, 평가 oracle, simulator, 실제 Agent harness, UI가 함께 있어 package 경계와 검증 경계가 일치하지 않는다.
2. orchestrator.py의 POC lifecycle과 mvp.py의 제품형 lifecycle이 병존해 Session 상태와 결과 bundle의 단일 source of truth가 없다.
3. 기존 Intent/Risk의 ALLOW/FLAG/KILL과 v1 Policy의 COMPLIANT/VIOLATION/INDETERMINATE, CONTINUE/CONTAIN/REFUSE가 함께 존재해 상태 의미를 잘못 연결할 위험이 있다.
4. 현재 P0 RecoveryStatus에는 VERIFIED가 있지만 제품 공식 모델에서는 복구 완료 의미를 RESTORED로 분리한다. 무결성의 VERIFIED와 복구의 RESTORED를 같은 값으로 저장하면 보고가 모호해진다.
5. Watchdog와 Runtime Observer는 process/temporal evidence를 제공하지만 opaque script 내부의 파일 writer를 항상 EXACT로 만들 수 없다. 실제 destructive probe의 PROCESS → REFUSE/NONE은 이 경계를 확인했다.
6. Process Manager의 PID/create_time 검증은 AIA가 소유한 process tree의 identity 보호에는 유용하지만 파일 변경의 실제 writer identity를 단독으로 증명하지 않는다.
7. command pattern은 EXECUTE의 lexical evidence에 머물러야 한다. 문자열 일치만으로 script 내부 효과나 DB 상태 변경을 확인했다고 주장할 수 없다.
8. P0에는 PreTool legacy policy와 v1 policy가 모두 있어, 같은 행동에 대해 사전 경고·차단과 runtime 판정이 서로 다른 권위로 판단될 가능성이 있다.
9. 결과가 raw JSONL, run-state, result bundle, security report로 나뉘어 있어 후속 MVP에서는 원시 기록과 canonical 결과 사이의 commit/조회 계약을 별도로 고정해야 한다.
10. Evaluation ground truth와 구현 회귀 테스트가 같은 Repository에 있어 source 변경이 평가 기준을 우연히 함께 바꾸지 않도록 새 MVP에서는 평가 자산을 명시적으로 격리해야 한다.
