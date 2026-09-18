# EPIC-005 Safe Checkpoint

## 목적

Safe Checkpoint는 Agent 실행 전에 현재 Workspace를 복구 가능한 기준 상태로
고정하는 기능이다. 이번 EPIC의 책임은 Checkpoint 생성과 Checkpoint 자체 검증까지다.
Rollback, Recovery, Sensor, Agent 실행은 포함하지 않는다.

Checkpoint는 단순한 백업 파일과 다르다. 백업이 파일을 보관하는 데 초점을 둔다면,
Checkpoint는 보관된 파일과 함께 당시 Workspace의 상대 경로, 파일·디렉터리 구조,
파일 크기, SHA-256 Manifest를 검증해 신뢰 가능한 기준점임을 표현한다.

## 생성 조건과 저장 경계

Safe Checkpoint는 하나의 `ProtectedRunSession`과
`ProtectionPreparationContext`에 귀속된다. 다음 조건을 모두 만족해야 한다.

- Session 상태가 `PREPARING`이다.
- Active Policy가 같은 Session에 귀속되어 있다.
- Workspace Lease가 같은 Session과 Workspace에 귀속되어 있다.
- Checkpoint 생성 직전에 현재 Lease Ownership을 다시 검증한다.

Checkpoint는 Agent Workspace 안에 저장하지 않는다. EPIC-004 Control Root 아래에
다음 구조로 staging 후 finalize한다.

```text
<control_root>/
└─ sessions/
   └─ <session-id>/
      └─ checkpoints/
         └─ <checkpoint-id>/
            ├─ workspace/
            ├─ manifest.json
            └─ metadata.json
```

Checkpoint ID는 내부에서 UUID4로 생성하며 기존 ID Artifact를 덮어쓰지 않는다.

## Workspace 범위와 Manifest

MVP 기본 범위는 Workspace 전체다. `.git`, `.env`, `node_modules`, `.venv`, hidden
file, lock file, `dist`, `build`를 자동 제외하지 않는다. Include/Exclude 정책은
후속 범위를 위해 확장할 수 있지만 이번 EPIC에서는 glob 제외 엔진을 구현하지 않는다.

Manifest는 Workspace-relative 경로만 저장하고 `/`로 정규화한다. 절대 경로, `../`,
Drive 변경 경로는 거부한다. 각 Entry는 다음 정보를 가진다.

```json
{
  "relative_path": "src/auth.py",
  "entry_type": "FILE",
  "size": 123,
  "sha256": "..."
}
```

`FILE`에는 크기와 SHA-256을 기록하고, `DIRECTORY`에는 경로와 타입만 기록한다.
빈 Directory도 포함하므로 Directory Set과 File Set을 함께 보존한다. Manifest Entry는
relative path 기준으로 결정론적으로 정렬한다.

## SHA-256과 Content Fingerprint

Regular File은 내용을 청크 단위로 읽어 SHA-256을 계산한다. 실제 File Content는
`workspace/` Snapshot에 복사하고, Manifest와 Metadata에는 경로·타입·크기·Digest만
기록한다.

`checkpoint_content_sha256`은 Manifest Entry만 결정론적으로 직렬화해 계산한다.
`session_id`, `checkpoint_id`, `created_at`, Artifact 경로는 포함하지 않는다. 따라서
서로 다른 Session과 Checkpoint ID라도 동일한 Workspace Content는 동일한 Content
Fingerprint를 갖는다.

```text
Checkpoint Identity != Workspace Content Identity
```

## Workspace Stability 검증

Checkpoint 생성 순서는 다음과 같다.

```text
Workspace Manifest A
→ staging Workspace 복사
→ staging Manifest와 복사본 검증
→ Workspace Manifest B
→ A = staging = B 비교
```

파일 생성·삭제·내용 변경·타입 변경·Directory 변경이 감지되면
`WORKSPACE_CHANGED_DURING_CHECKPOINT`로 실패한다. 부분 Snapshot은 `VALID`로
표시하지 않는다.

