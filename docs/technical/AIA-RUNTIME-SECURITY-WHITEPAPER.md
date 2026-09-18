# AIA Runtime Security Technical Paper

## Abstract

AIA is a local security assurance layer for a Codex CLI Protected Run on Windows. It does not interpret an Agent's private reasoning or infer intent. It records and evaluates observable runtime actions, connects those actions to a Workspace-bound Session, and applies a policy decision before choosing an enforcement path. The runtime chain is:

```text
Agent Hook request
  -> canonical action
  -> policy evaluation
  -> attribution
  -> enforcement
  -> filesystem or process evidence
  -> recovery
  -> integrity verification
  -> committed and verifiable Result Bundle
```

This paper describes the implemented AIA core and the boundary of each claim. A demo fixture is not an Actual Codex run, and an observed Process or File event does not by itself prove which exact tool wrote a file.

## 1. Scope and security boundary

AIA starts a Protected Run for a Workspace that already exists. It freezes the selected policy, acquires a Workspace Lease, creates a Safe Checkpoint, prepares sensors, and launches the supported Codex CLI path. The Control Root is kept outside the Workspace so evidence and control state are not mixed with files the Agent can edit.

The supported product path is local Windows 11 execution with Codex CLI. The current repository does not claim to protect MCP, Claude, arbitrary external Agents, network traffic, or tools outside the supported launch path. The local console is an Evidence Viewer and control surface; it is not a second policy authority.

## 2. Canonical runtime flow

### 2.1 Session preparation

The CLI creates a Session with a Workspace, Agent label, mode, policy identifier, and policy version. The Session moves through explicit lifecycle states. Preparation is complete only when the policy, lease, checkpoint, and sensor prerequisites are valid.

The policy is resolved before the Agent starts. During the run, the active policy is frozen and carries a fingerprint. Every later evaluation references that frozen policy rather than re-reading a mutable file.

The Workspace Lease binds the Session to the selected Workspace and the owning AIA process identity. It prevents two active Protected Runs from claiming the same Workspace and is released during finalization or controlled cleanup.

The Safe Checkpoint records the Workspace baseline used by Recovery and Integrity. Checkpoint creation is a preparation step; it is not an assertion that a later change will always be recoverable.

### 2.2 Evidence and action normalization

Sensors write bounded `RawEvidenceRecord` values to the Session's evidence store. The records carry a Session ID, source, record type, capture time, observation stage, and a structured payload. The normalizer converts an observed request into a `NormalizedAction` with an operation, target kind, paths or command metadata, evidence IDs, source evidence, and a completeness value.

The raw record is the audit origin. A canonical action is a derived interpretation. A policy result is a decision about that action. These values are kept separate so that a later reviewer can distinguish what the operating system or Hook reported from what AIA concluded.

## 3. Hook Sensor

### 3.1 Role

The Hook Sensor is the pre-action observation and policy gate for the supported Codex Hook path. A Codex `PreToolUse` request is received by the AIA Hook command, validated, bounded, and stored as `AGENT_HOOK` evidence. AIA then evaluates the request against the frozen policy and returns the Hook response.

The normal security outcome for a known policy violation is a deny or contain response before the tool is allowed to proceed. This is a pre-action block. It is not a Process Sensor termination and it is not proof that a process was killed.

### 3.2 Trust and verification

Installing a Hook definition and trusting it in Codex are separate facts. AIA therefore distinguishes:

1. Hook definition present in the Codex configuration.
2. Codex PreToolUse trust state.
3. A live Session-bound Hook Event observed during `hook verify` or a Protected Run.

Only the third fact proves that the Hook path was connected to an AIA Session for that run. A `READY` doctor result means the preconditions are satisfied; it does not mean every future Agent path is automatically supported.

### 3.3 Failure semantics

Malformed or incomplete Hook input is not silently upgraded to a compliant action. AIA can produce an `INDETERMINATE` result or refuse the action when the evidence is insufficient. The Hook Sensor does not decide arbitrary operating-system policy outside the supported Hook contract.

## 4. File Sensor

### 4.1 Role

The File Sensor observes filesystem changes in the protected Workspace and appends filesystem evidence. Its source is `FILESYSTEM_WATCHER`. The evidence describes bounded facts such as an event type, a normalized path label, and the observation stage. It is not a policy authority by itself.

The File Sensor can report create, modify, delete, move, or rename effects that are visible to the watcher. The observed event is compared with the checkpoint and the canonical action chain. A filesystem event may occur after an Agent tool request, so event timing and evidence lineage must be considered when explaining an incident.

### 4.2 Recovery and Integrity

File observation and rollback are different responsibilities. When a verified containment path requires restoration, the Recovery Coordinator applies a plan against the Safe Checkpoint. The Integrity Verifier then compares the resulting Workspace with the expected checkpoint state and reports `VERIFIED` or a failure state.

The accurate chain is therefore:

```text
File Sensor observes
  -> Enforcement or Recovery Coordinator acts
  -> Integrity Verifier checks
```

`RESTORED` alone is not the same as `VERIFIED`. A result is successful recovery only when both statuses are independently recorded as expected.

## 5. Process Sensor

### 5.1 Role

The Process Sensor observes a process tree rooted at an explicitly registered AIA-launched process. Its source is `PROCESS_RUNTIME`. Process identity includes the PID and process creation time so a reused PID is not treated as the same process. The sensor records root and descendant observations, role, parent identity where available, and exit observations.

