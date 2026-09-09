from datetime import datetime, timezone
from pathlib import Path

import pytest

from aia import (
    ActionTargetKind,
    AttributionGrade,
    EvidenceSource,
    NormalizationCompleteness,
    NormalizedAction,
    ObservationStage,
    Operation,
    PolicyDecision,
    PolicyEffect,
    PolicyProfile,
    PolicyRule,
    ProtectedRunSession,
    ResolvedPolicy,
    RuntimePathRole,
    RuntimePolicyEvaluator,
    RuntimePolicyReason,
    SecurityAssetPolicy,
    SecurityAssetType,
    SessionMode,
    SessionStatus,
    freeze_active_policy,
    normalize_evidence,
    prepare_protection,
    resolve_profile,
)


BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def resolved_policy(
    *,
    rules: tuple[PolicyRule, ...] = (),
    default_effect: PolicyEffect = PolicyEffect.ALLOW,
    policy_id: str = "runtime-test",
) -> ResolvedPolicy:
    return ResolvedPolicy(
        profile=PolicyProfile.CUSTOM,
        policy_id=policy_id,
        policy_version="1.0",
        source="test",
        policy=SecurityAssetPolicy(
            schema_version="1",
            policy_id=policy_id,
            policy_version="1.0",
            default_effect=default_effect,
            rules=rules,
            profile=PolicyProfile.CUSTOM,
        ),
    )


def file_rule(
    rule_id: str,
    pattern: str,
    effect: PolicyEffect,
    *,
    priority: int = 100,
    asset_type: SecurityAssetType = SecurityAssetType.WORKSPACE,
    operation: Operation = Operation.DELETE,
) -> PolicyRule:
    return PolicyRule(
        rule_id=rule_id,
        priority=priority,
        asset_type=asset_type,
        path_patterns=(pattern,),
        operation_effects={operation: effect},
    )


def command_rule(
    rule_id: str,
    pattern: str,
    effect: PolicyEffect,
    *,
    priority: int = 100,
    asset_type: SecurityAssetType = SecurityAssetType.WORKSPACE,
) -> PolicyRule:
    return PolicyRule(
        rule_id=rule_id,
        priority=priority,
        asset_type=asset_type,
        command_patterns=(pattern,),
        operation_effects={Operation.EXECUTE: effect},
    )


def make_snapshot(tmp_path: Path, policy: ResolvedPolicy):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session = ProtectedRunSession(
        workspace=workspace,
        agent="codex",
        mode=SessionMode.ENFORCE,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
    )
    session.transition(SessionStatus.PREPARING, at=BASE_TIME)
    snapshot = freeze_active_policy(session, policy, tmp_path / "control", frozen_at=BASE_TIME)
    return session, snapshot


def action(
    session_id: str,
    operation: Operation,
    *,
    target_kind: ActionTargetKind = ActionTargetKind.FILE,
    canonical_path: str | None = "target.txt",
    source_path: str | None = None,
    destination_path: str | None = None,
    raw_command: str | None = None,
    normalized_command: str | None = None,
    completeness: NormalizationCompleteness = NormalizationCompleteness.COMPLETE,
    limitations: tuple[str, ...] = (),
    stage: ObservationStage = ObservationStage.POST_ACTION,
    action_id: str = "action-1",
) -> NormalizedAction:
    return NormalizedAction(
        action_id=action_id,
        aia_session_id=session_id,
        operation=operation,
        stage=stage,
        target_kind=target_kind,
        observed_at=BASE_TIME,
        evidence_ids=(f"evidence-{action_id}",),
        evidence_sources=(EvidenceSource.FILESYSTEM_WATCHER,),
        completeness=completeness,
        normalizer_version="canonical-v1",
        limitations=limitations,
        canonical_path=canonical_path,
        source_path=source_path,
        destination_path=destination_path,
        raw_command=raw_command,
        normalized_command=normalized_command,
    )


def test_frozen_active_policy_metadata_and_source_change_do_not_change_result(
    tmp_path: Path,
) -> None:
    policy = resolved_policy(rules=(file_rule("deny-env", ".env", PolicyEffect.DENY),))
    session, snapshot = make_snapshot(tmp_path, policy)
    evaluator = RuntimePolicyEvaluator(snapshot)

    before = evaluator.evaluate(
        action(session.session_id, Operation.DELETE, canonical_path=".env"),
    )
    changed_source = SecurityAssetPolicy(
        schema_version=policy.policy.schema_version,
        policy_id=policy.policy.policy_id,
        policy_version=policy.policy.policy_version,
        default_effect=PolicyEffect.ALLOW,
        rules=(),
        profile=PolicyProfile.CUSTOM,
    )
    assert changed_source.default_effect is PolicyEffect.ALLOW
    after = evaluator.evaluate(
        action(session.session_id, Operation.DELETE, canonical_path=".env"),
    )

    assert before.policy_decision is PolicyDecision.VIOLATION
    assert after.policy_decision is before.policy_decision
    assert before.policy_id == policy.policy_id
    assert before.policy_version == policy.policy_version
    assert before.policy_profile is PolicyProfile.CUSTOM
    assert before.active_policy_fingerprint == snapshot.sha256


