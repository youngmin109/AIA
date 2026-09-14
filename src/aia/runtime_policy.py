"""Runtime evaluation of canonical actions against a frozen active policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Iterable

from .action import ActionTargetKind, NormalizedAction
from .evidence import ObservationStage
from .policy import (
    Operation,
    PolicyDecision,
    PolicyEffect,
    PolicyEvaluation,
    PolicyProfile,
    ResolvedPolicy,
    SecurityAssetType,
)
from .protection import (
    ActivePolicySnapshot,
    ProtectionPreparationContext,
    policy_content_sha256,
)


class RuntimePolicyError(ValueError):
    """Raised when a frozen runtime policy authority is invalid."""


class RuntimePolicyReason(StrEnum):
    """Stable reasons for a non-compliant or incomplete runtime evaluation."""

    POLICY_PATH_EVIDENCE_INSUFFICIENT = "POLICY_PATH_EVIDENCE_INSUFFICIENT"
    COMMAND_EVIDENCE_INSUFFICIENT = "COMMAND_EVIDENCE_INSUFFICIENT"
    POLICY_SESSION_MISMATCH = "POLICY_SESSION_MISMATCH"
    POLICY_AUTHORITY_MISMATCH = "POLICY_AUTHORITY_MISMATCH"
    POLICY_EVALUATION_ERROR = "POLICY_EVALUATION_ERROR"
    UNSUPPORTED_ACTION_TARGET = "UNSUPPORTED_ACTION_TARGET"


class RuntimePathRole(StrEnum):
    """The side of a MOVE or RENAME action represented by one path result."""

    SOURCE = "SOURCE"
    DESTINATION = "DESTINATION"


_FILE_OPERATIONS = frozenset(
    {
        Operation.READ,
        Operation.CREATE,
        Operation.MODIFY,
        Operation.DELETE,
        Operation.MOVE,
        Operation.RENAME,
    }
)
_PATH_LIMITATIONS = frozenset(
    {
        "PATH_MISSING",
        "OUTSIDE_WORKSPACE",
        "PATH_ESCAPE",
        "DIFFERENT_DRIVE",
        "INVALID_WORKSPACE_SCOPE",
        "UNUSABLE_PATH",
        "PATH_OUTSIDE_OR_INVALID",
        "PATH_MISSING_OR_INVALID",
        "CONFLICTING_PATH_TARGET",
    }
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RuntimePolicyError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class RuntimePathEvaluation:
    """One preserved Policy Evaluation for a source or destination path."""

    role: RuntimePathRole
    path: str | None
    policy_evaluation: PolicyEvaluation

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", RuntimePathRole(self.role))
        if not isinstance(self.policy_evaluation, PolicyEvaluation):
            raise RuntimePolicyError("policy_evaluation must be a PolicyEvaluation")

    @property
    def policy_decision(self) -> PolicyDecision:
        return self.policy_evaluation.policy_decision

    @property
    def operation_effect(self) -> PolicyEffect | None:
        return self.policy_evaluation.operation_effect

    @property
    def matched_rule_ids(self) -> tuple[str, ...]:
        return self.policy_evaluation.matched_rule_ids

    @property
    def audit_record(self) -> bool:
        return self.policy_evaluation.audit_record


@dataclass(frozen=True, slots=True)
class RuntimePolicyEvaluation:
    """Immutable policy result correlated to one NormalizedAction."""

    action_id: str
    aia_session_id: str
    operation: Operation
    stage: ObservationStage
    policy_id: str
    policy_version: str
    policy_profile: PolicyProfile
    active_policy_fingerprint: str
    policy_decision: PolicyDecision
    operation_effect: PolicyEffect | None
    asset_type: SecurityAssetType | None
    matched_rule_ids: tuple[str, ...]
    audit_record: bool
    evaluated_at: datetime
    limitation: str | None = None
    reason: str | None = None
    path: str | None = None
    raw_command: str | None = None
    normalized_command: str | None = None
    policy_evaluation: PolicyEvaluation | None = None
    path_evaluations: tuple[RuntimePathEvaluation, ...] = ()
    command_pattern_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.action_id.strip() or not self.aia_session_id.strip():
            raise RuntimePolicyError("action_id and aia_session_id must be non-empty")
        object.__setattr__(self, "operation", Operation(self.operation))
        object.__setattr__(self, "stage", ObservationStage(self.stage))
        object.__setattr__(self, "policy_decision", PolicyDecision(self.policy_decision))
        if self.operation_effect is not None:
            object.__setattr__(self, "operation_effect", PolicyEffect(self.operation_effect))
        if self.asset_type is not None:
            object.__setattr__(self, "asset_type", SecurityAssetType(self.asset_type))
        object.__setattr__(self, "policy_profile", PolicyProfile(self.policy_profile))
        object.__setattr__(self, "matched_rule_ids", tuple(self.matched_rule_ids))
        object.__setattr__(self, "path_evaluations", tuple(self.path_evaluations))
        object.__setattr__(self, "command_pattern_ids", tuple(self.command_pattern_ids))
        object.__setattr__(self, "evaluated_at", _aware_utc(self.evaluated_at, field_name="evaluated_at"))


@dataclass(frozen=True, slots=True)
class RuntimePolicyBatchResult:
    """Deterministic per-action results and aggregate counts."""

    aia_session_id: str
    policy_id: str
    policy_version: str
    policy_profile: PolicyProfile
    active_policy_fingerprint: str
    results: tuple[RuntimePolicyEvaluation, ...]
    compliant_count: int
    violation_count: int
    indeterminate_count: int
    audit_count: int
    evaluated_at: datetime

    def __post_init__(self) -> None:
        if not self.aia_session_id.strip():
            raise RuntimePolicyError("aia_session_id must be non-empty")
        object.__setattr__(self, "policy_profile", PolicyProfile(self.policy_profile))
        object.__setattr__(self, "results", tuple(self.results))
        object.__setattr__(self, "evaluated_at", _aware_utc(self.evaluated_at, field_name="evaluated_at"))
        expected = {
            "compliant_count": sum(
                result.policy_decision is PolicyDecision.COMPLIANT
                for result in self.results
            ),
            "violation_count": sum(
                result.policy_decision is PolicyDecision.VIOLATION
                for result in self.results
            ),
            "indeterminate_count": sum(
                result.policy_decision is PolicyDecision.INDETERMINATE
                for result in self.results
            ),
            "audit_count": sum(result.audit_record for result in self.results),
        }
        for name, value in expected.items():
            if getattr(self, name) != value:
                raise RuntimePolicyError(f"{name} does not match results")


class RuntimePolicyEvaluator:
    """Adapt Canonical Actions to the existing deterministic Policy Engine.

    NormalizedAction contains mechanical target facts, not semantic asset
    classification. The frozen policy's rules therefore supply candidate asset
    types during matching. No caller supplied asset type or fallback is used.
    No attribution, sensor health, or enforcement state is read here.
    """

    def __init__(
        self,
        active_policy: ActivePolicySnapshot | ProtectionPreparationContext,
        *,
        session_id: str | None = None,
    ) -> None:
        if isinstance(active_policy, ProtectionPreparationContext):
            active_policy = active_policy.active_policy
        if not isinstance(active_policy, ActivePolicySnapshot):
            raise RuntimePolicyError(
                "active_policy must be an ActivePolicySnapshot or preparation context"
            )
        expected_session = active_policy.session_id
        if session_id is not None and session_id != expected_session:
            raise RuntimePolicyError("session_id does not match active policy")
        if active_policy.policy_id != active_policy.policy.policy_id:
            raise RuntimePolicyError("active policy_id does not match frozen policy")
        if active_policy.policy_version != active_policy.policy.policy_version:
            raise RuntimePolicyError("active policy_version does not match frozen policy")
        if active_policy.policy.profile is not None and active_policy.profile != active_policy.policy.profile:
            raise RuntimePolicyError("active policy profile does not match frozen policy")
        resolved = ResolvedPolicy(
            profile=active_policy.profile,
            policy_id=active_policy.policy_id,
            policy_version=active_policy.policy_version,
            source="active-snapshot",
            policy=active_policy.policy,
        )
        if active_policy.sha256 != policy_content_sha256(resolved):
            raise RuntimePolicyError("active policy fingerprint does not match frozen policy")
        self._active_policy = active_policy
        self._session_id = expected_session

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def active_policy(self) -> ActivePolicySnapshot:
        return self._active_policy

    def evaluate(
        self,
        action: NormalizedAction,
        *,
        evaluated_at: datetime | None = None,
    ) -> RuntimePolicyEvaluation:
        """Evaluate one action, retaining structural failures as INDETERMINATE."""

        if not isinstance(action, NormalizedAction):
            raise RuntimePolicyError("action must be a NormalizedAction")
        timestamp = evaluated_at if evaluated_at is not None else _now_utc()
        if action.aia_session_id != self._session_id:
            return self._result(
                action,
                timestamp,
                policy_decision=PolicyDecision.INDETERMINATE,
                operation_effect=None,
                matched_rule_ids=(),
                audit_record=False,
                reason=RuntimePolicyReason.POLICY_SESSION_MISMATCH,
                limitation="action belongs to a different AIA Session",
            )
        try:
            return self._evaluate_action(action, timestamp)
        except Exception:
            return self._result(
                action,
                timestamp,
                policy_decision=PolicyDecision.INDETERMINATE,
                operation_effect=None,
                matched_rule_ids=(),
                audit_record=False,
                reason=RuntimePolicyReason.POLICY_EVALUATION_ERROR,
                limitation="runtime policy evaluation failed",
            )

    def evaluate_batch(
        self,
        actions: Iterable[NormalizedAction],
        *,
        evaluated_at: datetime | None = None,
    ) -> RuntimePolicyBatchResult:
        """Evaluate actions in input order without discarding other results."""

        results: list[RuntimePolicyEvaluation] = []
        for action in tuple(actions):
            try:
                results.append(
                    self.evaluate(
                        action,
                        evaluated_at=evaluated_at,
                    )
                )
            except Exception:
                if isinstance(action, NormalizedAction):
                    results.append(
                        self._result(
                            action,
                            evaluated_at if evaluated_at is not None else _now_utc(),
                            policy_decision=PolicyDecision.INDETERMINATE,
                            operation_effect=None,
                            matched_rule_ids=(),
                            audit_record=False,
                            reason=RuntimePolicyReason.POLICY_EVALUATION_ERROR,
                            limitation="runtime policy evaluation failed",
                        )
                    )
                else:
                    raise
        return RuntimePolicyBatchResult(
            aia_session_id=self._session_id,
            policy_id=self._active_policy.policy_id,
            policy_version=self._active_policy.policy_version,
            policy_profile=self._active_policy.profile,
            active_policy_fingerprint=self._active_policy.sha256,
            results=tuple(results),
            compliant_count=sum(
                result.policy_decision is PolicyDecision.COMPLIANT for result in results
            ),
            violation_count=sum(
                result.policy_decision is PolicyDecision.VIOLATION for result in results
            ),
            indeterminate_count=sum(
                result.policy_decision is PolicyDecision.INDETERMINATE
                for result in results
            ),
            audit_count=sum(result.audit_record for result in results),
            evaluated_at=evaluated_at if evaluated_at is not None else _now_utc(),
        )

    def _evaluate_action(
        self,
        action: NormalizedAction,
        evaluated_at: datetime,
    ) -> RuntimePolicyEvaluation:
        if action.operation in _FILE_OPERATIONS:
            if action.operation in {Operation.MOVE, Operation.RENAME}:
                return self._evaluate_move_or_rename(action, evaluated_at)
            if action.target_kind not in {ActionTargetKind.FILE, ActionTargetKind.DIRECTORY}:
                return self._unsupported_target(action, evaluated_at)
            path_result = self._evaluate_path(
                action,
                action.canonical_path,
                role=None,
            )
            return self._result_from_policy(
                action,
                evaluated_at,
                path_result.policy_evaluation,
                path=action.canonical_path,
                path_evaluations=(path_result,),
            )
        if action.operation is Operation.EXECUTE:
            if action.target_kind not in {ActionTargetKind.COMMAND, ActionTargetKind.PROCESS}:
                return self._unsupported_target(action, evaluated_at)
            if action.raw_command is None or not action.raw_command.strip():
                return self._result(
                    action,
                    evaluated_at,
                    policy_decision=PolicyDecision.INDETERMINATE,
                    operation_effect=None,
                    matched_rule_ids=(),
                    audit_record=False,
                    reason=RuntimePolicyReason.COMMAND_EVIDENCE_INSUFFICIENT,
                    limitation="raw command evidence is required for EXECUTE",
                )
            evaluation = self._active_policy.policy.evaluate_target(
                operation=Operation.EXECUTE,
                raw_command=action.raw_command,
            )
            return self._result_from_policy(
                action,
                evaluated_at,
                evaluation,
                path=action.canonical_path,
            )
        return self._unsupported_target(action, evaluated_at)

    def _evaluate_move_or_rename(
        self,
        action: NormalizedAction,
        evaluated_at: datetime,
    ) -> RuntimePolicyEvaluation:
        source = self._evaluate_path(action, action.source_path, RuntimePathRole.SOURCE)
        destination = self._evaluate_path(
            action,
            action.destination_path,
            RuntimePathRole.DESTINATION,
        )
        path_results = (source, destination)
        decisions = tuple(item.policy_decision for item in path_results)
        if PolicyDecision.VIOLATION in decisions:
            decision = PolicyDecision.VIOLATION
        elif PolicyDecision.INDETERMINATE in decisions:
            decision = PolicyDecision.INDETERMINATE
        else:
            decision = PolicyDecision.COMPLIANT
        effects = tuple(
            item.operation_effect for item in path_results if item.operation_effect is not None
        )
        effect = effects[0] if effects and all(value is effects[0] for value in effects) else None
        # Preserve source/destination order while removing only duplicate IDs.
        unique_matched: list[str] = []
        for item in path_results:
            for rule_id in item.matched_rule_ids:
                if rule_id not in unique_matched:
                    unique_matched.append(rule_id)
        matched_asset_types = {
            item.policy_evaluation.asset_type
            for item in path_results
            if item.policy_evaluation.asset_type is not None
        }
        return self._result(
            action,
            evaluated_at,
            policy_decision=decision,
            operation_effect=effect,
            matched_rule_ids=tuple(unique_matched),
            audit_record=any(item.audit_record for item in path_results),
            limitation=(
                "one or more MOVE/RENAME paths lack policy evidence"
                if PolicyDecision.INDETERMINATE in decisions
                else None
            ),
            asset_type=(
                next(iter(matched_asset_types))
                if len(matched_asset_types) == 1
                else None
            ),
            path_evaluations=path_results,
        )

    def _evaluate_path(
        self,
        action: NormalizedAction,
        path: str | None,
        role: RuntimePathRole | None,
    ) -> RuntimePathEvaluation:
        if not self._path_is_policy_safe(action, path):
            evaluation = self._indeterminate_policy(
                operation=action.operation,
                path=path,
                reason=RuntimePolicyReason.POLICY_PATH_EVIDENCE_INSUFFICIENT,
                limitation="canonical Workspace path evidence is required",
            )
        else:
            evaluation = self._active_policy.policy.evaluate_target(
                operation=action.operation,
                path=path,
            )
        return RuntimePathEvaluation(role or RuntimePathRole.SOURCE, path, evaluation)

    @staticmethod
    def _path_is_policy_safe(action: NormalizedAction, path: str | None) -> bool:
        if path is None or not path.strip():
            return False
        if action.operation in {Operation.MOVE, Operation.RENAME}:
            # MOVE/RENAME keeps one combined limitations tuple while the two
            # canonical paths remain independently observable. A present path
            # is therefore sufficient here; the other side can still be None.
            return True
        return not any(limitation in _PATH_LIMITATIONS for limitation in action.limitations)

    def _unsupported_target(
        self,
        action: NormalizedAction,
        evaluated_at: datetime,
    ) -> RuntimePolicyEvaluation:
        return self._result(
            action,
            evaluated_at,
            policy_decision=PolicyDecision.INDETERMINATE,
            operation_effect=None,
            matched_rule_ids=(),
            audit_record=False,
            reason=RuntimePolicyReason.UNSUPPORTED_ACTION_TARGET,
            limitation="NormalizedAction target kind does not match its Operation",
        )

    def _result_from_policy(
        self,
        action: NormalizedAction,
        evaluated_at: datetime,
        evaluation: PolicyEvaluation,
        *,
        path: str | None = None,
        path_evaluations: tuple[RuntimePathEvaluation, ...] = (),
    ) -> RuntimePolicyEvaluation:
        return self._result(
            action,
            evaluated_at,
            policy_decision=evaluation.policy_decision,
            operation_effect=evaluation.operation_effect,
            matched_rule_ids=evaluation.matched_rule_ids,
            audit_record=evaluation.audit_record,
            reason=evaluation.reason,
            limitation=evaluation.limitation,
            path=path,
            raw_command=action.raw_command,
            normalized_command=evaluation.normalized_command,
            policy_evaluation=evaluation,
            path_evaluations=path_evaluations,
            command_pattern_ids=evaluation.matched_rule_ids if action.operation is Operation.EXECUTE else (),
        )

    def _result(
        self,
        action: NormalizedAction,
        evaluated_at: datetime,
        *,
        policy_decision: PolicyDecision,
        operation_effect: PolicyEffect | None,
        matched_rule_ids: tuple[str, ...],
        audit_record: bool,
        reason: str | None = None,
        limitation: str | None = None,
        path: str | None = None,
        raw_command: str | None = None,
        normalized_command: str | None = None,
        policy_evaluation: PolicyEvaluation | None = None,
        asset_type: SecurityAssetType | None = None,
        path_evaluations: tuple[RuntimePathEvaluation, ...] = (),
        command_pattern_ids: tuple[str, ...] = (),
    ) -> RuntimePolicyEvaluation:
        return RuntimePolicyEvaluation(
            action_id=action.action_id,
            aia_session_id=action.aia_session_id,
            operation=action.operation,
            stage=action.stage,
            policy_id=self._active_policy.policy_id,
            policy_version=self._active_policy.policy_version,
            policy_profile=self._active_policy.profile,
            active_policy_fingerprint=self._active_policy.sha256,
            policy_decision=policy_decision,
            operation_effect=operation_effect,
            asset_type=(
                asset_type
                if asset_type is not None
                else (
                    policy_evaluation.asset_type
                    if policy_evaluation is not None
                    else None
                )
            ),
            matched_rule_ids=matched_rule_ids,
            audit_record=audit_record,
            evaluated_at=evaluated_at,
            limitation=limitation,
            reason=reason,
            path=path,
            raw_command=raw_command,
            normalized_command=normalized_command,
            policy_evaluation=policy_evaluation,
            path_evaluations=path_evaluations,
            command_pattern_ids=command_pattern_ids,
        )

    @staticmethod
    def _indeterminate_policy(
        *,
        operation: Operation,
        path: str | None = None,
        reason: str,
        limitation: str,
    ) -> PolicyEvaluation:
        return PolicyEvaluation(
            policy_decision=PolicyDecision.INDETERMINATE,
            matched_rule_ids=(),
            asset_type=None,
            operation=operation,
            operation_effect=None,
            audit_record=False,
            reason=reason,
            limitation=limitation,
            path=path,
        )


def evaluate_runtime_policy(
    action: NormalizedAction,
    active_policy: ActivePolicySnapshot | ProtectionPreparationContext,
    *,
    session_id: str | None = None,
    evaluated_at: datetime | None = None,
) -> RuntimePolicyEvaluation:
    """Evaluate one action against a frozen Active Policy Snapshot."""

    return RuntimePolicyEvaluator(
        active_policy,
        session_id=session_id,
    ).evaluate(action, evaluated_at=evaluated_at)


def evaluate_runtime_policy_batch(
    actions: Iterable[NormalizedAction],
    active_policy: ActivePolicySnapshot | ProtectionPreparationContext,
    *,
    session_id: str | None = None,
    evaluated_at: datetime | None = None,
) -> RuntimePolicyBatchResult:
    """Evaluate a Normalization batch against a frozen Active Policy Snapshot."""

    return RuntimePolicyEvaluator(
        active_policy,
        session_id=session_id,
    ).evaluate_batch(actions, evaluated_at=evaluated_at)


__all__ = [
    "RuntimePathEvaluation",
    "RuntimePathRole",
    "RuntimePolicyBatchResult",
    "RuntimePolicyError",
    "RuntimePolicyEvaluation",
    "RuntimePolicyEvaluator",
    "RuntimePolicyReason",
    "evaluate_runtime_policy",
    "evaluate_runtime_policy_batch",
]
