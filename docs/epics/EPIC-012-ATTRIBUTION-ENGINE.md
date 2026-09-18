# EPIC-012 — Attribution Engine

## 목적

Attribution은 `NormalizedAction`이 AIA가 보호 중인 Agent와 얼마나 강하게 관련되는지를 증거 기반으로 판정한다.

```text
NormalizedAction + Raw Evidence + Process Context + Turn Window
→ AttributionResult
```

Attribution은 행위자를 귀속하는 증거 강도만 계산한다. Policy Decision, 위험도, 자동 종료 권한, Rollback 권한을 만들지 않는다.

## 공식 등급

공식 등급은 네 가지다.

```text
EXACT / PROCESS / TEMPORAL / UNKNOWN
```

`VERIFIED_PROCESS`, `LIKELY`, `HIGH`, `LOW` 같은 보조 등급이나 확률 점수는 사용하지 않는다. `UNKNOWN`은 실패가 아니라 근거가 부족하거나 충돌하는 경우의 정상적인 보안 결과다.

## EXACT의 의미와 조건

`EXACT`는 신뢰 가능한 직접 Agent Tool Evidence와 Canonical Action이 명확하게 연결되었다는 뜻이다. 다음 조건을 모두 만족해야 한다.

- Action이 직접 `AGENT_HOOK` 계보를 가짐
- `PRETOOL_REQUEST.ingress_verified == true`
- 입력과 Raw Evidence의 AIA Session이 일치함
- non-empty `tool_use_id`가 존재하고 Action과 Raw Evidence에서 일치함
- Command Action이면 `COMMAND_OBSERVED.parent_evidence_id`가 정확한 PreTool Record를 참조함
- 부모와 자식의 Session 및 Tool ID가 일치함
- Native Session ID와 Turn ID가 양쪽에 존재하면 서로 일치함
- 동일 Tool ID의 충돌 Evidence가 없음

`EXACT`는 Tool 요청 또는 시도가 Agent Tool Use에 직접 귀속된다는 의미다. 실제 Tool 실행 성공, 파일 변경 성공, Command exit code 성공, Policy Violation, Kill 허가를 의미하지 않는다.

특히 `PRE_ACTION EXACT`는 그대로 `PRE_ACTION`이다. Attribution이 Action Stage를 `POST_ACTION`으로 바꾸거나 실행 성공을 생성하지 않는다.

## Hook Trust와 AIA Spawn Provenance

Hook Trust와 Process Provenance는 별도 축이다.

```text
Hook Trust          = ingress_verified
Process Provenance  = AIA_SPAWNED_ROOT / PROTECTED_LAUNCHER
```

AIA가 Root Process를 직접 Spawn했다는 사실만으로 Hook Action을 `EXACT`로 올리지 않는다. 현재 Codex 경로의 Hook은 `ingress_verified=false`이므로 `tool_use_id`가 있어도 `HOOK_INGRESS_UNVERIFIED`와 함께 `UNKNOWN`이다.

## Direct Hook Command / File

명시적으로 지원된 `read_file` File Tool은 Trusted Hook 조건을 만족하면 `READ` Action으로 `EXACT`가 될 수 있다. `COMMAND_OBSERVED`는 부모 PreTool과 자식 계보가 모두 검증된 경우 `EXECUTE` Action으로 `EXACT`가 될 수 있다.

이 결과는 각각 다음만 주장한다.

```text
READ .env / PRE_ACTION
→ 해당 Agent Tool Use가 직접 요청됨

EXECUTE raw command / PRE_ACTION
→ 해당 Agent Tool Use에서 Command 요청이 직접 관찰됨
```

실제 실행 완료나 내부 Script 효과는 판단하지 않는다.

## Duplicate와 Tool ID 충돌

Raw Evidence의 duplicate/replay Record는 삭제하지 않는다. 동일 Tool ID와 동일한 의미의 반복 Record는 `EXACT` 판단을 막지 않지만 `duplicate_evidence_count`로 보존한다.

동일 Tool ID에 대해 Operation, canonical target, raw command, Native Session, Turn 정보가 다르면 `CONFLICTING_TOOL_IDENTIFIER`와 `UNKNOWN`으로 처리한다. 충돌하는 Record 중 하나를 임의로 정답으로 선택하지 않는다.

## Process Tree Association

`PROCESS`는 Action이 AIA가 검증한 Agent Process Tree의 실행 구간과 관련된다는 뜻이다. 특정 Process가 해당 파일의 Writer라는 뜻이 아니다.

Process 귀속에는 다음을 사용한다.

- Process Identity = PID + Process Create Time
- Protected Root Identity와 Raw `root_pid + root_create_time` 일치
- `ROOT` Process는 Root Identity 자체와 일치
- `DESCENDANT` Process는 Parent Identity를 따라 Protected Root까지 연결
- 검증된 Root/Tree context가 없으면 Process 귀속을 만들지 않음

PID만 사용하지 않는다. 같은 PID라도 Create Time이 다르면 다른 Process이며, PID reuse 이후의 관찰은 기존 Identity의 귀속 근거로 사용하지 않는다.

## Process Lifetime과 polling 한계

Raw `PROCESS_OBSERVED`의 최초 관찰 시각을 `first_observed_at`으로 기록하고, `PROCESS_EXIT_OBSERVED` 관찰 시각을 `exit_observed_at`으로 기록한다.

