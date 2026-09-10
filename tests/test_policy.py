import json
from pathlib import Path

import pytest

from aia import (
    Operation,
    PolicyDecision,
    PolicyEffect,
    PolicyEngine,
    PolicyEvaluationError,
    PolicyProfile,
    PolicyResolutionError,
    PolicyRule,
    PolicySubject,
    PolicyValidationError,
    ProfileResolver,
    SecurityAssetPolicy,
    SecurityAssetType,
    load_policy_document,
    normalize_command,
    normalize_path,
    resolve_profile,
)


def evaluate(
    policy,
    asset_type,
    operation,
    *,
    path=None,
    command=None,
):
    return policy.evaluate(
        asset_type=asset_type,
        operation=operation,
        path=path,
        raw_command=command,
    )


def test_all_official_profiles_resolve() -> None:
    resolver = ProfileResolver()

    resolved = [
        resolver.resolve(profile)
        for profile in (
            PolicyProfile.PROTECTED_DEVELOPMENT,
            PolicyProfile.BASIC_DEVELOPMENT,
            PolicyProfile.CONSERVATIVE_SECURITY,
            PolicyProfile.FREE_DEVELOPMENT,
        )
    ]

    assert [item.profile for item in resolved] == [
        PolicyProfile.PROTECTED_DEVELOPMENT,
        PolicyProfile.BASIC_DEVELOPMENT,
        PolicyProfile.CONSERVATIVE_SECURITY,
        PolicyProfile.FREE_DEVELOPMENT,
    ]
    assert all(item.policy_id for item in resolved)
    assert all(item.policy_version == "1.0" for item in resolved)
    assert all(item.source for item in resolved)


@pytest.mark.parametrize(
    ("display_name", "profile"),
    [
        ("보호 우선 개발형", PolicyProfile.PROTECTED_DEVELOPMENT),
        ("기본 개발형", PolicyProfile.BASIC_DEVELOPMENT),
        ("보수적 보안형", PolicyProfile.CONSERVATIVE_SECURITY),
        ("자유 개발형", PolicyProfile.FREE_DEVELOPMENT),
        ("직접 설정", PolicyProfile.CUSTOM),
    ],
)
def test_korean_profile_name_maps_to_internal_enum(
    display_name: str,
    profile: PolicyProfile,
) -> None:
    assert PolicyProfile.from_value(display_name) is profile


def test_profile_is_distinct_from_session_mode() -> None:
    assert PolicyProfile.BASIC_DEVELOPMENT.value == "BASIC_DEVELOPMENT"
    assert PolicyProfile.BASIC_DEVELOPMENT.value != "ENFORCE"


def test_custom_profile_requires_explicit_policy() -> None:
    with pytest.raises(PolicyResolutionError):
        resolve_profile(PolicyProfile.CUSTOM)


def test_unsupported_profile_is_rejected() -> None:
    with pytest.raises(PolicyValidationError):
        PolicyProfile.from_value("차단형")


def test_basic_development_profile_has_expected_identity() -> None:
    resolved = resolve_profile("기본 개발형")

    assert resolved.profile is PolicyProfile.BASIC_DEVELOPMENT
    assert resolved.policy.policy_id == "aia-basic-development"
    assert resolved.policy.default_effect is PolicyEffect.ALLOW


def test_protected_development_profile_is_safe_by_default() -> None:
    policy = resolve_profile(PolicyProfile.PROTECTED_DEVELOPMENT).policy

    secret_read = policy.evaluate_target(operation=Operation.READ, path=".env")
    secret_command = policy.evaluate_target(
        operation=Operation.EXECUTE,
        raw_command="type .env",
    )
    normal_source_change = policy.evaluate_target(
        operation=Operation.MODIFY,
        path="src/app.py",
    )

    assert secret_read.policy_decision is PolicyDecision.VIOLATION
    assert secret_read.asset_type is SecurityAssetType.SECRET
    assert secret_command.policy_decision is PolicyDecision.VIOLATION
    assert secret_command.asset_type is SecurityAssetType.SECRET
    assert normal_source_change.policy_decision is PolicyDecision.COMPLIANT
    assert normal_source_change.operation_effect is PolicyEffect.AUDIT