def test_session_mismatch_is_indeterminate(tmp_path: Path) -> None:
    session, snapshot = make_snapshot(tmp_path, resolved_policy())
    result = RuntimePolicyEvaluator(snapshot).evaluate(
        action("different-session", Operation.READ),
    )
    assert result.policy_decision is PolicyDecision.INDETERMINATE
    assert result.reason == RuntimePolicyReason.POLICY_SESSION_MISMATCH


@pytest.mark.parametrize(
    ("effect", "decision", "audit"),
    [
        (PolicyEffect.ALLOW, PolicyDecision.COMPLIANT, False),
        (PolicyEffect.AUDIT, PolicyDecision.COMPLIANT, True),
        (PolicyEffect.DENY, PolicyDecision.VIOLATION, False),
    ],
)
def test_allow_audit_deny_mapping(
    tmp_path: Path,
    effect: PolicyEffect,
    decision: PolicyDecision,
    audit: bool,
) -> None:
    policy = resolved_policy(rules=(file_rule("rule", "target.txt", effect),))
    session, snapshot = make_snapshot(tmp_path, policy)
    result = RuntimePolicyEvaluator(snapshot).evaluate(
        action(session.session_id, Operation.DELETE),
    )
    assert result.policy_decision is decision
    assert result.audit_record is audit
    assert result.operation_effect is effect


@pytest.mark.parametrize("operation", [Operation.READ, Operation.CREATE, Operation.MODIFY, Operation.DELETE])
def test_file_operations_use_canonical_path(tmp_path: Path, operation: Operation) -> None:
    policy = resolved_policy(rules=(file_rule("file-rule", "src/*.py", PolicyEffect.DENY, operation=operation),))
    session, snapshot = make_snapshot(tmp_path, policy)
    result = RuntimePolicyEvaluator(snapshot).evaluate(
        action(session.session_id, operation, canonical_path="SRC/main.PY"),
    )
    assert result.policy_decision is PolicyDecision.VIOLATION
    assert result.path == "SRC/main.PY"


def test_missing_or_outside_path_is_indeterminate(tmp_path: Path) -> None:
    session, snapshot = make_snapshot(tmp_path, resolved_policy(default_effect=PolicyEffect.ALLOW))
    evaluator = RuntimePolicyEvaluator(snapshot)
    missing = evaluator.evaluate(action(session.session_id, Operation.DELETE, canonical_path=None))
    outside = evaluator.evaluate(
        action(
            session.session_id,
            Operation.DELETE,
            canonical_path=None,
            limitations=("OUTSIDE_WORKSPACE",),
        )
    )
    assert missing.policy_decision is PolicyDecision.INDETERMINATE
    assert missing.reason == RuntimePolicyReason.POLICY_PATH_EVIDENCE_INSUFFICIENT
    assert outside.policy_decision is PolicyDecision.INDETERMINATE


def test_partial_action_can_be_evaluated_when_policy_fields_exist(tmp_path: Path) -> None:
    policy = resolved_policy(rules=(file_rule("partial-ok", "target.txt", PolicyEffect.DENY),))
    session, snapshot = make_snapshot(tmp_path, policy)
    result = RuntimePolicyEvaluator(snapshot).evaluate(
        action(
            session.session_id,
            Operation.DELETE,
            completeness=NormalizationCompleteness.PARTIAL,
            limitations=("PARENT_IDENTITY_PARTIAL",),
        )
    )
    assert result.policy_decision is PolicyDecision.VIOLATION


def test_process_execute_without_command_is_indeterminate(tmp_path: Path) -> None:
    session, snapshot = make_snapshot(tmp_path, resolved_policy())
    result = RuntimePolicyEvaluator(snapshot).evaluate(
        action(
            session.session_id,
            Operation.EXECUTE,
            target_kind=ActionTargetKind.PROCESS,
            canonical_path=None,
            normalized_command="drop table users",
        )
    )
    assert result.policy_decision is PolicyDecision.INDETERMINATE
    assert result.reason == RuntimePolicyReason.COMMAND_EVIDENCE_INSUFFICIENT


