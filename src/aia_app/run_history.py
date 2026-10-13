"""Run history and completed-status presentation for the application service."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from aia import (
    ProcessIdentity,
    ProcessIdentityStatus,
    RawEvidenceStore,
    process_create_time,
    verify_process_identity,
)

from .presenters import (
    evidence_chain_views,
    evidence_timeline_views,
    result_action_chain_views,
    result_view,
    safe_event_views,
    safe_tool_name,
)
from .registry import RunRecord

_PRODUCT_SENSOR_NAMES = frozenset(
    {
        "AGENT_HOOK",
        "FILESYSTEM_WATCHER",
        "PROCESS_RUNTIME",
    }
)


def _sensor_summary_is_verified(sensor_summary: Any) -> bool:
    summaries = tuple(
        item for item in (sensor_summary or ()) if isinstance(item, Mapping)
    )
    observed_sensors = {
        item.get("sensor")
        for item in summaries
        if isinstance(item.get("sensor"), str)
    }
    return _PRODUCT_SENSOR_NAMES.issubset(observed_sensors) and all(
        item.get("runtime_health_before_stop") == "HEALTHY"
        and item.get("final_sensor_state") == "STOPPED"
        for item in summaries
    )


def _hook_broker_runtime_healthy(record: RunRecord) -> bool | None:
    """Return per-run Hook transport health when a launcher is available."""

    launcher = record.runtime.get("launcher")
    if launcher is None:
        return None
    broker = getattr(launcher, "hook_broker", None)
    if broker is None:
        return False
    status = getattr(broker, "is_running", None)
    if callable(status):
        status = status()
    return bool(status)


def _execution_observation_metadata(
    control_root: Path,
    session_id: str,
) -> tuple[set[str], dict[str, str]]:
    """Return PostToolUse links and capture times for display metadata."""

    try:
        records = RawEvidenceStore.for_session(control_root, session_id).records()
    except (OSError, ValueError):
        return set(), {}
    posttool_ids = {
        str(record.payload["tool_use_id"])
        for record in records
        if record.record_type.value == "POSTTOOL_OBSERVED"
        and isinstance(record.payload.get("tool_use_id"), str)
        and record.payload.get("tool_use_id")
    }
    observed: set[str] = {
        record.evidence_id
        for record in records
        if record.record_type.value == "POSTTOOL_OBSERVED"
        and isinstance(record.payload.get("tool_use_id"), str)
        and record.payload.get("tool_use_id") in posttool_ids
    }
    observed.update(
        record.evidence_id
        for record in records
        if record.record_type.value == "PRETOOL_REQUEST"
        and isinstance(record.payload.get("tool_use_id"), str)
        and record.payload.get("tool_use_id") in posttool_ids
    )
    capture_times = {
        record.evidence_id: record.captured_at.isoformat()
        for record in records
    }
    return observed, capture_times


def _annotate_execution_observations(
    view: dict[str, Any],
    *,
    control_root: Path,
    session_id: str,
    evidence_metadata: list[Mapping[str, Any]] | None = None,
    execution_observations: tuple[set[str], dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Add display-only PostToolUse status to a result view."""

    if execution_observations is None:
        observed_evidence_ids, capture_times = _execution_observation_metadata(
            control_root,
            session_id,
        )
    else:
        observed_evidence_ids, capture_times = execution_observations
    actions = []
    for action in view.get("actions", []):
        item = dict(action)
        item["execution_observed"] = any(
            evidence_id in observed_evidence_ids
            for evidence_id in item.get("evidence_ids", [])
        )
        if not item.get("observed_at"):
            timestamps = [
                capture_times[evidence_id]
                for evidence_id in item.get("evidence_ids", [])
                if evidence_id in capture_times
            ]
            if timestamps:
                item["observed_at"] = max(timestamps)
        actions.append(item)
    view["actions"] = actions
    view["events"] = safe_event_views(
        actions,
        evidence_metadata=evidence_metadata or (),
    )
    view["evidence_chains"] = evidence_chain_views(
        actions,
        evidence_metadata=evidence_metadata or (),
        attribution_results=view.get("attribution_results", ()),
        recovery=view.get("recovery"),
        integrity=view.get("integrity"),
    )
    view["result_action_chains"] = result_action_chain_views(
        actions,
        evidence_metadata=evidence_metadata or (),
        attribution_results=view.get("attribution_results", ()),
        recovery=view.get("recovery"),
    )
    view["evidence_timeline"] = evidence_timeline_views(
        evidence_metadata or (),
        actions=actions,
        attribution_results=view.get("attribution_results", ()),
    )
    return view


