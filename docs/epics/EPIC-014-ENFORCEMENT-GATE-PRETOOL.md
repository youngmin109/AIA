# EPIC-014 — Enforcement Gate + PreTool Enforcement

## 목적

이번 EPIC은 Canonical Action 이후의 정책 판정과 행위 귀속을 실제 통제 요청으로
넘길 수 있는 권한 경계를 추가한다.

```text
Canonical Action
├→ Policy Evaluation
└→ Attribution
        ↓
Enforcement Gate
        ↓
Execution Route
```

`Policy VIOLATION`만으로는 자동 통제를 승인하지 않는다. `EXACT` 귀속, Session,
정책 고정본, Root Process Identity, Sensor, Workspace Lease, Hook 신뢰 상태와
실행 단계를 모두 검증한 경우에만 Gate가 `CONTAIN`을 반환한다.

## Enforcement Domain

공식 상태 축은 다음과 같다.

| 축 | 값 | 의미 |
|---|---|---|
| Decision | `CONTINUE`, `CONTAIN`, `REFUSE` | Gate의 순수 결정 |
| Route | `NONE`, `PRETOOL_BLOCK`, `PROCESS_TERMINATION` | 후속 Adapter에 전달할 내부 경로 |
| Action | `NONE`, `BLOCKED`, `TERMINATED` | 실제 조치가 확인된 상태 |
| Execution Result | `NOT_ATTEMPTED`, `SUCCEEDED`, `FAILED` | 실행 결과 |

Gate 결과는 항상 `Action=NONE`, `ExecutionResult=NOT_ATTEMPTED`에서 시작한다.
`CONTAIN`은 `BLOCKED`나 `TERMINATED`를 의미하지 않는다. 실제 Codex deny 확인만
`BLOCKED/SUCCEEDED`를 만들며, 실제 Process Manager termination은 후속 EPIC의
책임이다.

## Gate 입력과 검증

`EnforcementGateInput`은 `NormalizedAction`, `RuntimePolicyEvaluation`,
`AttributionResult`, `ProtectedRunSession`, `ActivePolicySnapshot`,
`ProtectedLaunchContext`, Workspace Lease, Sensor Health, Hook Trust Status와
검사 시각을 묶는다.

다음 계층을 순서대로 확인한다.

1. Action ID와 AIA Session ID correlation
2. Runtime Policy 결과와 Frozen Active Policy의 ID, version, profile, fingerprint
3. Action과 Policy의 observation stage
4. `COMPLIANT → CONTINUE`, `INDETERMINATE → REFUSE`
5. `VIOLATION`에는 `EXACT` Attribution 필요
6. Session은 `RUNNING`, Mode는 `ENFORCE`여야 함
7. AIA-managed Hook path가 `VERIFIED`여야 함
8. Root PID와 create time 재검증, Root Registration binding 확인
9. `AIA_SPAWNED_ROOT` launch provenance와 Hook Bridge 준비 확인
10. 현재 Workspace Lease가 `LIVE_MATCH`인지 재검증
11. Hook, Filesystem, Process Runtime Sensor가 모두 `HEALTHY`인지 확인

`PROCESS`, `TEMPORAL`, `UNKNOWN` Attribution은 모두 `REFUSE/NONE`이다. Process
identity가 Attribution 결과에 포함된 경우 Root binding과 충돌하거나 identity를
검증할 수 없으면 거부한다.

## Stage Routing과 Checkpoint

`PRE_ACTION`의 통과 결과는 다음과 같다.

```text
VIOLATION + EXACT + 모든 Gate check 통과
→ CONTAIN + PRETOOL_BLOCK
```

`POST_ACTION`은 다음 경로만 만든다.

```text
VIOLATION + EXACT + 모든 Gate check 통과
→ CONTAIN + PROCESS_TERMINATION
```

Post Action은 절대 `BLOCKED`가 아니다. 실제 종료는 EPIC-015에서 수행한다.
Checkpoint 존재 여부는 Containment Gate 조건이 아니다. Checkpoint가 없어도 다른
조건이 모두 통과하면 Containment 요청을 만들 수 있으며, Recovery의 별도 조건으로
남는다.

## Gate는 순수 결정 계층이다

`EnforcementGate.evaluate()`는 Hook 응답을 출력하지 않고, Process를 종료하지
않으며, Session을 변경하거나 Evidence를 삭제·수정하지 않는다. Rollback, Policy
변경, Sensor 재시작도 수행하지 않는다. 각 `GateCheck`와 실패 사유는 immutable
`EnforcementGateResult`에 보존한다.

## Trusted PreTool ingress

현재 EPIC-007의 원시 Hook은 기본적으로 `ingress_verified=false`이다. 이번 EPIC의
`HookEnforcementBridge`는 다음을 결합한 AIA-managed session-scoped path를
검증한다.

- AIA Session ID와 launch ID
- Control Root에 보관하는 per-launch capability
- Codex native `session_id`
- `turn_id`, `tool_use_id`, `hook_event_name=PreToolUse`
- Workspace 내부의 `cwd`
- 첫 번째 trusted event에서 한 번만 수행하는 native session binding

Capability secret은 Control Root 외부의 Evidence, response, reason, repr에 넣지
않는다. 제품 Claim은 암호화된 OS channel이 아니라 “AIA-managed session-scoped
Hook path에서 검증된 event”로 제한한다.

AIA Session ID와 Codex native `session_id`는 별도 필드다. 첫 trusted event가
native session을 binding한 뒤 다른 값이 들어오면 `HOOK_NATIVE_SESSION_MISMATCH`로
unverified 처리하며 기존 binding을 덮어쓰지 않는다.

## Codex 0.149.1 로컬 계약 조사

