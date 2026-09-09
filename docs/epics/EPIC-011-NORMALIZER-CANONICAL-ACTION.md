# EPIC-011 — Normalizer / Canonical Action

## 목적

이 EPIC은 센서별 Raw Evidence를 AIA가 공통으로 처리할 수 있는 불변 `NormalizedAction`으로 변환한다.

```text
Raw Evidence
→ Normalization
→ Canonical Action
→ 후속 Attribution / Policy Evaluation
```

Raw Evidence는 관찰 사실이고, Canonical Action은 그 사실을 공식 Operation·Target·Stage·계보 형식으로 표현한 파생 객체다. Normalizer는 기계적이고 결정론적인 변환만 수행한다. Agent 귀속, 정책 위반, 위험도, 종료 권한, 실제 실행 성공 여부를 판단하지 않는다.

## 공식 Operation과 단일 Enum

공식 Operation은 `policy.Operation` 하나만 사용한다.

```text
READ / CREATE / MODIFY / DELETE / MOVE / RENAME / EXECUTE
```

`DOWNLOAD`, `INSTALL`, `DROP_TABLE`, `SECRET_READ`, `BULK_DELETE` 같은 의미론적 Operation은 추가하지 않는다. `normalizer.Operation`을 별도로 만들지 않았으며, 기존 Policy public contract를 유지한다.

## NormalizedAction

`NormalizedAction`은 `frozen=True`인 불변 Domain 객체다. 다음 사실을 보존한다.

- 결정론적 `action_id`
- AIA Session ID
- Operation, Observation Stage, Target Kind
- Workspace 기준 canonical path 또는 source/destination path
- Command 원문과 lexical normalized command
- Process Identity와 Root/Parent Identity
- Agent Native Session ID, turn ID, tool use ID가 Raw Evidence에 있을 때의 값
- 근거 Evidence ID와 Source
- 관찰 시각, completeness, limitation, normalizer version

Raw payload 전체는 복사하지 않는다. Action에는 정책 결과, Attribution grade, `kill_authorized`, Risk, Enforcement 결과를 넣지 않는다.

## Deterministic Action ID

Normalizer version, AIA Session ID, 근거 Evidence ID 순서, 해석 종류, interpretation ordinal을 canonical JSON으로 직렬화한 뒤 UUID5로 `action_id`를 생성한다. 같은 Raw Evidence와 같은 version은 다시 실행해도 같은 Action ID가 된다. Raw Evidence가 다르면 별도의 Action ID가 된다.

현재 version은 `canonical-v1`이다.

## Evidence Lineage와 불변성

모든 Action은 `evidence_ids`로 원본 Raw Evidence를 명시적으로 참조한다.

```text
PRETOOL_REQUEST P1
        ↓ parent_evidence_id
COMMAND_OBSERVED C1
        ↓
EXECUTE Action evidence_ids = [P1, C1]
```

Command 부모는 `parent_evidence_id`를 사용하고, 부모가 실제 `PRETOOL_REQUEST`인지, Session이 같은지, `tool_use_id`가 같은지를 검증한다. 검증할 수 없으면 Action을 조용히 삭제하지 않고 `PARTIAL`과 `COMMAND_PARENT_UNVERIFIED` limitation으로 남긴다.

Normalizer는 Raw Evidence를 수정·삭제·덮어쓰지 않는다. Raw Evidence Store의 append-only 원칙을 유지하며, NormalizedAction은 매번 Raw Evidence에서 재생성할 수 있는 파생 값이다.

## Path Canonicalization

Windows MVP의 lexical path 규칙을 사용한다.

- Workspace 기준 상대경로
- separator는 `/`
- case-insensitive semantics를 위해 casefold
- `.`와 redundant separator 정리
- lexical `..`가 Workspace 밖으로 나가면 거부
- 다른 drive, UNC, 외부 volume은 `OUTSIDE_WORKSPACE`
- 원본 path에 `Path.resolve()`나 파일시스템 symlink/reparse resolution을 적용하지 않음

Workspace 밖 Raw Evidence를 조용히 버리지 않는다. Action의 `canonical_path`를 `None`으로 하고 limitation과 `PATH_OUTSIDE_OR_INVALID` issue를 보존한다. 이 결과는 정상 Workspace 내부 Action이나 보안 판단으로 가장되지 않는다.

## Filesystem Event Mapping

Filesystem Raw Event는 다음과 같이 매핑한다.

```text
created  → CREATE
modified → MODIFY
deleted  → DELETE
moved    → MOVE 또는 RENAME
```

Filesystem Action은 기존 센서 계약에 따라 `POST_ACTION`이다. Filesystem Watcher가 `READ`를 생성하지 않는다. `is_directory`는 `FILE`과 `DIRECTORY` Target Kind 및 `target_is_directory`로 보존하며, 자식 삭제를 추론하지 않는다.

## MOVE / RENAME

`moved` Event는 source와 destination을 모두 보존한다.

```text
source parent == destination parent → RENAME
source parent != destination parent → MOVE
```