def test_command_uses_raw_command_and_existing_lexical_normalization(tmp_path: Path) -> None:
    policy = resolved_policy(
        rules=(command_rule("drop", "DROP TABLE", PolicyEffect.DENY),)
    )
    session, snapshot = make_snapshot(tmp_path, policy)
    result = RuntimePolicyEvaluator(snapshot).evaluate(
        action(
            session.session_id,
            Operation.EXECUTE,
            target_kind=ActionTargetKind.COMMAND,
            canonical_path=None,
            raw_command="  drop   table users  ",
            normalized_command="allow this fabricated value",
        )
    )
    assert result.policy_decision is PolicyDecision.VIOLATION
    assert result.normalized_command == "drop table users"
    assert result.command_pattern_ids == ("drop",)


def test_opaque_script_is_not_given_semantic_effect(tmp_path: Path) -> None:
    policy = resolved_policy(rules=(command_rule("drop", "DROP TABLE", PolicyEffect.DENY),))
    session, snapshot = make_snapshot(tmp_path, policy)
    result = RuntimePolicyEvaluator(snapshot).evaluate(
        action(
            session.session_id,
            Operation.EXECUTE,
            target_kind=ActionTargetKind.COMMAND,
            canonical_path=None,
            raw_command="python reset_db.py",
        )
    )
    assert result.policy_decision is PolicyDecision.COMPLIANT
    assert result.matched_rule_ids == ()


def test_move_evaluates_both_paths_and_aggregates_conservatively(tmp_path: Path) -> None:
    policy = resolved_policy(
        rules=(
            file_rule("source", "src/**", PolicyEffect.ALLOW, operation=Operation.MOVE),
            file_rule("destination", "protected/**", PolicyEffect.DENY, operation=Operation.MOVE),
        )
    )
    session, snapshot = make_snapshot(tmp_path, policy)
    result = RuntimePolicyEvaluator(snapshot).evaluate(
        action(
            session.session_id,
            Operation.MOVE,
            source_path="src/a.txt",
            destination_path="protected/a.txt",
            canonical_path=None,
        )
    )
    assert result.policy_decision is PolicyDecision.VIOLATION
    assert [item.role for item in result.path_evaluations] == [
        RuntimePathRole.SOURCE,
        RuntimePathRole.DESTINATION,
    ]
    assert [item.policy_decision for item in result.path_evaluations] == [
        PolicyDecision.COMPLIANT,
        PolicyDecision.VIOLATION,
    ]
    assert result.matched_rule_ids == ("source", "destination")


def test_move_with_valid_and_missing_path_is_indeterminate_without_violation(
    tmp_path: Path,
) -> None:
    policy = resolved_policy(
        rules=(file_rule("source", "src/**", PolicyEffect.ALLOW, operation=Operation.RENAME),)
    )
    session, snapshot = make_snapshot(tmp_path, policy)
    result = RuntimePolicyEvaluator(snapshot).evaluate(
        action(
            session.session_id,
            Operation.RENAME,
            source_path="src/a.txt",
            destination_path=None,
            canonical_path=None,
        )
    )
    assert result.policy_decision is PolicyDecision.INDETERMINATE
    assert result.path_evaluations[0].policy_decision is PolicyDecision.COMPLIANT
    assert result.path_evaluations[1].policy_decision is PolicyDecision.INDETERMINATE


def test_same_priority_conflict_is_indeterminate_and_does_not_deny_win(
    tmp_path: Path,
) -> None:
    policy = resolved_policy(
        rules=(
            file_rule("allow", "target.txt", PolicyEffect.ALLOW),
            file_rule("deny", "target.txt", PolicyEffect.DENY),
        )
    )
    session, snapshot = make_snapshot(tmp_path, policy)
    result = RuntimePolicyEvaluator(snapshot).evaluate(
        action(session.session_id, Operation.DELETE)
    )
    assert result.policy_decision is PolicyDecision.INDETERMINATE
    assert result.reason == "POLICY_CONFLICT"
    assert result.matched_rule_ids == ("allow", "deny")


