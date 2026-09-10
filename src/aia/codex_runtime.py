"""Actual Codex PreToolUse transport and protected evaluation runtime.

The Codex command hook runs in a separate process.  This module keeps the
authoritative AIA Session, frozen policy, sensors, and Enforcement Gate in the
parent process and exposes only a loopback, capability-authenticated request
endpoint to the hook process.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from typing import Any, TYPE_CHECKING
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid5

from .action import NormalizedAction
from .adapters import CodexHookAdapter, CodexHookPayloadError
from .attribution import AttributionEngine, AttributionResult
from .enforcement import (
    EnforcementAction,
    EnforcementDecision,
    EnforcementExecutionResult,
    EnforcementGate,
    EnforcementGateInput,
    EnforcementGateResult,
    EnforcementRoute,
    HookTrustStatus,
)
from .evidence import ObservationStage, RawEvidenceRecord
from .normalizer import normalize_evidence
from .policy import PolicyDecision
from .pretool_enforcement import (
    CodexPreToolResponse,
    HookEnforcementBridge,
    PreToolDecision,
    PreToolExecutionConfirmation,
    protected_pretool_deny,
)
from .runtime_policy import RuntimePolicyEvaluation, RuntimePolicyEvaluator
from .session import ProtectedRunSession
from .process_manager import ProcessTerminationResult

if TYPE_CHECKING:
    from .checkpoint import SafeCheckpoint
    from .protection import ProtectionPreparationContext, WorkspaceLeaseManager
    from .sensors.filesystem import FilesystemSensor
    from .sensors.hook import HookSensor


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class CodexPreToolEvent:
    """One real Codex PreToolUse evaluation preserved by the runtime."""

    tool_use_id: str
    records: tuple[RawEvidenceRecord, ...]
    action: NormalizedAction
    policy_evaluation: RuntimePolicyEvaluation
    attribution: AttributionResult
    gate_result: EnforcementGateResult
    decision: PreToolDecision
    confirmed_block: bool | None = None


@dataclass(frozen=True, slots=True)
class CodexPostActionContainment:
    """A verified post-action containment attempt for a bypassed PreTool deny."""

    source_event: CodexPreToolEvent
    action: NormalizedAction
    policy_evaluation: RuntimePolicyEvaluation
    attribution: AttributionResult
    gate_result: EnforcementGateResult
    termination_result: ProcessTerminationResult | None = None
    termination_error: str | None = None


class CodexPreToolController:
    """Bridge native Codex events into the existing AIA decision pipeline."""

    def __init__(
        self,
        session: ProtectedRunSession,
        preparation_context: "ProtectionPreparationContext",
        filesystem_sensor: "FilesystemSensor",
        hook_sensor: "HookSensor",
        *,
        checkpoint: "SafeCheckpoint",
        lease_manager: "WorkspaceLeaseManager",
        bridge: HookEnforcementBridge,
        launch_context_provider: Callable[[], Any | None],
        process_sensor_provider: Callable[[], Any | None],
        post_action_containment_callback: Callable[
            [CodexPostActionContainment], ProcessTerminationResult | None
        ] | None = None,
    ) -> None:
        self.session = session
        self.preparation_context = preparation_context
        self.filesystem_sensor = filesystem_sensor
        self.hook_sensor = hook_sensor
        self.checkpoint = checkpoint
        self.lease_manager = lease_manager
        self.bridge = bridge
        self.launch_context_provider = launch_context_provider
        self.process_sensor_provider = process_sensor_provider
        self.post_action_containment_callback = post_action_containment_callback
        self._events: list[CodexPreToolEvent] = []
        self._post_action_containments: list[CodexPostActionContainment] = []
        self._errors: list[str] = []
        self._lock = threading.RLock()

    @property
    def events(self) -> tuple[CodexPreToolEvent, ...]:
        with self._lock:
            return tuple(self._events)

    @property
    def errors(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._errors)

    @property
    def post_action_containments(self) -> tuple[CodexPostActionContainment, ...]:
        with self._lock:
            return tuple(self._post_action_containments)

    def evaluate(self, native_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Evaluate one native Codex payload and return the Codex wire response."""

        try:
            native = CodexHookAdapter.verify_ingress(
                self._bridge_payload(native_payload),
                bridge=self.bridge,
                session=self.session,
                launch_context=self.launch_context_provider(),
            )
        except (CodexHookPayloadError, ValueError) as error:
            self._record_error(f"INVALID_CODEX_PRETOOL: {error}")
            return protected_pretool_deny("INVALID_PRETOOL_EVENT")

        if native.status is not HookTrustStatus.VERIFIED:
            self._record_error(f"CODEX_INGRESS_{native.status.value}: {native.reason}")
            return protected_pretool_deny("UNTRUSTED_PRETOOL_INGRESS")

        try:
            records = self.hook_sensor.observe(
                self._sensor_payload(native_payload, native)
            )
            normalized = normalize_evidence(
                records,
                aia_session_id=self.session.session_id,
                workspace=self.session.workspace,
            )
            actions = tuple(normalized.actions)
            if len(actions) != 1:
                self._record_error("PRETOOL_NORMALIZATION_DID_NOT_PRODUCE_ONE_ACTION")
                # An empty response is Codex hook success and therefore
                # continues the tool call.  A bound Protected Run must not
                # turn an unclassifiable PreTool event into that fall-through.
                return protected_pretool_deny("PRETOOL_NORMALIZATION_FAILED")
            action = actions[0]
            launch_context = self.launch_context_provider()
            attribution = AttributionEngine(
                self.session.session_id,
                records,
                launch_context=launch_context,
                expected_agent_native_session_id=native.agent_native_session_id,
            ).attribute(action)
            policy_evaluation = RuntimePolicyEvaluator(
                self.preparation_context.active_policy,
                session_id=self.session.session_id,
            ).evaluate(action)
            process_sensor = self.process_sensor_provider()
            sensor_health = tuple(
                sensor.health
                for sensor in (
                    self.filesystem_sensor,
                    self.hook_sensor,
                    process_sensor,
                )
                if sensor is not None
            )
            gate_input = EnforcementGateInput(
                action=action,
                policy_evaluation=policy_evaluation,
                attribution=attribution,
                session=self.session,
                active_policy=self.preparation_context.active_policy,
                launch_context=launch_context,
                workspace_lease=self.preparation_context.workspace_lease,
                sensor_health=sensor_health,
                hook_trust_status=HookTrustStatus.VERIFIED,
                checked_at=_now_utc(),
            )
            decision = PreToolDecisionPlaceholder.evaluate(gate_input, self.lease_manager)
            event = CodexPreToolEvent(
                tool_use_id=native.tool_use_id or "",
                records=records,
                action=action,
                policy_evaluation=policy_evaluation,
                attribution=attribution,
                gate_result=decision.gate_result,
                decision=decision,
            )
            with self._lock:
                self._events.append(event)
            return decision.response.to_mapping()
        except Exception as error:
            self._record_error(f"PRETOOL_EVALUATION_FAILED: {type(error).__name__}: {error}")
            return protected_pretool_deny("PRETOOL_EVALUATION_FAILED")

    def handle(self, native_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Dispatch the two synchronous tool lifecycle events we observe.

        PreToolUse remains the only event that can return a deny decision.
        PostToolUse is evidence only; it can prove that a tool ran after a
        containment decision, but it cannot undo that tool's side effects.
        """

        if native_payload.get("hook_event_name") == "PostToolUse":
            return self.observe_posttool(native_payload)
        return self.evaluate(native_payload)

    def observe_posttool(self, native_payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Record a bounded post-tool observation and fail open only for the
        already-completed tool call.
        """

        try:
            native = CodexHookAdapter.verify_ingress(
                self._bridge_payload(native_payload),
                bridge=self.bridge,
                session=self.session,
                launch_context=self.launch_context_provider(),
                expected_event="PostToolUse",
            )
        except (CodexHookPayloadError, ValueError) as error:
            self._record_error(f"INVALID_CODEX_POSTTOOL: {error}")
            return {}

        if native.status is not HookTrustStatus.VERIFIED:
            self._record_error(f"CODEX_POSTTOOL_{native.status.value}: {native.reason}")
            return {}

        try:
            posttool_record = self.hook_sensor.observe_posttool(
                self._posttool_sensor_payload(native_payload, native)
            )
            if native.tool_use_id:
                event = next(
                    (
                        item
                        for item in self.events
                        if item.tool_use_id == native.tool_use_id
                    ),
                    None,
                )
                if (
                    event is not None
                    and event.gate_result.decision.value == "CONTAIN"
                    and event.gate_result.route.value == "PRETOOL_BLOCK"
                ):
                    updated_event = self.confirm_block(native.tool_use_id, False)
                    if updated_event is not None:
                        self._handle_bypassed_pretool(
                            updated_event,
                            posttool_record,
                        )
            return {}
        except Exception as error:
            self._record_error(
                f"POSTTOOL_EVIDENCE_FAILED: {type(error).__name__}: {error}"
            )
            return {}

    def _handle_bypassed_pretool(
        self,
        event: CodexPreToolEvent,
        posttool_record: RawEvidenceRecord,
    ) -> None:
        """Contain a tool that ran after AIA had issued a verified deny."""

        try:
            action = self._derive_post_action(event.action, posttool_record)
            records = (*event.records, posttool_record)
            launch_context = self.launch_context_provider()
            attribution = AttributionEngine(
                self.session.session_id,
                records,
                launch_context=launch_context,
                expected_agent_native_session_id=action.agent_native_session_id,
            ).attribute(action)
            policy_evaluation = RuntimePolicyEvaluator(
                self.preparation_context.active_policy,
                session_id=self.session.session_id,
            ).evaluate(action)
            process_sensor = self.process_sensor_provider()
            sensor_health = tuple(
                sensor.health
                for sensor in (
                    self.filesystem_sensor,
                    self.hook_sensor,
                    process_sensor,
                )
                if sensor is not None
            )
            gate_result = EnforcementGate(
                lease_manager=self.lease_manager
            ).evaluate(
                EnforcementGateInput(
                    action=action,
                    policy_evaluation=policy_evaluation,
                    attribution=attribution,
                    session=self.session,
                    active_policy=self.preparation_context.active_policy,
                    launch_context=launch_context,
                    workspace_lease=self.preparation_context.workspace_lease,
                    sensor_health=sensor_health,
                    hook_trust_status=HookTrustStatus.VERIFIED,
                    checked_at=_now_utc(),
                )
            )
            containment = CodexPostActionContainment(
                source_event=event,
                action=action,
                policy_evaluation=policy_evaluation,
                attribution=attribution,
                gate_result=gate_result,
            )
            result = None
            termination_error = None
            if (
                gate_result.decision is EnforcementDecision.CONTAIN
                and gate_result.route is EnforcementRoute.PROCESS_TERMINATION
            ):
                callback = self.post_action_containment_callback
                if callback is None:
                    termination_error = "PROCESS_CONTAINMENT_CALLBACK_UNAVAILABLE"
                else:
                    try:
                        result = callback(containment)
                    except Exception as error:
                        termination_error = f"{type(error).__name__}: {error}"
                        self._record_error("POST_ACTION_CONTAINMENT_FAILED")
            elif gate_result.decision is EnforcementDecision.CONTAIN:
                termination_error = "POST_ACTION_GATE_ROUTE_UNAVAILABLE"
            updated = replace(
                containment,
                termination_result=result,
                termination_error=termination_error,
            )
            with self._lock:
                self._post_action_containments.append(updated)
        except Exception as error:
            self._record_error(
                "POST_ACTION_CONTAINMENT_EVALUATION_FAILED: "
                f"{type(error).__name__}"
            )

    @staticmethod
    def _derive_post_action(
        action: NormalizedAction,
        posttool_record: RawEvidenceRecord,
    ) -> NormalizedAction:
        if posttool_record.record_type.value != "POSTTOOL_OBSERVED":
            raise ValueError("post_action derivation requires PostTool evidence")
        if posttool_record.session_id != action.aia_session_id:
            raise ValueError("PostTool evidence Session does not match Action")
        evidence_ids = tuple(
            dict.fromkeys((*action.evidence_ids, posttool_record.evidence_id))
        )
        evidence_sources = tuple(
            dict.fromkeys((*action.evidence_sources, posttool_record.source))
        )
        return replace(
            action,
            action_id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"{action.action_id}:POST_ACTION:{posttool_record.evidence_id}",
                )
            ),
            stage=ObservationStage.POST_ACTION,
            observed_at=posttool_record.captured_at,
            evidence_ids=evidence_ids,
            evidence_sources=evidence_sources,
        )

    def confirm_block(self, tool_use_id: str, blocked: bool) -> CodexPreToolEvent | None:
        """Attach an externally observed Codex execution confirmation."""

        with self._lock:
            for index, event in enumerate(self._events):
                if event.tool_use_id != tool_use_id:
                    continue
                confirmation = event.decision.confirm(
                    PreToolExecutionConfirmation(blocked, _now_utc())
                )
                updated_gate = event.gate_result
                if confirmation.action is EnforcementAction.BLOCKED:
                    updated_gate = replace(
                        updated_gate,
                        action=EnforcementAction.BLOCKED,
                        execution_result=EnforcementExecutionResult.SUCCEEDED,
                    )
                elif confirmation.execution_result is EnforcementExecutionResult.FAILED:
                    updated_gate = replace(
                        updated_gate,
                        action=EnforcementAction.NONE,
                        execution_result=EnforcementExecutionResult.FAILED,
                        failure_reasons=tuple(
                            dict.fromkeys(
                                (*updated_gate.failure_reasons, confirmation.reason)
                            )
                        ),
                    )
                updated = replace(
                    event,
                    gate_result=updated_gate,
                    confirmed_block=blocked,
                )
                self._events[index] = updated
                return updated
        return None

    def _bridge_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        capability = self.bridge.capability_secret
        if capability is None:
            raise ValueError("AIA Hook Enforcement Bridge is not prepared")
        return {
            **dict(payload),
            "aia_session_id": self.session.session_id,
            "aia_launch_id": self._launch_id(),
            "aia_capability": capability,
        }

    def _launch_id(self) -> str:
        launch_context = self.launch_context_provider()
        if launch_context is None:
            return "unbound-launch"
        return launch_context.launch_id

    def _sensor_payload(self, payload: Mapping[str, Any], ingress: Any) -> dict[str, Any]:
        return {
            "aia_session_id": self.session.session_id,
            "agent": self.session.agent,
            "agent_native_session_id": ingress.agent_native_session_id,
            "turn_id": ingress.turn_id,
            "tool_use_id": ingress.tool_use_id,
            "tool_name": ingress.tool_name,
            "tool_input": payload.get("tool_input"),
            "hook_event_name": "PRE_TOOL_USE",
            "source_metadata": {
                "adapter": "codex-pretooluse",
                "channel": "loopback",
                "provider": "codex",
                "transport": "http-localhost",
            },
            "ingress_status": "VERIFIED",
            "ingress_verified": True,
        }

    def _posttool_sensor_payload(
        self,
        payload: Mapping[str, Any],
        ingress: Any,
    ) -> dict[str, Any]:
        return {
            "aia_session_id": self.session.session_id,
            "agent": self.session.agent,
            "agent_native_session_id": ingress.agent_native_session_id,
            "turn_id": ingress.turn_id,
            "tool_use_id": ingress.tool_use_id,
            "tool_name": ingress.tool_name,
            "tool_input": payload.get("tool_input", {}),
            "tool_response": payload.get("tool_response"),
            "hook_event_name": "POST_TOOL_USE",
            "source_metadata": {
                "adapter": "codex-posttooluse",
                "channel": "loopback",
                "provider": "codex",
                "transport": "http-localhost",
            },
            "ingress_status": "VERIFIED",
            "ingress_verified": True,
        }

    def _record_error(self, value: str) -> None:
        with self._lock:
            self._errors.append(value)