양쪽 path는 canonical case-insensitive lexical path다. 따라서 Windows case-only rename도 두 path를 버리지 않고 `RENAME`으로 표현한다. 어느 한쪽을 정책 Target으로 선택하는 의미는 이번 EPIC에서 정하지 않는다.

## Command Normalization

`COMMAND_OBSERVED`는 하나의 Raw command 전체를 하나의 `EXECUTE` Action으로 만든다.

- Stage는 `PRE_ACTION`
- `raw_command`는 원문 그대로 보존
- `normalized_command`는 EPIC-003의 `normalize_command`를 재사용
- shell parsing, command splitting, SQL parsing을 하지 않음
- `python reset_db.py`가 내부에서 무엇을 했는지 추론하지 않음
- `DROP TABLE`을 별도 Operation으로 만들지 않음

`PRETOOL_REQUEST`의 `command_observed=true`는 Command child가 있을 때 별도 `EXECUTE` Action으로 만들지 않는다. Raw command의 권위 있는 원본과 EXECUTE Action은 `COMMAND_OBSERVED`에서만 생성된다.

## Hook Tool Semantic Registry

확인된 EPIC-007 fixture의 명시적 계약만 registry에 등록한다.

| 정확한 `tool_name` | Operation | 필요한 구조화 필드 |
| --- | --- | --- |
| `read_file` | `READ` | `tool_input.path` |

이름의 substring이나 추측으로 Operation을 만들지 않는다. `inspect_secret`, `cleanup`, `read_file_backup` 같은 Tool은 `UNSUPPORTED_TOOL_SEMANTICS` issue가 되고 Action을 생성하지 않는다. 현재 `shell`은 직접 File Operation으로 매핑하지 않으며, raw command가 별도의 `COMMAND_OBSERVED`로 수집된 경우 그 Record에서 `EXECUTE`를 만든다.

## Process Evidence

`PROCESS_OBSERVED`는 Process Runtime에서 Process가 실행 상태로 관찰된 사실이므로 `EXECUTE`와 `PROCESS` Target으로 표현한다. PID만 보존하지 않고 Process Create Time을 포함한 Process Identity, Root Identity, 가능한 Parent Identity, Process Role, 이름과 executable을 선택적으로 보존한다.

이 Action은 특정 Hook Command의 성공을 뜻하지 않는다. 파일을 해당 Process가 수정했다거나 Process가 Agent 행동이라고 주장하지 않는다. Process command line은 EPIC-008 계약상 기본 저장 대상이 아니므로 raw command를 임의 생성하지 않는다. Runtime metadata가 불완전하면 `PARTIAL`로 남긴다.

`PROCESS_EXIT_OBSERVED`는 공식 7개 Operation이 아니므로 Action을 생성하지 않는다. `NON_ACTION_LIFECYCLE_EVIDENCE`로 Batch 결과에 보존한다. `SENSOR_HEALTH`도 사용자/Agent Action이 아니므로 `NON_ACTION_SENSOR_EVIDENCE`로 분리한다.

## Completeness

```text
COMPLETE  = 구조적 Action 표현에 필요한 사실이 충분함
PARTIAL   = Operation은 표현할 수 있으나 일부 Target/계보/metadata 부족
UNUSABLE  = 안전한 Action 표현을 만들 수 없음
```

Completeness는 Policy Evidence 충분성, Attribution 충분성, Security Authority를 의미하지 않는다. 예를 들어 정상적으로 수집된 Process Action이 `COMPLETE`여도 Agent 귀속이나 정책 위반을 뜻하지 않는다.

## Batch와 순서

`Normalizer`는 하나의 AIA Session을 기준으로 Batch를 처리한다. 다른 Session Record는 `SESSION_MISMATCH` issue로 남기고 현재 Session Action으로 만들지 않는다. 개별 Record 오류가 전체 Batch의 정상 Record를 잃게 하지 않으며, `NormalizationResult`에 Action·Issue·non-action Evidence와 각 count를 함께 반환한다.

결과 순서는 `captured_at`, `evidence_id`, `action_id` 기준으로 결정론적이다. 같은 tool ID나 같은 Filesystem Event가 반복되어도 이번 EPIC에서 Dedup나 Cross-Source Merge를 하지 않는다.

```text
Hook command + Process observation + Filesystem event
→ 각각 독립 Action
→ 인과관계/행위자 연결은 EPIC-012 Attribution 책임
```

## 경계와 현재 Claim

이번 구현으로 다음을 주장할 수 있다.

> AIA는 Filesystem, Hook, Command, Process Runtime Raw Evidence를 공통 Operation·Path·Command·Stage·Evidence Lineage를 가진 결정론적 Canonical Action으로 변환한다.

아직 다음을 주장하지 않는다.

- Agent 행동을 정확히 식별함
- Policy Violation이나 Policy Decision을 판정함
- 동일 Raw Event를 실제 행동으로 완벽하게 병합함
- Command 내부 효과나 Script/SQL 의미를 이해함
- Process와 File Event의 인과관계를 증명함
- Enforcement, 종료, Recovery, Rollback, Integrity를 수행함

새 Dependency는 추가하지 않았다. Attribution, Policy Evaluation, Enforcement, Network Action, API, GUI, Action durable DB는 후속 EPIC의 책임이다.
