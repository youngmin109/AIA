"""Read-only, verified readers for completed Core Result Bundles."""

from __future__ import annotations

import json
from pathlib import Path
from pathlib import PurePath, PureWindowsPath
import re
import math
from typing import Any

from aia import BundleVerificationStatus, verify_evidence_bundle


_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9-]+$")


class ResultBundleReader:
    """Read completed bundles without exposing arbitrary local files."""

    def __init__(self, control_root: str | Path) -> None:
        self.control_root = Path(control_root).expanduser().resolve(strict=False)

    def session_directory(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not _SAFE_SESSION_ID.fullmatch(session_id):
            raise ValueError("invalid session_id")
        sessions = (self.control_root / "sessions").resolve(strict=False)
        candidate = (sessions / session_id).resolve(strict=False)
        if not candidate.is_relative_to(sessions):
            raise ValueError("session path escaped control root")
        return candidate

    def result_directory(self, session_id: str) -> Path:
        return self.session_directory(session_id) / "result"

    def verification(self, session_id: str):
        result_directory = self.result_directory(session_id)
        if not result_directory.is_dir():
            return None
        return verify_evidence_bundle(result_directory)

    def read_result(self, session_id: str) -> dict[str, Any]:
        result_directory = self.result_directory(session_id)
        verification = self.verification(session_id)
        if verification is None or verification.status is not BundleVerificationStatus.VALID:
            raise ValueError("Evidence Bundle Integrity Failure")
        return self._read_json(result_directory / "result.json")

    def read_report(self, session_id: str) -> str:
        result_directory = self.result_directory(session_id)
        self._require_valid(session_id)
        return (result_directory / "security-report.md").read_text(encoding="utf-8")

    def read_audit_records(self, session_id: str) -> list[dict[str, Any]]:
        """Read the finalized, integrity-verified Audit Trail records."""

        result_directory = self.result_directory(session_id)
        self._require_valid(session_id)
        path = result_directory / "audit.jsonl"
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"audit trail contains invalid JSON at line {line_number}") from error
            if not isinstance(record, dict):
                raise ValueError(f"audit trail record at line {line_number} is invalid")
            # AuditRecord is a bounded reference record. Keep the web view on
            # that schema and never pass raw sensor payloads through this path.
            records.append(
                {
                    key: record[key]
                    for key in (
                        "audit_id",
                        "aia_session_id",
                        "occurred_at",
                        "event_type",
                        "entity_type",
                        "entity_id",
                        "source_reference",
                        "action_id",
                        "reason_code",
                        "summary",
                    )
                    if key in record
                }
            )
        return records

    def read_result_json(self, session_id: str) -> bytes:
        result_directory = self.result_directory(session_id)
        self._require_valid(session_id)
        return (result_directory / "result.json").read_bytes()

    def read_evidence_metadata(
        self,
        session_id: str,
        *,
        require_valid: bool = True,
    ) -> list[dict[str, Any]]:
        """Read metadata without returning Evidence payload values.

        Completed-result callers keep the default verified-bundle requirement.
        Live-run status may opt out because the bundle does not exist until
        finalization; that path still returns metadata keys only and never
        exposes raw payload values.
        """

        session_directory = self.session_directory(session_id)
        if require_valid:
            self._require_valid(session_id)
        path = session_directory / "evidence" / "raw-evidence.jsonl"
        if not path.is_file():
            return []
        items: list[dict[str, Any]] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                items.append({"line": line_number, "status": "MALFORMED"})
                continue
            payload = record.get("payload")
            items.append(
                {
                    "captured_at": record.get("captured_at"),
                    "evidence_id": record.get("evidence_id"),
                    "line": line_number,
                    "observation_stage": record.get("observation_stage"),
                    "payload_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
                    "record_type": record.get("record_type"),
                    "source": record.get("source"),
                }
            )
        return items

    def read_process_tree(self, session_id: str, *, require_valid: bool = True) -> list[dict[str, Any]]:
        """Read a redacted process tree from Process Runtime Evidence.

        The view deliberately omits executable paths, command lines, and
        process creation timestamps. Creation timestamps are used internally
        to avoid joining reused PIDs to the wrong parent.
        """

        session_directory = self.session_directory(session_id)
        if require_valid:
            self._require_valid(session_id)
        path = session_directory / "evidence" / "raw-evidence.jsonl"
        if not path.is_file():
            return []

        observed: dict[tuple[int, float], dict[str, Any]] = {}
        exited: set[tuple[int, float]] = set()
        root_identities: set[tuple[int, float]] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                not isinstance(record, dict)
                or record.get("session_id") != session_id
                or record.get("source") != "PROCESS_RUNTIME"
            ):
                continue
            record_type = record.get("record_type")
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            identity = self._process_identity(payload.get("pid"), payload.get("create_time"))
            root_identity = self._process_identity(
                payload.get("root_pid"), payload.get("root_create_time")
            )
            if identity is None or root_identity is None:
                continue
            if record_type == "PROCESS_EXIT_OBSERVED":
                exited.add(identity)
                root_identities.add(root_identity)
                continue
            if record_type != "PROCESS_OBSERVED":
                continue

            role = payload.get("process_role")
            if role not in {"ROOT", "CHILD"}:
                continue
            ppid = payload.get("ppid", payload.get("parent_pid"))
            if not isinstance(ppid, int) or isinstance(ppid, bool) or ppid < 0:
                ppid = None
            parent_identity = self._process_identity(
                payload.get("parent_pid", ppid), payload.get("parent_create_time")
            )
            name = payload.get("name")
            executable = payload.get("executable")
            label = name if isinstance(name, str) and name else executable
            if isinstance(label, str):
                label = PureWindowsPath(label).name or PurePath(label).name
            else:
                label = "프로세스 이름 확인 불가"
            observed[identity] = {
                "evidence_id": record.get("evidence_id"),
                "identity": identity,
                "parent_identity": parent_identity,
                "parent_pid": ppid,
                "pid": identity[0],
                "process_role": role,
                "root_identity": root_identity,
                "name": label[:120],
                "observed_at": payload.get("observed_at") or record.get("captured_at"),
            }
            root_identities.add(root_identity)

        output: list[dict[str, Any]] = []
        for root_identity in sorted(root_identities):
            members = {
                identity: item
                for identity, item in observed.items()
                if item["root_identity"] == root_identity
            }
            evidence_id_by_identity = {
                identity: item.get("evidence_id") for identity, item in members.items()
            }
            for identity, item in members.items():
                if item["process_role"] != "ROOT" and item["parent_identity"] not in members:
                    # Keep an observed descendant even if its parent exited
                    # before the first observation, but do not invent a link.
                    item = {**item, "parent_pid": None}
                else:
                    item = dict(item)
                parent_identity = item.get("parent_identity")
                item["node_id"] = item.get("evidence_id")
                item["parent_node_id"] = evidence_id_by_identity.get(parent_identity)
                item["state"] = "EXIT_OBSERVED" if identity in exited else "OBSERVED"
                item.pop("identity", None)
                item.pop("parent_identity", None)
                item.pop("root_identity", None)
                output.append(item)
        return sorted(
            output,
            key=lambda item: (
                0 if item["process_role"] == "ROOT" else 1,
                item["parent_pid"] or 0,
                item["pid"],
            ),
        )

    def read_workspace_changes(
        self,
        session_id: str,
        workspace_root: str | Path,
        *,
        require_valid: bool = True,
    ) -> list[dict[str, Any]]:
        """Read bounded, path-redacted File Sensor change events."""

        session_directory = self.session_directory(session_id)
        if require_valid:
            self._require_valid(session_id)
        root = Path(workspace_root).expanduser().resolve(strict=False)
        path = session_directory / "evidence" / "raw-evidence.jsonl"
        if not path.is_file():
            return []

        changes: list[dict[str, Any]] = []
        supported_types = {"created", "modified", "deleted", "moved"}
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                not isinstance(record, dict)
                or record.get("session_id") != session_id
                or record.get("source") != "FILESYSTEM_WATCHER"
                or record.get("record_type") != "FILESYSTEM_EVENT"
            ):
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict) or payload.get("event_type") not in supported_types:
                continue
            source_path = self._workspace_relative_path(payload.get("src_path"), root)
            if source_path is None:
                continue
            destination_path = None
            if payload.get("event_type") == "moved":
                destination_path = self._workspace_relative_path(payload.get("dest_path"), root)
                if destination_path is None:
                    destination_path = "Workspace 밖"
            changes.append(
                {
                    "evidence_id": record.get("evidence_id"),
                    "event_type": payload["event_type"],
                    "source_path": source_path,
                    "destination_path": destination_path,
                    "is_directory": bool(payload.get("is_directory", False)),
                    "occurred_at": record.get("captured_at"),
                }
            )
        return changes[-100:]

    @staticmethod
    def _workspace_relative_path(value: Any, workspace_root: Path) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = workspace_root / candidate
            resolved = candidate.resolve(strict=False)
            relative = resolved.relative_to(workspace_root)
        except (OSError, RuntimeError, ValueError):
            return None
        return relative.as_posix() or "."

    @staticmethod
    def _process_identity(pid: Any, create_time: Any) -> tuple[int, float] | None:
        try:
            normalized_create_time = float(create_time)
        except (OverflowError, TypeError, ValueError):
            return None
        if (
            not isinstance(pid, int)
            or isinstance(pid, bool)
            or pid <= 0
            or not isinstance(create_time, (int, float))
            or isinstance(create_time, bool)
            or not math.isfinite(normalized_create_time)
            or create_time < 0
        ):
            return None
        return pid, normalized_create_time

    def list_completed(self) -> list[dict[str, Any]]:
        """List only committed, valid Result Bundles under this Control Root."""

        sessions = self.control_root / "sessions"
        if not sessions.is_dir():
            return []
        completed: list[dict[str, Any]] = []
        for candidate in sessions.iterdir():
            if not candidate.is_dir() or not _SAFE_SESSION_ID.fullmatch(candidate.name):
                continue
            try:
                result = self.read_result(candidate.name)
                verification = self.verification(candidate.name)
            except (OSError, ValueError, KeyError):
                continue
            if verification is None:
                continue
            hook_event_count = self.hook_event_count(candidate.name)
            posttool_event_count = self.posttool_event_count(candidate.name)
            session_status = result.get("session_status")
            session_end_reason = result.get("session_end_reason")
            protection_downgraded = any(
                item in {
                    "CODEX_SANDBOX_DOWNGRADED",
                    "CODEX_APPROVAL_POLICY_DOWNGRADED",
                    "HOOK_BROKER_RUNTIME_NOT_VERIFIED",
                    "PROTECTION_BOUNDARY_LOST",
                }
                for item in result.get("limitations", ())
            )
            completed.append(
                {
                    "session_id": candidate.name,
                    "status": result.get("session_status"),
                    "ended_at": result.get("ended_at"),
                    "created_at": result.get("created_at"),
                    "workspace": result.get("workspace"),
                    "agent": result.get("agent"),
                    "policy": result.get("policy", {}),
                    "run_classification": result.get("run_classification"),
                    "bundle_status": verification.status.value,
                    "protection_state": (
                        "FAILED_DEGRADED"
                        if session_status == "FAILED"
                        or session_end_reason == "PROTECTION_FAILURE"
                        else "ABORTED_VERIFIED"
                        if session_status == "ABORTED"
                        and session_end_reason == "USER_ABORT"
                        and hook_event_count
                        and not protection_downgraded
                        else "ABORTED_DEGRADED"
                        if session_status == "ABORTED"
                        and session_end_reason == "USER_ABORT"
                        else "COMPLETED_VERIFIED"
                        if hook_event_count and not protection_downgraded
                        else "COMPLETED_DEGRADED"
                    ),
                    "hook_event_count": hook_event_count,
                    "posttool_event_count": posttool_event_count,
                    "incident_count": sum(
                        1
                        for item in result.get("action_outcomes", ())
                        if item.get("policy_decision") in {"VIOLATION", "INDETERMINATE"}
                    ),
                    "result_url": f"/runs/{candidate.name}/result",
                }
            )
        return sorted(
            completed,
            key=lambda item: str(item.get("ended_at") or item.get("created_at") or ""),
            reverse=True,
        )

    def hook_event_count(self, session_id: str) -> int:
        """Count verified PreTool records without exposing their payloads."""

        return sum(
            1
            for item in self.read_evidence_metadata(session_id)
            if item.get("source") == "AGENT_HOOK"
            and item.get("record_type") == "PRETOOL_REQUEST"
        )

    def posttool_event_count(self, session_id: str) -> int:
        """Count bounded PostTool observations without exposing tool output."""

        return sum(
            1
            for item in self.read_evidence_metadata(session_id)
            if item.get("source") == "AGENT_HOOK"
            and item.get("record_type") == "POSTTOOL_OBSERVED"
        )

    def _require_valid(self, session_id: str) -> None:
        verification = self.verification(session_id)
        if verification is None or verification.status is not BundleVerificationStatus.VALID:
            raise ValueError("Evidence Bundle Integrity Failure")

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("result bundle JSON is invalid") from error
        if not isinstance(value, dict):
            raise ValueError("result bundle JSON must be an object")
        return value