class PreToolDecisionPlaceholder:
    """Small indirection to keep Gate construction explicit in this module."""

    @staticmethod
    def evaluate(gate_input: EnforcementGateInput, lease_manager: "WorkspaceLeaseManager") -> PreToolDecision:
        from .pretool_enforcement import PreToolEnforcementAdapter

        return PreToolEnforcementAdapter(
            EnforcementGate(lease_manager=lease_manager)
        ).evaluate(gate_input)


class CodexHookBroker:
    """Capability-authenticated loopback HTTP broker for a Codex Hook process."""

    def __init__(
        self,
        *,
        capability_secret: str,
        session_id: str,
        launch_id: str,
        control_root: str | Path,
        handler: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    ) -> None:
        if not capability_secret or not session_id or not launch_id:
            raise ValueError("Codex Hook Broker identifiers must be non-empty")
        self.capability_secret = capability_secret
        self.session_id = session_id
        self.launch_id = launch_id
        self.control_root = Path(control_root).resolve(strict=False)
        self.handler = handler
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def endpoint(self) -> str | None:
        if self._server is None:
            return None
        host, port = self._server.server_address
        return f"http://{host}:{port}/pretool"

    @property
    def environment(self) -> dict[str, str]:
        endpoint = self.endpoint
        if endpoint is None:
            raise RuntimeError("Codex Hook Broker is not started")
        return {
            "AIA_CODEX_HOOK_ENDPOINT": endpoint,
            "AIA_CODEX_HOOK_CAPABILITY": self.capability_secret,
            "AIA_SESSION_ID": self.session_id,
            "AIA_LAUNCH_ID": self.launch_id,
            "AIA_CONTROL_ROOT": str(self.control_root),
        }

    def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("Codex Hook Broker is already started")
        broker = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/pretool":
                    self.send_error(404)
                    return
                if self.headers.get("X-AIA-Capability") != broker.capability_secret:
                    self.send_error(403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 256 * 1024:
                        raise ValueError("invalid request size")
                    value = json.loads(self.rfile.read(length))
                    if not isinstance(value, Mapping):
                        raise ValueError("payload must be an object")
                    result = broker.handler(value)
                    body = json.dumps(dict(result), ensure_ascii=False).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except Exception:
                    self.send_error(500)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="aia-codex-hook-broker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2)


def send_hook_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Send stdin Payload from the Codex command hook to the AIA broker."""

    import os

    endpoint = os.environ.get("AIA_CODEX_HOOK_ENDPOINT")
    capability = os.environ.get("AIA_CODEX_HOOK_CAPABILITY")
    if not endpoint:
        return {}
    if not capability:
        # An endpoint without its per-run capability is a partially bound
        # Protected Run.  Returning an empty response here would make Codex
        # continue because an empty exit-0 hook response is successful.
        raise RuntimeError("AIA Hook Broker capability is missing")
    request = Request(
        endpoint,
        data=json.dumps(dict(payload), ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-AIA-Capability": capability,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            value = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"AIA Hook Broker unavailable: {error}") from error
    if not isinstance(value, Mapping):
        raise RuntimeError("AIA Hook Broker response must be an object")
    return value


__all__ = [
    "CodexHookBroker",
    "CodexPostActionContainment",
    "CodexPreToolController",
    "CodexPreToolEvent",
    "send_hook_payload",
]
