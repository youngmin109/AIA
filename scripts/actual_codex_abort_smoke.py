"""Verify safe user-abort termination of an Actual Codex process tree.

This opt-in evaluation launches Codex through ``ProtectedLauncher`` with a
disposable Workspace, asks it to run a fixture that creates a Root -> Child ->
Grandchild tree, and requests the same identity-checked abort operation used
by the product's user-stop path. An unrelated sibling process is checked for
preservation. The smoke is not a policy-violation or automatic-kill claim.
"""

from __future__ import annotations

from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import psutil
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4

from aia import (
    CodexAdapter,
    FilesystemSensor,
    HookSensor,
    PolicyProfile,
    ProcessObserverCapability,
    ProtectedLaunchRequest,
    ProtectedLauncher,
    ProtectedRunSession,
    RawEvidenceStore,
    SessionFinalizer,
    SessionMode,
    SessionStatus,
    WorkspaceLeaseManager,
    create_safe_checkpoint,
    prepare_protection,
    process_create_time,
    resolve_profile,
    verify_evidence_bundle,
)
from aia.readiness import ProtectionReadinessBarrier


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _identity(pid: int) -> dict[str, Any]:
    try:
        process = psutil.Process(pid)
        return {"pid": pid, "create_time": process.create_time()}
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return {"pid": pid, "create_time": None}


def _same_live_process(identity: dict[str, Any]) -> bool:
    create_time = identity.get("create_time")
    if not isinstance(create_time, (int, float)):
        return False
    try:
        process = psutil.Process(int(identity["pid"]))
        return abs(process.create_time() - float(create_time)) < 0.001
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