@pytest.mark.parametrize(
    ("operation", "decision", "audit"),
    [
        (Operation.READ, PolicyDecision.COMPLIANT, False),
        (Operation.MODIFY, PolicyDecision.COMPLIANT, True),
        (Operation.DELETE, PolicyDecision.VIOLATION, False),
    ],
)
def test_basic_secret_policy(
    operation: Operation,
    decision: PolicyDecision,
    audit: bool,
) -> None:
    policy = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT).policy

    result = evaluate(
        policy,
        SecurityAssetType.SECRET,
        operation,
        path=".env",
    )

    assert result.policy_decision is decision
    assert result.audit_record is audit


def test_basic_dependency_delete_is_a_violation() -> None:
    policy = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT).policy

    result = evaluate(
        policy,
        SecurityAssetType.DEPENDENCY,
        Operation.DELETE,
        path="UV.LOCK",
    )

    assert result.policy_decision is PolicyDecision.VIOLATION


def test_basic_dockerfile_modify_is_audit() -> None:
    policy = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT).policy

    result = evaluate(
        policy,
        SecurityAssetType.INFRASTRUCTURE,
        Operation.MODIFY,
        path="dockerfile",
    )

    assert result.policy_decision is PolicyDecision.COMPLIANT
    assert result.operation_effect is PolicyEffect.AUDIT
    assert result.audit_record


@pytest.mark.parametrize(
    ("command", "decision", "audit"),
    [
        ("DROP TABLE users", PolicyDecision.VIOLATION, False),
        ("alembic downgrade head", PolicyDecision.COMPLIANT, True),
        ("git reset --hard HEAD", PolicyDecision.COMPLIANT, True),
        ("git clean -fdx", PolicyDecision.VIOLATION, False),
    ],
)
def test_basic_command_rules(
    command: str,
    decision: PolicyDecision,
    audit: bool,
) -> None:
    policy = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT).policy

    result = evaluate(
        policy,
        SecurityAssetType.DATABASE_RELATED
        if command.startswith(("DROP", "alembic"))
        else SecurityAssetType.REPOSITORY,
        Operation.EXECUTE,
        command=command,
    )

    assert result.policy_decision is decision
    assert result.audit_record is audit


def test_conservative_profile_rules() -> None:
    policy = resolve_profile(PolicyProfile.CONSERVATIVE_SECURITY).policy

    secret_read = evaluate(
        policy,
        SecurityAssetType.SECRET,
        Operation.READ,
        path=".env",
    )
    secret_modify = evaluate(
        policy,
        SecurityAssetType.SECRET,
        Operation.MODIFY,
        path=".env",
    )
    drop_table = evaluate(
        policy,
        SecurityAssetType.DATABASE_RELATED,
        Operation.EXECUTE,
        command="DROP TABLE users",
    )
    git_reset = evaluate(
        policy,
        SecurityAssetType.REPOSITORY,
        Operation.EXECUTE,
        command="git reset --hard HEAD",
    )

    assert secret_read.policy_decision is PolicyDecision.COMPLIANT
    assert secret_read.operation_effect is PolicyEffect.AUDIT
    assert secret_modify.policy_decision is PolicyDecision.VIOLATION
    assert drop_table.policy_decision is PolicyDecision.VIOLATION
    assert git_reset.policy_decision is PolicyDecision.VIOLATION


def test_conservative_unmatched_action_uses_audit_default() -> None:
    policy = resolve_profile(PolicyProfile.CONSERVATIVE_SECURITY).policy

    result = evaluate(
        policy,
        SecurityAssetType.WORKSPACE,
        Operation.MODIFY,
        path="src/aia/new.py",
    )

    assert result.policy_decision is PolicyDecision.COMPLIANT
    assert result.operation_effect is PolicyEffect.AUDIT
    assert result.audit_record


