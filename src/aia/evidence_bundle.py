"""Atomic, verifiable Evidence Bundle publication for finalized sessions."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from .result import SessionResult


class EvidenceBundleError(ValueError):
    """Base error for Evidence Bundle operations."""


class ResultAlreadyCommittedConflict(EvidenceBundleError):
    """Raised when an existing committed Session result differs."""

    code = "RESULT_ALREADY_COMMITTED_CONFLICT"


class BundleVerificationStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNCOMMITTED = "UNCOMMITTED"


@dataclass(frozen=True, slots=True)
class BundleVerificationResult:
    status: BundleVerificationStatus
    session_id: str
    result_id: str | None
    reason: str | None = None
    verified_artifact_count: int = 0

    @property
    def is_valid(self) -> bool:
        return self.status is BundleVerificationStatus.VALID


@dataclass(frozen=True, slots=True)
class BundleCommitResult:
    session_id: str
    result_id: str
    result_directory: Path
    commit_marker: Path
    manifest_path: Path
    fingerprint: str
    reused: bool = False
    content_fingerprint: str | None = None


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def _safe_relative(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = Path(normalized)
    first_part = path.parts[0] if path.parts else ""
    if (
        path.is_absolute()
        or ".." in path.parts
        or normalized.startswith("/")
        or len(first_part) >= 2 and first_part[1] == ":"
    ):
        raise EvidenceBundleError("artifact path escapes Session directory")
    return normalized


_VOLATILE_RESULT_FIELDS = frozenset(
    {
        "finalization_completed_at",
        "finalization_duration_ms",
        "finalization_started_at",
    }
)


def canonical_result_fingerprint(result: SessionResult) -> str:
    """Hash semantic Result content while excluding retry timing metadata."""

    mapping = result.to_mapping()
    for field_name in _VOLATILE_RESULT_FIELDS:
        mapping.pop(field_name, None)
    canonical = json.dumps(
        mapping,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(canonical)


class EvidenceBundleVerifier:
    """Verify committed artifacts and external Raw Evidence references."""

    def verify(
        self,
        result_directory: str | Path,
        *,
        on_result_bytes: Callable[[bytes], None] | None = None,
    ) -> BundleVerificationResult:
        result_path = Path(result_directory).expanduser().resolve(strict=False)
        if result_path.name != "result" and (result_path / "result").is_dir():
            result_path = result_path / "result"
        session_directory = result_path.parent
        session_id = session_directory.name
        commit_path = result_path / "commit.json"
        manifest_path = result_path / "evidence-manifest.json"
        if not result_path.exists() or not commit_path.exists():
            return BundleVerificationResult(
                BundleVerificationStatus.UNCOMMITTED,
                session_id,
                None,
                "COMMIT_MARKER_MISSING",
            )
        try:
            commit = json.loads(commit_path.read_text(encoding="utf-8"))
            manifest_bytes = manifest_path.read_bytes()
            manifest = json.loads(manifest_bytes)
        except (OSError, json.JSONDecodeError) as error:
            return BundleVerificationResult(
                BundleVerificationStatus.INVALID,
                session_id,
                None,
                "BUNDLE_METADATA_INVALID",
            )
        result_id = commit.get("result_id")
        try:
            if commit.get("session_id") != session_id or manifest.get("aia_session_id") != session_id:
                raise EvidenceBundleError("SESSION_BINDING_MISMATCH")
            if commit.get("evidence_manifest_sha256") != _sha256_bytes(manifest_bytes):
                raise EvidenceBundleError("MANIFEST_SHA256_MISMATCH")
            if commit.get("bundle_fingerprint") != _sha256_bytes(manifest_bytes):
                raise EvidenceBundleError("BUNDLE_FINGERPRINT_MISMATCH")
            artifacts = manifest.get("artifacts")
            if not isinstance(artifacts, list):
                raise EvidenceBundleError("MANIFEST_ARTIFACTS_INVALID")
            paths = {item.get("relative_path") for item in artifacts if isinstance(item, dict)}
            mandatory = {"result/result.json", "result/audit.jsonl", "result/security-report.md"}
            if not mandatory.issubset(paths):
                raise EvidenceBundleError("MANDATORY_ARTIFACT_MISSING")
            result_bytes: bytes | None = None
            for item in artifacts:
                if not isinstance(item, dict):
                    raise EvidenceBundleError("MANIFEST_ARTIFACT_INVALID")
                relative = _safe_relative(item["relative_path"])
                artifact_path = session_directory / relative
                if not artifact_path.is_file():
                    raise EvidenceBundleError(f"ARTIFACT_MISSING:{relative}")
                data = artifact_path.read_bytes()
                if item.get("byte_size") != len(data) or item.get("sha256") != _sha256_bytes(data):
                    raise EvidenceBundleError(f"ARTIFACT_HASH_MISMATCH:{relative}")
                if item.get("session_id") != session_id:
                    raise EvidenceBundleError(f"ARTIFACT_BINDING_MISMATCH:{relative}")
                if relative == "result/result.json":
                    result_bytes = data
            if result_bytes is None:
                raise EvidenceBundleError("MANDATORY_ARTIFACT_MISSING")
            if on_result_bytes is not None:
                on_result_bytes(result_bytes)
            result_value = json.loads(result_bytes)
            if result_value.get("aia_session_id") != session_id or result_value.get("result_id") != result_id:
                raise EvidenceBundleError("RESULT_BINDING_MISMATCH")
            result = SessionResult.from_mapping(result_value)
            if commit.get("content_fingerprint") != canonical_result_fingerprint(result):
                raise EvidenceBundleError("RESULT_CONTENT_FINGERPRINT_MISMATCH")
        except (EvidenceBundleError, OSError, json.JSONDecodeError, KeyError, TypeError) as error:
            return BundleVerificationResult(
                BundleVerificationStatus.INVALID,
                session_id,
                result_id,
                str(error),
            )
        return BundleVerificationResult(
            BundleVerificationStatus.VALID,
            session_id,
            result_id,
            verified_artifact_count=len(artifacts),
        )


class EvidenceBundleCommitter:
    """Publish one Session Result without exposing partial final artifacts."""

    def __init__(
        self,
        session_directory: str | Path,
        *,
        write_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.session_directory = Path(session_directory).expanduser().resolve(strict=False)
        self.result_directory = self.session_directory / "result"
        self.write_hook = write_hook
        self.verifier = EvidenceBundleVerifier()

    def commit(
        self,
        result: SessionResult,
        *,
        audit_bytes: bytes,
        report_bytes: bytes,
        evidence_artifacts: Iterable[Mapping[str, Any]] = (),
        extra_artifacts: Iterable[Mapping[str, Any]] = (),
        committed_at: datetime | None = None,
    ) -> BundleCommitResult:
        if not isinstance(result, SessionResult):
            raise EvidenceBundleError("result must be a SessionResult")
        content_fingerprint = canonical_result_fingerprint(result)
        self.session_directory.mkdir(parents=True, exist_ok=True)
        if self.result_directory.exists():
            existing = self.verifier.verify(self.result_directory)
            if existing.status is BundleVerificationStatus.VALID:
                try:
                    existing_commit = json.loads(
                        (self.result_directory / "commit.json").read_text(encoding="utf-8")
                    )
                    existing_content_fingerprint = existing_commit.get("content_fingerprint")
                    if existing_content_fingerprint != content_fingerprint:
                        raise ResultAlreadyCommittedConflict(ResultAlreadyCommittedConflict.code)
                except ResultAlreadyCommittedConflict:
                    raise
                except (OSError, json.JSONDecodeError) as error:
                    raise EvidenceBundleError("committed bundle marker is invalid") from error
                if existing.result_id == result.result_id:
                    return BundleCommitResult(
                        result.aia_session_id,
                        result.result_id,
                        self.result_directory,
                        self.result_directory / "commit.json",
                        self.result_directory / "evidence-manifest.json",
                        self._read_fingerprint(),
                        reused=True,
                        content_fingerprint=content_fingerprint,
                    )
                raise ResultAlreadyCommittedConflict(ResultAlreadyCommittedConflict.code)
            if (self.result_directory / "commit.json").exists():
                raise EvidenceBundleError("COMMITTED_BUNDLE_INVALID")
            shutil.rmtree(self.result_directory)

        staging = self.session_directory / f"result.tmp-{uuid4().hex}"
        try:
            self._write(staging / "result.json", result.to_json_bytes())
            self._write(staging / "audit.jsonl", audit_bytes)
            self._write(staging / "security-report.md", report_bytes)
            artifacts = [
                self._artifact(staging / "result.json", "result/result.json", "RESULT", result.aia_session_id),
                self._artifact(staging / "audit.jsonl", "result/audit.jsonl", "AUDIT_TRAIL", result.aia_session_id),
                self._artifact(staging / "security-report.md", "result/security-report.md", "SECURITY_REPORT", result.aia_session_id),
            ]
            for item in (*evidence_artifacts, *extra_artifacts):
                source = Path(item["path"]).expanduser().resolve(strict=False)
                relative = _safe_relative(str(item["relative_path"]))
                if not source.is_file():
                    raise EvidenceBundleError(f"artifact source missing: {source}")
                artifacts.append(
                    self._artifact(
                        source,
                        relative,
                        str(item.get("type", "ARTIFACT")),
                        result.aia_session_id,
                    )
                )
            artifacts.sort(key=lambda item: item["relative_path"])
            manifest = {
                "aia_session_id": result.aia_session_id,
                "artifacts": artifacts,
                "result_id": result.result_id,
                "schema_version": "aia-evidence-manifest-1",
            }
            manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
            self._write(staging / "evidence-manifest.json", manifest_bytes)
            fingerprint = _sha256_bytes(manifest_bytes)
            commit = {
                "bundle_fingerprint": fingerprint,
                "committed_at": (committed_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
                "content_fingerprint": content_fingerprint,
                "evidence_manifest_sha256": fingerprint,
                "result_id": result.result_id,
                "schema_version": "aia-commit-1",
                "session_id": result.aia_session_id,
            }
            self._write(
                staging / "commit.json",
                (json.dumps(commit, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"),
            )
            os.replace(staging, self.result_directory)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise
        verification = self.verifier.verify(self.result_directory)
        if verification.status is not BundleVerificationStatus.VALID:
            raise EvidenceBundleError(f"bundle commit verification failed: {verification.reason}")
        return BundleCommitResult(
            result.aia_session_id,
            result.result_id,
            self.result_directory,
            self.result_directory / "commit.json",
            self.result_directory / "evidence-manifest.json",
            fingerprint,
            content_fingerprint=content_fingerprint,
        )

    def _write(self, path: Path, value: bytes) -> None:
        self.write_hook(path.name) if self.write_hook is not None else None
        _write_bytes(path, value)

    @staticmethod
    def _artifact(path: Path, relative: str, artifact_type: str, session_id: str) -> dict[str, Any]:
        data = path.read_bytes()
        return {
            "artifact_type": artifact_type,
            "byte_size": len(data),
            "relative_path": relative.replace("\\", "/"),
            "session_id": session_id,
            "sha256": _sha256_bytes(data),
        }

    def _read_fingerprint(self) -> str:
        try:
            return json.loads((self.result_directory / "commit.json").read_text(encoding="utf-8"))["bundle_fingerprint"]
        except (OSError, KeyError, json.JSONDecodeError) as error:
            raise EvidenceBundleError("committed bundle marker is invalid") from error


def verify_evidence_bundle(
    result_directory: str | Path,
    *,
    on_result_bytes: Callable[[bytes], None] | None = None,
) -> BundleVerificationResult:
    return EvidenceBundleVerifier().verify(
        result_directory,
        on_result_bytes=on_result_bytes,
    )


__all__ = [
    "BundleCommitResult",
    "BundleVerificationResult",
    "BundleVerificationStatus",
    "EvidenceBundleCommitter",
    "EvidenceBundleError",
    "EvidenceBundleVerifier",
    "canonical_result_fingerprint",
    "ResultAlreadyCommittedConflict",
    "verify_evidence_bundle",
]