## Atomic Finalization과 불변성

최종 Checkpoint 경로에 파일을 하나씩 직접 쓰지 않는다. 임시 staging Directory에서
복사, Manifest 작성, Metadata 작성, Snapshot 검증을 모두 완료한 뒤 Checkpoint별
잠금 아래에서 동일 Filesystem의 atomic rename으로 finalize한다.

실패하면 최종 Checkpoint 경로를 만들지 않으며 staging은 best-effort cleanup한다.
Cleanup 실패도 숨기지 않는다. Finalized Checkpoint는 제품 로직상 immutable
Artifact로 취급하고 자동 수정·overwrite하지 않는다. 이 EPIC에서는 Windows ACL이나
관리자 권한으로 물리적 변경을 막는다고 주장하지 않는다.

## Unsupported Filesystem Entry와 Path Safety

MVP는 regular file과 directory만 지원한다. symbolic link, junction, Windows
reparse point, socket, device 등은 `UNSUPPORTED_FILESYSTEM_ENTRY`로 처리한다.
Symlink나 junction target을 따라가면 Workspace 밖 파일이 Snapshot에 들어가거나
동일 경로가 다른 대상에 매핑될 수 있으므로 자동 follow하지 않는다.

실제 Symlink 통합 테스트는 Windows 권한과 실행 환경에 따라 생성할 수 없어 skip될
수 있다. 이 경우에도 link-like `lstat`/reparse 판정과 Snapshot Copy 차단은 OS 권한에
의존하지 않는 결정론적 Unit Test로 항상 검증한다.

## Checkpoint Validation

Finalization 전에 다음을 검증한다.

- Manifest Entry Set과 Snapshot Entry Set 일치
- Directory Set 일치
- File path, size, SHA-256 일치
- Manifest SHA-256 일치
- Content Fingerprint 일치
- file/directory count와 total bytes 일치

검증 성공한 결과만 `CheckpointValidity.VALID`이 된다. `validate_checkpoint()`는
이후 Artifact가 변조되었는지 다시 확인하고 `VALID` 또는 `INVALID`를 반환한다.

이 검증은 Recovery 뒤의 Integrity Verification과 책임이 다르다.

```text
Checkpoint Validation
= 기준점 자체가 정상인가?

Post-Recovery Integrity Verification
= 복원 후 현재 Workspace가 기준점과 같은가?
```

## Lease와 민감정보

Checkpoint 생성 직전에 Lease를 다시 검증한다. 다른 Session 소유, PID/Create Time
불일치, `OWNER_UNVERIFIABLE`이면 Checkpoint를 만들지 않는다. Workspace Lease는
File Writer Attribution이 아니며, Checkpoint 생성은 Attribution이나 Enforcement
권한을 만들지 않는다.

`.env` 같은 민감 파일의 실제 Content는 복구를 위해 Snapshot에 포함될 수 있다.
Secret Value는 Manifest, Metadata, 오류 메시지에 복제하지 않는다. 현재 Control Root
보호 주장은 Workspace와 논리적으로 분리된 저장 경계까지다.

Checkpoint는 Containment의 선행 조건이 아니다. 유효한 Checkpoint가 없으면 이후
Rollback이 `RECOVERY_UNAVAILABLE`이 될 수 있지만, Checkpoint 부재만으로
Containment 판단이나 실행을 자동으로 막지 않는다.

## Session Lifecycle과 범위

Safe Checkpoint 생성 후에도 Session은 `PREPARING`에 남는다. Sensor가 아직 없으므로
Checkpoint 성공만으로 `READY`로 전환하지 않는다.

이번 EPIC에서 구현하지 않는 항목은 Rollback, Recovery Coordinator, Post-Recovery
Integrity Verification, Agent 실행, Sensor, Attribution, Enforcement, Process Kill,
API, GUI, Network Security, Incremental Checkpoint, Deduplication, Compression,
Cloud Backup, Git Recovery, OS ACL Hardening이다.