def test_free_profile_has_no_default_deny_rule() -> None:
    policy = resolve_profile(PolicyProfile.FREE_DEVELOPMENT).policy

    assert policy.default_effect is PolicyEffect.ALLOW
    assert all(
        rule.operation_effects.get(Operation.EXECUTE) is not PolicyEffect.DENY
        for rule in policy.rules
    )


def test_free_profile_secret_and_command_actions_are_audited() -> None:
    policy = resolve_profile(PolicyProfile.FREE_DEVELOPMENT).policy

    secret_modify = evaluate(
        policy,
        SecurityAssetType.SECRET,
        Operation.MODIFY,
        path=".env",
    )
    secret_delete = evaluate(
        policy,
        SecurityAssetType.SECRET,
        Operation.DELETE,
        path=".env",
    )
    drop_table = evaluate(
        policy,
        SecurityAssetType.DATABASE_RELATED,
        Operation.EXECUTE,
        command="DROP TABLE users",
    )
    clean = evaluate(
        policy,
        SecurityAssetType.REPOSITORY,
        Operation.EXECUTE,
        command="git clean -fdx",
    )

    assert all(
        result.policy_decision is PolicyDecision.COMPLIANT
        and result.operation_effect is PolicyEffect.AUDIT
        for result in (secret_modify, secret_delete, drop_table, clean)
    )


def custom_document(default_effect="금지"):
    return {
        "프로필": "직접 설정",
        "정책명": "테스트 직접 설정",
        "정책ID": "test-custom",
        "정책버전": "1.0",
        "스키마버전": "1",
        "기본효과": default_effect,
        "규칙": [
            {
                "규칙ID": "custom-drop-table",
                "우선순위": 100,
                "자산유형": "데이터베이스 관련 자산",
                "명령패턴": ["DROP TABLE"],
                "행위효과": {"실행": "허용"},
            },
            {
                "규칙ID": "custom-env-delete",
                "우선순위": 100,
                "자산유형": "비밀정보",
                "경로패턴": [".env"],
                "행위효과": {"삭제": "허용"},
            },
            {
                "규칙ID": "custom-git-reset",
                "우선순위": 100,
                "자산유형": "저장소 관련 자산",
                "명령패턴": ["git reset --hard"],
                "행위효과": {"실행": "금지"},
            },
        ],
    }


def test_custom_policy_is_complete_and_does_not_inherit_builtin_rules() -> None:
    resolved = resolve_profile(PolicyProfile.CUSTOM, custom_document())

    drop_table = evaluate(
        resolved.policy,
        SecurityAssetType.DATABASE_RELATED,
        Operation.EXECUTE,
        command="DROP TABLE users",
    )
    truncate = evaluate(
        resolved.policy,
        SecurityAssetType.DATABASE_RELATED,
        Operation.EXECUTE,
        command="TRUNCATE users",
    )

    assert drop_table.operation_effect is PolicyEffect.ALLOW
    assert truncate.operation_effect is PolicyEffect.DENY
    assert resolved.source == "<custom-policy>"


def test_custom_policy_can_allow_env_delete_and_deny_git_reset() -> None:
    policy = resolve_profile(PolicyProfile.CUSTOM, custom_document()).policy

    env_delete = evaluate(
        policy,
        SecurityAssetType.SECRET,
        Operation.DELETE,
        path=".env",
    )
    git_reset = evaluate(
        policy,
        SecurityAssetType.REPOSITORY,
        Operation.EXECUTE,
        command="git reset --hard",
    )

    assert env_delete.policy_decision is PolicyDecision.COMPLIANT
    assert git_reset.policy_decision is PolicyDecision.VIOLATION


def test_custom_policy_may_omit_asset_types() -> None:
    policy = load_policy_document(custom_document())

    assert len(policy.rules) == 3