Exit 시각은 실제 OS 종료 순간이 아니라 해당 Identity가 더 이상 유효하지 않음을 AIA가 관찰한 시각이다. 따라서 Process Window는 polling으로 얻은 근사 구간이며 완벽한 실행 interval이라고 주장하지 않는다.

Filesystem Action이 최초 Process 관찰 이후이고 확정된 Exit 관찰 이전이면 Process Tree Association 후보가 된다. 이 결과의 limitation은 `PROCESS_TREE_ASSOCIATION_ONLY`다.

## Filesystem Action과 PROCESS

Filesystem Action은 Writer PID를 직접 제공하지 않는다. 따라서 검증된 Agent Process Tree의 관찰 Window와 시간상 겹치면 최대 `PROCESS`까지 가능하다.

```text
Agent Process Tree 관찰 구간
        +
Filesystem DELETE
        ↓
PROCESS_TREE_ASSOCIATION_ONLY
```

Filesystem Action을 `EXACT` Writer로 만들지 않는다. OS-level Writer Sensor 또는 동등한 더 강한 직접 근거는 후속 범위다.

## Competing Candidate와 Decoy Safety

`CompetingCandidate`는 명시적으로 알려진 다른 후보의 활동 구간이다. Action의 Session, 대상, 시간에 적용되는 경쟁 후보가 Agent Tree에 속하지 않으면 `COMPETING_CANDIDATE`와 `UNKNOWN`으로 강등한다.

Agent Process와 알려진 Decoy가 같은 대상과 시간에 겹치면 특정 Writer를 임의로 선택하지 않는다. 이로써 잘못된 `EXACT`를 생성하지 않는다. 알려진 경쟁 후보가 없다는 사실은 실제 경쟁 후보가 존재하지 않는다는 증명이 아니다.

## TEMPORAL과 TurnWindow

`TEMPORAL`은 직접 Hook이나 Process 근거가 부족하지만 명시적으로 제공된 Agent Turn Window 안에 Action timestamp가 포함된 경우에만 사용한다.

`TurnWindow`는 다음을 가진다.

- `turn_id`
- `aia_session_id`
- `started_at`, `ended_at`
- optional Agent Native Session ID
- optional supporting Evidence IDs

PreTool timestamp를 기준으로 ±2초 같은 Window를 만들지 않는다. Session 전체를 Turn Window로 부르지 않는다. 서로 다른 Turn Window가 동시에 겹치면 하나를 고르지 않고 `AMBIGUOUS_TURN_WINDOW`와 `UNKNOWN`으로 처리한다.

## UNKNOWN 주요 원인

- Hook ingress가 UNVERIFIED
- Session mismatch
- Native Session mismatch
- Tool ID 누락
- 동일 Tool ID의 conflicting target/operation/command
- malformed Hook lineage
- Root 또는 Process Identity mismatch
- PID reuse
- verified Process Tree 근거 부족
- 알려진 Competing Candidate
- 명시적 Turn Window 부족 또는 충돌
- 지원되지 않는 provenance

근거보다 강한 등급을 만들지 않는 것이 이 Engine의 핵심 안전 계약이다.

## AttributionResult와 Batch

`AttributionResult`는 `NormalizedAction`과 별도의 불변 객체다. Action ID, Session, Grade, Reason Code, 설명, supporting Evidence IDs, Tool/Turn/Native ID, Process Identity, 경쟁 후보, limitation, duplicate count를 보존한다.

`kill_authorized`, Policy Decision, Enforcement Action은 존재하지 않는다. 필요하면 `AttributedAction` wrapper로 Action과 결과를 함께 전달할 수 있지만 원본 Action은 수정하지 않는다.

`AttributionBatchResult`는 Action 순서를 `observed_at + evidence_ids + action_id`로 결정하고, 각 Grade count와 conflict/limitation을 보존한다. 한 Action의 Attribution 실패가 다른 Action 결과를 버리게 하지 않는다.

## Policy와 Enforcement 경계

Attribution은 `SecurityAssetPolicy`, `PolicyEffect`, `PolicyDecision`, `rule_id`를 읽지 않는다. Policy가 DENY이거나 Violation이어도 Attribution Evidence가 부족하면 `UNKNOWN`이다.

Attribution은 `CONTAIN`, `REFUSE`, `BLOCKED`, `TERMINATED`, `kill_authorized`를 생성하지 않는다. `PROCESS`는 자동 종료 권한이 아니며, Enforcement Gate는 후속 EPIC에서 Policy·Attribution·Identity·Session·Sensor·Lease·Stage를 독립적으로 검증한다.

## 현재 Claim과 제한

이번 EPIC으로 다음을 주장할 수 있다.

> AIA는 Canonical Action을 직접 Hook 식별자와 Hook Trust, AIA-spawned Process Tree, Process 관찰 구간, 명시적 Turn Window 등의 증거를 사용해 EXACT / PROCESS / TEMPORAL / UNKNOWN으로 보수적으로 귀속한다.

아직 다음을 주장하지 않는다.

- 모든 File Writer를 정확히 식별함
- Process Action이 특정 파일을 썼음을 증명함
- Process 결과로 자동 종료할 수 있음
- 현재 실제 Codex Hook을 Trusted EXACT로 검증함
- 시간상 겹친다는 이유만으로 Agent가 했다고 확정함
- Attribution만으로 Policy Violation을 결정함

새 Dependency는 추가하지 않았다. Policy Runtime Evaluation, Enforcement, Process Termination, Recovery, Rollback, Integrity, Network Attribution, LLM Attribution, API, GUI, Canonical Action durable DB는 구현하지 않았다.
