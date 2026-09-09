# EPIC-016 — Recovery / Rollback + Integrity Verification

## 목적

EPIC-015에서 실제 managed process termination이
`TERMINATED / SUCCEEDED`로 확인된 뒤에만 Safe Checkpoint를 사용해
Workspace 전체를 baseline으로 복원한다. 복원 실행과 복원 후 무결성 검증은
서로 다른 상태 축으로 보존한다.

```text
Enforcement Gate
→ Process Manager
→ TERMINATED / SUCCEEDED
→ Recovery Coordinator
→ Safe Checkpoint Validation
→ Workspace Restore
→ Integrity Verifier
```

`RESTORED`는 복원 작업 자체가 끝났다는 뜻이다. 제품의 검증된 복구 성공은
`Recovery = RESTORED`와 `Integrity = VERIFIED`가 함께 성립할 때만 사용한다.
따라서 `RESTORED + FAILED`는 유효한 결과이며, 복원 실행은 끝났지만 최종
Workspace가 기준과 일치하지 않았다는 뜻이다.

## 책임과 공식 상태

`RecoveryCoordinator`는 Gate, ProcessTerminationResult, Session, Workspace
Lease, SafeCheckpoint를 대조하고 복원 계획과 파일 작업을 실행한다.
`IntegrityVerifier`는 복원 실행과 분리되어 Trusted Checkpoint Manifest와 현재
Workspace의 path set, entry type, directory structure, size, SHA-256을 비교한다.

Recovery 상태:

- `NOT_REQUIRED`: PreTool BLOCKED, CONTINUE, REFUSE 또는 이미 baseline인 경우.
- `RESTORED`: valid checkpoint를 기준으로 계획된 복원 작업이 모두 완료됨.
- `REFUSED`: 종료 성공, Session, Lease, Workspace, path safety 조건이 부족함.
- `FAILED`: 복원 작업을 시작한 뒤 하나 이상의 operation이 실패함.
- `RECOVERY_UNAVAILABLE`: checkpoint가 없거나 validation/tamper 검사를 통과하지 못함.

Integrity 상태:

- `NOT_CHECKED`: 복원 조건이 없거나 mutation 전에 거부되어 검증하지 않음.
- `VERIFIED`: expected path set과 실제 path set, type, directory, size, SHA-256이 일치함.
- `FAILED`: missing, unexpected, type mismatch, hash mismatch 또는 scan error가 있음.

## 자동 Recovery 관문

자동 Recovery는 다음 조건을 모두 만족할 때만 후보가 된다.

- Enforcement Decision = `CONTAIN`
- Enforcement Route = `PROCESS_TERMINATION`
- ProcessTerminationResult = `action TERMINATED / execution SUCCEEDED / outcome TERMINATED`
- Session ID가 일치하고 Session이 `RUNNING`
- Checkpoint, Lease, Workspace binding이 일치함

Gate 승인만으로 복원하지 않는다. `CONTAIN`이 승인됐지만
`Action = NONE / Execution = FAILED`이면 `REFUSED + NOT_CHECKED`로 남긴다.
Gate 객체 자체는 실제 실행 전 결과이므로 `NONE / NOT_ATTEMPTED`일 수 있으며,
실제 `TERMINATED / SUCCEEDED` 권위는 ProcessTerminationResult에서 확인한다.
PreTool의 실제 `BLOCKED`도 이미 실행 전에 조치가 끝났으므로 `NOT_REQUIRED +
NOT_CHECKED`이다. PROCESS/TEMPORAL/UNKNOWN의 REFUSE도 자동 Recovery를
시작하지 않는다.

## Checkpoint와 Trusted Manifest

Recovery Authority는 Git HEAD, Git index, `git reset`, `git clean`, 현재 diff가
아니라 EPIC-005 `SafeCheckpoint`다. Recovery 시작 전 `validate_checkpoint`를
호출하며 artifact, metadata, session, Workspace, manifest fingerprint, count,
size, SHA-256, snapshot layout을 확인한다. 검증 실패 시 Workspace mutation은
0이고 `RECOVERY_UNAVAILABLE + NOT_CHECKED`다.

validation에 성공하면 해당 실행의 manifest tuple을 Trusted Baseline으로 고정한다.
각 checkpoint source file은 실제 복사 직전에 다시 regular file, expected path,
size, SHA-256을 확인한다. snapshot root 자체도 link-like entry가 아닌 directory인지
확인한다.

## Binding과 Lease

다음 값은 하나의 실행을 가리켜야 한다.

- `ProtectedRunSession.session_id`
- `SafeCheckpoint.session_id`
- `ProcessTerminationResult.aia_session_id`
- Enforcement result session ID
- Workspace Lease session ID
- canonical Workspace

