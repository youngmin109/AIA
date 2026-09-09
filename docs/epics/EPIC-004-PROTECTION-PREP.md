# EPIC-004 보호 준비와 활성 정책 고정

## 목적

EPIC-002의 `ProtectedRunSession`과 EPIC-003의 `ResolvedPolicy`를 연결해 하나의
보호 실행에서 사용할 정책과 Workspace 소유권을 정적으로 준비한다. 이번 EPIC의
완료 결과는 `Policy와 Workspace Ownership에 대한 정적 보호 준비가 완료됨`이라는
의미만 갖는다.

Safe Checkpoint와 Sensor Initialization이 아직 없으므로 Session을 `READY` 또는
`RUNNING`으로 전환하지 않는다. Session은 `PREPARING`에 머문다.

## AIA Control Root

호출자가 명시한 `control_root`를 사용한다. 제품 내부에 Windows 기본 경로를
하드코딩하지 않는다. Control Root는 생성 가능하거나 이미 존재하는 directory여야
하며 canonical absolute path로 정규화한다.

Workspace와 Control Root가 같거나 서로의 하위 경로이면 거부한다. 따라서 AIA가
보존하는 Policy Artifact와 Lease Artifact를 Agent가 쓰는 Workspace 내부에 만들지
않는다.

현재 보안 Claim은 다음 범위로 제한한다.

> AIA 제어 데이터가 보호 대상 Workspace와 논리적으로 분리되어 있다.

현재 구조는 다음과 같다.

```text
<control_root>/
├─ sessions/
│  └─ <aia-session-id>/
│     └─ active-policy.json
└─ workspaces/
   └─ <sha256(canonical workspace path)>/
      ├─ lease.json
      └─ stale-lease-<id>.json
```

OS ACL hardening, 관리자 권한 보호, Windows 서비스 격리는 구현하지 않는다.

## Active Policy Freeze

Active Policy Freeze는 현재 `PREPARING` Session이 사용할 검증된 정책을 Session
전용 Control Directory에 고정하는 단계다.

```text
User Policy JSON
→ Strict Validation
→ 내부 Enum 변환
→ ResolvedPolicy
→ deterministic serialization
→ Frozen Active Policy
→ Runtime Policy Source
```

Freeze 전에 Session의 `policy_id`와 `policy_version`이 `ResolvedPolicy`의 값과
일치하는지 확인한다. 불일치하거나 Session이 `PREPARING`이 아니면 거부한다.

원본 한국어 JSON은 Runtime Source of Truth가 아니다. Resolver가 만든 immutable
`SecurityAssetPolicy`를 `ActivePolicySnapshot`이 참조하고, 원본 파일을 다시 읽지
않는다. 원본 Profile JSON이 변경되어도 이미 고정된 Snapshot과 Session Artifact는
영향을 받지 않는다.

Frozen Artifact에는 다음 정보를 기록한다.

- `schema_version`
- `policy_id`
- `policy_version`
- `profile`
- `default_effect`
- `rules`
- `frozen_at`
- `session_id`
- `policy_content_sha256`

## Policy Content Fingerprint

Policy Content Fingerprint는 Session Metadata와 분리한다. Hash 입력에는 정책 내용인
schema version, policy identity, profile, default effect, rules만 포함한다.
`session_id`와 `frozen_at`은 Artifact Metadata이므로 Hash 입력에 포함하지 않는다.

동일한 Policy Content는 서로 다른 Session과 Freeze 시각에서도 같은 SHA-256을
만든다. 정책 Rule은 결정적인 순서와 영어 내부 Enum 값으로 직렬화한다.

```text
Policy Content Fingerprint != Session Artifact Metadata
```

하나의 Session에 Artifact가 이미 존재하면 조용히 덮어쓰지 않는다. 동일 내용의
직접 Freeze 재요청은 `ALREADY_FROZEN`, 다른 내용은 `ACTIVE_POLICY_CONFLICT`로
거부한다. `prepare_protection()`은 동일 내용의 기존 Artifact를 재사용할 수 있다.

## Workspace Lease

Workspace Lease는 canonical Workspace 하나에 동시에 하나의 활성 AIA 보호 Session만
허용하는 소유권 경계다. Workspace 경로를 파일명으로 직접 사용하지 않고,
canonical path의 case-insensitive normalized text를 SHA-256한 identifier를 사용한다.

Lease에는 다음을 기록한다.

- canonical workspace path
- `session_id`
- `owner_pid`
- `owner_process_create_time`
- `acquired_at`

Lease Artifact는 Workspace가 아니라 Control Root 아래에 저장한다. 최초 생성은
OS/filesystem exclusive create로 수행하며, 이미 존재하면 덮어쓰지 않고 기존 Lease
검증 경로로 이동한다. Stale Lease 교체는 Workspace별 파일 잠금 아래에서 stale
evidence를 남긴 뒤 같은 파일 시스템 내 원자적 replace로 수행한다. 따라서 동시에
여러 Session이 acquire를 시도해도 하나의 Owner만 유지된다.