def test_loader_maps_korean_vocabularies_at_boundary() -> None:
    policy = load_policy_document(custom_document())
    rule = policy.rules[0]

    assert rule.asset_type is SecurityAssetType.DATABASE_RELATED
    assert rule.operation_effects[Operation.EXECUTE] is PolicyEffect.ALLOW


def test_unknown_korean_vocabulary_is_rejected() -> None:
    document = custom_document()
    document["기본효과"] = "차단"

    with pytest.raises(PolicyValidationError):
        load_policy_document(document)


def test_policy_id_and_version_are_required() -> None:
    for field in ("정책ID", "정책버전"):
        document = custom_document()
        del document[field]
        with pytest.raises(PolicyValidationError):
            load_policy_document(document)


def test_duplicate_rule_id_is_rejected() -> None:
    document = custom_document()
    document["규칙"].append(dict(document["규칙"][0]))

    with pytest.raises(PolicyValidationError):
        load_policy_document(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [("규칙ID", ""), ("우선순위", "높음"), ("우선순위", True)],
)
def test_invalid_rule_fields_are_rejected(field: str, value) -> None:
    document = custom_document()
    document["규칙"][0][field] = value

    with pytest.raises(PolicyValidationError):
        load_policy_document(document)


def test_empty_path_and_command_patterns_are_rejected() -> None:
    for field in ("경로패턴", "명령패턴"):
        document = custom_document()
        document["규칙"][0][field] = [""]
        with pytest.raises(PolicyValidationError):
            load_policy_document(document)


def test_command_rule_requires_execute_effect() -> None:
    document = custom_document()
    document["규칙"][0]["행위효과"] = {"읽기": "허용"}

    with pytest.raises(PolicyValidationError):
        load_policy_document(document)


def test_unknown_top_level_key_is_rejected() -> None:
    document = custom_document()
    document["정책버젼"] = "typo"

    with pytest.raises(PolicyValidationError):
        load_policy_document(document)


def test_unknown_rule_key_is_rejected() -> None:
    document = custom_document()
    document["규칙"][0]["우선도"] = 100

    with pytest.raises(PolicyValidationError):
        load_policy_document(document)


def test_unknown_operation_effect_key_is_rejected() -> None:
    document = custom_document()
    document["규칙"][0]["행위효과"]["행위효과오타"] = "허용"

    with pytest.raises(PolicyValidationError):
        load_policy_document(document)


def test_path_and_command_targets_on_one_rule_are_rejected() -> None:
    document = custom_document()
    document["규칙"][0]["경로패턴"] = [".env"]

    with pytest.raises(PolicyValidationError):
        load_policy_document(document)


def test_empty_opposite_target_key_is_also_rejected() -> None:
    document = custom_document()
    document["규칙"][0]["경로패턴"] = []

    with pytest.raises(PolicyValidationError):
        load_policy_document(document)


def test_rule_without_path_or_command_target_is_rejected() -> None:
    document = custom_document()
    del document["규칙"][0]["명령패턴"]

    with pytest.raises(PolicyValidationError):
        load_policy_document(document)


def test_file_rule_cannot_define_execute_effect() -> None:
    document = custom_document()
    rule = document["규칙"][0]
    del rule["명령패턴"]
    rule["경로패턴"] = [".env"]
    rule["자산유형"] = "비밀정보"
    rule["행위효과"] = {"실행": "금지"}

    with pytest.raises(PolicyValidationError):
        load_policy_document(document)


def test_command_rule_cannot_define_non_execute_effect() -> None:
    document = custom_document()
    document["규칙"][0]["행위효과"] = {"읽기": "허용"}

    with pytest.raises(PolicyValidationError):
        load_policy_document(document)