def test_batch_preserves_order_counts_and_action_failures(tmp_path: Path) -> None:
    policy = resolved_policy(rules=(file_rule("deny", "blocked.txt", PolicyEffect.DENY),))
    session, snapshot = make_snapshot(tmp_path, policy)
    evaluator = RuntimePolicyEvaluator(snapshot)
    actions = (
        action(session.session_id, Operation.DELETE, canonical_path="ok.txt", action_id="a"),
        action(session.session_id, Operation.DELETE, canonical_path="blocked.txt", action_id="b"),
        action(session.session_id, Operation.DELETE, canonical_path=None, action_id="c"),
    )
    batch = evaluator.evaluate_batch(actions, evaluated_at=BASE_TIME)
    assert [result.action_id for result in batch.results] == ["a", "b", "c"]
    assert batch.compliant_count == 1
    assert batch.violation_count == 1
    assert batch.indeterminate_count == 1
    assert batch.audit_count == 0


def test_policy_and_attribution_can_be_created_independently(tmp_path: Path) -> None:
    policy = resolved_policy(rules=(file_rule("deny", ".env", PolicyEffect.DENY),))
    session, snapshot = make_snapshot(tmp_path, policy)
    action_value = action(session.session_id, Operation.DELETE, canonical_path=".env")
    result = RuntimePolicyEvaluator(snapshot).evaluate(action_value)
    assert result.policy_decision is PolicyDecision.VIOLATION
    assert not hasattr(result, "attribution_grade")


@pytest.mark.parametrize(
    "grade",
    [
        AttributionGrade.EXACT,
        AttributionGrade.PROCESS,
        AttributionGrade.TEMPORAL,
        AttributionGrade.UNKNOWN,
    ],
)
def test_all_attribution_grades_leave_policy_decision_unchanged(
    tmp_path: Path,
    grade: AttributionGrade,
) -> None:
    policy = resolved_policy(rules=(file_rule("deny", ".env", PolicyEffect.DENY),))
    session, snapshot = make_snapshot(tmp_path, policy)
    action_value = action(session.session_id, Operation.DELETE, canonical_path=".env")
    # The grade is deliberately only a parallel result input in this fixture;
    # RuntimePolicyEvaluator has no Attribution dependency or parameter.
    policy_result = RuntimePolicyEvaluator(snapshot).evaluate(action_value)
    parallel_result = (action_value.action_id, grade, policy_result.policy_decision)
    assert parallel_result == (
        action_value.action_id,
        grade,
        PolicyDecision.VIOLATION,
    )


def test_stage_is_preserved_and_violation_has_no_enforcement_action(
    tmp_path: Path,
) -> None:
    policy = resolved_policy(rules=(file_rule("deny", ".env", PolicyEffect.DENY),))
    session, snapshot = make_snapshot(tmp_path, policy)
    result = RuntimePolicyEvaluator(snapshot).evaluate(
        action(
            session.session_id,
            Operation.DELETE,
            canonical_path=".env",
            stage=ObservationStage.PRE_ACTION,
        )
    )
    assert result.stage is ObservationStage.PRE_ACTION
    assert result.policy_decision is PolicyDecision.VIOLATION
    assert not hasattr(result, "blocked")
    assert not hasattr(result, "terminated")


def test_real_raw_to_normalize_to_policy_pipeline(tmp_path: Path) -> None:
    policy = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT)
    session, snapshot = make_snapshot(tmp_path, policy)
    raw = {
        "event_type": "deleted",
        "src_path": ".env",
        "dest_path": None,
        "is_directory": False,
    }
    from aia import EvidenceRecordType, RawEvidenceRecord

    record = RawEvidenceRecord(
        session_id=session.session_id,
        source=EvidenceSource.FILESYSTEM_WATCHER,
        record_type=EvidenceRecordType.FILESYSTEM_EVENT,
        captured_at=BASE_TIME,
        observation_stage=ObservationStage.POST_ACTION,
        payload=raw,
        evidence_id="raw-delete-env",
    )
    normalized = normalize_evidence(
        [record], aia_session_id=session.session_id, workspace=session.workspace
    )
    result = RuntimePolicyEvaluator(snapshot, asset_type=SecurityAssetType.SECRET).evaluate(
        normalized.actions[0]
    )
    assert result.policy_decision is PolicyDecision.VIOLATION
    assert result.action_id == normalized.actions[0].action_id


def test_preparing_context_can_supply_the_frozen_authority(tmp_path: Path) -> None:
    policy = resolved_policy()
    session, snapshot = make_snapshot(tmp_path, policy)
    # prepare_protection is intentionally not required for evaluation, but its
    # context is accepted when a caller already has the EPIC-004 preparation object.
    context = prepare_protection(session, policy, tmp_path / "control-2")
    assert context.active_policy.sha256 == snapshot.sha256
    result = RuntimePolicyEvaluator(context).evaluate(action(session.session_id, Operation.READ))
    assert result.policy_decision is PolicyDecision.COMPLIANT
