# EPIC-006 파일시스템 Raw Evidence Sensor

## 목적

EPIC-006은 AIA 보호 실행 세션에서 Workspace의 파일시스템 변화를 관찰하고, 관찰된 사실을 **Raw Evidence**로 보존하는 첫 번째 런타임 관찰 계층이다. 이번 EPIC의 센서는 파일시스템 watcher 하나만 제공한다. 관찰 결과를 정책 판단, Agent 귀속, 차단, 종료 또는 복구 결과로 해석하지 않는다.

구현은 기존 P0 코드를 복사하지 않고 제품 MVP의 독립 코드베이스에 필요한 계약만 새로 구현한다. 센서가 HEALTHY가 되어도 아직 Hook, Command, Process 센서가 없으므로 Session은 `PREPARING`에 머문다.

## Raw Evidence와 Evidence Collector

Raw Evidence는 정규화·Canonical Action 변환·Attribution·Policy Evaluation 이전의 관찰 사실이다. Evidence Collector는 watcher callback에서 받은 사실을 필요한 최소 변환만 거쳐 저장한다.

현재 레코드는 다음 필드를 가진다.

```json
{
  "captured_at": "2026-01-01T01:00:00+00:00",
  "evidence_id": "uuid4",
  "observation_stage": "POST_ACTION",
  "payload": {
    "event_type": "created",
    "src_path": "C:\\workspace\\file.txt",
    "dest_path": null,
    "is_directory": false
  },
  "record_type": "FILESYSTEM_EVENT",
  "session_id": "aia-session-id",
  "source": "FILESYSTEM_WATCHER"
}
```

`evidence_id`는 UUID로 생성하고 `captured_at`은 UTC offset을 가진 시각으로 저장한다. 모든 레코드는 Agent native session이나 tool call ID가 아니라 AIA `session_id`에 귀속된다. Agent identity와 AIA Session의 책임 관계는 후속 Adapter EPIC에서 추가로 연결한다.

## 저장 경계와 JSONL 계약

Raw Evidence는 다음 세션 전용 Control Root 경로에 저장한다.

```text
<control_root>/sessions/<session-id>/evidence/raw-evidence.jsonl
```

저장소는 append-only JSONL이다. 한 이벤트마다 한 JSON object를 한 줄 추가하며 기존 줄을 덮어쓰거나 전체 파일을 다시 쓰지 않는다. 같은 프로세스에서 발생하는 동시 callback은 thread-safe append로 직렬화한다. 보존 기간, garbage collection, 암호화, hash chain, 서명, 데이터베이스 저장은 이번 EPIC에 포함하지 않는다.

Raw Evidence에는 파일 내용이나 secret을 수집하지 않는다. `src_path`와 `dest_path`는 watcher가 제공한 원시 경로 문자열을 보존한다. 이번 EPIC에서는 policy target용 canonical path로 바꾸지 않는다.

## Filesystem Sensor 계약

센서는 Workspace 전체를 recursive로 관찰한다. 시작하기 전에 다음 조건을 모두 다시 확인한다.

- Session이 `PREPARING`이다.
- `ProtectionPreparationContext`가 Session과 Workspace에 일치한다.
- Session에 귀속된 frozen Active Policy가 존재한다.
- 현재 Workspace Lease 소유권과 PID/process create time이 다시 검증된다.
- 같은 Session과 Workspace에 귀속된 Safe Checkpoint가 `VALID`이고 `validate_checkpoint()`를 통과한다.

observer가 실제로 시작되고 살아 있는지 확인한 뒤에만 센서를 `HEALTHY`로 기록한다. 이 상태 전이는 보호 실행을 `READY`로 바꾸지 않는다. 센서 시작을 재시도하면 같은 Session의 기존 JSONL에 이어 쓰며, 이미 실행 중인 센서가 두 번째 observer를 만들지 않도록 `ALREADY_RUNNING`으로 거부한다. 반복적인 `stop()`은 안전하게 처리한다.

## 이벤트 의미

현재 저장하는 파일시스템 event type은 `created`, `modified`, `deleted`, `moved`이다. 모든 event는 `observation_stage = POST_ACTION`으로 저장한다. 이는 watcher가 OS 파일시스템 변화를 관찰한 시점이라는 뜻이며, 어떤 행위가 허용됐는지 또는 Agent가 수행했는지를 판정하지 않는다.

