# EPIC-010 — Protected Launcher / Codex 실행 경계

## 목적

Protected Launcher는 `READY` Session에서 Agent를 직접 Spawn하고, PID와 process create time으로 Root Process Identity를 확보하며, Root Registration과 Process Runtime Sensor가 정상적으로 완료된 뒤에만 `RUNNING`으로 전환한다.

```text
READY
→ Launch-Time Revalidation
→ Codex Adapter
→ AIA 직접 Spawn
→ PID + create_time
→ Root Registration
→ Process Runtime Sensor HEALTHY
→ 최종 검증
→ RUNNING
```

`READY`는 Agent가 실행 중이라는 뜻이 아니다. `Popen()` 성공도 Protected Launch 성공을 의미하지 않는다.

## Agent Adapter와 Codex 조사 결과

이번 환경에서 직접 확인한 CLI는 다음과 같다.

- Version: `codex-cli 0.149.1`
- Subcommand: `codex exec`
- 확인된 주요 옵션: `-C/--cd`, `--ephemeral`, `--json`, `-m/--model`, `--sandbox`, `--skip-git-repo-check`, `-` stdin prompt
- Prompt 전달: `codex exec ... -` 형식으로 stdin 전달
- JSON/stream: `--json` 옵션은 확인했지만 이번 Launcher는 전체 stdout을 보존하지 않으며, native session ID parser도 확인되지 않은 Schema를 추측하지 않도록 `None`을 유지한다.

`CodexAdapter`가 executable discovery와 Codex argv 변환을 담당한다. Launcher는 Codex 전용 flag를 직접 조립하지 않는다. Claude Adapter는 구현하지 않았다.

Windows에서는 PATH의 npm wrapper보다 직접 실행 가능한 `codex.exe`를 우선 선택한다. 실제 Spawn은 항상 `shell=False`와 canonical Workspace `cwd`를 사용한다.

권한 확대 옵션인 approval bypass, full access, YOLO 계열 옵션은 기본 argv에 추가하지 않으며 Adapter에서 거부한다. Smoke Test에서만 사용자가 명시한 `sandbox=read-only`와 `skip_git_repo_check=true`를 전달했다.

## Launch-Time Revalidation

Spawn 직전에 다음을 다시 확인한다.

- Session이 `READY`인지
- `ProtectionReadinessContext`의 Session·Workspace binding
- Active Policy, Checkpoint, Lease binding
- Workspace Lease의 live ownership
- Filesystem Sensor와 Hook Sensor의 현재 `HEALTHY` 상태
- Readiness Context의 Filesystem observation sequence
- 현재 Workspace baseline이 READY 당시 기준과 일치하는지

READY 이후 Workspace 변경이나 sequence mismatch는 `LAUNCH_REFUSED`로 처리하고 Process를 생성하지 않는다. 보호 invariant가 깨진 경우 Session은 `FAILED`로 전환한다. Adapter executable 미발견처럼 Process가 생성되기 전의 구성 오류는 Session을 `READY`로 유지하여 재시도할 수 있다.

## Spawn과 Process Identity

Launcher는 구조화된 argv를 `subprocess.Popen(..., shell=False, cwd=workspace)`에 전달한다. Prompt는 stdin으로만 보내며 Launch Context와 오류에는 원문을 저장하지 않고 SHA-256만 보존한다. 전체 환경변수, stdout, stderr, token, API key는 Raw Evidence나 Launcher Context에 복제하지 않는다.

Popen 이후 즉시 PID와 process create time을 읽고 `LIVE_MATCH`를 확인한다. PID만으로 등록하지 않는다. 성공하면 `RootProcessRegistration.registration_source`는 `PROTECTED_LAUNCHER`가 된다.

```text
AIA가 Root Process를 직접 Spawn했다
≠
그 Process의 모든 행위가 EXACT Attribution이다.
```

Process Launch Provenance와 Hook Ingress Trust도 별도다. Launcher가 직접 Spawn해도 `hook_ingress_verified`를 `true`로 바꾸지 않는다.

## Runtime Sensor와 RUNNING

Root Registration 직후 EPIC-008 Process Runtime Sensor를 launch-authorized `READY` Session에서 시작한다. Sensor가 `HEALTHY`가 되고 Root `PROCESS_OBSERVED` Evidence가 확인되어야 다음 검사를 수행한다.

- Root Process `LIVE_MATCH`
- Process Sensor `HEALTHY`
- Filesystem Sensor `HEALTHY`
- Hook Sensor `HEALTHY`
- Workspace Lease `LIVE_MATCH`
- Session `READY`

모두 통과한 뒤 기존 Session transition API로 `READY → RUNNING`을 수행한다. Spawn부터 Identity 등록과 Sensor healthy까지의 latency를 `ProtectedLaunchContext`에 millisecond 단위로 보존한다. 이 구간을 0ms라고 주장하지 않는다.

## Startup Failure Cleanup

Identity 등록 이후 Sensor 시작 또는 최종 검증이 실패하면 Launcher가 이번 시도에서 직접 Spawn하고 검증한 Root Process Tree만 best-effort로 정리한다. PID 단독 종료는 수행하지 않는다. Cleanup은 `LAUNCH_FAILURE_CLEANUP` 목적이며 Policy Enforcement나 Enforcement Action이 아니다.

Cleanup에 실패하면 `LAUNCH_CLEANUP_FAILED`를 반환하고 Session은 `FAILED`가 된다. Process가 생성되기 전 Adapter 오류에서는 종료했다는 Cleanup Claim을 만들지 않는다. Agent가 자연 종료해도 이번 EPIC은 Session을 자동으로 `COMPLETED`로 전환하지 않는다.

## Native Session ID와 Hook

실제 Codex output Schema가 확인되지 않았으므로 Agent Native Session ID는 추측하거나 생성하지 않는다. 현재는 `None`이다. Codex stdout JSON event를 Trusted PreTool Hook으로 간주하지 않으며 Hook Sensor의 `UNVERIFIED` 계약을 유지한다.

## 실제 검증

결정론적 Python Test Adapter로 실제 Python Root Process를 Spawn하고 다음을 검증했다.

- shell false
- canonical Workspace cwd
- PID + create time
- `PROTECTED_LAUNCHER` Root Registration
- Root Process Evidence
- Process Runtime Sensor `HEALTHY`
- `READY → RUNNING`
- startup timing

추가로 Disposable Workspace에서 로컬 `codex-cli 0.149.1`을 실제 실행했다. `codex exec`, stdin prompt, read-only sandbox, skip-git-repo-check를 사용했고, 실제 Codex executable discovery, Root Registration, Process Sensor `HEALTHY`, `RUNNING` 전환을 확인했다. Prompt와 전체 output은 저장하지 않았다.

## 현재 범위와 제한

이번 EPIC은 Normalization, Canonical Action, Policy Evaluation, Attribution, Enforcement, 정책 기반 종료, Recovery, Rollback, Integrity Verification, Network Sensor, API, GUI, Claude Adapter를 구현하지 않는다.

이번 단계의 제품 Claim은 다음까지다.

> AIA는 READY 검증을 통과한 Session에서 Agent Process를 직접 시작하고, PID와 Process Create Time으로 Root Identity를 등록한 뒤 Runtime Process Sensor가 활성화된 경우에만 Session을 RUNNING으로 전환한다.

AIA가 모든 Agent 행위를 정책적으로 통제하거나 모든 Tool Call을 신뢰된 Hook으로 증명하거나 정책 위반 시 Process를 종료한다는 Claim은 아직 제공하지 않는다.