Launch context가 제공되면 Launch ID와 Workspace도 확인한다. Lease는 mutation 직전에
재검증하고 operation마다 다시 확인한다. Lease가 missing, stale, PID reused,
owner unverifiable이거나 다른 Session/Workspace에 속하면 `REFUSED + NOT_CHECKED`이며
Workspace를 변경하지 않는다.

## Deterministic Recovery Plan

Action history를 역연산하지 않는다. Checkpoint와 현재 Workspace의 최종 tree를
비교해 다음 operation을 결정론적으로 만든다.

- `REPLACE_TYPE_CONFLICT`
- `CREATE_DIRECTORY`
- `REMOVE_UNEXPECTED_FILE`
- `RESTORE_FILE`
- `REMOVE_UNEXPECTED_DIRECTORY`

Expected directory는 shallow-first로 준비하고, unexpected file은 제거한 뒤,
expected file을 복원하며, unexpected directory는 deepest-first로 제거한다.
Checkpoint에 있던 파일이 삭제됐으면 snapshot에서 복원하고, 수정됐으면 임시 파일에
쓴 뒤 `os.replace()`로 교체한다. Agent가 만든 파일과 디렉터리는 제거한다. MOVE와
RENAME도 Action history가 아니라 checkpoint path set을 기준으로 처리한다.

File ↔ Directory 충돌은 `lstat` 기반으로 현재 entry type을 확인한 뒤 안전하게
제거하고 expected type으로 만든다. 각 작업은 path, operation, attempted,
succeeded, safe reason, expected/final SHA-256만 보존하며 파일 내용이나 secret은
저장하지 않는다.

## Path Safety와 Unsupported Entry

Trusted manifest의 relative path만 canonical Workspace 아래에 lexical join한다.
`resolve()` 결과를 신뢰해 symlink를 따라가지 않는다. target과 모든 기존 parent
component를 `lstat`으로 확인한다. symlink, junction, reparse point, device, socket,
unverifiable entry가 복구 대상 또는 traversal path에 있으면 자동 복구를
`REFUSED + NOT_CHECKED`로 중단한다. 외부 target을 삭제하거나 snapshot을 따라가지
않는다.

Whole Workspace 복원은 파일 단위로 수행되며 whole-workspace atomicity를 주장하지
않는다. Security invariant가 깨지면 즉시 중단한다. 일반 파일 operation 실패는
가능한 독립 operation을 best-effort로 계속할 수 있지만 최종 Recovery는 `FAILED`다.

## Integrity Verification

복원 mutation을 하나라도 시도했다면 복원 결과가 `RESTORED`인지 `FAILED`인지와
관계없이 IntegrityVerifier를 실행한다. 가능하면 Workspace를 두 번 연속 scan하며
두 manifest가 같고 모두 Trusted Manifest와 일치해야 `VERIFIED`로 기록한다.

검증 대상은 path set, missing/unexpected path, file/directory type, nested/empty
directory, file size, SHA-256이다. mtime, ctime, ACL, ADS, owner와 같은 metadata는
현재 MVP Claim에 포함하지 않는다. 외부 writer를 Lease가 물리적으로 차단하지
않으므로 `WORKSPACE_CHANGED_DURING_INTEGRITY`를 failure로 기록한다.

## Replay와 Sensor 한계

이미 baseline인 Workspace에는 불필요한 mutation을 하지 않고
`NOT_REQUIRED + VERIFIED`를 반환한다. 같은 termination 결과로 다시 실행해도
baseline 비교 뒤 no-op이 되므로 안전하다.

Recovery가 만든 filesystem event는 Agent Runtime Action으로 재해석하거나 새로운
Policy/Enforcement loop를 만들지 않는다. 현재 Sensor를 전면 재설계하지 않으며,
Recovery mutation은 AIA-controlled operation이라는 한계를 보존한다. 향후
Orchestrator/Audit EPIC에서 maintenance window와 사건 묶음을 정의한다.

## 현재 Claim과 한계

현재 제품이 주장하는 복구 범위는 expected path/existence, file/directory type,
directory structure, file size, file content SHA-256이다. Whole Workspace atomicity,
ACL/NTFS metadata 복원, selective recovery, Git rollback, DB/network recovery,
incremental checkpoint는 이 EPIC의 범위가 아니다. 외부 writer와 복원 중 TOCTOU는
두 번의 integrity scan과 명시적 failure로 다룬다.

Standalone filesystem smoke:

```powershell
uv run python scripts/epic016_recovery_smoke.py
```

Baseline의 DELETE, MODIFY, CREATE, MOVE/RENAME, unexpected directory, empty directory,
`.env`를 동시에 변경한 뒤 `RESTORED + VERIFIED`와 빈 missing/unexpected/changed path를
확인한다. Secret 내용은 출력하지 않는다.