def _write_report(root: Path, report: dict[str, Any], exit_code: int) -> int:
    root.mkdir(parents=True, exist_ok=True)
    report["report_path"] = str(root / "run.json")
    (root / "run.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return exit_code


def _write_fixture(workspace: Path) -> tuple[Path, Path]:
    child = workspace / "AIA_ABORT_CHILD.py"
    root = workspace / "AIA_ABORT_ROOT.py"
    child.write_text(
        "from pathlib import Path\n"
        "import json, os, subprocess, sys, time\n"
        "base = Path(__file__).parent\n"
        "grandchild = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'], cwd=str(base))\n"
        "(base / 'abort-child.json').write_text(json.dumps({'pid': os.getpid(), 'grandchild_pid': grandchild.pid}), encoding='utf-8')\n"
        "time.sleep(120)\n",
        encoding="utf-8",
    )
    root.write_text(
        "from pathlib import Path\n"
        "import json, os, subprocess, sys, time\n"
        "base = Path(__file__).parent\n"
        "child = subprocess.Popen([sys.executable, str(base / 'AIA_ABORT_CHILD.py')], cwd=str(base))\n"
        "(base / 'abort-root.json').write_text(json.dumps({'pid': os.getpid(), 'child_pid': child.pid}), encoding='utf-8')\n"
        "time.sleep(120)\n",
        encoding="utf-8",
    )
    return root, child


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation") / "actual-codex" / "abort",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--model")
    args = parser.parse_args(argv)
    if os.name != "nt":
        print("SKIP: this runner is intended for Windows Actual Codex integration")
        return 2
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    repository = Path(__file__).resolve().parents[1]
    root = args.output.resolve() / (
        f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
    )
    workspace = root / "workspace"
    control_root = root / "control"
    workspace.mkdir(parents=True, exist_ok=True)
    fixture_root, _ = _write_fixture(workspace)
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        cwd=workspace,
    )
    unrelated_identity = _identity(unrelated.pid)
    result: dict[str, Any] = {
        "proof": "actual-codex-user-abort",
        "scenario": "actual-codex-process-tree-user-abort",
        "workspace": str(workspace),
        "control_root": str(control_root),
        "session_id": None,
        "scenario_realized": False,
        "proof_passed": False,
        "failure_classification": None,
        "unrelated_process": unrelated_identity,
    }
    launcher: ProtectedLauncher | None = None
    session: ProtectedRunSession | None = None
    filesystem: FilesystemSensor | None = None
    hook: HookSensor | None = None
    process = None
    codex_stdout = root / "codex.stdout.txt"
    codex_stderr = root / "codex.stderr.txt"
    output_handles: list[Any] = []
    try:
        now = _now()
        resolved = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT)
        session = ProtectedRunSession(
            workspace=workspace,
            agent="codex",
            mode=SessionMode.ENFORCE,
            policy_id=resolved.policy_id,
            policy_version=resolved.policy_version,
            created_at=now,
        )
        session.transition(SessionStatus.PREPARING, at=now)
        manager = WorkspaceLeaseManager(
            control_root,
            process_identity_provider=process_create_time,
        )
        preparation = prepare_protection(
            session,
            resolved,
            control_root,
            lease_manager=manager,
            owner_pid=os.getpid(),
            owner_process_create_time=process_create_time(os.getpid()),
        )
        checkpoint = create_safe_checkpoint(session, preparation, lease_manager=manager)
        filesystem = FilesystemSensor(session, preparation, checkpoint, lease_manager=manager)
        hook = HookSensor(session, preparation, checkpoint, lease_manager=manager)
        filesystem.start()
        hook.start()
        readiness = ProtectionReadinessBarrier(
            session,
            preparation,
            checkpoint,
            filesystem,
            hook,
            ProcessObserverCapability(aia_session_id=session.session_id, workspace=workspace),
            lease_manager=manager,
        ).evaluate()
        result["readiness"] = readiness.status.value
        result["session_id"] = session.session_id
        if readiness.readiness_context is None:
            result["failure_classification"] = "PRODUCT_DEFECT"
            return _write_report(root, result, 1)

        adapter = CodexAdapter(allow_hook_trust_bypass=True)

        def capture_popen(argv: list[str], **kwargs: Any) -> Any:
            stdout_stream = codex_stdout.open("wb")
            stderr_stream = codex_stderr.open("wb")
            output_handles.extend((stdout_stream, stderr_stream))
            kwargs["stdout"] = stdout_stream
            kwargs["stderr"] = stderr_stream
            try:
                return subprocess.Popen(argv, **kwargs)
            except Exception:
                stdout_stream.close()
                stderr_stream.close()
                raise

        launcher = ProtectedLauncher(
            session,
            readiness.readiness_context,
            preparation,
            checkpoint,
            filesystem,
            hook,
            adapter=adapter,
            lease_manager=manager,
            popen_factory=capture_popen,
        )
        launch = launcher.launch(
            ProtectedLaunchRequest(
                aia_session_id=session.session_id,
                workspace=workspace,
                agent="codex",
                model=args.model,
                prompt=(
                    "Use the Bash tool to run exactly: python AIA_ABORT_ROOT.py. "
                    "Do not use another tool."
                ),
                adapter_options={
                    "ignore_user_config": True,
                    "approval_policy": "on-request",
                    "sandbox": "workspace-write",
                    "skip_git_repo_check": True,
                },
            )
        )
        result.update(
            {
                "launch_status": launch.status.value,
                "launch_failure_code": launch.failure_code,
                "root_pid": launch.context.root_process_identity.pid if launch.context else None,
            }
        )
        if launch.status.value != "RUNNING" or launch.context is None:
            result["failure_classification"] = "EXTERNAL_INTERFACE_LIMITATION"
            return _write_report(root, result, 1)
        process = launcher.process_handle
        assert process is not None
        root_state = workspace / "abort-root.json"
        child_state = workspace / "abort-child.json"
        deadline = time.monotonic() + min(args.timeout, 60.0)
        while time.monotonic() < deadline and (
            not root_state.exists() or not child_state.exists()
        ):
            if process.poll() is not None:
                break
            time.sleep(0.25)
        if not root_state.exists() or not child_state.exists():
            result["failure_classification"] = "SCENARIO_NOT_REALIZED"
            result["codex_stdout"] = (
                codex_stdout.read_text(encoding="utf-8", errors="replace")
                if codex_stdout.exists()
                else ""
            )[-20_000:]
            result["codex_stderr"] = (
                codex_stderr.read_text(encoding="utf-8", errors="replace")
                if codex_stderr.exists()
                else ""
            )[-20_000:]
            return _write_report(root, result, 1)

        root_data = json.loads(root_state.read_text(encoding="utf-8"))
        child_data = json.loads(child_state.read_text(encoding="utf-8"))
        managed = [
            _identity(int(root_data["pid"])),
            _identity(int(root_data["child_pid"])),
            _identity(int(child_data["grandchild_pid"])),
        ]
        result["managed_processes_before_abort"] = managed
        abort_succeeded = launcher.request_user_abort()
        result["abort_request_succeeded"] = abort_succeeded
        wait_deadline = time.monotonic() + 30.0
        while time.monotonic() < wait_deadline and process.poll() is None:
            time.sleep(0.25)
        managed_alive = [_same_live_process(identity) for identity in managed]
        unrelated_alive = _same_live_process(unrelated_identity)
        result.update(
            {
                "scenario_realized": True,
                "managed_processes_alive_after_abort": managed_alive,
                "unrelated_process_alive_after_abort": unrelated_alive,
                "managed_tree_gone": not any(managed_alive),
                "unrelated_process_preserved": unrelated_alive,
            }
        )
        if process.poll() is None:
            result["failure_classification"] = "PRODUCT_ASSERTION_FAILED"
            return _write_report(root, result, 1)
        final = SessionFinalizer(
            evidence_store=RawEvidenceStore.for_session(control_root, session.session_id),
            sensors=(filesystem, hook, launcher.process_sensor),
            lease_manager=manager,
            workspace_lease=preparation.workspace_lease,
        ).finalize(
            session,
            end_reason="USER_ABORT",
            process_identity=launch.context.root_process_identity,
            process_end_status="PROCESS_GONE",
            active_policy=preparation.active_policy,
            checkpoint=checkpoint,
            launch_context=launch.context,
            run_classification="ENGINEERING_FIXTURE",
            agent_end_observed_at=_now(),
            agent_end_verification="PROCESS_GONE",
            limitations=() if abort_succeeded else ("USER_ABORT_TERMINATION_UNCONFIRMED",),
        )
        result.update(
            {
                "session_status": final.result.session_status.value,
                "bundle_status": verify_evidence_bundle(final.bundle.result_directory).status.value,
                "result_path": str(final.bundle.result_directory / "result.json"),
            }
        )
        result["proof_passed"] = bool(
            abort_succeeded
            and result["managed_tree_gone"]
            and result["unrelated_process_preserved"]
            and result["session_status"] == "ABORTED"
            and result["bundle_status"] == "VALID"
        )
        if not result["proof_passed"]:
            result["failure_classification"] = "PRODUCT_ASSERTION_FAILED"
        return _write_report(root, result, 0 if result["proof_passed"] else 1)
    except Exception as error:
        result["failure_classification"] = "HARNESS_ERROR"
        result["error_type"] = type(error).__name__
        result["error"] = str(error)
        return _write_report(root, result, 1)
    finally:
        for handle in output_handles:
            try:
                handle.flush()
            except Exception:
                pass
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                pass
        if unrelated.poll() is None:
            try:
                unrelated.terminate()
                unrelated.wait(timeout=5)
            except Exception:
                pass
        for handle in output_handles:
            try:
                handle.close()
            except Exception:
                pass
        for sensor in (
            hook,
            filesystem,
            launcher.process_sensor if launcher is not None else None,
        ):
            if sensor is None:
                continue
            try:
                if sensor.status.value != "STOPPED":
                    sensor.stop()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
