# EPIC-015 — Process Manager / Safe Termination

## Scope

This EPIC adds the Process Manager after the Enforcement Gate. It executes a
process termination only for a correlated Gate result whose decision is
`CONTAIN`, route is `PROCESS_TERMINATION`, action is `NONE`, and execution
result is `NOT_ATTEMPTED`.

The manager is bound to the AIA Session, Protected Launch Context, managed
root registration, workspace lease, and launch provenance. There is no public
PID-only `kill`, `terminate`, or `kill_tree` operation. The Session is not
mutated by termination and there is no `SessionStatus.TERMINATED` state.

## Managed root and identity

`ManagedProcess` is an immutable binding containing the AIA Session ID,
Launch ID, canonical Workspace, root `ProcessIdentity`, registration time,
launch provenance, and optional executable. The only accepted provenance is
`AIA_SPAWNED_ROOT`. `ManagedProcessRegistry` is idempotent for the same root
and rejects a conflicting root with `MANAGED_ROOT_CONFLICT`.

The Protected Launcher registers the root after Spawn, PID/create-time
identity capture, root evidence registration, and a healthy Process Sensor.
Registration happens before the Hook Bridge, Session `RUNNING`, and Prompt
release. A later launch cannot overwrite a different root for the same
Session or Launch.

If registry registration fails, the Launcher returns a named launch failure,
does not enter `RUNNING`, does not write the Prompt, and uses the existing
startup cleanup path to terminate the spawned root safely.

## Gate, lease, and binding checks

Before the first process lookup, the manager verifies:

- Gate decision, route, action, and execution result;
- Session is `RUNNING` and all Session IDs match;
- Launch ID, root identity, Workspace, and `AIA_SPAWNED_ROOT` provenance;
- the immutable managed-root registry binding; and
- current Workspace Lease ownership.

`READY`, terminal Sessions, Gate `REFUSE`, PreTool routes, attribution
failures, mismatched launch or Workspace context, and stale or unverifiable
leases produce `REFUSED`/`NOT_ATTEMPTED` without a termination API call.

## PID/create-time safe termination

The root is revalidated immediately before any termination API call:

- `LIVE_MATCH` permits the verified process handle to be used;
- `PROCESS_GONE` produces `ALREADY_EXITED`, action `NONE`, and execution
  `NOT_ATTEMPTED`; and
- `PID_REUSED` or `OWNER_UNVERIFIABLE` refuses unsafe termination.

The manager uses `psutil.Process.terminate()`, a bounded wait, identity
revalidation, and then `psutil.Process.kill()` only when the same identity is
still live. It does not use `taskkill`, `shell=True`, or public `os.kill`.

For descendants, the manager snapshots the current verified root tree,
records parent identity and depth, verifies the parent chain back to the root,
and terminates deepest descendants first. An unrelated process is excluded
even when its executable, command, working directory, or name is similar.
The refresh loop is bounded to three passes. Detached descendants that are no
longer visible in the verified tree are a documented limitation; Job Objects
and kernel process groups are outside this EPIC.

## Official result model

Each process result records its identity, role, depth, initial and final
verification, graceful and force attempts/results, outcome, and reason. The
official Process Manager result includes:

- `TERMINATED` + `SUCCEEDED` only when the Gate-authorized root termination
  API was called and all known managed identities are no longer live without a
  fatal verification failure;
- `ALREADY_EXITED` + `NONE` + `NOT_ATTEMPTED` when the root was gone before
  the termination API;
- `PARTIAL` or `FAILED` + `NONE` + `FAILED` for an incomplete or failed tree;
- `REFUSED` + `NONE` + `NOT_ATTEMPTED` for invalid Gate, binding, Session, or
  Lease context.

Repeated execution for a completed `(AIA Session, Launch)` returns the stored
result without another PID lookup or termination call. Checkpoint, Recovery,
Rollback, and Integrity are not invoked by this EPIC. Process Sensor exit
evidence remains supplementary; the manager's PID/create-time post-check is
the termination authority.

Timing fields are recorded as `termination_requested_at`,
`termination_started_at`, `termination_completed_at`,
`gate_to_termination_start_ms`, and `termination_duration_ms`. Process
arguments, environment values, and raw command text are not included in the
result.

## Verification

The deterministic tests cover registry conflict protection, Gate refusal,
children-first ordering, unrelated-process exclusion, partial failure, PID
reuse, root-already-gone handling, and replay idempotency. A real
Root→Child→Grandchild integration test is included for environments where the
test runner does not place the process tree in a Windows Job Object. On the
current Windows runner it is skipped because the runner may terminate the
protected root while terminating a child; the identity-safe tree behavior is
still covered by the deterministic process graph tests.

The standalone Windows runner is
`scripts/epic015_process_manager_smoke.py`. Run it from an ordinary PowerShell
session with:

```powershell
uv run python scripts/epic015_process_manager_smoke.py
```

It creates real Root→Child→Grandchild and unrelated Python processes,
registers only the managed root, prints PID/create-time identities and the
termination order, and exits successfully only for
`TERMINATED / SUCCEEDED` with the unrelated process still
`LIVE_MATCH`. The runner is separate from product code and does not add Job
Object or process-group escape logic to `ProcessManager`. In the current
Codex host it returned `PARTIAL / FAILED` because the host Job Object removed
the Root while descendants were being terminated; this is reported as a
failure rather than converted into a false success.

No Policy Engine, Attribution, Checkpoint, Recovery, Rollback, Integrity,
Hook, Watcher, GUI, API, or new dependency is introduced here.
