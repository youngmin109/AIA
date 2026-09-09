# EPIC-017 — Session Finalization + Audit / Evidence Bundle + Result / Report

EPIC-017은 새로운 보안 판단기를 추가하지 않고, 하나의 Protected Run에서 이미 생성된
Evidence, Canonical Action, Policy, Attribution, Enforcement, Recovery, Integrity 결과를
검증 가능한 사건 기록으로 닫는다. `SessionFinalizer`는 기존 결과를 소비하며 Policy,
Attribution, Enforcement를 다시 판단하지 않는다.

## Session 종료 의미

- `COMPLETED / AGENT_EXITED`: Agent가 AIA 강제 종료 없이 자연 종료했고 Managed Root의
  PID/create_time 검증 결과가 `PROCESS_GONE` 또는 `PID_REUSED`이다.
- `ABORTED / SECURITY_CONTAINMENT`: `ProcessTerminationResult`가
  `TERMINATED / SUCCEEDED`로 확인되어 AIA가 Agent 실행을 보안 통제로 중단했다.
- `ABORTED / USER_ABORT`: 사용자가 명시적으로 보호 실행을 중단했다.
- `FAILED / PROTECTION_FAILURE`: 보호 체계가 신뢰성 있게 실행을 완료하지 못했다.

Session 상태는 Policy, Attribution, Enforcement, Recovery, Integrity의 verdict를
대체하지 않는다. 따라서 `TERMINATED + RESTORED + VERIFIED`는 `ABORTED /
SECURITY_CONTAINMENT`과 함께 표현된다. Recovery 또는 Integrity 실패도 보통
Containment Session을 `FAILED`로 다시 쓰지 않는다.

PreTool `BLOCKED`는 하나의 실행 전 Tool Action을 차단한 결과일 뿐 Session 종료가
아니다. `VIOLATION + PROCESS + REFUSE + NONE`도 허용으로 표현하지 않고 사용자 검토가
필요한 정책 위반으로 기록한다. `INDETERMINATE`는 정상 또는 `COMPLIANT`로 표시하지
않는다.

## Finalization 순서

1. Terminal outcome과 Process Identity를 검증한다.
2. 활성 Sensor를 stop하고 stop 전 health와 최종 lifecycle state를 별도로 기록한다.
3. 마지막 Sensor event append가 끝난 뒤 Raw Evidence Index와 Seal을 생성한다.
4. Session을 terminal state로 전이하고 `ended_at`과 `SessionEndReason`을 고정한다.
5. Recovery/Integrity 이후 현재 Session, canonical Workspace, owner identity가 일치하는
   Workspace Lease를 release하고 실패하면 `LEASE_RELEASE_FAILED` limitation을
   남긴다.
6. Canonical Result, Audit Trail, Security Report를 생성한다.
7. staging directory에서 Evidence Manifest와 Commit Marker를 생성한 뒤 `result/`를
   atomic rename으로 publish한다.

Lease release는 과거의 Policy, Enforcement, Recovery, Integrity 결과를 다시 판정하지
않는다. Release 실패는 operational limitation으로만 Result/Report에 보존한다. Release가
완료되면 lease artifact는 더 이상 active ownership을 주장하지 않으며 같은 Workspace의
다음 Session이 새 Lease를 획득할 수 있다.

정상 종료에서 Managed Root가 `LIVE_MATCH`이면 `COMPLETED` 전이를 거부한다.
`OWNER_UNVERIFIABLE`은 정상 완료 Claim을 만들지 않고 `FAILED /
PROTECTION_FAILURE`로 기록한다.

## Evidence Seal과 Index

Raw Evidence는 기존 append-only JSONL을 그대로 보존한다. Finalization은
`evidence/raw-evidence.seal.json`에 Session ID, byte size, line count, SHA-256,
마지막 Evidence ID를 기록하고 `evidence/evidence-index.json`에
`evidence_id → JSONL line number`와 최소 source/type/timestamp를 기록한다.
Seal 이후 `RawEvidenceStore.append()`는 `EVIDENCE_STORE_SEALED`로 거부된다.

SHA-256 Seal은 Finalization 시점 이후 변경을 검증할 수 있는 snapshot이라는 의미다.
서명, 공격자 방지, tamper-proof를 주장하지 않는다.

## Canonical Result