def test_missing_operation_effect_uses_policy_default() -> None:
    policy = load_policy_document(custom_document(default_effect="기록"))

    result = evaluate(
        policy,
        SecurityAssetType.SECRET,
        Operation.READ,
        path=".env",
    )

    assert result.matched_rule_ids == ()
    assert result.operation_effect is PolicyEffect.AUDIT
    assert result.policy_decision is PolicyDecision.COMPLIANT
    assert result.audit_record


def test_partial_file_operation_rule_is_valid() -> None:
    policy = load_policy_document(custom_document(default_effect="기록"))

    delete_result = evaluate(
        policy,
        SecurityAssetType.SECRET,
        Operation.DELETE,
        path=".env",
    )
    read_result = evaluate(
        policy,
        SecurityAssetType.SECRET,
        Operation.READ,
        path=".env",
    )

    assert delete_result.operation_effect is PolicyEffect.ALLOW
    assert read_result.operation_effect is PolicyEffect.AUDIT


def test_resolved_policy_evaluates_its_immutable_policy_object() -> None:
    resolved = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT)

    result = resolved.evaluate(
        asset_type=SecurityAssetType.SECRET,
        operation=Operation.DELETE,
        path=".env",
    )

    assert resolved.resolved_policy is resolved.policy
    assert result.policy_decision is PolicyDecision.VIOLATION


def test_path_matching_is_case_insensitive_and_separator_stable() -> None:
    policy = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT).policy

    result = evaluate(
        policy,
        SecurityAssetType.SECRET,
        Operation.DELETE,
        path=r"SRC\..\.ENV",
    )
    nested = evaluate(
        policy,
        SecurityAssetType.DEPENDENCY,
        Operation.DELETE,
        path=r"UV.LOCK",
    )

    assert normalize_path(r"SRC\AUTH\LOGIN.PY") == "src/auth/login.py"
    assert result.policy_decision is PolicyDecision.VIOLATION
    assert nested.policy_decision is PolicyDecision.VIOLATION


def test_command_normalization_preserves_raw_command() -> None:
    policy = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT).policy
    raw = "  DROP   TABLE users  "

    result = evaluate(
        policy,
        SecurityAssetType.DATABASE_RELATED,
        Operation.EXECUTE,
        command=raw,
    )

    assert normalize_command(raw) == "drop table users"
    assert result.raw_command == raw
    assert result.normalized_command == "drop table users"
    assert result.policy_decision is PolicyDecision.VIOLATION


def test_command_matching_does_not_infer_script_meaning() -> None:
    policy = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT).policy

    result = evaluate(
        policy,
        SecurityAssetType.DATABASE_RELATED,
        Operation.EXECUTE,
        command="python reset_db.py",
    )

    assert result.policy_decision is PolicyDecision.COMPLIANT
    assert result.operation_effect is PolicyEffect.ALLOW
    assert result.matched_rule_ids == ()


def test_missing_file_path_evidence_is_indeterminate() -> None:
    policy = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT).policy

    result = evaluate(
        policy,
        SecurityAssetType.SECRET,
        Operation.DELETE,
    )

    assert result.policy_decision is PolicyDecision.INDETERMINATE
    assert result.reason == "MISSING_PATH_EVIDENCE"
    assert not result.audit_record


def test_missing_command_evidence_is_indeterminate() -> None:
    policy = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT).policy

    result = evaluate(
        policy,
        SecurityAssetType.DATABASE_RELATED,
        Operation.EXECUTE,
    )

    assert result.policy_decision is PolicyDecision.INDETERMINATE
    assert result.reason == "MISSING_COMMAND_EVIDENCE"


def make_conflict_policy() -> SecurityAssetPolicy:
    rules = [
        PolicyRule(
            rule_id="allow-rule",
            priority=10,
            asset_type=SecurityAssetType.WORKSPACE,
            path_patterns=["src/*.py"],
            operation_effects={Operation.MODIFY: PolicyEffect.ALLOW},
        ),
        PolicyRule(
            rule_id="deny-rule",
            priority=10,
            asset_type=SecurityAssetType.WORKSPACE,
            path_patterns=["src/*.py"],
            operation_effects={Operation.MODIFY: PolicyEffect.DENY},
        ),
    ]
    return SecurityAssetPolicy(
        schema_version="1",
        policy_id="conflict",
        policy_version="1.0",
        default_effect=PolicyEffect.ALLOW,
        rules=rules,
    )


