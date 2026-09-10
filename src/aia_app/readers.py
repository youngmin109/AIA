"""Read-only, verified readers for completed Core Result Bundles."""

from __future__ import annotations

import json
from pathlib import Path
import re
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

    def read_result_json(self, session_id: str) -> bytes:
        result_directory = self.result_directory(session_id)
        self._require_valid(session_id)
        return (result_directory / "result.json").read_bytes()

    def read_evidence_metadata(self, session_id: str) -> list[dict[str, Any]]:
        session_directory = self.session_directory(session_id)
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
