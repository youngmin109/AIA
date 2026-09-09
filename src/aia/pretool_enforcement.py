"""Trusted PreTool ingress and the Codex deny execution boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
from pathlib import Path
import secrets
from threading import Lock
from typing import Any, TYPE_CHECKING

from .enforcement import (
    EnforcementAction,
    EnforcementDecision,
    EnforcementExecutionResult,
    EnforcementGate,
    EnforcementGateInput,
    EnforcementGateResult,
    EnforcementReason,
    EnforcementRoute,
    HookTrustStatus,
)
from .session import ProtectedRunSession, canonicalize_workspace

if TYPE_CHECKING:
    from .launcher import ProtectedLaunchContext


class PreToolEnforcementError(ValueError):
    """Raised when a trusted PreTool boundary cannot be established."""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PreToolEnforcementError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PreToolEnforcementError(f"{field_name} must be non-empty")
    return value


@dataclass(frozen=True, slots=True, repr=False)
class HookCapability:
    """A per-launch capability; only its hash is suitable for evidence."""

    aia_session_id: str
    launch_id: str
    capability_hash: str
    _secret: str = field(repr=False)
    artifact_path: Path | None = field(default=None, repr=False)

    @classmethod
    def create(
        cls,
        aia_session_id: str,
        launch_id: str,
        control_directory: str | Path,
    ) -> "HookCapability":
        secret = secrets.token_urlsafe(32)
        digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        directory = Path(control_directory).resolve(strict=False)
        directory.mkdir(parents=True, exist_ok=True)
        artifact = directory / "hook-capability.bin"
        # The secret is held in the AIA control root only.  It is never part
        # of a Raw Evidence payload, response, repr, or reason string.
        artifact.write_text(secret, encoding="utf-8")
        try:
            artifact.chmod(0o600)
        except OSError:
            pass
        return cls(
            aia_session_id=_text(aia_session_id, field_name="aia_session_id"),
            launch_id=_text(launch_id, field_name="launch_id"),
            capability_hash=digest,
            _secret=secret,
            artifact_path=artifact,
        )

    def verify(self, supplied: Any) -> bool:
        return isinstance(supplied, str) and hmac.compare_digest(supplied, self._secret)

    def public_mapping(self) -> dict[str, str]:
        return {
            "aia_session_id": self.aia_session_id,
            "aia_launch_id": self.launch_id,
            "capability_hash": self.capability_hash,
        }


@dataclass(frozen=True, slots=True)
class TrustedHookIngress:
    """Result of verifying an AIA-managed PreTool event envelope."""

    status: HookTrustStatus
    reason: str
    aia_session_id: str | None = None
    launch_id: str | None = None
    agent_native_session_id: str | None = None
    turn_id: str | None = None
    tool_use_id: str | None = None
    tool_name: str | None = None
    cwd: str | None = None

    @property
    def ingress_verified(self) -> bool:
        return self.status is HookTrustStatus.VERIFIED


class HookEnforcementBridge:
    """Session and launch scoped bridge state used by trusted PreTool input."""

    def __init__(self) -> None:
        self._capability: HookCapability | None = None
        self._prepared_at: datetime | None = None
        self._workspace: Path | None = None
        self._native_session_id: str | None = None
        self._lock = Lock()

    @property
    def ready(self) -> bool:
        return self._capability is not None and self._prepared_at is not None

    @property
    def ready_at(self) -> datetime | None:
        return self._prepared_at

    @property
    def capability_hash(self) -> str | None:
        return self._capability.capability_hash if self._capability is not None else None

    @property
    def native_session_id(self) -> str | None:
        return self._native_session_id

    def prepare(
        self,
        *,
        aia_session_id: str,
        launch_id: str,
        workspace: str | Path,
        control_directory: str | Path,
        agent_native_session_id: str | None = None,
        at: datetime | None = None,
    ) -> datetime:
        with self._lock:
            if self.ready:
                raise PreToolEnforcementError("Hook Enforcement Bridge is already prepared")
            workspace_path = canonicalize_workspace(workspace)
            control_path = Path(control_directory).resolve(strict=False)
            try:
                control_path.relative_to(workspace_path)
            except ValueError:
                pass
            else:
                raise PreToolEnforcementError(
                    "Hook Enforcement Bridge control directory must be outside Workspace"
                )
            self._capability = HookCapability.create(aia_session_id, launch_id, control_directory)
            self._workspace = workspace_path
            self._native_session_id = agent_native_session_id
            self._prepared_at = _aware_utc(at or _now_utc(), field_name="prepared_at")
            return self._prepared_at

    def verify(
        self,
        payload: Mapping[str, Any],
        *,
        session: ProtectedRunSession,
        launch_context: "ProtectedLaunchContext | None" = None,
    ) -> TrustedHookIngress:
        """Verify the official Codex fields plus the AIA bridge envelope."""

        if not self.ready or self._capability is None or self._workspace is None:
            return TrustedHookIngress(HookTrustStatus.UNAVAILABLE, "HOOK_BRIDGE_UNAVAILABLE")
        if not isinstance(payload, Mapping):
            return TrustedHookIngress(HookTrustStatus.UNVERIFIED, "HOOK_PAYLOAD_INVALID")
        required = (
            "hook_event_name",
            "session_id",
            "turn_id",
            "tool_use_id",
            "cwd",
            "tool_name",
            "tool_input",
            "aia_session_id",
            "aia_launch_id",
            "aia_capability",
        )
        if any(key not in payload for key in required):
            return TrustedHookIngress(HookTrustStatus.UNVERIFIED, "HOOK_REQUIRED_FIELD_MISSING")
        if payload.get("hook_event_name") != "PreToolUse":
            return TrustedHookIngress(HookTrustStatus.UNVERIFIED, "HOOK_EVENT_UNSUPPORTED")
        try:
            native_id = _text(payload["session_id"], field_name="session_id")
            turn_id = _text(payload["turn_id"], field_name="turn_id")
            tool_use_id = _text(payload["tool_use_id"], field_name="tool_use_id")
            tool_name = _text(payload["tool_name"], field_name="tool_name")
            cwd = _text(payload["cwd"], field_name="cwd")
            aia_session_id = _text(payload["aia_session_id"], field_name="aia_session_id")
            launch_id = _text(payload["aia_launch_id"], field_name="aia_launch_id")
        except PreToolEnforcementError:
            return TrustedHookIngress(HookTrustStatus.UNVERIFIED, "HOOK_FIELD_INVALID")
        if aia_session_id != self._capability.aia_session_id or aia_session_id != session.session_id:
            return TrustedHookIngress(HookTrustStatus.MISMATCHED, "SESSION_MISMATCH", aia_session_id=aia_session_id)
        if launch_id != self._capability.launch_id:
            return TrustedHookIngress(HookTrustStatus.MISMATCHED, "LAUNCH_ID_MISMATCH", aia_session_id=aia_session_id, launch_id=launch_id)
        if launch_context is not None and launch_context.launch_id != launch_id:
            return TrustedHookIngress(HookTrustStatus.MISMATCHED, "LAUNCH_ID_MISMATCH", aia_session_id=aia_session_id, launch_id=launch_id)
        try:
            cwd_path = canonicalize_workspace(cwd)
            cwd_path.relative_to(self._workspace)
        except (ValueError, OSError):
            return TrustedHookIngress(HookTrustStatus.MISMATCHED, "WORKSPACE_CWD_MISMATCH", aia_session_id=aia_session_id, launch_id=launch_id)
        if not self._capability.verify(payload.get("aia_capability")):
            return TrustedHookIngress(HookTrustStatus.UNVERIFIED, "CAPABILITY_MISMATCH", aia_session_id=aia_session_id, launch_id=launch_id)
        with self._lock:
            if self._native_session_id is None:
                self._native_session_id = native_id
            elif self._native_session_id != native_id:
                return TrustedHookIngress(
                    HookTrustStatus.MISMATCHED,
                    EnforcementReason.NATIVE_SESSION_MISMATCH.value,
                    aia_session_id=aia_session_id,
                    launch_id=launch_id,
                    agent_native_session_id=native_id,
                    turn_id=turn_id,
                    tool_use_id=tool_use_id,
                    tool_name=tool_name,
                    cwd=cwd,
                )
        return TrustedHookIngress(
            HookTrustStatus.VERIFIED,
            "AIA_MANAGED_SESSION_SCOPED_HOOK",
            aia_session_id=aia_session_id,
            launch_id=launch_id,
            agent_native_session_id=native_id,
            turn_id=turn_id,
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            cwd=cwd,
        )


@dataclass(frozen=True, slots=True)
class CodexPreToolResponse:
    """Wire response. Empty mapping is deliberately neutral."""

    gate_result: EnforcementGateResult
    mapping: Mapping[str, Any]
    deny_emitted_at: datetime | None
    pretool_received_at: datetime
    gate_decided_at: datetime
    pretool_gate_latency_ms: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "mapping", dict(self.mapping))
        object.__setattr__(self, "pretool_received_at", _aware_utc(self.pretool_received_at, field_name="pretool_received_at"))
        object.__setattr__(self, "gate_decided_at", _aware_utc(self.gate_decided_at, field_name="gate_decided_at"))
        if self.deny_emitted_at is not None:
            object.__setattr__(self, "deny_emitted_at", _aware_utc(self.deny_emitted_at, field_name="deny_emitted_at"))

    def to_mapping(self) -> dict[str, Any]:
        return dict(self.mapping)


@dataclass(frozen=True, slots=True)
class PreToolExecutionConfirmation:
    """Adapter observation of actual Codex block behavior."""

    blocked: bool | None
    observed_at: datetime | None = None
    source: str = "codex"

    def __post_init__(self) -> None:
        if self.blocked is not None and not isinstance(self.blocked, bool):
            raise ValueError("blocked must be bool or None")
        if self.observed_at is not None:
            object.__setattr__(self, "observed_at", _aware_utc(self.observed_at, field_name="observed_at"))


@dataclass(frozen=True, slots=True)
class PreToolExecutionResult:
    action: EnforcementAction
    execution_result: EnforcementExecutionResult
    reason: str
    confirmed_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", EnforcementAction(self.action))
        object.__setattr__(self, "execution_result", EnforcementExecutionResult(self.execution_result))
        if self.confirmed_at is not None:
            object.__setattr__(self, "confirmed_at", _aware_utc(self.confirmed_at, field_name="confirmed_at"))


@dataclass(frozen=True, slots=True)
class PreToolDecision:
    gate_result: EnforcementGateResult
    pretool_received_at: datetime
    gate_decided_at: datetime
    response: CodexPreToolResponse

    @property
    def pretool_gate_latency_ms(self) -> float:
        return self.response.pretool_gate_latency_ms

    def confirm(self, confirmation: PreToolExecutionConfirmation) -> PreToolExecutionResult:
        if (
            self.gate_result.decision is not EnforcementDecision.CONTAIN
            or self.gate_result.route is not EnforcementRoute.PRETOOL_BLOCK
        ):
            return PreToolExecutionResult(
                EnforcementAction.NONE,
                EnforcementExecutionResult.FAILED,
                "NO_PRETOOL_CONTAINMENT_ROUTE",
            )
        if confirmation.blocked is True:
            return PreToolExecutionResult(
                EnforcementAction.BLOCKED,
                EnforcementExecutionResult.SUCCEEDED,
                "CODEX_BLOCK_CONFIRMED",
                confirmation.observed_at or _now_utc(),
            )
        if confirmation.blocked is False:
            return PreToolExecutionResult(
                EnforcementAction.NONE,
                EnforcementExecutionResult.FAILED,
                EnforcementReason.HOOK_ENFORCEMENT_FAILURE.value,
                confirmation.observed_at,
            )
        return PreToolExecutionResult(
            EnforcementAction.NONE,
            EnforcementExecutionResult.FAILED,
            EnforcementReason.BLOCK_CONFIRMATION_UNAVAILABLE.value,
            confirmation.observed_at,
        )


class PreToolEnforcementAdapter:
    """Convert a pure Gate result into a Codex-neutral or deny response."""

    def __init__(self, gate: EnforcementGate | None = None) -> None:
        self.gate = gate or EnforcementGate()

    def evaluate(
        self,
        gate_input: EnforcementGateInput,
        *,
        pretool_received_at: datetime | None = None,
        gate_decided_at: datetime | None = None,
    ) -> PreToolDecision:
        received = _aware_utc(pretool_received_at or _now_utc(), field_name="pretool_received_at")
        decided = _aware_utc(gate_decided_at or _now_utc(), field_name="gate_decided_at")
        if decided < received:
            raise PreToolEnforcementError("gate_decided_at must not precede pretool_received_at")
        result = self.gate.evaluate(gate_input)
        denied = (
            result.decision is EnforcementDecision.CONTAIN
            and result.route is EnforcementRoute.PRETOOL_BLOCK
        )
        if denied:
            reason = self._safe_deny_reason(gate_input, result)
            mapping: Mapping[str, Any] = {
                "decision": "block",
                "reason": reason,
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                },
            }
            emitted_at = decided
        else:
            # Empty output preserves Codex's native permission handling.  AIA
            # never turns CONTINUE or REFUSE into an explicit allow.
            mapping = {}
            emitted_at = None
        latency = max(0.0, (decided - received).total_seconds() * 1000)
        response = CodexPreToolResponse(
            gate_result=result,
            mapping=mapping,
            deny_emitted_at=emitted_at,
            pretool_received_at=received,
            gate_decided_at=decided,
            pretool_gate_latency_ms=latency,
        )
        return PreToolDecision(result, received, decided, response)

    @staticmethod
    def _safe_deny_reason(
        gate_input: EnforcementGateInput,
        result: EnforcementGateResult,
    ) -> str:
        policy = gate_input.policy_evaluation
        rule_ids = ",".join(policy.matched_rule_ids) or "UNSPECIFIED"
        asset = policy.asset_type.value if policy.asset_type is not None else "UNSPECIFIED"
        return (
            f"AIA policy violation; rule_ids={rule_ids}; "
            f"asset_type={asset}; operation={policy.operation.value}"
        )


def evaluate_pretool(
    gate_input: EnforcementGateInput,
    *,
    gate: EnforcementGate | None = None,
    pretool_received_at: datetime | None = None,
    gate_decided_at: datetime | None = None,
) -> PreToolDecision:
    return PreToolEnforcementAdapter(gate).evaluate(
        gate_input,
        pretool_received_at=pretool_received_at,
        gate_decided_at=gate_decided_at,
    )


__all__ = [
    "CodexPreToolResponse",
    "HookCapability",
    "HookEnforcementBridge",
    "PreToolDecision",
    "PreToolEnforcementAdapter",
    "PreToolEnforcementError",
    "PreToolExecutionConfirmation",
    "PreToolExecutionResult",
    "TrustedHookIngress",
    "evaluate_pretool",
]