def test_highest_priority_rule_wins() -> None:
    policy = SecurityAssetPolicy(
        schema_version="1",
        policy_id="priority",
        policy_version="1.0",
        default_effect=PolicyEffect.ALLOW,
        rules=[
            PolicyRule(
                rule_id="low",
                priority=1,
                asset_type=SecurityAssetType.WORKSPACE,
                path_patterns=["src/*.py"],
                operation_effects={Operation.MODIFY: PolicyEffect.DENY},
            ),
            PolicyRule(
                rule_id="high",
                priority=2,
                asset_type=SecurityAssetType.WORKSPACE,
                path_patterns=["src/*.py"],
                operation_effects={Operation.MODIFY: PolicyEffect.ALLOW},
            ),
        ],
    )

    result = evaluate(
        policy,
        SecurityAssetType.WORKSPACE,
        Operation.MODIFY,
        path="src/a.py",
    )

    assert result.operation_effect is PolicyEffect.ALLOW
    assert result.matched_rule_ids == ("high",)


def test_same_priority_conflict_is_indeterminate() -> None:
    result = evaluate(
        make_conflict_policy(),
        SecurityAssetType.WORKSPACE,
        Operation.MODIFY,
        path="SRC\\a.py",
    )

    assert result.policy_decision is PolicyDecision.INDETERMINATE
    assert result.reason == "POLICY_CONFLICT"
    assert result.matched_rule_ids == ("allow-rule", "deny-rule")


def test_same_priority_same_effect_keeps_all_rule_ids() -> None:
    policy = SecurityAssetPolicy(
        schema_version="1",
        policy_id="same-effect",
        policy_version="1.0",
        default_effect=PolicyEffect.DENY,
        rules=[
            PolicyRule(
                rule_id="first",
                priority=5,
                asset_type=SecurityAssetType.WORKSPACE,
                path_patterns=["src/*.py"],
                operation_effects={Operation.READ: PolicyEffect.ALLOW},
            ),
            PolicyRule(
                rule_id="second",
                priority=5,
                asset_type=SecurityAssetType.WORKSPACE,
                path_patterns=["src/*.py"],
                operation_effects={Operation.READ: PolicyEffect.ALLOW},
            ),
        ],
    )

    result = evaluate(
        policy,
        SecurityAssetType.WORKSPACE,
        Operation.READ,
        path="src/a.py",
    )

    assert result.policy_decision is PolicyDecision.COMPLIANT
    assert result.matched_rule_ids == ("first", "second")


def test_policy_engine_does_not_require_attribution() -> None:
    policy = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT).policy

    result = PolicyEngine(policy).evaluate(
        PolicySubject(
            asset_type=SecurityAssetType.SECRET,
            operation=Operation.DELETE,
            path=".env",
        )
    )

    assert result.policy_decision is PolicyDecision.VIOLATION


def test_policy_engine_rejects_mixed_subject_and_keywords() -> None:
    policy = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT).policy

    with pytest.raises(PolicyEvaluationError):
        PolicyEngine(policy).evaluate(
            PolicySubject(
                asset_type=SecurityAssetType.SECRET,
                operation=Operation.READ,
                path=".env",
            ),
            path=".env",
        )


def test_policy_document_can_be_loaded_from_a_file(tmp_path: Path) -> None:
    policy_path = tmp_path / "custom.ko.json"
    policy_path.write_text(
        json.dumps(custom_document(), ensure_ascii=False),
        encoding="utf-8",
    )

    resolved = resolve_profile(PolicyProfile.CUSTOM, policy_path)

    assert resolved.source == str(policy_path)
    assert resolved.policy.policy_id == "test-custom"
