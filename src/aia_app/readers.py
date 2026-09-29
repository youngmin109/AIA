"""Read-only, verified readers for completed Core Result Bundles."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
from threading import RLock
from typing import Any, Callable

from aia import BundleVerificationStatus, verify_evidence_bundle


_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9-]+$")
_PARSED_FILE_CACHE_LIMIT = 512


class ResultBundleReader:
    """Read completed bundles without exposing arbitrary local files."""

    def __init__(self, control_root: str | Path) -> None:
        self.control_root = Path(control_root).expanduser().resolve(strict=False)
        self._parsed_cache_lock = RLock()
        self._result_cache: dict[Path, tuple[int, int, bytes, dict[str, Any]]] = {}
        self._metadata_cache: dict[Path, tuple[int, int, bytes, list[dict[str, Any]]]] = {}

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

    def verification(
        self,
        session_id: str,
        *,
        on_result_bytes: Callable[[bytes], None] | None = None,
        on_raw_evidence_bytes: Callable[[bytes], None] | None = None,
    ):
        result_directory = self.result_directory(session_id)
        if not result_directory.is_dir():
            return None
        return verify_evidence_bundle(
            result_directory,
            on_result_bytes=on_result_bytes,
            on_raw_evidence_bytes=on_raw_evidence_bytes,
        )

    def _read_verified_result(
        self,
        session_id: str,
    ) -> tuple[dict[str, Any], Any, bytes | None]:
        """Read a result together with the single verification used for it."""

        result_directory = self.result_directory(session_id)
        verified_result_bytes: bytes | None = None
        verified_raw_evidence_bytes: bytes | None = None

        def capture_result_bytes(contents: bytes) -> None:
            nonlocal verified_result_bytes
            verified_result_bytes = contents

        def capture_raw_evidence_bytes(contents: bytes) -> None:
            nonlocal verified_raw_evidence_bytes
            verified_raw_evidence_bytes = contents

        verification = self.verification(
            session_id,
            on_result_bytes=capture_result_bytes,
            on_raw_evidence_bytes=capture_raw_evidence_bytes,
        )
        if verification is None or verification.status is not BundleVerificationStatus.VALID:
            raise ValueError("Evidence Bundle Integrity Failure")
        result_path = result_directory / "result.json"
        if verified_result_bytes is None:
            return self._read_json(result_path), verification, verified_raw_evidence_bytes
        try:
            stat = result_path.stat()
        except OSError:
            return (
                self._parse_json_bytes(verified_result_bytes),
                verification,
                verified_raw_evidence_bytes,
            )
        contents = verified_result_bytes
        digest = hashlib.blake2b(contents, digest_size=16).digest()
        signature = (stat.st_mtime_ns, stat.st_size, digest)
        with self._parsed_cache_lock:
            cached = self._result_cache.get(result_path)
            if cached is not None and cached[:3] == signature:
                result = deepcopy(cached[3])
            else:
                result = self._parse_json_bytes(contents)
                self._result_cache[result_path] = (*signature, result)
                if len(self._result_cache) > _PARSED_FILE_CACHE_LIMIT:
                    self._result_cache.pop(next(iter(self._result_cache)))
        return result, verification, verified_raw_evidence_bytes

    def read_result(self, session_id: str) -> dict[str, Any]:
        result, _, _ = self._read_verified_result(session_id)
        return result

    def read_report(self, session_id: str) -> str:
        result_directory = self.result_directory(session_id)
        self._require_valid(session_id)
        return (result_directory / "security-report.md").read_text(encoding="utf-8")

    def read_result_json(self, session_id: str) -> bytes:
        result_directory = self.result_directory(session_id)
        self._require_valid(session_id)
        return (result_directory / "result.json").read_bytes()

    def read_evidence_metadata(
        self,
        session_id: str,
        *,
        require_valid: bool = True,
        verified_bytes: bytes | None = None,
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
        try:
            stat = path.stat()
        except OSError:
            return []
        contents = path.read_bytes() if verified_bytes is None else verified_bytes
        digest = hashlib.blake2b(contents, digest_size=16).digest()
        signature = (stat.st_mtime_ns, stat.st_size, digest)
        with self._parsed_cache_lock:
            cached = self._metadata_cache.get(path)
            if cached is not None and cached[:3] == signature:
                return [
                    {**item, "payload_keys": list(item["payload_keys"])}
                    for item in cached[3]
                ]
        items: list[dict[str, Any]] = []
        for line_number, line in enumerate(contents.decode("utf-8").splitlines(), 1):
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
        with self._parsed_cache_lock:
            cached_items = [
                {**item, "payload_keys": list(item["payload_keys"])}
                for item in items
            ]
            self._metadata_cache[path] = (*signature, cached_items)
            if len(self._metadata_cache) > _PARSED_FILE_CACHE_LIMIT:
                self._metadata_cache.pop(next(iter(self._metadata_cache)))
        return items

    def list_completed(self) -> list[dict[str, Any]]:
        """List only committed, valid Result Bundles under this Control Root."""

        sessions = self.control_root / "sessions"
        if not sessions.is_dir():
            return []
        completed: list[dict[str, Any]] = []

        candidates = [
            candidate
            for candidate in sessions.iterdir()
            if candidate.is_dir() and _SAFE_SESSION_ID.fullmatch(candidate.name)
        ]
        verified_candidates: list[
            tuple[Path, dict[str, Any], Any, bytes | None]
        ] = []

        def read_verified_candidate(
            candidate: Path,
        ) -> tuple[dict[str, Any], Any, bytes | None] | None:
            try:
                return self._read_verified_result(candidate.name)
            except (OSError, ValueError, KeyError):
                return None

        with ThreadPoolExecutor(max_workers=4) as executor:
            # executor.map keeps results in candidate order while work overlaps.
            for candidate, verified_result in zip(
                candidates, executor.map(read_verified_candidate, candidates)
            ):
                if verified_result is None:
                    continue
                result, verification, raw_evidence_bytes = verified_result
                if verification is None:
                    continue
                verified_candidates.append(
                    (candidate, result, verification, raw_evidence_bytes)
                )

        for candidate, result, verification, raw_evidence_bytes in verified_candidates:
            evidence_metadata = (
                self.read_evidence_metadata(
                    candidate.name,
                    require_valid=False,
                    verified_bytes=raw_evidence_bytes,
                )
                if raw_evidence_bytes is not None
                else []
            )
            hook_event_count = sum(
                1
                for item in evidence_metadata
                if item.get("source") == "AGENT_HOOK"
                and item.get("record_type") == "PRETOOL_REQUEST"
            )
            posttool_event_count = sum(
                1
                for item in evidence_metadata
                if item.get("source") == "AGENT_HOOK"
                and item.get("record_type") == "POSTTOOL_OBSERVED"
            )
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
                    "launch_mode": result.get("launch_mode", "inherit"),
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

    def checkpoint_status(self, session_id: str) -> str:
        """Return a display-safe status for the completed run Checkpoint.

        A completed Result Bundle does not put the preparation Checkpoint ID in
        ``SessionResult`` unless Recovery used it.  The Checkpoint metadata and
        manifest are committed as separately hashed artifacts, so use those
        already-verified artifacts to preserve the preparation status in the
        UI.  Unknown is intentional for older bundles or bundles that do not
        prove a valid Checkpoint.
        """

        try:
            self._require_valid(session_id)
            session_directory = self.session_directory(session_id)
            manifest = self._read_json(
                self.result_directory(session_id) / "evidence-manifest.json"
            )
            artifacts = manifest.get("artifacts")
            if not isinstance(artifacts, list):
                return "UNKNOWN"

            artifact_types: dict[Path, set[str]] = {}
            for item in artifacts:
                if not isinstance(item, dict):
                    continue
                relative_path = item.get("relative_path")
                if not isinstance(relative_path, str):
                    continue
                artifact_path = self._safe_artifact_path(
                    session_directory,
                    relative_path,
                )
                if artifact_path is None:
                    continue
                artifact_types.setdefault(artifact_path, set()).add(
                    str(item.get("artifact_type", ""))
                )

            for metadata_path, types in artifact_types.items():
                if "CHECKPOINT_METADATA" not in types or metadata_path.name != "metadata.json":
                    continue
                checkpoint_path = metadata_path.parent
                manifest_path = checkpoint_path / "manifest.json"
                if "CHECKPOINT_MANIFEST" not in artifact_types.get(manifest_path, set()):
                    continue
                try:
                    metadata = self._read_json(metadata_path)
                    if (
                        metadata.get("session_id") != session_id
                        or metadata.get("validity") != "VALID"
                        or metadata.get("checkpoint_id") != checkpoint_path.name
                    ):
                        continue
                    if metadata.get("schema_version") == "1.0":
                        return "READY"
                except (OSError, ValueError, KeyError):
                    continue
        except (OSError, ValueError, KeyError):
            return "UNKNOWN"
        return "UNKNOWN"

    def _require_valid(self, session_id: str) -> None:
        verification = self.verification(session_id)
        if verification is None or verification.status is not BundleVerificationStatus.VALID:
            raise ValueError("Evidence Bundle Integrity Failure")

    @staticmethod
    def _safe_artifact_path(
        session_directory: Path,
        relative_path: str,
    ) -> Path | None:
        """Resolve a manifest path while keeping it inside the Session."""

        normalized = relative_path.replace("\\", "/")
        parsed = PurePosixPath(normalized)
        if (
            not normalized
            or parsed.is_absolute()
            or any(part in {"", ".", ".."} for part in parsed.parts)
        ):
            return None
        candidate = (session_directory / Path(*parsed.parts)).resolve(strict=False)
        try:
            candidate.relative_to(session_directory.resolve(strict=False))
        except ValueError:
            return None
        return candidate

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            return ResultBundleReader._parse_json_bytes(path.read_bytes())
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError("result bundle JSON is invalid") from error

    @staticmethod
    def _parse_json_bytes(contents: bytes) -> dict[str, Any]:
        try:
            value = json.loads(contents)
        except json.JSONDecodeError as error:
            raise ValueError("result bundle JSON is invalid") from error
        if not isinstance(value, dict):
            raise ValueError("result bundle JSON must be an object")
        return value
