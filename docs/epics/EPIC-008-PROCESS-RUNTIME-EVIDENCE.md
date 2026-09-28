# EPIC-008 Process Runtime Evidence

## 목적

EPIC-008은 외부에서 명시적으로 등록된 Agent Root Process와 그 Descendant Process Tree를 `psutil`로 주기적으로 관찰하고 Raw Evidence로 보존하는 단계다.

이번 단계의 질문은 다음까지다.

> 등록된 Root Process와 Descendant Process가 Runtime에 실제로 존재했는가?

다음 질문에는 답하지 않는다.

- 특정 Process가 어떤 파일을 수정했는가
- 해당 Process가 정책을 위반했는가
- 해당 Process를 종료해야 하는가
- Process Evidence가 `Attribution.PROCESS` 또는 `EXACT`인가

```text
Process Runtime Evidence
≠ File Writer Attribution
≠ Policy Decision
≠ Termination Authority
```

## Dependency와 Identity

이번 EPIC에서 추가한 Runtime Dependency는 `psutil` 하나다. 기존 `watchdog`는 유지하며 P0의 runtime observer/process manager 코드를 복사하지 않는다.

PID만으로 Process Identity를 정의하지 않는다.

```text
ProcessIdentity = pid + create_time
```

같은 PID라도 create time이 다르면 PID reuse로 판단해 다른 Process다. `ProcessIdentity`와 검증 결과는 [process_identity.py](../../src/aia/process_identity.py)에 정의되어 있다.

검증 결과는 다음 네 가지다.

```text
LIVE_MATCH
PROCESS_GONE
PID_REUSED
OWNER_UNVERIFIABLE
```

`AccessDenied`, OS query failure, 신뢰할 수 없는 create time 조회 실패는 `OWNER_UNVERIFIABLE`로 처리한다. 이를 Process Gone으로 오판하거나 Sensor를 Healthy로 만들지 않는다.

## Root Process Registration

이번 단계에서는 Agent Launcher와 Codex 자동 탐색을 구현하지 않는다. 외부에서 다음 `RootProcessRegistration`을 제공해야 한다.

- `aia_session_id`
- `workspace`
- `root_process_identity`
- `registered_at`
- `registration_source`

Sensor는 임의 PID를 찾아 Agent라고 추정하지 않는다. 시작할 때 Session, Workspace, Lease, valid Checkpoint, Root registration을 모두 상관 검증하고 Root의 PID와 create time이 현재 Process와 일치하는지 확인한다.

Agent Process는 아직 시작 전이므로 Process Runtime Sensor의 구현·구성 준비 자체가 Capability다. 실제 Root가 없으면 Sensor를 시작할 수 없고, 그 사실 때문에 Session을 `READY`로 자동 전환하지 않는다.

## Raw Evidence 구조

기존 Session Evidence Stream을 재사용한다.

```text
<control_root>/sessions/<session-id>/evidence/raw-evidence.jsonl
```

새 Source와 Record Type은 다음과 같다.

```text
source      = PROCESS_RUNTIME
record_type = PROCESS_OBSERVED | PROCESS_EXIT_OBSERVED | SENSOR_HEALTH
```

`PROCESS_OBSERVED` payload에는 다음을 저장한다.

- `pid`
- `create_time`
- `ppid`
- `process_role` (`ROOT` 또는 `DESCENDANT`)
- `root_pid`
- `root_create_time`
- `observed_at` (UTC)
- 가능한 경우 `name`, `executable`
- `metadata_status`
- 검증된 경우 `parent_pid`, `parent_create_time`

전체 command line은 저장하지 않는다. Command와 Credential은 EPIC-007 Hook Command Evidence의 책임이다.

`PROCESS_EXIT_OBSERVED`는 이미 관찰한 Identity가 `NoSuchProcess` 또는 PID reuse로 더 이상 같은 Process가 아님을 확인했을 때 기록한다. Process가 polling 결과에서 한 번 보이지 않았다는 이유만으로 Exit를 확정하지 않는다.

## Process Tree

Root에서 시작해 직접 Child를 재귀적으로 탐색한다.

```text
ROOT
 └─ DESCENDANT
     └─ DESCENDANT
```

여러 세대의 Process를 지원하며, 각 Child의 PID와 create time을 확인한 뒤에만 Tree에 포함한다. OS 전체 Process를 수집하지 않으며, unrelated Process는 Session Evidence에 추가하지 않는다.

실행 중 전체 Process snapshot 조회에서 `NoSuchProcess`, `ZombieProcess` 또는 `ProcessLookupError`가 발생하면 해당 poll은 불완전하므로 observation이나 exit evidence를 기록하지 않고 다음 polling interval에 다시 시도한다. 처음 실패할 때 health evidence는 `HEALTHY/POLL_RETRY`로 기록하며, 다음 전체 poll이 성공한 뒤 `HEALTHY/POLL_RECOVERED`를 기록한다. 연속 3회 실패하면 health를 `FAILED/OWNER_UNVERIFIABLE`로 바꾸고 observer를 종료한다. 시작 시 같은 오류가 나거나 `AccessDenied`, `PermissionError` 및 다른 OS query 오류가 나면 재시도 가능한 race로 보지 않고 Sensor를 실패시킨다. Root identity가 `OWNER_UNVERIFIABLE`인 경우에도 retry하지 않는다.

