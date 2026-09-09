# EPIC-007 Agent Hook / PreTool 및 Command Raw Evidence

## 목적

EPIC-007은 Agent가 Tool을 실행하려는 실행 전 요청을 Raw Evidence로 보존하는 단계다. Hook Sensor는 지원되는 `PRE_TOOL_USE` 입력을 검증하고 기록한다. 이 단계는 Policy Evaluation, Attribution, Allow/Deny, Enforcement를 수행하지 않는다.

```text
Agent Tool 요청
    ↓
PreTool Hook 관찰
    ↓
Raw Evidence
```

따라서 다음은 아직 알 수 없다.

- 정책 위반인지
- 어느 수준으로 Agent에 귀속되는지
- 실제 Tool이 실행됐는지
- 요청이 차단됐는지
- 명령이 성공했는지

## 기존 Evidence Store 재사용

Hook Evidence와 Command Evidence는 EPIC-006의 `RawEvidenceRecord`와 `RawEvidenceStore`를 재사용한다. 별도 저장소를 만들지 않으며, Filesystem Evidence와 같은 Session Evidence Stream에 append한다.

```text
<control_root>/sessions/<session-id>/evidence/raw-evidence.jsonl
```

새 Source와 Record Type은 다음과 같다.

```text
source       = AGENT_HOOK
record_type  = PRETOOL_REQUEST | COMMAND_OBSERVED | SENSOR_HEALTH
stage        = PRE_ACTION
```

기존 `FILESYSTEM_WATCHER`와 `POST_ACTION` 계약은 변경하지 않는다.

## Hook Input 계약

제품 공통 Hook 입력은 JSON object 또는 그 JSON text/bytes이며 현재 지원 Event는 `PRE_TOOL_USE` 하나다. 입력에는 다음 필드를 사용한다.

```json
{
  "aia_session_id": "aia-session-id",
  "agent": "codex",
  "agent_native_session_id": "native-session-id",
  "turn_id": "turn-id",
  "tool_use_id": "T100",
  "tool_name": "shell",
  "tool_input": {
    "path": ".env",
    "command": "python reset_db.py",
    "cwd": "C:\\workspace",
    "target": ".env"
  },
  "hook_event_name": "PRE_TOOL_USE",
  "source_metadata": {
    "provider": "codex",
    "channel": "fixture"
  }
}
```

`aia_session_id`, `agent`, `tool_use_id`, `tool_name`, `tool_input`, `hook_event_name`은 필수다. AIA Session ID는 현재 보호 실행 Session과 일치해야 하고 Agent도 Session의 Agent와 일치해야 한다. `agent_native_session_id`와 `turn_id`는 입력에 있을 때만 보존하며 없으면 생성하지 않는다.

알 수 없는 최상위 Key, 필수 필드 누락, 빈 식별자, 잘못된 타입, 다른 Session ID, 다른 Agent, malformed JSON, 지원하지 않는 Event, 64 KiB 초과 입력은 명시적인 Validation Error로 거부한다. 잘못된 payload 전체를 Error Evidence로 평문 저장하지 않는다.

Agent별 실제 Hook Schema는 Adapter 경계에서 변환되어야 한다. 현재 개발 환경에서는 공식 Codex CLI Hook Schema를 제품 계약으로 추측하거나 문서화하지 않았으며, 결정론적 fixture가 이 공통 입력 경계를 검증한다.

## PreTool Raw Evidence

검증된 입력은 `PRETOOL_REQUEST` 레코드 하나로 기록한다. Payload에는 Agent, AIA Session ID, 선택적인 Agent native session/turn, Tool Use ID, Tool name, 지원 Event, 선택된 Tool input, 제한된 source metadata, 그리고 `ingress_verified = false`가 포함된다.

`tool_use_id`는 Hook이 제공한 직접 식별자를 원본 그대로 보존한다. 그러나 ID가 존재한다는 사실만으로 `Attribution.EXACT`를 만들지 않는다. Hook channel의 신뢰성, Session correlation, stage, 경쟁 Evidence는 후속 Attribution Engine이 별도로 판단한다.

`PRE_ACTION`은 실행 전 관찰 시점이라는 뜻이다. `PRE_ACTION`을 `BLOCKED`나 Deny 결과로 기록하지 않는다. 이번 EPIC에는 Tool deny Adapter가 없다.

## Tool Input 선택 저장

Hook input 전체를 JSONL에 복사하지 않는다. 현재 선택 저장하는 Tool input field는 다음과 같다.

- `path`
- `command`
- `cwd`
- `target`

`stdout`, `stderr`, Tool output, Prompt, source content, file content, 환경변수와 같은 값은 저장하지 않는다. Tool name의 의미를 AIA `READ`, `DELETE`, `MODIFY` 같은 Operation으로 변환하지 않는다. 예를 들어 `tool_name = read_file`과 `path = .env`는 Raw Fact로만 보존한다.

## Command Raw Evidence

선택된 `tool_input.command`가 있으면 같은 Hook Source와 `PRE_ACTION` stage로 `COMMAND_OBSERVED` 레코드를 추가한다. `PRETOOL_REQUEST`에는 command 원문을 저장하지 않고 `command_observed` 여부만 남긴다. Raw Command의 authoritative copy는 `COMMAND_OBSERVED` 하나다.

