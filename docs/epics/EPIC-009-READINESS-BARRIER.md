# EPIC-009 — Protection Readiness Barrier

## 목적

Readiness Barrier는 Agent를 시작하기 직전에 현재 보호 구성이 유효한지 다시 확인하는 파생 검증 경계다. 모든 필수 검사가 통과할 때만 `PREPARING → READY` 전이를 수행한다.

`READY`는 Agent가 이미 실행 중이라는 뜻이 아니다. Protected Launcher가 Agent를 시작해도 되는 준비 상태라는 뜻이다. 실제 Agent 실행과 `RUNNING` 전이는 후속 EPIC의 책임이다.

## 검사 범위

Barrier는 다음을 현재 상태로 확인한다.

- Session이 `PREPARING`인지와 Session/Workspace binding
- frozen Active Policy Artifact의 존재, Session·정책 식별자, 내용 SHA-256, resolved policy binding
- Workspace Lease의 Session·Workspace·PID·process create time 및 live owner 검증
- finalized Safe Checkpoint의 Artifact, Manifest, metadata, hash와 Session·Workspace binding
- 현재 Workspace의 file/directory set, 파일 크기와 SHA-256, 빈 디렉터리, content fingerprint
- Filesystem Sensor의 현재 `HEALTHY` 상태, observer 생존, binding, Evidence Store 경계
- Hook Sensor의 현재 `HEALTHY` 상태, binding, Evidence Store 경계
- Process Observer Capability의 유효한 polling 설정과 sensor factory
- 최종 Workspace 검사 전후의 Filesystem observation sequence

Checkpoint가 만든 기준점과 현재 Workspace가 다르면 `WORKSPACE_DRIFTED_AFTER_CHECKPOINT`로 실패한다. Symlink, Junction, Reparse Point 또는 기타 지원하지 않는 entry가 발견되면 기존 Checkpoint의 path safety 검사 결과를 그대로 사용하여 READY를 거부한다.

현재 Workspace 비교는 Recovery 이후의 `IntegrityStatus.VERIFIED`가 아니다. Readiness는 Agent 시작 전 baseline 확인이고, Recovery 후 Integrity는 별도의 상태 축이다.

## Sensor와 Hook 신뢰

Filesystem Sensor와 Hook Sensor는 READY 시점에 현재 `HEALTHY`여야 한다. 과거에 저장된 Context만으로 통과하지 않고 live sensor 상태를 다시 확인한다.

Hook `ingress_verified=false` 또는 `UNVERIFIED`는 현재 단계에서 READY를 막지 않는다. 결과에는 `hook_ingress_verified`를 그대로 보존하며, 이것을 enforcement-grade trust나 자동 `EXACT` 권한으로 승격하지 않는다.

Process Runtime Sensor가 `HEALTHY`일 필요는 없다. READY 이전에는 Agent Process가 존재하지 않으므로, 이번 EPIC은 실제 Sensor를 시작하지 않고 Root Process 등록 이후 사용할 수 있는 Capability만 검증한다. Dummy Process, Agent 실행, Protected Launcher는 구현하지 않는다.

## Workspace Stability

Filesystem Sensor의 monotonic `observation_sequence`를 읽어 다음 경계를 확인한다.

```text
sequence_before
→ 현재 Workspace Manifest 생성
→ Checkpoint와 비교
→ sequence_after
```

두 값이 다르면 `WORKSPACE_CHANGED_DURING_READINESS`로 실패한다. 이 검사는 관찰 generation을 사용하는 보수적인 변경 감지이며 OS 수준 atomic snapshot, transaction, lock 또는 동시 수정 차단을 주장하지 않는다.

## 결과와 성공 Context

`ProtectionReadinessResult`는 `READY` 또는 `NOT_READY`, 검사별 결과와 실패 이유, Active Policy fingerprint, Checkpoint fingerprint, 현재 Workspace fingerprint, Sensor 상태 및 Hook ingress trust 상태를 보존한다. 이 결과는 Raw Evidence가 아니므로 JSONL Evidence Store에 기록하지 않는다.

성공한 경우에만 immutable `ProtectionReadinessContext`를 만든다. Context는 후속 Protected Launcher가 사용할 Session, Workspace, Policy baseline, Workspace baseline, Lease identity, Sensor 상태와 Process Observer Capability를 함께 보존한다. Context 생성은 Barrier 성공 경로에서만 가능하도록 내부 생성 token을 사용한다.

검사 실패 시 Session은 `PREPARING`에 남고 자동으로 `FAILED`가 되지 않는다. 원인을 해결한 뒤 다시 시도할 수 있다. 같은 Barrier에서 이미 성공한 동일 결과를 다시 요청하면 기존 성공 결과를 재사용하며 중복 READY 전이를 만들지 않는다. `READY`인데 성공 Context가 없는 상태는 성공으로 숨기지 않는다.

## 현재 Claim과 제한

현재 Claim은 다음까지다.

> Active Sensor 아래에서 READY 직전 Workspace baseline을 재검증했고, 검증 구간에 관찰된 변경 generation이 없음을 확인했다.

이번 EPIC은 Policy Evaluation, Attribution, Enforcement, Process Termination, Recovery, Rollback, post-Recovery Integrity Verification, Network Sensor, Audit, API, GUI 또는 Agent 실행을 구현하지 않는다. READY 이후 Sensor 장애의 Session 처리도 후속 Runtime Orchestration의 책임이다. READY는 영구적인 보증이 아니며 RUNNING 중 Sensor Health는 계속 검증되어야 한다.