Parent 관계는 검증된 경우에만 `parent_create_time`으로 보존한다. 확인하지 못한 Parent Identity를 추측해 채우지 않는다.

## Polling과 중복 관찰

기본 polling interval은 `0.25`초이며 테스트에서 변경할 수 있다. Sensor는 주기적으로 등록된 Root Tree를 다시 읽는다.

Polling snapshot은 OS Event가 아니므로 동일 Process Identity를 매 cycle마다 무한히 기록하지 않는다. 한 Session에서 동일 Identity의 최초 관찰만 `PROCESS_OBSERVED`로 저장한다. 새로운 Identity가 나타나면 새 Evidence를 추가한다.

Polling interval보다 짧게 생성되고 종료된 Process는 놓칠 수 있다. Sensor `HEALTHY`는 polling thread가 동작한다는 뜻이며, 모든 짧은 Process를 관찰했다는 뜻이 아니다. Sensor Health와 Observation Coverage를 구분한다.

## Process Exit와 Sensor Health

정상적인 Root 또는 Descendant 종료는 Process Exit Evidence다. Root 종료만으로 Session을 `COMPLETED`, `FAILED`, `ABORTED`로 자동 전환하지 않는다. Root 종료가 정상적으로 기록된 뒤 Sensor는 관찰 thread를 종료할 수 있지만, 이를 Sensor Failure로 바꾸지 않는다.

반대로 다음은 Sensor Failure다.

- Root Identity를 확인할 수 없음
- Process Evidence append 실패
- Process Exit Evidence append 실패
- observer thread의 치명적 오류
- bounded stop/join 실패

공통 Sensor lifecycle을 재사용한다.

```text
STARTING → HEALTHY → STOPPED
      └→ FAILED
HEALTHY ─→ FAILED
```

중복 start로 Thread 두 개를 만들지 않으며, stop/join은 bounded timeout을 사용한다. 자동 재시작은 구현하지 않는다.

## Metadata Partial Failure

PID와 create time이 검증되면 Process Identity 관찰은 유효하다. `name` 또는 `executable` 조회만 실패한 경우 전체 Sensor를 실패시키지 않고 해당 필드를 생략하며 `metadata_status = PARTIAL`로 기록한다.

PID 또는 create time 자체를 신뢰할 수 없으면 Identity를 Evidence로 기록하지 않는다. 핵심 Identity 조회 실패와 비핵심 Metadata 실패를 구분한다.

## 다른 Evidence와의 관계

Hook에서 `tool_use_id = T100`, `command = python delete.py`를 관찰하고 Runtime에서 `python.exe`를 관찰해도 이번 EPIC에서는 두 Record를 같은 행위라고 연결하지 않는다.

Runtime에서 Process가 살아 있고 Filesystem에서 파일 삭제가 관찰되어도 해당 Process가 파일 Writer라고 확정하지 않는다.

Normalizer와 Attribution Engine이 향후 Process lifetime, Hook correlation, Filesystem timestamp, competing candidates를 종합해 별도의 판단을 수행한다. Sensor는 `Attribution.PROCESS`, `EXACT`, Policy Decision을 생성하지 않는다.

## 범위 제외와 제품 Claim

이번 EPIC에서는 다음을 구현하지 않는다.

- Agent Launcher와 Codex 자동 탐색
- Process Manager, terminate, kill, taskkill
- Policy Runtime, Enforcement Gate
- Canonical Action, Normalizer, Attribution
- Recovery, Rollback, Integrity Verification
- Network Socket/DNS/Outbound Observation
- API, GUI, Claude Adapter

이번 결과로 주장 가능한 범위는 다음과 같다.

> AIA는 명시적으로 등록되고 PID와 Process Create Time으로 검증된 Root Process 및 Descendant Process를 주기적으로 관찰해 Session Raw Evidence로 보존할 수 있다.

다음은 주장하지 않는다.

- AIA가 Codex Process를 자동 식별한다.
- Process가 특정 파일의 Writer임을 증명한다.
- Process Tree 존재가 `EXACT` 또는 `PROCESS` Attribution이다.
- 모든 short-lived Process를 빠짐없이 탐지한다.
- Network Activity를 감시한다.

Process Capability가 준비되어도 실제 Agent Root Process가 실행되기 전에는 Runtime Tree를 관찰할 수 없다. 따라서 Session은 계속 `PREPARING`이며, 후속 EPIC-009 Readiness Barrier에서 준비 상태를 통합한다.
