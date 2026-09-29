"""Run history and completed-status presentation for the application service."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from aia import RawEvidenceStore

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
) -> dict[str, Any]:
    """Add display-only PostToolUse status to a result view."""

    observed_evidence_ids, capture_times = _execution_observation_metadata(
        control_root,
        session_id,
    )
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


class RunHistoryMixin:
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
            return status
        hook_broker_healthy = (
            live_hook_broker_healthy
            if live_record is not None
            else _hook_broker_runtime_healthy(record)
        )
        incidents = list(record.incidents)
        display_view = {"actions": [dict(item) for item in record.actions]}
        evidence_metadata = self._evidence_metadata(session_id, require_valid=False)
        _annotate_execution_observations(
            display_view,
            control_root=self.control_root,
            session_id=session_id,
            evidence_metadata=evidence_metadata,
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