def _runtime_coordinator_reconciliation(state: Mapping[str, Any]) -> dict[str, Any]:
    """Classify whether a persisted non-terminal run still has a coordinator.

    Runtime state is a recovery hint, not a termination authority.  A stale
    state is therefore reported explicitly and never converted into a
    successful or terminal Session result here.
    """

    session = state.get("session") if isinstance(state.get("session"), Mapping) else {}
    session_status = session.get("status")
    if session_status in {"COMPLETED", "ABORTED", "FAILED"}:
        return {
            "status": "TERMINAL",
            "orphaned": False,
            "action": "NONE",
            "detail": "Session is already terminal; the Result Bundle is authoritative.",
        }

    coordinator = state.get("coordinator")
    if not isinstance(coordinator, Mapping):
        return {
            "status": "UNKNOWN",
            "orphaned": False,
            "action": "NO_AUTOMATIC_CONCLUSION",
            "detail": "This runtime snapshot has no coordinator identity; live state cannot be proven.",
        }
    pid = coordinator.get("pid")
    create_time = coordinator.get("create_time")
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 0
        or not isinstance(create_time, (int, float))
        or isinstance(create_time, bool)
    ):
        return {
            "status": "OWNER_UNVERIFIABLE",
            "orphaned": False,
            "action": "DO_NOT_TAKE_OVER",
            "detail": "The persisted AIA coordinator identity is malformed; takeover is refused.",
        }

    try:
        process_status = verify_process_identity(
            ProcessIdentity(pid=pid, create_time=float(create_time))
        )
    except (OSError, ValueError, TypeError):
        process_status = ProcessIdentityStatus.OWNER_UNVERIFIABLE
    if process_status is ProcessIdentityStatus.PID_REUSED:
        # The coordinator create time is recorded with process_create_time
        # (as for the Workspace lease owner).  psutil reports the same instant
        # with different float rounding for most processes, so a live
        # coordinator would look reused.  psutil already proved the PID is
        # live; confirm the identity with the reader that recorded it.
        try:
            if process_create_time(pid) == float(create_time):
                process_status = ProcessIdentityStatus.LIVE_MATCH
        except (OSError, ValueError, TypeError):
            pass

    managed_process = state.get("managed_process")
    agent_process_status = "NOT_RECORDED"
    phase = state.get("phase")
    if (
        managed_process is None
        and phase == "PREPARING"
        and session_status == "PREPARING"
    ):
        # Preparation can fail before the Agent is spawned and before a root
        # identity is persisted. In that narrow state there is no Agent root
        # to terminate; treating it as an evidence gap strands the workspace
        # behind a stale lease after an AIA crash.
        agent_process_status = "NOT_STARTED"
    elif isinstance(managed_process, Mapping):
        root = managed_process.get("root_process_identity")
        root_pid = root.get("pid") if isinstance(root, Mapping) else None
        root_create_time = root.get("create_time") if isinstance(root, Mapping) else None
        if (
            isinstance(root_pid, int)
            and not isinstance(root_pid, bool)
            and root_pid > 0
            and isinstance(root_create_time, (int, float))
            and not isinstance(root_create_time, bool)
        ):
            try:
                agent_process_status = verify_process_identity(
                    ProcessIdentity(
                        pid=root_pid,
                        create_time=float(root_create_time),
                    )
                ).value
            except (OSError, TypeError, ValueError):
                agent_process_status = ProcessIdentityStatus.OWNER_UNVERIFIABLE.value
        else:
            agent_process_status = ProcessIdentityStatus.OWNER_UNVERIFIABLE.value

    if process_status is ProcessIdentityStatus.LIVE_MATCH:
        return {
            "status": "LIVE_MATCH",
            "orphaned": False,
            "action": "NONE",
            "agent_process_status": agent_process_status,
            "acknowledged": False,
            "detail": "The AIA coordinator process identity is still live.",
        }
    if process_status in {
        ProcessIdentityStatus.PROCESS_GONE,
        ProcessIdentityStatus.PID_REUSED,
    }:
        acknowledged = (
            isinstance(state.get("orphan_reconciliation"), Mapping)
            and state["orphan_reconciliation"].get("status") == "ACKNOWLEDGED"
        )
        return {
            "status": (
                "STALE_PROCESS_GONE"
                if process_status is ProcessIdentityStatus.PROCESS_GONE
                else "STALE_PID_REUSED"
            ),
            "orphaned": True,
            "action": "RECONCILED" if acknowledged else "REVIEW_AND_RESTART",
            "agent_process_status": agent_process_status,
            "acknowledged": acknowledged,
            "detail": (
                "The stale run was acknowledged after its recorded Agent root was verified gone."
                if acknowledged
                else "The AIA coordinator is no longer live. Protection cannot be assumed; "
                "review the run and restart only after the old Agent is closed."
            ),
        }
    return {
        "status": "OWNER_UNVERIFIABLE",
        "orphaned": False,
        "action": "DO_NOT_TAKE_OVER",
        "agent_process_status": agent_process_status,
        "acknowledged": False,
        "detail": "The AIA coordinator identity could not be verified; takeover is refused.",
    }