```json
{
  "parent_evidence_id": "pretool-evidence-id",
  "ingress_status": "UNVERIFIED",
  "ingress_verified": false,
  "raw_command": "python reset_db.py",
  "tool_use_id": "T100",
  "cwd": "C:\\workspace"
}
```

`parent_evidence_id`는 이 Command Record를 발생시킨 정확한 `PRETOOL_REQUEST.evidence_id`다. `tool_use_id`만으로 부모를 추정하지 않으므로 동일한 `tool_use_id`의 중복 Hook Event도 각 Command Record의 계보를 결정적으로 추적할 수 있다. `raw_command`는 대소문자·공백을 포함해 원문 그대로 저장한다. lower/case normalization, whitespace normalization, shell parsing, SQL parsing, script effect inference를 수행하지 않는다. `python reset_db.py`를 보고 내부에서 `DROP TABLE`이 실행됐다고 추론하지 않으며, `psql -c "DROP TABLE users"`를 보고 DB 상태가 실제로 변경됐다고 주장하지 않는다.

Raw Command는 민감정보를 포함할 수 있다. 예를 들어 Authorization header나 token이 command 문자열에 들어 있을 수 있다. 현재 Control Root에는 암호화와 ACL hardening이 없으며, 이번 EPIC에는 Redaction Engine을 추가하지 않는다. `PRETOOL_REQUEST`와 `COMMAND_OBSERVED`에 command를 중복 저장하지 않으며, command를 Error message, Sensor Health, 사용자 요약, 다른 metadata에 복사하지 않는다. PreTool append 후 Command append가 실패하면 이미 저장된 PreTool Record는 삭제·수정하지 않고 Sensor를 `FAILED`로 둔다.

## Hook Channel Trust

현재 Hook Ingress는 authenticated IPC, session secret, OS ACL channel protection, Agent Process Launcher를 구현하지 않았다. 그러므로 `ingress_verified`는 항상 `false`, `ingress_status`는 `UNVERIFIED`다. Hook payload를 수신했다는 사실만으로 위조 불가능한 채널이나 자동 EXACT를 주장하지 않는다.

## Sensor Lifecycle과 Health

Hook Sensor는 Filesystem Sensor와 같은 `SensorStatus`와 `SensorHealth`를 사용한다.

```text
STARTING → HEALTHY → STOPPED
      └→ FAILED
HEALTHY ─→ FAILED
```

Lifecycle 전이는 `source = AGENT_HOOK`, `record_type = SENSOR_HEALTH`로 같은 JSONL에 기록한다. Evidence append 실패는 Sensor를 `FAILED`로 바꾸며 Healthy 성공으로 반환하거나 자동 재시작하지 않는다. malformed Hook input은 센서 전체의 치명적 실패가 아니라 명시적인 `HookInputError`로 거부한다.

Sensor 시작 전에 다음을 다시 확인한다.

- Session이 `PREPARING`인지
- `ProtectionPreparationContext`가 Session/Workspace와 일치하는지
- frozen Active Policy가 Session에 속하는지
- 현재 Workspace Lease ownership이 유효한지
- 같은 Session/Workspace의 Safe Checkpoint가 `VALID`인지
- `validate_checkpoint()`가 통과하는지

`HookSensorContext`는 AIA Session ID, Agent, Workspace, status, 시작 시각, evidence path, ingress verification 상태를 제공한다. Agent native session ID는 Context의 고정 식별자가 아니라 각 Event payload의 선택 필드다.

## Filesystem Evidence와의 관계

다음 두 레코드는 모두 같은 Session Stream에 보존될 수 있다.

```text
PreTool:  tool_use_id=T100, command="python delete.py" → PRE_ACTION
후속 관찰: deleted foo.txt                         → POST_ACTION
```

이번 EPIC에서는 두 레코드가 같은 행동이라고 merge하지 않는다. 시간적 연결, Canonical Action, Attribution은 후속 Normalizer와 Attribution 책임이다. Raw Evidence 계층에서는 동일 `tool_use_id` Hook Event도 deduplicate하지 않는다.

## 제품 Claim과 범위

이번 EPIC에서 가능한 Claim은 다음까지다.

> AIA는 지원되는 Hook 입력에서 Tool 실행 전 요청과 명시적인 Command 문자열을 AIA Session별 Raw Evidence로 보존할 수 있다.

이번 EPIC에서 다음은 구현하거나 주장하지 않는다.

- Policy Evaluation과 Allow/Deny
- `BLOCKED` 기록과 PreTool 차단
- Attribution Grade, EXACT/PROCESS/TEMPORAL/UNKNOWN
- Canonical Action과 Normalizer
- Hook/Filesystem Evidence 자동 Merge
- Process Runtime, Process Manager, Kill, Recovery, Rollback
- Network Security, API, GUI, Claude Adapter

Hook Sensor가 HEALTHY여도 Process Runtime Sensor가 없으므로 Session은 `PREPARING`이다. 모든 보호 센서와 Readiness Barrier가 준비된 뒤에야 `PREPARING → READY`를 검토한다.