`moved`는 source와 destination을 가진 원시 이동 사실로 보존한다. 이 단계에서 `MOVE`와 `RENAME`을 추론하거나 변환하지 않는다. 동일한 OS event가 여러 번 들어오면 모두 기록하며 Deduplication을 수행하지 않는다. `opened`, `closed`, access-like event는 `READ` Evidence로 승격하지 않고 무시한다. 파일 Rule의 READ 정책 판정은 후속 정규화·정책 계층의 책임이다.

Filesystem Sensor는 Attribution이나 Policy Evaluation을 수행하지 않는다. 충분한 Raw Evidence가 쌓이더라도 이번 EPIC에서는 Canonical Action, policy violation, Agent attribution, Enforcement Decision을 만들지 않는다.

## Sensor Health와 저장 실패

센서 수명 상태는 다음과 같다.

```text
STARTING → HEALTHY → STOPPED
      └→ FAILED
HEALTHY ─→ FAILED
```

`SENSOR_HEALTH` 레코드로 `STARTING`, `HEALTHY`, `FAILED`, `STOPPED` 전이를 기록한다. observer가 예기치 않게 죽으면 `check_health()`가 `FAILED`를 표시한다. 실제 observer를 시작하지 못하거나 중지하지 못해도 성공으로 주장하지 않는다.

Evidence append가 실패하면 센서는 메모리 상태를 `FAILED`로 바꾸고 `HEALTHY`로 남거나 자동 재시작하지 않는다. 저장소 자체가 고장 난 동안에는 그 실패를 Raw Evidence로 추가 기록할 수 없으므로 메모리 상태와 반환 오류가 실패를 전달한다.

## Lease, Checkpoint, Session의 관계

Lease는 현재 AIA 프로세스가 Workspace 보호 책임을 보유하는지 확인하는 경계다. Attribution은 관찰된 행위를 Agent에 어느 수준까지 귀속할 수 있는지 판단하는 별도 책임이다. Lease 보유만으로 Agent 행위를 증명하지 않는다.

Checkpoint는 센서의 복사 대상이 아니다. 센서는 Workspace를 관찰하고 Raw Evidence를 Control Root에 기록한다. 시작 전 Lease와 valid Checkpoint를 재검증하는 것은 관찰 계층이 잘못된 Session이나 준비되지 않은 Workspace에 붙지 않게 하기 위한 조건이다. Checkpoint, Recovery, Integrity Verification 자체는 이 EPIC에서 확장하지 않는다.

## 실제 검증과 환경 한계

테스트는 fake observer와 watcher event 객체를 사용한 환경 독립 검증으로 다음을 고정한다.

- raw filesystem event가 `POST_ACTION`으로 기록된다.
- moved source/destination이 보존되고 MOVE/RENAME으로 승격되지 않는다.
- duplicate event가 deduplicate되지 않는다.
- opened/closed event가 READ Evidence가 되지 않는다.
- append 실패와 observer 비정상 종료가 `FAILED`가 된다.
- 중복 start와 반복 stop이 정의된 lifecycle을 지킨다.

Windows에서는 실제 `watchdog.Observer`로 임시 Workspace의 create/modify/delete 이벤트를 bounded polling으로 확인한다. 운영체제 watcher scheduling 권한이나 환경 문제로 실제 통합 테스트를 실행할 수 없는 환경에서는 그 원인을 테스트 결과에 표시한다. 결정론적 unit 검증은 OS 파일시스템 권한에 의존하지 않는다.

## 범위와 Claim 제한

이번 EPIC의 제품 보호 범위는 파일시스템 Raw Evidence 수집까지다. Agent Hook, PreTool, Command Telemetry, Process Runtime, Network, Normalization, Canonical Action, Dedup/Merge, Attribution, Policy Runtime, Enforcement, Kill, Rollback, Recovery, Integrity Verification, API, GUI, 자동 재시작은 구현하지 않는다.

따라서 이번 결과로 다음을 주장할 수 없다.

- 모든 Agent 행위를 관찰했다.
- 파일시스템 event가 특정 Agent의 행위라고 입증했다.
- 정책 위반을 판정했다.
- 보호 조치나 프로세스 종료를 수행했다.
- Network Security를 제공한다.

Network telemetry가 기존 P0 Inventory에 존재하더라도 이는 Legacy / Optional Telemetry / Future Scope로 취급한다. Network Evidence만으로 AIA MVP의 Security Authority나 보안 Claim을 만들지 않는다.

## 다음 단계

후속 EPIC에서 Hook·Command·Process 관찰 계층을 추가할 때도 이 Raw Evidence 경계와 AIA Session correlation을 유지한다. 이후 별도 Normalization 계층이 여러 센서의 사실을 Canonical Action으로 변환하고, 그 다음에 Policy Evaluation과 Attribution을 독립적으로 수행한다.