동일 Workspace의 두 번째 활성 Lease 요청은 `WORKSPACE_BUSY`로 거부한다. 단, 동일
Session이 같은 PID와 Process Create Time으로 재시도하면 기존 Lease를 재사용한다.
서로 다른 Workspace는 동시에 Lease를 가질 수 있다.

## PID와 Process Create Time

PID는 재사용될 수 있으므로 PID만으로 Owner를 식별하지 않는다. Lease Ownership은
다음 두 값을 함께 비교한다.

```text
PID + Process Create Time
```

Windows에서는 OS Process API로 Create Time을 읽고, 테스트와 다른 환경에서는 주입된
Identity Provider를 사용할 수 있다. PID가 사라졌거나 같은 PID의 Create Time이
달라지면 기존 Lease를 stale 후보로 판단한다.

## Stale Lease

Stale Lease를 처리할 때 기존 `lease.json`을 증거 없이 조용히 삭제하지 않는다.
새 Lease를 기록하기 전에 별도의 stale evidence artifact를 남긴다. 이 기록에는
stale 판단 이유, 이전 `session_id`, 이전 PID, 이전 Process Create Time, 발견 시각과
기존 Lease 내용이 포함된다.

Owner 검증 결과는 다음 네 가지 의미를 구분한다.

- `LIVE_MATCH`: PID와 Process Create Time이 일치하므로 `WORKSPACE_BUSY`
- `STALE_PROCESS_GONE`: PID가 더 이상 존재하지 않아 stale takeover 가능
- `STALE_PID_REUSED`: PID는 존재하지만 Process Create Time이 달라 stale takeover 가능
- `OWNER_UNVERIFIABLE`: 권한 또는 OS 조회 실패로 확인할 수 없어 takeover 금지

`OWNER_UNVERIFIABLE`은 stale로 기록하지 않고 fail-closed 오류를 반환한다. 소유자가
살아 있지 않다는 증거와 소유자 상태를 확인하지 못한 상황을 같은 것으로 취급하지
않는다.

Stale evidence는 이전 소유권 기록을 보존하는 결과이며, 파일 변경의 원인이나
Agent Attribution을 증명하지 않는다.

## Lease와 Attribution의 차이

Workspace Lease는 다음 질문에 답한다.

> 이 Workspace를 어느 AIA Session이 보호 중인가?

Lease는 다음을 증명하지 않는다.

> 이 파일을 어느 Agent가 수정했는가?

따라서 `Workspace Lease != File Writer Attribution`이며, Lease가 존재한다고
Attribution이 `EXACT`가 되지 않는다. Attribution과 Enforcement는 후속 책임이다.

## Preparation Retry와 부분 실패

`prepare_protection()`은 동일 Session의 정상적인 재시도를 지원한다. 이미 같은
정책 내용으로 Freeze된 Artifact가 있으면 immutable `ActivePolicySnapshot`을 다시
읽어 재사용한다. 다른 정책 내용이면 `ACTIVE_POLICY_CONFLICT`를 반환한다.

동일 Session이 같은 Workspace에 대해 동일한 PID와 Process Create Time으로 다시
요청하면 기존 Lease를 재사용한다. 다른 Session이 보유한 Lease는 계속
`WORKSPACE_BUSY`다.

정책 Freeze 후 Lease 획득이 실패해도 Frozen Artifact는 삭제하지 않는다. 이후
경쟁 Lease가 해제되면 같은 Session이 Snapshot을 재사용해 다시 준비할 수 있다.
이번 호출에서 새로 획득한 Lease 뒤의 후속 준비 단계가 실패하면 그 호출이 획득한
Lease만 Release를 시도하며, 기존부터 존재한 동일 Session Lease는 삭제하지 않는다.

## Lease Release

Lease를 획득한 Session만 자신의 Session ID와 현재 Process Identity를 검증한 뒤
Release할 수 있다. 다른 Session ID, 다른 PID, 다른 Process Create Time은 거부한다.
Session terminal transition과 자동 Release 연결은 Lifecycle Orchestrator EPIC에서
수행한다.

## Protection Preparation Context

`ProtectionPreparationContext`는 다음 결과를 하나로 묶는다.

- `session_id`
- canonical `workspace`
- `active_policy`
- `workspace_lease`
- Session Control Directory
- `prepared_at`

Context가 생성되면 Policy Freeze와 Workspace Ownership에 대한 정적 준비는 완료된
것이다. 그러나 Checkpoint와 Sensor가 아직 준비되지 않았으므로 Context 생성만으로
Session을 `READY`로 바꾸지 않는다.

## 범위 밖 책임

Agent 실행, Codex Adapter, Watchdog, Hook, Runtime Evidence, Attribution,
Enforcement, Process Kill, Safe Checkpoint, Snapshot, Recovery, Integrity, API, GUI,
Network Security, Policy 자동 추천과 OS ACL hardening은 구현하지 않는다.

Session Active Policy Freeze를 외부 Trusted Storage에 기록하거나 Session Lifecycle과
자동으로 연결하는 책임도 후속 EPIC의 범위다.