The sensor watches a managed tree. It does not treat every process on Windows as part of the run. The Process Manager may terminate a verified managed tree only after the enforcement gate has established the policy decision, attribution, lease, root identity, and other required checks.

### 5.2 Termination safety

The Process Sensor observes; the Process Manager enforces. The Process Manager verifies process identities before termination and reports each managed entry's final status. Unrelated processes are outside the managed registry and must remain unaffected. A successful termination result must therefore include both the managed-tree outcome and the unrelated-process check.

Process evidence can establish that a process was observed or exited. It does not, by itself, prove that the process wrote a particular file. That attribution requires a separate evidence chain and is intentionally not claimed by AIA's Process Sensor.

## 6. Policy, attribution, and enforcement

The policy evaluator matches a canonical action using its operation, target kind, path or command pattern, asset type, priority, and active policy fingerprint. A matched rule produces an effect such as allow or deny. The runtime caller does not invent an asset type; it uses the matched policy rule's asset type.

Attribution evaluates whether the available evidence supports connecting the action to the Session. The result may be exact, partial, or indeterminate depending on the evidence sources and completeness. Enforcement receives the combined decision and chooses the supported route. The routes represented in the current core include pre-tool blocking and managed process termination.

The display phrase `BLOCKED / SUCCEEDED` has a precise meaning: AIA's block action succeeded and the actual tool execution was verified as prevented. A deny response alone is insufficient to claim that the external side effect did not occur.

## 7. Result Bundle and auditability

Finalization publishes a Result Bundle containing the canonical result, audit JSONL, security report, and hashed evidence artifacts. The bundle has a commit marker and manifest. The verifier checks the Session binding, mandatory artifacts, hashes, and referenced evidence before a completed result is shown as valid.

The result separates:

- Sensor health before stop and final sensor state.
- Action outcome and evidence references.
- Policy evaluation and matched rules.
- Attribution result and supporting evidence IDs.
- Enforcement action and execution result.
- Process termination result.
- Recovery result.
- Integrity result.
- Limitations and run classification.

`ENGINEERING_FIXTURE` is a first-class classification for deterministic demonstration data. It is intentionally distinct from an Actual Codex protected run.

## 8. Demonstration cases

The command below creates a dedicated presentation Workspace and Control Root. It safely resets only roots carrying AIA demo markers.

```powershell
uv run --isolated --project . python -m aia.cli demo `
  --scenario process-kill `
  --workspace C:\workspace\aia-demo-fixture `
  --control-root C:\workspace\aia-demo-control-fixture `
  --open
```

`--open`은 별도 UI를 만들지 않고 기존 Workbench에서 방금 생성한 Session을 바로 연다.

The three deterministic cases are:

| Case | Evidence path | Result shown |
|---|---|---|
| `process-kill` | Hook request, managed Process observations, exit observations | `CONTAIN` and `TERMINATED`, unrelated process unaffected |
| `hook-block` | PreToolUse request and Hook health | `CONTAIN` and `BLOCKED`, no Process termination claimed |
| `file-rollback` | Hook request, filesystem delete, process exit | `RESTORED` and `VERIFIED` |

These cases make the product flow visible in the existing Result and Workbench screens. The bundle is verifiable, but it is still synthetic presentation data. For an Actual Codex Hook proof, run:

```powershell
uv run --isolated --project . python -m aia.cli hook verify
uv run --isolated --project . python -m aia.cli demo --live --scenario block-canary
```

## 9. Quantitative evaluation

The product evaluation keeps AIA OFF and AIA ON separate and repeats the same scenario in a fresh Workspace. It does not collapse security and productivity into one score.

The fixed matrix contains N-01 through N-06 for normal development, V-01 through V-04 for violations, U-01 for insufficient evidence, and R-01 for recovery and integrity. The default fixture count is 30 repetitions per scenario. Actual Codex representative runs are recorded separately, with five repetitions as the current default.

The report includes:

- Risk side effect rate and risk reduction.
- Normal task success and false-block rate.
- PreTool block success and recovery verification.
- Hook, File, and Process Sensor success rates with their own `N`.
- Minimum, median, P95, and maximum for the recorded timing phases.
- Evidence coverage, lineage completeness, decision consistency, and over-attribution.

Fixture sensor rates are explicitly labelled as synthetic evidence-path measurements. They are not substituted for Actual Codex or Windows integration evidence. A scenario that was not realized is recorded as a limitation, not a pass.

## 10. Security limitations

- The current scope is Codex CLI on Windows 11 through the supported AIA launch and Hook path.
- MCP, Claude, arbitrary external Agents, network security, and OS-wide monitoring are outside the claim boundary.
- A Process Sensor event does not prove exact file authorship.
- A Hook deny does not prove the external side effect was absent unless execution absence is verified.
- A File Sensor observation does not itself roll back a change.
- Recovery and Integrity are separate results; `RESTORED` without `VERIFIED` is incomplete.
- The deterministic demo is not an Actual Codex test.

## 11. Reproducibility commands

```powershell
uv run --isolated --project . python -m pytest -q --tb=no --disable-warnings
uv run --isolated --project . python scripts/product_evaluation/run_fixture_evaluation.py `
  --output-root evaluation/product-before-after/fixture-local `
  --evaluation-id fixture-local `
  --repetitions 30
uv run --isolated --project . --group evaluation python scripts/product_evaluation/build_report.py `
  --input evaluation/product-before-after/fixture-local/raw-runs.jsonl `
  --output evaluation/product-before-after/fixture-local/report.html
```

The raw JSONL, SQLite files, logs, and personal Workspaces remain local and are excluded from the public repository.
