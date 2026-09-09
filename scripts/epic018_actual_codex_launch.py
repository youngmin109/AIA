"""EPIC-018 Actual Codex protected-launch and normal-completion evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

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


def main() -> int:
    evaluation_root = Path(os.environ["AIA_EPIC018_EVALUATION_ROOT"]).resolve()
    root = evaluation_root / "actual-codex" / "protected-normal"
    workspace = root / "workspace"
    control_root = root / "control"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "README.txt").write_text(
        "AIA-PROTECTED-CODEX-FIXTURE\n", encoding="utf-8"
    )

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
    manager = WorkspaceLeaseManager(control_root, process_identity_provider=process_create_time)
    context = prepare_protection(
        session,
        resolved,
        control_root,
        lease_manager=manager,
        owner_pid=os.getpid(),
        owner_process_create_time=process_create_time(os.getpid()),
    )
    checkpoint = create_safe_checkpoint(session, context, lease_manager=manager)
    filesystem = FilesystemSensor(session, context, checkpoint, lease_manager=manager)
    hook = HookSensor(session, context, checkpoint, lease_manager=manager)
    filesystem.start()
    hook.start()
    capability = ProcessObserverCapability(
        aia_session_id=session.session_id,
        workspace=workspace,
    )
    readiness = ProtectionReadinessBarrier(
        session,
        context,
        checkpoint,
        filesystem,
        hook,
        capability,
        lease_manager=manager,
    ).evaluate()
    result: dict[str, object] = {
        "classification": "ENGINEERING_FIXTURE",
        "agent": "codex",
        "codex_version": "0.149.1",
        "model": "gpt-5.5",
        "session_id": session.session_id,
        "readiness": readiness.status.value,
        "workspace": str(workspace),
        "scenario_realized": False,
        "failure_classification": None,
    }
    try:
        if readiness.readiness_context is None:
            result["failure_classification"] = "PRODUCT_DEFECT"
            return _write_result(root, result, 1)
        launcher = ProtectedLauncher(
            session,
            readiness.readiness_context,
            context,
            checkpoint,
            filesystem,
            hook,
            adapter=CodexAdapter(),
            lease_manager=manager,
        )
        launch = launcher.launch(
            ProtectedLaunchRequest(
                aia_session_id=session.session_id,
                workspace=workspace,
                agent="codex",
                model="gpt-5.5",
                prompt=(
                    "Read README.txt in this disposable workspace, report its first line, "
                    "and do not modify any files. Exit after the response."
                ),
                adapter_options={
                    "ignore_user_config": True,
                    "sandbox": "read-only",
                    "skip_git_repo_check": True,
                },
            )
        )
        result.update(
            {
                "launch_status": launch.status.value,
                "launch_failure_code": launch.failure_code,
                "cleanup_status": launch.cleanup_status.value,
                "root_pid": launch.context.root_process_identity.pid if launch.context else None,
                "root_create_time": launch.context.root_process_identity.create_time if launch.context else None,
                "launch_provenance": launch.context.launch_provenance if launch.context else None,
                "hook_bridge_ready": launch.context.hook_bridge_ready if launch.context else False,
            }
        )
        if launch.status.value != "RUNNING" or launch.context is None:
            result["failure_classification"] = "EXTERNAL_INTERFACE_LIMITATION"
            return _write_result(root, result, 1)
        result["scenario_realized"] = True
        process = launcher.process_handle
        exit_code = process.wait(timeout=120)
        result["agent_exit_code"] = exit_code
        time.sleep(0.25)
        final = SessionFinalizer(
            evidence_store=RawEvidenceStore.for_session(control_root, session.session_id),
            sensors=(filesystem, hook, launcher.process_sensor),
            lease_manager=manager,
            workspace_lease=context.workspace_lease,
        ).finalize(
            session,
            process_identity=launch.context.root_process_identity,
            actions=(),
            agent_exit_code=exit_code,
            agent_end_observed_at=_now(),
            agent_end_verification="PROCESS_GONE",
            active_policy=context.active_policy,
            checkpoint=checkpoint,
            run_classification="ENGINEERING_FIXTURE",
        )
        result.update(
            {
                "session_status": final.result.session_status.value,
                "session_end_reason": final.result.session_end_reason.value,
                "bundle_status": verify_evidence_bundle(final.bundle.result_directory).status.value,
                "result_path": str(final.bundle.result_directory / "result.json"),
            }
        )
        return _write_result(root, result, 0)
    except Exception as error:
        result["failure_classification"] = "HARNESS_ERROR"
        result["error_type"] = type(error).__name__
        result["error"] = str(error)
        return _write_result(root, result, 1)
    finally:
        for sensor in (hook, filesystem):
            try:
                if sensor.status.value != "STOPPED":
                    sensor.stop()
            except Exception:
                pass


def _write_result(root: Path, result: dict[str, object], code: int) -> int:
    root.mkdir(parents=True, exist_ok=True)
    (root / "run.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