def _workspace_key(value: str | Path) -> str | None:
    """Return a case-insensitive key for comparing persisted workspaces."""

    try:
        return str(Path(value).expanduser().resolve(strict=False)).casefold()
    except (OSError, TypeError, ValueError):
        return None


class RunHistoryMixin:
    def _read_live_evidence_snapshot(
        self,
        session_id: str,
    ) -> tuple[list[dict[str, Any]], set[str], dict[str, str]]:
        try:
            return self.reader.read_live_evidence_snapshot(session_id)
        except (KeyError, OSError, TypeError, ValueError):
            return [], set(), {}

    def get_run_status(self, session_id: str) -> dict[str, Any]:
        live_record = self.registry.get(session_id)
        live_hook_broker_healthy: bool | None = None
        if live_record is not None:
            self._refresh_protection_state(live_record)
            live_hook_broker_healthy = _hook_broker_runtime_healthy(live_record)
        record = self.registry.snapshot(session_id)
        if record is None:
            try:
                status = self._status_from_completed_bundle(session_id)
            except (KeyError, OSError, ValueError):
                runtime_state = self._read_runtime_state(session_id)
                if runtime_state is None:
                    raise
                return self._status_from_runtime_state(runtime_state)
            # Older Result Bundles do not contain the UI-only launch mode.
            # Preserve it from the durable runtime snapshot so a completed
            # Workbench run still opens with the correct terminal context.
            runtime_state = self._read_runtime_state(session_id)
            runtime_launch_mode = (
                runtime_state.get("launch_mode")
                if isinstance(runtime_state, Mapping)
                else None
            )
            if (
                status.get("launch_mode", "inherit") == "inherit"
                and runtime_launch_mode
                and runtime_launch_mode != "inherit"
            ):
                status = dict(status)
                status["launch_mode"] = runtime_launch_mode
                status["session"] = {
                    **(status.get("session") or {}),
                    "launch_mode": runtime_launch_mode,
                }
            # Permission grants are Workbench decisions, not Core evidence; they
            # live in the runtime snapshot and stay visible after the run ends.
            grants = runtime_state.get("permission_grants") if isinstance(runtime_state, Mapping) else None
            if isinstance(grants, list) and grants:
                status = {**status, "permission_grants": grants}
            if isinstance(runtime_state, Mapping) and runtime_state.get("full_access_used") is True:
                status = {**status, "full_access_used": True, "permission_mode": runtime_state.get("permission_mode")}
            thread_id = runtime_state.get("codex_thread_id") if isinstance(runtime_state, Mapping) else None
            if isinstance(thread_id, str) and thread_id:
                status = {**status, "codex_thread_id": thread_id}
            return status
        hook_broker_healthy = (
            live_hook_broker_healthy
            if live_record is not None
            else _hook_broker_runtime_healthy(record)
        )
        incidents = list(record.incidents)
        display_view = {"actions": [dict(item) for item in record.actions]}
        (
            evidence_metadata,
            observed_evidence_ids,
            capture_times,
        ) = self._read_live_evidence_snapshot(session_id)
        _annotate_execution_observations(
            display_view,
            control_root=self.control_root,
            session_id=session_id,
            evidence_metadata=evidence_metadata,
            execution_observations=(observed_evidence_ids, capture_times),
        )
        return {
            "checkpoint": record.checkpoint,
            "error": record.error,
            "incident_count": len(incidents),
            "latest_actions": display_view["actions"][-20:],
            "events": safe_event_views(
                display_view["actions"],
                sensor_health=record.sensor_health,
                evidence_metadata=evidence_metadata,
            ),
            "evidence_chains": display_view["evidence_chains"],
            "evidence_timeline": display_view["evidence_timeline"],
            "lease": record.lease,
            "mode": record.mode,
            "interactive": record.interactive,
            "phase": record.phase,
            "startup": record.startup,
            "permission_grants": record.permission_grants,
            "permission_mode": record.permission_mode,
            "full_access_used": record.full_access_used,
            "codex_thread_id": record.codex_thread_id,
            "resumed_from": record.resumed_from,
            "result_path": str(record.result_path) if record.result_path is not None else None,
            "protection": {
                "state": record.protection_state,
                "hook_events": record.hook_event_count,
                "hook_broker": (
                    "HEALTHY"
                    if hook_broker_healthy is True
                    else "FAILED"
                    if hook_broker_healthy is False
                    else "NOT_STARTED"
                ),
            },
            "stop": {
                "requested": record.stop_requested,
                "error": record.stop_error,
            },
            "policy": {
                "id": record.policy_id,
                "profile": record.policy_profile,
                "version": record.policy_version,
            },
            "bundle_status": record.bundle_status or (
                "PENDING" if record.result_path is None else "UNVERIFIED"
            ),
            "result_available": bool(record.result_path),
            "evidence_summary": self._evidence_summary(
                session_id,
                require_valid=record.result_path is not None,
                metadata=evidence_metadata,
            ),
            "sensor_health": dict(record.sensor_health),
            "session": {
                "agent": record.agent,
                "created_at": record.created_at.isoformat(),
                "model": record.model,
                "session_id": record.session_id,
                "status": record.status,
                "workspace": str(record.workspace),
                "launch_mode": record.launch_mode,
            },
            "launch_mode": record.launch_mode,
        }

    def _status_from_completed_bundle(self, session_id: str) -> dict[str, Any]:
        result = self.reader.read_result(session_id)
        view = result_view(result, self.reader.verification(session_id).status.value)
        evidence_metadata = self._evidence_metadata(
            session_id,
            require_valid=False,
        )
        _annotate_execution_observations(
            view,
            control_root=self.control_root,
            session_id=session_id,
            evidence_metadata=evidence_metadata,
        )
        hook_events = sum(
            1
            for item in evidence_metadata
            if item.get("source") == "AGENT_HOOK"
            and item.get("record_type") == "PRETOOL_REQUEST"
        )
        sensor_failed = any(
            item.get("runtime_health_before_stop") == "FAILED"
            for item in result.get("sensor_summary", [])
            if isinstance(item, Mapping)
        )
        sensor_verified = _sensor_summary_is_verified(result.get("sensor_summary", []))
        protection_downgraded = any(
            item in {
                "CODEX_SANDBOX_DOWNGRADED",
                "CODEX_APPROVAL_POLICY_DOWNGRADED",
                "HOOK_BROKER_RUNTIME_NOT_VERIFIED",
                "PROTECTION_BOUNDARY_LOST",
                "CODEX_PERMISSIONS_USER_GRANTED",
            }
            for item in result.get("limitations", [])
        )
        aborted = (
            result.get("session_status") == "ABORTED"
            and result.get("session_end_reason") == "USER_ABORT"
        )
        if result.get("session_status") == "FAILED" or result.get("session_end_reason") == "PROTECTION_FAILURE":
            protection_state = "FAILED_DEGRADED"
        elif aborted:
            protection_state = (
                "ABORTED_VERIFIED"
                if hook_events and sensor_verified and not sensor_failed and not protection_downgraded
                else "ABORTED_DEGRADED"
            )
        else:
            protection_state = (
                "COMPLETED_VERIFIED"
                if hook_events and sensor_verified and not sensor_failed and not protection_downgraded
                else "COMPLETED_DEGRADED"
            )
        return {
            "checkpoint": self.reader.checkpoint_status(session_id),
            "error": None,
            "incident_count": len(view["incidents"]),
            "latest_actions": view["actions"][-20:],
            "events": view.get("events", []),
            "evidence_chains": view.get("evidence_chains", []),
            "evidence_timeline": view.get("evidence_timeline", []),
            "lease": "RELEASED",
            "mode": view["mode"],
            "phase": view["session_status"],
            "result_path": str(self.result_directory_for(session_id)),
            "protection": {
                "state": protection_state,
                "hook_events": hook_events,
            },
            "stop": {"requested": aborted, "error": None},
            "policy": view["policy"],
            "bundle_status": view["bundle_status"],
            "result_available": True,
            "evidence_summary": self._evidence_summary(
                session_id,
                metadata=evidence_metadata,
            ),
            "sensor_health": {
                item.get("sensor"): item.get("runtime_health_before_stop")
                for item in result.get("sensor_summary", [])
            },
            "session": {
                "agent": result.get("agent"),
                "created_at": result.get("created_at"),
                "model": None,
                "session_id": session_id,
                "status": result.get("session_status"),
                "workspace": result.get("workspace"),
                "launch_mode": result.get("launch_mode", "inherit"),
            },
            "launch_mode": result.get("launch_mode", "inherit"),
        }

    def list_runs(self) -> list[dict[str, Any]]:
        """Return live runs plus valid persisted Bundles for the local console."""

        completed_runs = self._list_completed_runs()
        completed_by_session = {
            item.get("session_id"): item
            for item in completed_runs
            if isinstance(item.get("session_id"), str)
        }
        values: dict[str, dict[str, Any]] = {}
        for state in self._list_runtime_states():
            state = self._runtime_state_for_display(state)
            session = state.get("session") if isinstance(state.get("session"), dict) else {}
            policy = state.get("policy") if isinstance(state.get("policy"), dict) else {}
            protection = state.get("protection") if isinstance(state.get("protection"), dict) else {}
            session_id = state.get("session_id")
            if not isinstance(session_id, str):
                continue
            session_status = session.get("status", "UNKNOWN")
            result_available = bool(state.get("result_available"))
            # A runtime snapshot is only a recovery hint. It must not look
            # like a committed product result when its Result Bundle cannot
            # be verified (for example after an interrupted probe or an old
            # incompatible artifact).
            completed_item = completed_by_session.get(session_id) if result_available else None
            if completed_item is not None and completed_item.get("bundle_status") == "VALID":
                run_classification = "PRODUCT_PROTECTED_RUN"
                bundle_status = "VALID"
            elif session_status in {"COMPLETED", "ABORTED", "FAILED"}:
                run_classification = "UNVERIFIED_RUNTIME_STATE"
                bundle_status = "UNVERIFIED"
            else:
                run_classification = "LIVE_PROTECTED_RUN"
                bundle_status = "PENDING"
            values[session_id] = {
                "session_id": session_id,
                "status": session_status,
                "ended_at": None,
                "created_at": session.get("created_at"),
                "workspace": session.get("workspace"),
                "agent": session.get("agent"),
                "policy": {
                    "id": policy.get("id"),
                    "version": policy.get("version"),
                },
                "run_classification": run_classification,
                "bundle_status": bundle_status,
                "incident_count": state.get("incident_count", 0),
                "result_url": f"/runs/{session_id}/result",
                "protection_state": protection.get("state", "UNKNOWN"),
                "hook_event_count": protection.get("hook_events", 0),
                "launch_mode": state.get("launch_mode", "inherit"),
                "runtime_reconciliation": state.get("runtime_reconciliation"),
            }
        for record in self.registry.snapshots():
            live_record = self.registry.get(record.session_id)
            if live_record is not None:
                self._refresh_protection_state(live_record)
                record = self.registry.snapshot(record.session_id) or record
            if record.status in {"COMPLETED", "ABORTED", "FAILED"} and record.bundle_status != "VALID":
                run_classification = "UNVERIFIED_RUNTIME_STATE"
                bundle_status = "UNVERIFIED"
            else:
                run_classification = "PRODUCT_PROTECTED_RUN"
                bundle_status = record.bundle_status or "PENDING"
            values[record.session_id] = {
                "session_id": record.session_id,
                "status": record.status,
                "ended_at": None,
                "created_at": record.created_at.isoformat(),
                "workspace": str(record.workspace),
                "agent": record.agent,
                "policy": {"id": record.policy_id, "version": record.policy_version},
                "run_classification": run_classification,
                "bundle_status": bundle_status,
                "incident_count": len(record.incidents),
                "result_url": f"/runs/{record.session_id}/result",
                "protection_state": record.protection_state,
                "hook_event_count": record.hook_event_count,
                "launch_mode": record.launch_mode,
            }
        for item in completed_runs:
            existing = values.get(item["session_id"])
            # Result Bundles created before launch_mode became a persisted
            # history field still need to retain the live runtime metadata
            # while that metadata is available.  Otherwise a Workbench run
            # falls back to the generic status page after a refresh.
            if existing and item.get("launch_mode", "inherit") == "inherit":
                item = dict(item)
                item["launch_mode"] = existing.get("launch_mode", "inherit")
            values[item["session_id"]] = item
        return sorted(
            values.values(),
            key=lambda item: str(item.get("ended_at") or item.get("created_at") or ""),
            reverse=True,
        )

    def _runtime_state_for_display(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """Add crash reconciliation metadata to a persisted runtime view."""

        displayed = dict(state)
        reconciliation = _runtime_coordinator_reconciliation(state)
        displayed["runtime_reconciliation"] = reconciliation
        protection = state.get("protection")
        if isinstance(protection, Mapping):
            protection_view = dict(protection)
            if reconciliation.get("orphaned"):
                protection_view["state"] = "ORPHANED_DEGRADED"
            displayed["protection"] = protection_view
        return displayed

    def _status_from_runtime_state(self, state: dict[str, Any]) -> dict[str, Any]:
        state = self._runtime_state_for_display(state)
        session = state.get("session") if isinstance(state.get("session"), dict) else {}
        protection = state.get("protection") if isinstance(state.get("protection"), dict) else {}
        policy = state.get("policy") if isinstance(state.get("policy"), dict) else {}
        stop = state.get("stop") if isinstance(state.get("stop"), dict) else {}
        actions = [
            dict(item)
            for item in state.get("latest_actions", [])
            if isinstance(item, Mapping)
        ]
        display_view = {"actions": actions}
        evidence_metadata = self._evidence_metadata(
            str(state.get("session_id")),
            require_valid=False,
        )
        _annotate_execution_observations(
            display_view,
            control_root=self.control_root,
            session_id=str(state.get("session_id")),
            evidence_metadata=evidence_metadata,
        )
        return {
            "checkpoint": state.get("checkpoint", "UNKNOWN"),
            "error": state.get("error"),
            "incident_count": state.get("incident_count", 0),
            "latest_actions": display_view["actions"],
            "events": safe_event_views(
                display_view["actions"],
                sensor_health=state.get("sensor_health", {}),
                evidence_metadata=evidence_metadata,
            ),
            "evidence_chains": display_view["evidence_chains"],
            "evidence_timeline": display_view["evidence_timeline"],
            "lease": state.get("lease", "UNKNOWN"),
            "mode": state.get("mode"),
            "phase": state.get("phase", session.get("status", "UNKNOWN")),
            "startup": state.get("startup") if isinstance(state.get("startup"), dict) else {},
            "permission_grants": state.get("permission_grants") if isinstance(state.get("permission_grants"), list) else [],
            "permission_mode": state.get("permission_mode") if state.get("permission_mode") in {"full_access", "workspace"} else "workspace",
            "full_access_used": state.get("full_access_used") is True,
            "codex_thread_id": state.get("codex_thread_id") if isinstance(state.get("codex_thread_id"), str) else None,
            "resumed_from": state.get("resumed_from") if isinstance(state.get("resumed_from"), str) else None,
            "result_path": state.get("result_path"),
            "protection": protection,
            "stop": stop,
            "policy": policy,
            "bundle_status": (
                "UNVERIFIED"
                if state.get("result_available")
                else state.get("bundle_status", "PENDING")
            ),
            "result_available": bool(state.get("result_available")),
            "evidence_summary": self._evidence_summary(
                str(state.get("session_id")),
                require_valid=False,
            ),
            "sensor_health": state.get("sensor_health", {}),
            "runtime_reconciliation": state.get("runtime_reconciliation"),
            "session": session,
            "launch_mode": state.get("launch_mode", "inherit"),
        }