로컬 실행 파일에서 확인한 버전은 `codex-cli 0.149.1`이다. `codex features list`
에서 `hooks`는 `stable / true`였다. 로컬 설치본의 PreToolUse command hook 입력에는
다음 필드가 실제로 전달됐다.

```json
{
  "session_id": "<Codex native session>",
  "turn_id": "<turn>",
  "tool_use_id": "<tool call>",
  "cwd": "<effective workdir>",
  "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": {"command": "..."},
  "model": "gpt-5.5",
  "permission_mode": "bypassPermissions",
  "transcript_path": null
}
```

현재 로컬 CLI는 `[hooks]`의 `PreToolUse` matcher와 command handler를
`config.toml`/`-c` 계층에서 읽었다. Windows disposable workspace의
`.codex/hooks.json`만 둔 구성은 이번 설치본에서 Hook이 실행되지 않았으므로
Agent-writable project layer를 Trusted External Configuration이라고 주장하지
않는다. Protected Launcher가 사용할 권위 있는 외부 runtime override는 후속
Adapter 통합에서 별도로 고정해야 한다.

PreToolUse deny response는 다음 형태로 확인했다.

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "..."
  }
}
```

`CodexHookAdapter`는 이 native payload와 response를 엄격히 번역한다. native
`session_id`만으로 AIA 신뢰를 만들지 않고 AIA bridge envelope 검증을 요구한다.

## Actual Codex smoke와 Tool coverage

모든 smoke는 별도 disposable workspace에서 수행했다.

| Tool / 경로 | PreTool fired | Payload | deny honored | block confirmed | AIA claim |
|---|---:|---:|---:|---:|---|
| Bash shell | 예 | session/turn/tool/cwd/input 확인 | 예 | 예: Codex가 `Command blocked by PreToolUse hook` 반환 | 현재 확인된 native 경로 |
| `apply_patch` | 예 | patch command payload 확인 | 예 | 예: 파일 미생성 및 blocked event 확인 | 현재 확인된 native 경로 |
| structured file read | 이번 CLI smoke에서 관찰하지 못함 | 미확인 | 미확인 | 미확인 | 지원 Claim 보류 |

Allow smoke에서는 Bash가 파일을 생성했고 Hook payload의 effective `cwd`가
disposable workspace와 같았다. Deny smoke에서는 `deny.txt`가 생성되지 않았고
Codex JSONL에 blocked error가 남았다. `apply_patch` deny도 확인했으며 파일이
생성되지 않았다.

Hook handler가 exit code 1로 실패하는 smoke에서는 Codex 0.149.1이 Bash를 계속
실행했다. 따라서 현재 제품은 Hook failure만으로 fail-closed를 주장하지 않는다.
이 경우 AIA 실행 결과는 `Action=NONE`, `ExecutionResult=FAILED`,
`HOOK_ENFORCEMENT_FAILURE`로 기록해야 한다. Deny 출력이 전달됐다는 사실과
실제 `BLOCKED` 확정은 분리한다.

Codex가 structured file-read tool을 제공하는지 이번 로컬 Tool smoke에서 확인하지
못했다. 따라서 `.env`를 Bash로 읽은 `EXECUTE`를 Canonical `READ`로 바꾸지 않으며,
literal `.env READ → BLOCKED` Acceptance는 structured READ Adapter 확인 전까지
보류한다.

## PreTool Adapter와 latency

`PreToolEnforcementAdapter`의 흐름은 다음과 같다.

```text
Native Codex payload
→ AIA trusted ingress
→ Gate input
→ EnforcementGate
→ neutral response 또는 Codex deny
```

`CONTINUE`와 `REFUSE`는 빈 response를 사용해 Codex native permission을
강제로 `allow`로 완화하지 않는다. `CONTAIN/PRETOOL_BLOCK`에서만 `deny` response를
만든다.

`PreToolDecision.confirm()`은 실제 Adapter 관찰을 받는다.

- explicit block confirmation → `BLOCKED/SUCCEEDED`
- deny 무시 또는 Tool 실행 확인 → `NONE/FAILED`
- confirmation 없음 → `NONE/FAILED`, `BLOCK_CONFIRMATION_UNAVAILABLE`

`pretool_received_at`, `gate_decided_at`, `deny_emitted_at`,
`pretool_gate_latency_ms`를 결과에 보존한다. Reason에는 command 원문, `.env` 내용,
token, API key, full environment, capability secret을 넣지 않는다.

## Launcher bootstrap barrier

Protected Launcher의 순서를 다음으로 고정했다.

```text
Spawn
→ Root identity
→ Root registration
→ Process Sensor HEALTHY
→ Hook Enforcement Bridge 준비
→ Session RUNNING
→ task prompt stdin 전달
```

Process가 존재한다는 사실만으로 Task가 활성화된 것으로 보지 않는다. Prompt
전달 실패 시 실행 결과를 성공으로 기록하지 않고 기존 identity 기반 startup
cleanup 경로를 사용한다.

## 현재 Claim과 제한

이번 EPIC에서 실제 Process Termination, Recovery, Rollback, Integrity, Policy
변경, Network Security, Shell semantic parser, OS File Writer Attribution, API,
GUI는 구현하지 않았다. `PROCESS/TEMPORAL/UNKNOWN` 자동 종료도 없다.

현재 실제 Codex 검증은 Windows 0.149.1의 Bash와 apply_patch command hook 경로에
한정된다. Project-local `.codex/hooks.json`의 Windows 동작은 확인되지 않았고,
Hook failure 시 Codex가 계속 실행될 수 있으므로 후속 외부 runtime configuration과
fail-closed 보증을 별도 EPIC에서 확정해야 한다.
