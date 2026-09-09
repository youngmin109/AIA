"""Agent Hook and PreTool Raw Evidence sensor."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any

from ..checkpoint import CheckpointValidity, SafeCheckpoint, validate_checkpoint
from ..evidence import (
    EvidenceRecordType,
    EvidenceSource,
    EvidenceStoreError,
    ObservationStage,
    RawEvidenceRecord,
    RawEvidenceStore,
)
from ..protection import (
    ControlRoot,
    ProtectionPreparationContext,
    WorkspaceLeaseManager,
)
from ..session import ProtectedRunSession, SessionStatus
from .base import (
    SensorAlreadyRunningError,
    SensorError,
    SensorHealth,
    SensorStartError,
    SensorStatus,
    SensorStopError,
)


class HookInputError(SensorError):
    """Raised when a Hook payload cannot become a validated observation."""

    code = "INVALID_HOOK_PAYLOAD"


class UnsupportedHookEventError(HookInputError):
    """Raised when a Hook event has no supported product meaning."""

    code = "UNSUPPORTED_HOOK_EVENT"


class HookPayloadTooLargeError(HookInputError):
    """Raised when an ingress payload exceeds the bounded input size."""

    code = "HOOK_PAYLOAD_TOO_LARGE"


class HookNotHealthyError(HookInputError):
    """Raised when input arrives before a Hook Sensor is healthy."""

    code = "HOOK_SENSOR_NOT_HEALTHY"


class HookEvidenceStoreError(SensorError):
    """Raised when Hook Raw Evidence cannot be appended."""

    code = "EVIDENCE_STORE_FAILURE"


_SUPPORTED_EVENT = "PRE_TOOL_USE"
_MAX_PAYLOAD_BYTES = 64 * 1024
_ALLOWED_TOP_LEVEL_KEYS = frozenset(
    {
        "aia_session_id",
        "agent",
        "agent_native_session_id",
        "turn_id",
        "tool_use_id",
        "tool_name",
        "tool_input",
        "hook_event_name",
        "source_metadata",
    }
)
_REQUIRED_TOP_LEVEL_KEYS = frozenset(
    {
        "aia_session_id",
        "agent",
        "tool_use_id",
        "tool_name",
        "tool_input",
        "hook_event_name",
    }
)
_SELECTED_TOOL_INPUT_KEYS = frozenset({"path", "command", "cwd", "target"})
_SAFE_SOURCE_METADATA_KEYS = frozenset(
    {"adapter", "channel", "event_id", "provider", "transport"}
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HookInputError(f"{field_name} must be a non-empty string")
    return value


def _control_root_for_context(
    session: ProtectedRunSession,
    context: ProtectionPreparationContext,
) -> ControlRoot:
    try:
        control_directory = context.control_directory.resolve(strict=True)
    except OSError as error:
        raise SensorStartError("Protection control directory is unavailable") from error
    root = ControlRoot.for_workspace(
        session.workspace,
        control_directory.parent.parent,
    )
    if root.session_directory(session.session_id) != control_directory:
        raise SensorStartError("Protection context control directory is invalid")
    return root


def _validate_preparation(
    session: ProtectedRunSession,
    context: ProtectionPreparationContext,
    checkpoint: SafeCheckpoint,
) -> None:
    if not isinstance(session, ProtectedRunSession):
        raise SensorStartError("session must be a ProtectedRunSession")
    if not isinstance(context, ProtectionPreparationContext):
        raise SensorStartError(
            "context must be a ProtectionPreparationContext"
        )
    if not isinstance(checkpoint, SafeCheckpoint):
        raise SensorStartError("checkpoint must be a SafeCheckpoint")
    if session.status is not SessionStatus.PREPARING:
        raise SensorStartError("Hook Sensor requires PREPARING Session")
    if context.session_id != session.session_id:
        raise SensorStartError("Protection context Session ID does not match")
    if context.workspace != session.workspace:
        raise SensorStartError("Protection context Workspace does not match")
    if context.active_policy.session_id != session.session_id:
        raise SensorStartError("Active Policy does not belong to Session")
    if context.workspace_lease.session_id != session.session_id:
        raise SensorStartError("Workspace Lease does not belong to Session")
    if context.workspace_lease.workspace != session.workspace:
        raise SensorStartError("Workspace Lease Workspace does not match")
    if checkpoint.session_id != session.session_id:
        raise SensorStartError("Checkpoint does not belong to Session")
    if checkpoint.workspace != session.workspace:
        raise SensorStartError("Checkpoint Workspace does not match")
    if checkpoint.validity is not CheckpointValidity.VALID:
        raise SensorStartError("Hook Sensor requires a VALID Checkpoint")
    validation = validate_checkpoint(checkpoint)
    if validation.validity is not CheckpointValidity.VALID:
        raise SensorStartError("Checkpoint validation failed")


def _json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError) as error:
        raise HookInputError("Hook payload must be JSON serializable") from error


def _decode_payload(
    payload: Mapping[str, Any] | str | bytes,
    *,
    max_payload_bytes: int,
) -> Mapping[str, Any]:
    if isinstance(payload, bytes):
        if len(payload) > max_payload_bytes:
            raise HookPayloadTooLargeError("Hook payload exceeds size limit")
        try:
            decoded = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise HookInputError("Hook payload is not valid UTF-8") from error
        try:
            value = json.loads(decoded)
        except json.JSONDecodeError as error:
            raise HookInputError("Hook payload is malformed JSON") from error
    elif isinstance(payload, str):
        if len(payload.encode("utf-8")) > max_payload_bytes:
            raise HookPayloadTooLargeError("Hook payload exceeds size limit")
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as error:
            raise HookInputError("Hook payload is malformed JSON") from error
    elif isinstance(payload, Mapping):
        if _json_size(payload) > max_payload_bytes:
            raise HookPayloadTooLargeError("Hook payload exceeds size limit")
        value = payload
    else:
        raise HookInputError("Hook payload must be a JSON object")
    if not isinstance(value, Mapping):
        raise HookInputError("Hook payload must be a JSON object")
    return value


def _select_source_metadata(value: Any) -> dict[str, str | int | float | bool]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise HookInputError("source_metadata must be an object")
    selected: dict[str, str | int | float | bool] = {}
    for key in _SAFE_SOURCE_METADATA_KEYS:
        if key not in value:
            continue
        item = value[key]
        if not isinstance(item, (str, int, float, bool)):
            raise HookInputError(
                f"source_metadata.{key} must be a scalar value"
            )
        selected[key] = item
    return selected


def _select_tool_input(value: Any) -> tuple[dict[str, Any], str | None, str | None]:
    if not isinstance(value, Mapping):
        raise HookInputError("tool_input must be an object")
    selected: dict[str, Any] = {}
    for key in _SELECTED_TOOL_INPUT_KEYS - {"command"}:
        if key not in value:
            continue
        item = value[key]
        if key in {"path", "cwd"} and not isinstance(item, str):
            raise HookInputError(f"tool_input.{key} must be a string")
        if key == "target" and not isinstance(item, (str, Mapping)):
            raise HookInputError("tool_input.target must be a string or object")
        if _json_size(item) > _MAX_PAYLOAD_BYTES:
            raise HookPayloadTooLargeError("tool_input field exceeds size limit")
        selected[key] = item
    raw_command = value.get("command")
    if raw_command is not None:
        if not isinstance(raw_command, str) or not raw_command:
            raise HookInputError("tool_input.command must be a non-empty string")
        if _json_size(raw_command) > _MAX_PAYLOAD_BYTES:
            raise HookPayloadTooLargeError("tool_input.command exceeds size limit")
    cwd = selected.get("cwd")
    return selected, raw_command, cwd


@dataclass(frozen=True, slots=True)
class ValidatedHookRequest:
    """Validated, minimal Hook input before Raw Evidence serialization."""

    aia_session_id: str
    agent: str
    agent_native_session_id: str | None
    turn_id: str | None
    tool_use_id: str
    tool_name: str
    tool_input: Mapping[str, Any]
    raw_command: str | None
    hook_event_name: str
    source_metadata: Mapping[str, str | int | float | bool]
    ingress_verified: bool = False

    def to_pretool_payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "agent": self.agent,
            "aia_session_id": self.aia_session_id,
            "command_observed": self.raw_command is not None,
            "hook_event_name": self.hook_event_name,
            "ingress_status": "UNVERIFIED",
            "ingress_verified": self.ingress_verified,
            "source_metadata": dict(self.source_metadata),
            "tool_input": dict(self.tool_input),
            "tool_name": self.tool_name,
            "tool_use_id": self.tool_use_id,
        }
        if self.agent_native_session_id is not None:
            result["agent_native_session_id"] = self.agent_native_session_id
        if self.turn_id is not None:
            result["turn_id"] = self.turn_id
        return result


def validate_hook_input(
    payload: Mapping[str, Any] | str | bytes,
    *,
    expected_session_id: str,
    expected_agent: str,
    max_payload_bytes: int = _MAX_PAYLOAD_BYTES,
) -> ValidatedHookRequest:
    """Validate the product Hook boundary without interpreting tool semantics."""

    value = _decode_payload(payload, max_payload_bytes=max_payload_bytes)
    unknown_keys = set(value) - _ALLOWED_TOP_LEVEL_KEYS
    if unknown_keys:
        raise HookInputError(
            f"unsupported Hook fields: {', '.join(sorted(map(str, unknown_keys)))}"
        )
    missing = _REQUIRED_TOP_LEVEL_KEYS - set(value)
    if missing:
        raise HookInputError(
            f"missing Hook fields: {', '.join(sorted(missing))}"
        )
    aia_session_id = _required_text(
        value["aia_session_id"],
        field_name="aia_session_id",
    )
    if aia_session_id != expected_session_id:
        raise HookInputError("aia_session_id does not match the protected Session")
    agent = _required_text(value["agent"], field_name="agent")
    if agent != expected_agent:
        raise HookInputError("agent does not match the protected Session")
    event_name = _required_text(
        value["hook_event_name"],
        field_name="hook_event_name",
    )
    if event_name != _SUPPORTED_EVENT:
        raise UnsupportedHookEventError(
            f"unsupported Hook event: {event_name}"
        )
    tool_use_id = _required_text(value["tool_use_id"], field_name="tool_use_id")
    tool_name = _required_text(value["tool_name"], field_name="tool_name")
    agent_native_session_id = value.get("agent_native_session_id")
    if agent_native_session_id is not None:
        agent_native_session_id = _required_text(
            agent_native_session_id,
            field_name="agent_native_session_id",
        )
    turn_id = value.get("turn_id")
    if turn_id is not None:
        turn_id = _required_text(turn_id, field_name="turn_id")
    tool_input, raw_command, _ = _select_tool_input(value["tool_input"])
    source_metadata = _select_source_metadata(value.get("source_metadata"))
    return ValidatedHookRequest(
        aia_session_id=aia_session_id,
        agent=agent,
        agent_native_session_id=agent_native_session_id,
        turn_id=turn_id,
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        tool_input=tool_input,
        raw_command=raw_command,
        hook_event_name=event_name,
        source_metadata=source_metadata,
    )


validate_hook_payload = validate_hook_input


@dataclass(frozen=True, slots=True)
class HookSensorContext:
    aia_session_id: str
    agent: str
    workspace: Path
    status: SensorStatus
    started_at: datetime
    evidence_path: Path
    ingress_verified: bool
    health: SensorHealth

    @property
    def session_id(self) -> str:
        return self.aia_session_id


class HookSensor:
    """Collect validated PreTool and Command Raw Evidence only."""

    def __init__(
        self,
        session: ProtectedRunSession,
        context: ProtectionPreparationContext,
        checkpoint: SafeCheckpoint,
        *,
        lease_manager: WorkspaceLeaseManager | None = None,
        evidence_store: RawEvidenceStore | None = None,
        max_payload_bytes: int = _MAX_PAYLOAD_BYTES,
    ) -> None:
        self.session = session
        self.preparation_context = context
        self.checkpoint = checkpoint
        self.lease_manager = lease_manager
        self.max_payload_bytes = max_payload_bytes
        self._control_root: ControlRoot | None = None
        if evidence_store is None:
            try:
                control_directory = context.control_directory.resolve(strict=False)
                evidence_store = RawEvidenceStore(
                    control_directory / "evidence" / "raw-evidence.jsonl",
                    session_id=session.session_id,
                )
            except (OSError, ValueError, TypeError) as error:
                raise SensorStartError("Evidence Store path cannot be prepared") from error
        if evidence_store.session_id not in {None, session.session_id}:
            raise SensorStartError("Evidence Store Session ID does not match")
        if evidence_store.path.is_relative_to(session.workspace):
            raise SensorStartError("Evidence Store must be outside Workspace")
        evidence_root = (
            context.control_directory.resolve(strict=False) / "evidence"
        ).resolve(strict=False)
        if not evidence_store.path.is_relative_to(evidence_root):
            raise SensorStartError(
                "Evidence Store must be under the Session Control Root"
            )
        self.evidence_store = evidence_store
        self._lock = RLock()
        self._status = SensorStatus.STOPPED
        self._started_at: datetime | None = None
        self._health = SensorHealth(
            EvidenceSource.AGENT_HOOK,
            SensorStatus.STOPPED,
            _now_utc(),
            reason="NOT_STARTED",
        )

    @property
    def status(self) -> SensorStatus:
        return self.check_health().status

    @property
    def health(self) -> SensorHealth:
        return self.check_health()

    @property
    def context(self) -> HookSensorContext:
        return self._context()

    def start(self) -> HookSensorContext:
        with self._lock:
            if self._status in {SensorStatus.STARTING, SensorStatus.HEALTHY}:
                raise SensorAlreadyRunningError(
                    "Agent Hook Sensor is already running"
                )
            self._status = SensorStatus.STARTING
            self._health = SensorHealth(
                EvidenceSource.AGENT_HOOK,
                SensorStatus.STARTING,
                _now_utc(),
                reason="STARTING",
            )
            try:
                self._set_health(SensorStatus.STARTING, "STARTING", append=True)
                if self._status is not SensorStatus.STARTING:
                    raise SensorStartError(
                        "Agent Hook starting health could not be persisted"
                    )
                _validate_preparation(
                    self.session,
                    self.preparation_context,
                    self.checkpoint,
                )
                self._control_root = _control_root_for_context(
                    self.session,
                    self.preparation_context,
                )
                manager = self.lease_manager or WorkspaceLeaseManager(
                    self._control_root
                )
                manager.validate_ownership(self.preparation_context.workspace_lease)
                self._started_at = _now_utc()
                self._set_health(SensorStatus.HEALTHY, "STARTED", append=True)
                if self._status is not SensorStatus.HEALTHY:
                    raise SensorStartError(
                        "Agent Hook health could not be persisted"
                    )
                return self._context()
            except Exception as error:
                if self._health.reason != "EVIDENCE_STORE_FAILURE":
                    self._set_health(
                        SensorStatus.FAILED,
                        self._failure_reason(error, "START_FAILED"),
                        append=True,
                    )
                if isinstance(error, SensorStartError):
                    raise
                raise SensorStartError("Agent Hook Sensor failed to start") from error

    def stop(self) -> HookSensorContext:
        with self._lock:
            if self._status is SensorStatus.STOPPED:
                return self._context()
            if self._status is SensorStatus.FAILED:
                return self._context()
            try:
                self._set_health(SensorStatus.STOPPED, "STOPPED", append=True)
                if self._status is not SensorStatus.STOPPED:
                    raise SensorStopError(
                        "Agent Hook stop health could not be persisted"
                    )
                return self._context()
            except Exception as error:
                if self._health.reason != "EVIDENCE_STORE_FAILURE":
                    self._set_health(
                        SensorStatus.FAILED,
                        self._failure_reason(error, "STOP_FAILED"),
                        append=True,
                    )
                if isinstance(error, SensorStopError):
                    raise
                raise SensorStopError("Agent Hook Sensor failed to stop") from error

    def check_health(self) -> SensorHealth:
        with self._lock:
            return self._health

    def observe(
        self,
        payload: Mapping[str, Any] | str | bytes,
    ) -> tuple[RawEvidenceRecord, ...]:
        """Validate and append PreTool evidence, plus Command evidence if present."""

        with self._lock:
            if self._status is not SensorStatus.HEALTHY:
                raise HookNotHealthyError("Agent Hook Sensor is not HEALTHY")
            request = validate_hook_input(
                payload,
                expected_session_id=self.session.session_id,
                expected_agent=self.session.agent,
                max_payload_bytes=self.max_payload_bytes,
            )
            pretool_record = RawEvidenceRecord(
                session_id=self.session.session_id,
                source=EvidenceSource.AGENT_HOOK,
                record_type=EvidenceRecordType.PRETOOL_REQUEST,
                captured_at=_now_utc(),
                observation_stage=ObservationStage.PRE_ACTION,
                payload=request.to_pretool_payload(),
            )
            try:
                self.evidence_store.append(pretool_record)
                records = [pretool_record]
                raw_command = request.raw_command
                if isinstance(raw_command, str):
                    command_payload: dict[str, Any] = {
                        "ingress_status": "UNVERIFIED",
                        "ingress_verified": False,
                        "parent_evidence_id": pretool_record.evidence_id,
                        "raw_command": raw_command,
                        "tool_use_id": request.tool_use_id,
                    }
                    cwd = request.tool_input.get("cwd")
                    if isinstance(cwd, str):
                        command_payload["cwd"] = cwd
                    if request.agent_native_session_id is not None:
                        command_payload[
                            "agent_native_session_id"
                        ] = request.agent_native_session_id
                    if request.turn_id is not None:
                        command_payload["turn_id"] = request.turn_id
                    command_record = RawEvidenceRecord(
                        session_id=self.session.session_id,
                        source=EvidenceSource.AGENT_HOOK,
                        record_type=EvidenceRecordType.COMMAND_OBSERVED,
                        captured_at=_now_utc(),
                        observation_stage=ObservationStage.PRE_ACTION,
                        payload=command_payload,
                    )
                    self.evidence_store.append(command_record)
                    records.append(command_record)
                return tuple(records)
            except EvidenceStoreError as error:
                self._set_failed("EVIDENCE_STORE_FAILURE", append=True)
                raise HookEvidenceStoreError(
                    "Hook Raw Evidence could not be appended"
                ) from error

    record = observe
    ingest = observe

    def _context(self) -> HookSensorContext:
        started_at = self._started_at or self._health.checked_at
        return HookSensorContext(
            aia_session_id=self.session.session_id,
            agent=self.session.agent,
            workspace=self.session.workspace,
            status=self._status,
            started_at=started_at,
            evidence_path=self.evidence_store.path,
            ingress_verified=False,
            health=self._health,
        )

    def _set_failed(self, reason: str, *, append: bool) -> None:
        self._set_health(SensorStatus.FAILED, reason, append=append)

    def _set_health(
        self,
        status: SensorStatus,
        reason: str,
        *,
        append: bool,
    ) -> None:
        self._status = status
        self._health = SensorHealth(
            EvidenceSource.AGENT_HOOK,
            status,
            _now_utc(),
            reason=reason,
        )
        if not append:
            return
        record = RawEvidenceRecord(
            session_id=self.session.session_id,
            source=EvidenceSource.AGENT_HOOK,
            record_type=EvidenceRecordType.SENSOR_HEALTH,
            captured_at=self._health.checked_at,
            observation_stage=ObservationStage.PRE_ACTION,
            payload=self._health.to_mapping() | {"reason": reason},
        )
        try:
            self.evidence_store.append(record)
        except EvidenceStoreError:
            if status is not SensorStatus.FAILED:
                self._status = SensorStatus.FAILED
                self._health = SensorHealth(
                    EvidenceSource.AGENT_HOOK,
                    SensorStatus.FAILED,
                    _now_utc(),
                    reason="EVIDENCE_STORE_FAILURE",
                )

    def _failure_reason(self, error: Exception, fallback: str) -> str:
        if isinstance(error, SensorError):
            return getattr(error, "code", fallback)
        return fallback


__all__ = [
    "HookEvidenceStoreError",
    "HookInputError",
    "HookNotHealthyError",
    "HookPayloadTooLargeError",
    "HookSensor",
    "HookSensorContext",
    "SensorAlreadyRunningError",
    "SensorError",
    "SensorHealth",
    "SensorStartError",
    "SensorStatus",
    "SensorStopError",
    "UnsupportedHookEventError",
    "ValidatedHookRequest",
    "validate_hook_input",
    "validate_hook_payload",
]
