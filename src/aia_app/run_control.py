"""Run creation and stop handling for the application service."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import subprocess
from threading import Thread
from typing import Any
from uuid import UUID

from aia import (
    CodexAdapter,
    CodexHookInstaller,
    PolicyProfile,
    ProtectedLauncher,
    ProtectedRunSession,
    RawEvidenceStore,
    SessionFinalizer,
    SessionMode,
    WorkspaceLeaseManager,
    load_policy_document,
    process_create_time,
    resolve_profile,
)
from aia.codex_hook_trust import inspect_codex_hook_trust
from aia.hook_verification import HookVerificationStore
from aia.session import SessionEndReason, WorkspaceValidationError

from .codex_workbench import _END_SESSION_REQUEST
from .dto import CreateRunRequest, DTOValidationError
from .preflight import _aia_cli_prefix
from .protected_run import ApplicationValidationError, _now
from .registry import RunRecord
from .run_history import _runtime_coordinator_reconciliation, _workspace_key


class RunControlMixin:

    def shutdown(self, wait: bool = True) -> None:
        """Stop live Protected Runs before closing the application service.

        A console process can be interrupted while a Codex child is still
        running.  Leaving the executor to shut down by itself would close the
        AIA coordinator while the managed Agent remains alive.  Requesting a
        user abort first lets the existing identity-safe launcher cleanup path
        terminate the registered tree and finalize the run honestly.
        """

        for record in self.registry.snapshots():
            if record.status in {"COMPLETED", "ABORTED", "FAILED"}:
                continue
            try:
                self.request_stop(record.session_id)
            except (KeyError, OSError, ValueError):
                # The worker may have finalized between the snapshot and the
                # stop request.  Its own finalization remains authoritative.
                continue
        self._executor.shutdown(wait=wait, cancel_futures=False)

    @staticmethod
    def validate_policy_document(document: Mapping[str, Any]) -> dict[str, Any]:
        """Strictly validate a console-authored policy without saving it."""

        if not isinstance(document, Mapping):
            raise ApplicationValidationError("policy document must be a JSON object")
        try:
            policy = load_policy_document(document, source="<console-editor>")
        except (OSError, ValueError) as error:
            raise ApplicationValidationError(f"policy validation failed: {error}") from error
        return {
            "valid": True,
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "rule_count": len(policy.rules),
            "default_effect": policy.default_effect.value,
        }

    @staticmethod
    def save_policy_document(payload: Mapping[str, Any]) -> dict[str, Any]:
        """Validate then save one user policy JSON for later CUSTOM runs."""

        if not isinstance(payload, Mapping):
            raise ApplicationValidationError("policy save request must be a JSON object")
        document = payload.get("document")
        if not isinstance(document, Mapping):
            raise ApplicationValidationError("document must be a JSON object")
        RunControlMixin.validate_policy_document(document)
        requested_path = payload.get("path")
        if requested_path is None or not str(requested_path).strip():
            policy_id = str(document.get("정책ID") or document.get("policy_id") or "custom-policy")
            safe_name = "".join(
                character if character.isalnum() or character in {"-", "_"} else "-"
                for character in policy_id
            ).strip("-") or "custom-policy"
            path = Path.home() / ".aia" / "policies" / f"{safe_name}.json"
        else:
            if not isinstance(requested_path, str):
                raise ApplicationValidationError("path must be a string")
            path = Path(requested_path).expanduser()
            if path.suffix.casefold() != ".json":
                raise ApplicationValidationError("policy path must end with .json")
        path = path.resolve(strict=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(dict(document), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        summary = RunControlMixin.validate_policy_document(document)
        return {**summary, "path": str(path)}

    @staticmethod
    def _workspace_policy_path(
        workspace: Path,
        profile_name: str,
        protected_paths: tuple[str, ...],
        policy_source: str | Path | Mapping[str, Any] | None = None,
    ) -> Path | None:
        """Create a validated custom policy for paths selected in the UI."""

        if not protected_paths:
            return None
        try:
            resolved = resolve_profile(profile_name, policy_source=policy_source)
        except (OSError, ValueError) as error:
            raise ApplicationValidationError(f"policy validation failed: {error}") from error

        normalized: list[tuple[str, bool]] = []
        for raw_path in protected_paths:
            candidate = Path(raw_path).expanduser().resolve(strict=False)
            try:
                relative = candidate.relative_to(workspace).as_posix()
            except ValueError as error:
                raise ApplicationValidationError(
                    "보호할 파일·폴더는 선택한 Workspace 안에 있어야 합니다."
                ) from error
            if not relative or relative == ".":
                raise ApplicationValidationError("Workspace 자체는 보호 목록에 추가할 수 없습니다.")
            normalized.append((relative, candidate.is_dir()))

        rules: list[dict[str, Any]] = []
        for rule in resolved.policy.rules:
            rule_mapping: dict[str, Any] = {
                "rule_id": rule.rule_id,
                "priority": rule.priority,
                "asset_type": rule.asset_type.value,
                "operation_effects": {
                    operation.value: effect.value
                    for operation, effect in rule.operation_effects.items()
                },
            }
            if rule.path_patterns:
                rule_mapping["path_patterns"] = list(rule.path_patterns)
            else:
                rule_mapping["command_patterns"] = list(rule.command_patterns)
            rules.append(rule_mapping)

        for index, (relative, is_directory) in enumerate(normalized, start=1):
            patterns = [relative]
            if is_directory:
                patterns.append(f"{relative}/**")
            rules.append(
                {
                    "rule_id": f"aia-user-protected-path-{index}",
                    "priority": 2000 + index,
                    "asset_type": "WORKSPACE",
                    "path_patterns": patterns,
                    "operation_effects": {
                        "CREATE": "DENY",
                        "MODIFY": "DENY",
                        "DELETE": "DENY",
                        "MOVE": "DENY",
                        "RENAME": "DENY",
                    },
                }
            )

        policy_document = {
            "profile": PolicyProfile.CUSTOM.value,
            "policy_name": "AIA Workspace Protected Paths",
            "policy_id": "aia-workspace-protected",
            "policy_version": "1.0",
            "schema_version": "1",
            "default_effect": resolved.policy.default_effect.value,
            "rules": rules,
        }
        digest = hashlib.sha256(
            json.dumps(
                {"workspace": str(workspace), "paths": normalized},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:16]
        path = Path.home() / ".aia" / "policies" / f"workspace-{digest}.json"
        RunControlMixin.save_policy_document(
            {"document": policy_document, "path": str(path)}
        )
        return path

    @staticmethod
    def _validate_workspace(value: str) -> Path:
        try:
            from aia import canonicalize_workspace

            return canonicalize_workspace(value)
        except (WorkspaceValidationError, OSError, ValueError) as error:
            raise ApplicationValidationError(f"workspace validation failed: {error}") from error

    def _unresolved_orphan_for_workspace(self, workspace: Path) -> dict[str, Any] | None:
        """Refuse reuse until a stale run's recorded Agent root is reconciled.

        Workspace lease takeover is identity-safe for the AIA owner, but it
        cannot by itself prove that a crashed coordinator's Agent child has
        stopped.  The persisted run must therefore be acknowledged after the
        Agent root is gone before another protected run can use the workspace.
        """

        workspace_key = _workspace_key(workspace)
        if workspace_key is None:
            return None
        for state in self._list_runtime_states():
            session = state.get("session")
            if not isinstance(session, Mapping):
                continue
            state_workspace = session.get("workspace")
            if _workspace_key(state_workspace) != workspace_key:
                continue
            reconciliation = _runtime_coordinator_reconciliation(state)
            if not reconciliation.get("orphaned"):
                continue
            if reconciliation.get("action") == "RECONCILED":
                continue
            session_id = state.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                continue
            return {
                "session_id": session_id,
                "phase": state.get("phase"),
                "runtime_reconciliation": reconciliation,
            }
        return None

    def create_protected_run(self, request: CreateRunRequest | dict[str, Any]) -> dict[str, Any]:
        if isinstance(request, dict):
            try:
                request = CreateRunRequest.from_mapping(request)
            except DTOValidationError as error:
                raise ApplicationValidationError(str(error)) from error
        if not isinstance(request, CreateRunRequest):
            raise ApplicationValidationError("request is invalid")
        installer = CodexHookInstaller()
        cli_prefix = _aia_cli_prefix(installer)
        if self.require_hook_verification:
            try:
                executable = CodexAdapter().discover()
            except Exception as error:
                raise ApplicationValidationError(
                    "Codex 실행 파일을 찾을 수 없습니다"
                ) from error
            if not HookVerificationStore(self.control_root).is_current(
                installer,
                executable,
            ):
                raise ApplicationValidationError(
                    f"실제 Codex Hook 검증이 없습니다. 먼저 '{cli_prefix} hook verify'를 실행하세요."
                )
            inspection = inspect_codex_hook_trust(
                executable,
                hook_path=installer.path,
                cwd=Path.cwd(),
                timeout=8.0,
            ).to_mapping()
            pretool_status = next(
                (
                    item.get("trust_status")
                    for item in (inspection.get("hooks") or [])
                    if isinstance(item, dict) and item.get("event") == "preToolUse"
                ),
                None,
            )
            if pretool_status not in {"TRUSTED", "MANAGED"}:
                raise ApplicationValidationError(
                    "Codex PreToolUse Hook Trust가 확인되지 않았습니다. "
                    "Codex /hooks에서 AIA Hook을 검토·신뢰한 뒤 다시 시도하세요."
                )
        workspace = self._validate_workspace(request.workspace)
        orphan = self._unresolved_orphan_for_workspace(workspace)
        if orphan is not None:
            session_id = orphan["session_id"]
            reconciliation = orphan["runtime_reconciliation"]
            raise ApplicationValidationError(
                "이 Workspace에는 정리되지 않은 이전 Protected Run이 있습니다 "
                f"({session_id}, {reconciliation.get('status', 'UNKNOWN')}). "
                "이전 Codex가 실행 중이면 먼저 종료하고, Agent Root가 사라진 것을 "
                f"확인한 뒤 '{cli_prefix} reconcile {session_id}'를 실행하세요."
            )
        if not request.interactive and not request.task.strip():
            raise ApplicationValidationError(
                "task is required for a non-interactive protected run"
            )
        if request.agent.lower() != "codex":
            raise ApplicationValidationError("only Codex is supported in this console")
        if request.launch_mode == "new_terminal" and os.name != "nt":
            raise ApplicationValidationError(
                f"{request.launch_mode} launch mode requires Windows 11"
            )
        try:
            mode = SessionMode(request.mode.upper())
        except ValueError as error:
            raise ApplicationValidationError("mode must be ENFORCE or AUDIT") from error
        workspace_policy_path = self._workspace_policy_path(
            workspace,
            request.policy_profile,
            request.protected_paths,
            Path(request.custom_policy_path)
            if request.custom_policy_path is not None
            else None,
        )
        selected_policy_profile = (
            PolicyProfile.CUSTOM
            if workspace_policy_path is not None
            else PolicyProfile.from_value(request.policy_profile)
        )
        selected_policy_source = (
            workspace_policy_path
            if workspace_policy_path is not None
            else (
                Path(request.custom_policy_path)
                if request.custom_policy_path is not None
                else None
            )
        )
        try:
            resolved = resolve_profile(
                selected_policy_profile,
                policy_source=selected_policy_source,
            )
        except (OSError, ValueError) as error:
            raise ApplicationValidationError(f"policy validation failed: {error}") from error
        session = ProtectedRunSession(
            workspace=workspace,
            agent="codex",
            mode=mode,
            policy_id=resolved.policy_id,
            policy_version=resolved.policy_version,
            created_at=_now(),
        )
        record = RunRecord(
            session_id=session.session_id,
            workspace=workspace,
            agent=session.agent,
            model=request.model,
            policy_profile=selected_policy_profile.value,
            policy_id=resolved.policy_id,
            policy_version=resolved.policy_version,
            mode=mode.value,
            task=request.task,
            interactive=request.interactive,
            launch_mode=request.launch_mode,
            reasoning_effort=request.reasoning_effort,
            created_at=session.created_at,
            protection_state="STARTING",
            coordinator_pid=os.getpid(),
            coordinator_process_create_time=process_create_time(os.getpid()),
        )
        record.runtime.update({"request": request, "resolved_policy": resolved, "session": session})
        self._persist_runtime_state(record, strict=True)
        self.registry.add(record)
        self._executor.submit(self._run, record)
        return {
            "redirect_url": (
                f"/runs/{session.session_id}/workbench"
                if request.launch_mode == "codex_app_server"
                else f"/runs/{session.session_id}"
            ),
            "session_id": session.session_id,
            "status": session.status.value,
        }

    def request_stop(self, session_id: str) -> dict[str, Any]:
        """Request a user-initiated stop for one live Protected Run.

        The launcher performs identity-safe tree termination.  This method
        records the request and never turns a failed stop into a success claim.
        """

        record = self.registry.get(session_id)
        if record is None:
            try:
                result = self.reader.read_result(session_id)
            except (KeyError, OSError, ValueError):
                try:
                    self._write_stop_request(session_id)
                except (OSError, ValueError):
                    raise KeyError(session_id) from None
                return {
                    "accepted": True,
                    "session_id": session_id,
                    "status": "STOP_REQUESTED",
                    "reason": "STOP_REQUEST_STORED",
                }
            return {
                "accepted": False,
                "session_id": session_id,
                "status": result.get("session_status", "UNKNOWN"),
                "reason": "RUN_ALREADY_TERMINAL",
            }
        if record.status in {"COMPLETED", "ABORTED", "FAILED"}:
            return {
                "accepted": False,
                "session_id": session_id,
                "status": record.status,
                "reason": "RUN_ALREADY_TERMINAL",
            }
        record.stop_requested = True
        try:
            self._write_stop_request(session_id)
        except (OSError, ValueError) as error:
            record.stop_error = f"STOP_REQUEST_PERSIST_FAILED: {type(error).__name__}"
        self._persist_runtime_state(record)
        launcher = record.runtime.get("launcher")
        launcher_status = getattr(getattr(launcher, "status", None), "value", None)
        if launcher is not None and launcher_status == "STARTING":
            try:
                stopped = self._request_user_abort(record, launcher)
            except Exception as error:
                stopped = False
                record.stop_error = f"{type(error).__name__}: {error}"
            if stopped:
                record.protection_state = "STOP_REQUESTED"
                self._persist_runtime_state(record)
                return {
                    "accepted": True,
                    "session_id": session_id,
                    "status": "STOP_REQUESTED",
                    "reason": "USER_ABORT_DURING_LAUNCH",
                }
            if record.runtime.get("user_abort_termination_result"):
                record.stop_error = record.stop_error or "USER_ABORT_TERMINATION_UNCONFIRMED"
                record.protection_state = "DEGRADED"
            else:
                record.protection_state = "STOP_REQUESTED"
            self._persist_runtime_state(record)
            return {
                "accepted": True,
                "session_id": session_id,
                "status": "STOP_REQUESTED",
                "reason": "STOP_WILL_BE_APPLIED_BEFORE_AGENT_LAUNCH",
            }
        if launcher is None or launcher_status != "RUNNING":
            record.protection_state = "STOP_REQUESTED"
            self._persist_runtime_state(record)
            return {
                "accepted": True,
                "session_id": session_id,
                "status": "STOP_REQUESTED",
                "reason": "STOP_WILL_BE_APPLIED_BEFORE_AGENT_LAUNCH",
            }
        try:
            stopped = self._request_user_abort(record, launcher)
        except Exception as error:
            stopped = False
            record.stop_error = f"{type(error).__name__}: {error}"
        if not stopped:
            record.stop_error = record.stop_error or "USER_ABORT_TERMINATION_UNCONFIRMED"
            record.protection_state = "DEGRADED"
            self._persist_runtime_state(record)
            return {
                "accepted": False,
                "session_id": session_id,
                "status": record.status,
                "reason": record.stop_error,
            }
        record.protection_state = "STOP_REQUESTED"
        self._persist_runtime_state(record)
        return {
            "accepted": True,
            "session_id": session_id,
            "status": "STOP_REQUESTED",
            "reason": "USER_ABORT_REQUESTED",
        }

    @staticmethod
    def _request_user_abort(record: RunRecord, launcher: ProtectedLauncher) -> bool:
        """Request a user stop and retain its verified result separately."""

        detailed = getattr(launcher, "request_user_abort_result", None)
        try:
            if callable(detailed):
                result = detailed()
                if result is None:
                    return False
                mapping = result.to_mapping() if hasattr(result, "to_mapping") else dict(result)
                record.runtime["user_abort_termination_result"] = mapping
                if hasattr(result, "succeeded"):
                    return bool(result.succeeded)
                return bool(
                    mapping.get("status") == "SUCCEEDED"
                    and mapping.get("verified_tree_gone") is True
                )
            return bool(launcher.request_user_abort())
        except Exception as error:
            record.stop_error = f"{type(error).__name__}: {error}"
            return False

    def _is_stop_requested(self, record: RunRecord) -> bool:
        if record.stop_requested:
            return True
        # A graceful end request is handled separately in _wait_for_agent and
        # must not turn the run into a user abort.
        requested = self._stop_request_reason(record.session_id) not in {None, _END_SESSION_REQUEST}
        if requested:
            record.stop_requested = True
        return requested

    def _stop_request_reason(self, session_id: str) -> str | None:
        """Return the pending cross-process request reason, if any.

        An unreadable request file still counts as a user stop, as before.
        """

        try:
            path = self._stop_request_path(session_id)
            if not path.is_file():
                return None
        except (OSError, ValueError):
            return None
        try:
            reason = json.loads(path.read_text(encoding="utf-8")).get("reason")
        except (OSError, ValueError, AttributeError):
            return "USER_ABORT"
        return reason if reason == _END_SESSION_REQUEST else "USER_ABORT"

    def _write_stop_request(self, session_id: str, *, reason: str = "USER_ABORT") -> Path:
        path = self._stop_request_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "session_id": session_id,
                    "requested_at": _now().isoformat(),
                    "reason": reason,
                },
                ensure_ascii=True,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path

    def _stop_request_path(self, session_id: str) -> Path:
        try:
            UUID(session_id)
        except (ValueError, AttributeError, TypeError) as error:
            raise ValueError("invalid session_id") from error
        requests = (self.control_root / "stop-requests").resolve(strict=False)
        requests.mkdir(parents=True, exist_ok=True)
        candidate = (requests / f"{session_id}.json").resolve(strict=False)
        if not candidate.is_relative_to(requests):
            raise ValueError("stop request path escaped control root")
        return candidate

    def _finalize_user_abort_before_launch(
        self,
        record: RunRecord,
        session: ProtectedRunSession,
        preparation: Any,
        checkpoint: Any,
        sensors: tuple[Any, ...],
        manager: WorkspaceLeaseManager,
        lease: Any,
    ) -> None:
        raw_store = RawEvidenceStore.for_session(self.control_root, session.session_id)
        final = SessionFinalizer(
            evidence_store=raw_store,
            sensors=sensors,
            lease_manager=manager,
            workspace_lease=lease,
        ).finalize(
            session,
            end_reason=SessionEndReason.USER_ABORT,
            active_policy=preparation.active_policy,
            checkpoint=checkpoint,
            run_classification="PRODUCT_PROTECTED_RUN",
            limitations=("AGENT_NOT_LAUNCHED",),
        )
        verification = final.bundle_verification
        self.registry.update(
            record.session_id,
            status=final.result.session_status.value,
            phase=final.result.session_status.value,
            lease="RELEASED",
            result_path=final.bundle.result_directory / "result.json",
            result=final.result.to_mapping(),
            bundle_status=verification.status.value,
            protection_state="ABORTED_BEFORE_LAUNCH",
        )
        self._persist_runtime_state(record)

    def _wait_for_agent(
        self,
        record: RunRecord,
        process: Any,
        launcher: ProtectedLauncher,
    ) -> int:
        while True:
            try:
                return int(process.wait(timeout=0.5))
            except subprocess.TimeoutExpired:
                if (
                    not record.runtime.get("end_session_requested")
                    and self._stop_request_reason(record.session_id) == _END_SESSION_REQUEST
                ):
                    # Another AIA window asked to end this conversation.  Close
                    # it the same way this window's own "end session" does so
                    # the run finalizes as Agent-exited, not as an abort.
                    record.runtime["end_session_requested"] = True
                    codex_session = record.runtime.get("codex_session")
                    if codex_session is not None:
                        Thread(
                            target=codex_session.close,
                            kwargs={"force": False},
                            name=f"aia-end-session-{record.session_id[:8]}",
                            daemon=True,
                        ).start()
                    else:
                        record.stop_requested = True
                    continue
                if self._is_stop_requested(record):
                    if record.runtime.get("stop_action_attempted"):
                        continue
                    record.runtime["stop_action_attempted"] = True
                    record.protection_state = "STOP_REQUESTED"
                    if not self._request_user_abort(record, launcher):
                        record.stop_error = record.stop_error or "USER_ABORT_TERMINATION_UNCONFIRMED"
                        record.protection_state = "DEGRADED"
                    self._persist_runtime_state(record)
                    continue
                broker = getattr(launcher, "hook_broker", None)
                broker_running = (
                    broker is not None and bool(getattr(broker, "is_running", False))
                )
                if not broker_running:
                    reason = "HOOK_BROKER_LOST"
                    if not record.runtime.get("protection_failure_termination_attempted"):
                        record.runtime["protection_failure_termination_attempted"] = True
                        record.runtime["protection_failure_reason"] = reason
                        record.protection_state = "DEGRADED"
                        try:
                            result = launcher.request_protection_failure_termination_result(
                                reason
                            )
                        except Exception as error:
                            result = {
                                "status": "FAILED",
                                "outcome": "FAILED",
                                "verified_tree_gone": False,
                                "reason": f"{type(error).__name__}",
                                "control": "PROTECTION_FAILURE",
                            }
                        if result is None:
                            result = {
                                "status": "FAILED",
                                "outcome": "FAILED",
                                "verified_tree_gone": False,
                                "reason": "PROTECTION_FAILURE_TERMINATION_UNAVAILABLE",
                                "control": "PROTECTION_FAILURE",
                            }
                        record.runtime["protection_failure_termination_result"] = result
                        self._persist_runtime_state(record)
                    continue
                self._maybe_auto_checkpoint(record)
                continue