`SessionResult`는 `schema_version = aia-result-1`과 Session에서 결정적으로 파생한
UUID5 `result_id`를 사용한다. Policy binding, Sensor summary, Action Outcome,
Policy/Attribution/Enforcement 결과, Process Termination, Recovery, Integrity,
limitation, Evidence reference, finalization timing을 포함한다.

`ActionOutcomeRecord`는 다음 계보를 한 행으로 보존한다.

```text
Raw Evidence IDs
→ Canonical Action
→ Policy Evaluation
→ Attribution
→ Enforcement
→ Termination
→ Recovery
```

각 Action의 `matched_asset_types`는 여러 Rule이 일치할 때 모두 보존한다. Command는
Result와 Report에 원문을 복제하지 않고 SHA-256 fingerprint와 Raw Evidence reference만
기록한다. `.env` 내용, token, password, API key, capability, prompt, 전체 환경변수는
Result/Audit/Report에 복제하지 않는다.

## Audit Trail

`audit/audit.jsonl` 대신 현재 Bundle layout에서는 `result/audit.jsonl`에 canonical
AuditRecord를 기록한다. 이는 OS raw observation이 아니라 authoritative result object를
시간 순으로 연결한 기록이다. 실제 source timestamp가 있는 Event만 생성하며 임의
timestamp를 만들지 않는다. 같은 timestamp에서는 phase order와 entity ID로 결정적으로
정렬한다.

## Security Report

`security-report.md`는 LLM 없이 deterministic template으로 생성한다. 다음 Section을
한국어 중심으로 포함한다.

- 실행 정보
- 최종 상태
- 무슨 일이 발생했는가
- 왜 이런 판정이 나왔는가
- AIA가 수행한 조치
- Policy / Attribution / Enforcement
- Recovery / Integrity
- Sensor 상태
- 주요 Action / Incident
- Evidence
- Limitation

Report는 기존 Result를 표현할 뿐 새로운 Policy 또는 Attribution 판단을 하지 않는다.

## Evidence Bundle

Session Control Root의 layout은 다음과 같다.

```text
sessions/<session-id>/
├─ active-policy.json
├─ checkpoints/
├─ evidence/
│  ├─ raw-evidence.jsonl
│  ├─ raw-evidence.seal.json
│  └─ evidence-index.json
└─ result/
   ├─ result.json
   ├─ audit.jsonl
   ├─ security-report.md
   ├─ evidence-manifest.json
   └─ commit.json
```

Checkpoint Workspace snapshot 자체는 Result directory로 복사하지 않고 Manifest와
Metadata를 reference한다. Manifest는 artifact type, relative path, byte size, SHA-256,
Session binding만 가진다.

`commit.json`은 마지막에 생성한다. Manifest SHA-256과 Bundle fingerprint가 일치하고
모든 artifact를 검증할 수 있을 때만 Bundle을 `VALID`로 본다. `commit.json`이 없으면
`UNCOMMITTED`이며 partial result는 유효한 Finalized Result가 아니다.

이미 committed Bundle이 있으면 같은 Result ID는 idempotent reuse하고 다른 내용은
비휘발성 canonical Result content fingerprint가 다르면
`RESULT_ALREADY_COMMITTED_CONFLICT`로 거부한다. 같은 Result ID와 같은 content fingerprint일
때만 idempotent reuse한다. Commit 실패 후에는 terminal Session과
`ended_at`을 다시 RUNNING으로 되돌리지 않고 같은 Result ID로 retry한다.

Bundle Verifier는 result, audit, report, raw evidence, manifest를 변경하면 `INVALID`를
반환한다. Recovery가 만든 Filesystem Event는 Agent Action으로 재해석하지 않으며,
현재 Finalization은 이를 limitation으로 표시한다.

## Run Classification과 범위

필요할 때 `FIRST_ATTEMPT`, `REVIEWER_APPROVED_RERUN`, `EXPLORATORY`,
`ENGINEERING_FIXTURE`를 metadata로 기록할 수 있다. 일반 Run의 classification을
추론하지 않는다. 이전 Session Bundle은 덮어쓰지 않으며 새 Session은 새 Bundle을 만든다.

이번 EPIC에서는 Web API, GUI, DB, LLM Report, Network/MCP, 새로운 Policy/Attribution/
Enforcement/Recovery algorithm, Actual Codex 재평가를 구현하지 않는다. P0 코드는 복사하지
않고 durability, report, commit marker, evidence preservation 개념만 참고한다.
