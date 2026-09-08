"""User-defined security policy domain and deterministic evaluation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatchcase
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any


class PolicyError(ValueError):
    """Base error for policy loading, validation, and evaluation."""


class PolicyValidationError(PolicyError):
    """Raised when a policy document or domain value is invalid."""


class PolicyResolutionError(PolicyError):
    """Raised when a requested policy profile cannot be resolved."""


class PolicyEvaluationError(PolicyError):
    """Raised when an evaluation input cannot be represented."""


class PolicyProfile(StrEnum):
    BASIC_DEVELOPMENT = "BASIC_DEVELOPMENT"
    CONSERVATIVE_SECURITY = "CONSERVATIVE_SECURITY"
    FREE_DEVELOPMENT = "FREE_DEVELOPMENT"
    CUSTOM = "CUSTOM"

    @property
    def display_name(self) -> str:
        return POLICY_PROFILE_DISPLAY_NAMES[self]

    @classmethod
    def from_value(cls, value: "PolicyProfile | str") -> "PolicyProfile":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            for profile in cls:
                if value == profile.value or value == profile.display_name:
                    return profile
        raise PolicyValidationError(f"unsupported policy profile: {value!r}")


POLICY_PROFILE_DISPLAY_NAMES: Mapping[PolicyProfile, str] = MappingProxyType(
    {
        PolicyProfile.BASIC_DEVELOPMENT: "기본 개발형",
        PolicyProfile.CONSERVATIVE_SECURITY: "보수적 보안형",
        PolicyProfile.FREE_DEVELOPMENT: "자유 개발형",
        PolicyProfile.CUSTOM: "직접 설정",
    }
)


class SecurityAssetType(StrEnum):
    SECRET = "SECRET"
    DATABASE_RELATED = "DATABASE_RELATED"
    CRITICAL_CODE = "CRITICAL_CODE"
    DEPENDENCY = "DEPENDENCY"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    REPOSITORY = "REPOSITORY"
    WORKSPACE = "WORKSPACE"


class Operation(StrEnum):
    READ = "READ"
    CREATE = "CREATE"
    MODIFY = "MODIFY"
    DELETE = "DELETE"
    MOVE = "MOVE"
    RENAME = "RENAME"
    EXECUTE = "EXECUTE"


class PolicyEffect(StrEnum):
    ALLOW = "ALLOW"
    AUDIT = "AUDIT"
    DENY = "DENY"


class PolicyDecision(StrEnum):
    COMPLIANT = "COMPLIANT"
    VIOLATION = "VIOLATION"
    INDETERMINATE = "INDETERMINATE"


KOREAN_ASSET_TYPES: Mapping[str, SecurityAssetType] = MappingProxyType(
    {
        "비밀정보": SecurityAssetType.SECRET,
        "데이터베이스 관련 자산": SecurityAssetType.DATABASE_RELATED,
        "핵심 코드": SecurityAssetType.CRITICAL_CODE,
        "의존성 파일": SecurityAssetType.DEPENDENCY,
        "인프라 설정": SecurityAssetType.INFRASTRUCTURE,
        "저장소 관련 자산": SecurityAssetType.REPOSITORY,
        "작업공간": SecurityAssetType.WORKSPACE,
    }
)

KOREAN_OPERATIONS: Mapping[str, Operation] = MappingProxyType(
    {
        "읽기": Operation.READ,
        "생성": Operation.CREATE,
        "수정": Operation.MODIFY,
        "삭제": Operation.DELETE,
        "이동": Operation.MOVE,
        "이름변경": Operation.RENAME,
        "실행": Operation.EXECUTE,
    }
)

KOREAN_EFFECTS: Mapping[str, PolicyEffect] = MappingProxyType(
    {
        "허용": PolicyEffect.ALLOW,
        "기록": PolicyEffect.AUDIT,
        "금지": PolicyEffect.DENY,
    }
)

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


def _enum_value(
    value: Any,
    enum_type: type[StrEnum],
    *,
    label: str,
) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise PolicyValidationError(f"unknown {label}: {value!r}")
    try:
        return enum_type(value)
    except ValueError as error:
        raise PolicyValidationError(f"unknown {label}: {value!r}") from error


def _required_text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyValidationError(f"{label} must not be empty")
    return value


def _patterns(value: Sequence[str] | str | None, *, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, Sequence):
        values = tuple(value)
    else:
        raise PolicyValidationError(f"{label} must be a string list")
    result: list[str] = []
    for pattern in values:
        if not isinstance(pattern, str) or not pattern.strip():
            raise PolicyValidationError(f"{label} must not contain empty patterns")
        result.append(pattern)
    return tuple(result)


def normalize_path(path: str) -> str:
    """Normalize a workspace-relative path without touching the filesystem."""

    if not isinstance(path, str) or not path.strip():
        raise PolicyEvaluationError("path must not be empty")
    normalized = path.strip().replace("\\", "/")
    normalized = re.sub(r"/+", "/", normalized)
    leading_slash = normalized.startswith("/")
    parts: list[str] = []
    for part in normalized.split("/"):
        if not part or part == ".":
            continue
        if part == ".." and parts and parts[-1] != "..":
            parts.pop()
        else:
            parts.append(part)
    result = "/".join(parts).casefold()
    return f"/{result}" if leading_slash else result


def normalize_command(raw_command: str) -> str:
    """Apply only deterministic lexical command normalization."""

    if not isinstance(raw_command, str) or not raw_command.strip():
        raise PolicyEvaluationError("raw_command must not be empty")
    return re.sub(r"\s+", " ", raw_command.strip()).casefold()


def _path_pattern_matches(path: str, pattern: str) -> bool:
    return fnmatchcase(normalize_path(path), normalize_path(pattern))


def _command_pattern_matches(command: str, pattern: str) -> bool:
    normalized_command = normalize_command(command)
    normalized_pattern = normalize_command(pattern)
    if any(char in normalized_pattern for char in "*?["):
        return fnmatchcase(normalized_command, normalized_pattern)
    return normalized_command == normalized_pattern or normalized_command.startswith(
        f"{normalized_pattern} "
    )


@dataclass(frozen=True, slots=True)
class PolicySubject:
    """The observed facts supplied to policy evaluation."""

    asset_type: SecurityAssetType | str
    operation: Operation | str
    path: str | None = None
    raw_command: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "asset_type",
            _enum_value(
                self.asset_type,
                SecurityAssetType,
                label="asset type",
            ),
        )
        object.__setattr__(
            self,
            "operation",
            _enum_value(self.operation, Operation, label="operation"),
        )


@dataclass(frozen=True, slots=True)
class PolicyRule:
    rule_id: str
    priority: int
    asset_type: SecurityAssetType | str
    path_patterns: tuple[str, ...] | Sequence[str] = ()
    command_patterns: tuple[str, ...] | Sequence[str] = ()
    operation_effects: Mapping[Operation | str, PolicyEffect | str] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "rule_id",
            _required_text(self.rule_id, label="rule_id"),
        )
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise PolicyValidationError("priority must be an integer")
        object.__setattr__(
            self,
            "asset_type",
            _enum_value(
                self.asset_type,
                SecurityAssetType,
                label="asset type",
            ),
        )
        normalized_paths = _patterns(self.path_patterns, label="path_patterns")
        normalized_commands = _patterns(
            self.command_patterns,
            label="command_patterns",
        )
        object.__setattr__(self, "path_patterns", normalized_paths)
        object.__setattr__(self, "command_patterns", normalized_commands)

        if not isinstance(self.operation_effects, Mapping):
            raise PolicyValidationError("operation_effects must be a mapping")
        effects: dict[Operation, PolicyEffect] = {}
        for operation, effect in self.operation_effects.items():
            normalized_operation = _enum_value(
                operation,
                Operation,
                label="operation",
            )
            if normalized_operation in effects:
                raise PolicyValidationError(
                    f"duplicate operation in rule: {normalized_operation}"
                )
            effects[normalized_operation] = _enum_value(
                effect,
                PolicyEffect,
                label="effect",
            )
        if normalized_commands and Operation.EXECUTE not in effects:
            raise PolicyValidationError(
                "a command rule must define an EXECUTE effect"
            )
        object.__setattr__(self, "operation_effects", MappingProxyType(effects))

    def matches(self, subject: PolicySubject) -> bool:
        if self.asset_type is not subject.asset_type:
            return False
        if subject.operation not in self.operation_effects:
            return False
        if self.path_patterns and (
            subject.path is None
            or not any(
                _path_pattern_matches(subject.path, pattern)
                for pattern in self.path_patterns
            )
        ):
            return False
        if self.command_patterns and (
            subject.raw_command is None
            or not any(
                _command_pattern_matches(subject.raw_command, pattern)
                for pattern in self.command_patterns
            )
        ):
            return False
        return True


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    policy_decision: PolicyDecision
    matched_rule_ids: tuple[str, ...]
    asset_type: SecurityAssetType
    operation: Operation
    operation_effect: PolicyEffect | None
    audit_record: bool
    reason: str | None = None
    limitation: str | None = None
    path: str | None = None
    raw_command: str | None = None
    normalized_command: str | None = None


@dataclass(frozen=True, slots=True)
class SecurityAssetPolicy:
    schema_version: str
    policy_id: str
    policy_version: str
    default_effect: PolicyEffect | str
    rules: tuple[PolicyRule, ...] | Sequence[PolicyRule] = ()
    profile: PolicyProfile | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, label="schema_version"),
        )
        object.__setattr__(
            self,
            "policy_id",
            _required_text(self.policy_id, label="policy_id"),
        )
        object.__setattr__(
            self,
            "policy_version",
            _required_text(self.policy_version, label="policy_version"),
        )
        object.__setattr__(
            self,
            "default_effect",
            _enum_value(
                self.default_effect,
                PolicyEffect,
                label="default effect",
            ),
        )
        if not isinstance(self.rules, Sequence):
            raise PolicyValidationError("rules must be a sequence")
        normalized_rules = tuple(self.rules)
        if any(not isinstance(rule, PolicyRule) for rule in normalized_rules):
            raise PolicyValidationError("rules must contain PolicyRule values")
        rule_ids = [rule.rule_id for rule in normalized_rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise PolicyValidationError("duplicate rule ID")
        object.__setattr__(self, "rules", normalized_rules)
        if self.profile is not None:
            object.__setattr__(
                self,
                "profile",
                PolicyProfile.from_value(self.profile),
            )

    def evaluate(
        self,
        subject: PolicySubject | None = None,
        *,
        asset_type: SecurityAssetType | str | None = None,
        operation: Operation | str | None = None,
        path: str | None = None,
        raw_command: str | None = None,
        command: str | None = None,
    ) -> PolicyEvaluation:
        return PolicyEngine(self).evaluate(
            subject,
            asset_type=asset_type,
            operation=operation,
            path=path,
            raw_command=raw_command,
            command=command,
        )


@dataclass(frozen=True, slots=True)
class ResolvedPolicy:
    profile: PolicyProfile
    policy_id: str
    policy_version: str
    source: str
    policy: SecurityAssetPolicy

    @property
    def resolved_policy(self) -> SecurityAssetPolicy:
        return self.policy


class PolicyEngine:
    """Deterministic policy evaluator with no attribution or enforcement logic."""

    def __init__(self, policy: SecurityAssetPolicy) -> None:
        if not isinstance(policy, SecurityAssetPolicy):
            raise PolicyEvaluationError("policy must be a SecurityAssetPolicy")
        self.policy = policy

    def evaluate(
        self,
        subject: PolicySubject | None = None,
        *,
        asset_type: SecurityAssetType | str | None = None,
        operation: Operation | str | None = None,
        path: str | None = None,
        raw_command: str | None = None,
        command: str | None = None,
    ) -> PolicyEvaluation:
        if raw_command is not None and command is not None:
            raise PolicyEvaluationError(
                "provide only one of raw_command and command"
            )
        if command is not None:
            raw_command = command
        if subject is not None and any(
            value is not None
            for value in (asset_type, operation, path, raw_command)
        ):
            raise PolicyEvaluationError(
                "subject cannot be combined with evaluation keyword arguments"
            )
        if subject is None:
            if asset_type is None or operation is None:
                raise PolicyEvaluationError(
                    "asset_type and operation are required"
                )
            subject = PolicySubject(
                asset_type=asset_type,
                operation=operation,
                path=path,
                raw_command=raw_command,
            )
        elif not isinstance(subject, PolicySubject):
            raise PolicyEvaluationError("subject must be a PolicySubject")

        normalized_command: str | None = None
        if subject.raw_command is not None and subject.raw_command.strip():
            normalized_command = normalize_command(subject.raw_command)

        if subject.operation in _FILE_OPERATIONS and (
            subject.path is None or not subject.path.strip()
        ):
            return PolicyEvaluation(
                policy_decision=PolicyDecision.INDETERMINATE,
                matched_rule_ids=(),
                asset_type=subject.asset_type,
                operation=subject.operation,
                operation_effect=None,
                audit_record=False,
                reason="MISSING_PATH_EVIDENCE",
                limitation="path evidence is required for file operations",
                path=subject.path,
                raw_command=subject.raw_command,
                normalized_command=normalized_command,
            )
        if subject.operation is Operation.EXECUTE and (
            subject.raw_command is None or not subject.raw_command.strip()
        ):
            return PolicyEvaluation(
                policy_decision=PolicyDecision.INDETERMINATE,
                matched_rule_ids=(),
                asset_type=subject.asset_type,
                operation=subject.operation,
                operation_effect=None,
                audit_record=False,
                reason="MISSING_COMMAND_EVIDENCE",
                limitation="raw command evidence is required for EXECUTE",
                path=subject.path,
                raw_command=subject.raw_command,
                normalized_command=normalized_command,
            )

        matches = [rule for rule in self.policy.rules if rule.matches(subject)]
        if matches:
            highest_priority = max(rule.priority for rule in matches)
            highest = [
                rule for rule in matches if rule.priority == highest_priority
            ]
            effects = {rule.operation_effects[subject.operation] for rule in highest}
            matched_rule_ids = tuple(rule.rule_id for rule in highest)
            if len(effects) > 1:
                return PolicyEvaluation(
                    policy_decision=PolicyDecision.INDETERMINATE,
                    matched_rule_ids=matched_rule_ids,
                    asset_type=subject.asset_type,
                    operation=subject.operation,
                    operation_effect=None,
                    audit_record=False,
                    reason="POLICY_CONFLICT",
                    limitation="same-priority rules have conflicting effects",
                    path=subject.path,
                    raw_command=subject.raw_command,
                    normalized_command=normalized_command,
                )
            effect = next(iter(effects))
        else:
            matched_rule_ids = ()
            effect = self.policy.default_effect

        decision = (
            PolicyDecision.VIOLATION
            if effect is PolicyEffect.DENY
            else PolicyDecision.COMPLIANT
        )
        return PolicyEvaluation(
            policy_decision=decision,
            matched_rule_ids=matched_rule_ids,
            asset_type=subject.asset_type,
            operation=subject.operation,
            operation_effect=effect,
            audit_record=effect is PolicyEffect.AUDIT,
            path=subject.path,
            raw_command=subject.raw_command,
            normalized_command=normalized_command,
        )


def evaluate_policy(
    policy: SecurityAssetPolicy,
    subject: PolicySubject | None = None,
    **kwargs: Any,
) -> PolicyEvaluation:
    """Convenience function for one deterministic policy evaluation."""

    return PolicyEngine(policy).evaluate(subject, **kwargs)


_PROFILE_FIELD = "프로필"
_POLICY_ID_FIELD = "정책ID"
_POLICY_VERSION_FIELD = "정책버전"
_SCHEMA_VERSION_FIELD = "스키마버전"
_DEFAULT_EFFECT_FIELD = "기본효과"
_RULES_FIELD = "규칙"


def _document_value(
    document: Mapping[str, Any],
    korean_name: str,
    english_name: str,
    *,
    required: bool = True,
) -> Any:
    if korean_name in document:
        return document[korean_name]
    if english_name in document:
        return document[english_name]
    if required:
        raise PolicyValidationError(f"missing policy field: {korean_name}")
    return None


def _map_korean_or_internal(
    value: Any,
    *,
    korean: Mapping[str, StrEnum],
    enum_type: type[StrEnum],
    label: str,
) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str) and value in korean:
        return korean[value]
    return _enum_value(value, enum_type, label=label)


def _load_rule(raw_rule: Mapping[str, Any]) -> PolicyRule:
    if not isinstance(raw_rule, Mapping):
        raise PolicyValidationError("each rule must be an object")
    raw_effects = _document_value(
        raw_rule,
        "행위효과",
        "operation_effects",
    )
    if not isinstance(raw_effects, Mapping):
        raise PolicyValidationError("행위효과 must be an object")
    operation_effects: dict[Operation, PolicyEffect] = {}
    for raw_operation, raw_effect in raw_effects.items():
        operation = _map_korean_or_internal(
            raw_operation,
            korean=KOREAN_OPERATIONS,
            enum_type=Operation,
            label="operation",
        )
        effect = _map_korean_or_internal(
            raw_effect,
            korean=KOREAN_EFFECTS,
            enum_type=PolicyEffect,
            label="effect",
        )
        operation_effects[operation] = effect
    raw_asset_type = _document_value(
        raw_rule,
        "자산유형",
        "asset_type",
    )
    asset_type = _map_korean_or_internal(
        raw_asset_type,
        korean=KOREAN_ASSET_TYPES,
        enum_type=SecurityAssetType,
        label="asset type",
    )
    return PolicyRule(
        rule_id=_document_value(raw_rule, "규칙ID", "rule_id"),
        priority=_document_value(raw_rule, "우선순위", "priority"),
        asset_type=asset_type,
        path_patterns=_document_value(
            raw_rule,
            "경로패턴",
            "path_patterns",
            required=False,
        )
        or (),
        command_patterns=_document_value(
            raw_rule,
            "명령패턴",
            "command_patterns",
            required=False,
        )
        or (),
        operation_effects=operation_effects,
    )


def load_policy_document(
    document: Mapping[str, Any],
    *,
    source: str = "<mapping>",
) -> SecurityAssetPolicy:
    """Convert a Korean user policy document into the internal domain model."""

    if not isinstance(document, Mapping):
        raise PolicyValidationError("policy document must be an object")
    raw_profile = _document_value(
        document,
        _PROFILE_FIELD,
        "profile",
        required=False,
    )
    profile = (
        PolicyProfile.from_value(raw_profile) if raw_profile is not None else None
    )
    raw_rules = _document_value(document, _RULES_FIELD, "rules")
    if not isinstance(raw_rules, Sequence) or isinstance(raw_rules, str):
        raise PolicyValidationError("규칙 must be a list")
    rules = tuple(_load_rule(raw_rule) for raw_rule in raw_rules)
    return SecurityAssetPolicy(
        schema_version=_document_value(
            document,
            _SCHEMA_VERSION_FIELD,
            "schema_version",
        ),
        policy_id=_document_value(document, _POLICY_ID_FIELD, "policy_id"),
        policy_version=_document_value(
            document,
            _POLICY_VERSION_FIELD,
            "policy_version",
        ),
        default_effect=_map_korean_or_internal(
            _document_value(document, _DEFAULT_EFFECT_FIELD, "default_effect"),
            korean=KOREAN_EFFECTS,
            enum_type=PolicyEffect,
            label="default effect",
        ),
        rules=rules,
        profile=profile,
    )


def load_policy(path_or_document: str | Path | Mapping[str, Any]) -> SecurityAssetPolicy:
    """Load a UTF-8 Korean JSON policy or an already parsed policy document."""

    if isinstance(path_or_document, Mapping):
        return load_policy_document(path_or_document)
    path = Path(path_or_document)
    try:
        with path.open("r", encoding="utf-8") as stream:
            document = json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise PolicyValidationError(f"cannot load policy: {path}") from error
    return load_policy_document(document, source=str(path))


load_korean_policy = load_policy


_BUILTIN_PROFILE_FILES: Mapping[PolicyProfile, str] = MappingProxyType(
    {
        PolicyProfile.BASIC_DEVELOPMENT: "기본-개발형.ko.json",
        PolicyProfile.CONSERVATIVE_SECURITY: "보수적-보안형.ko.json",
        PolicyProfile.FREE_DEVELOPMENT: "자유-개발형.ko.json",
    }
)


class ProfileResolver:
    """Resolve a profile selection into one traceable SecurityAssetPolicy."""

    def __init__(self, profile_directory: str | Path | None = None) -> None:
        self.profile_directory = (
            Path(profile_directory)
            if profile_directory is not None
            else Path(__file__).resolve().parents[2] / "policies" / "profiles"
        )

    def resolve(
        self,
        profile: PolicyProfile | str,
        policy_source: str | Path | Mapping[str, Any] | None = None,
    ) -> ResolvedPolicy:
        selected = PolicyProfile.from_value(profile)
        if selected is PolicyProfile.CUSTOM:
            if policy_source is None:
                raise PolicyResolutionError(
                    "CUSTOM requires an explicit user policy document"
                )
            source_label = (
                str(policy_source)
                if isinstance(policy_source, (str, Path))
                else "<custom-policy>"
            )
        else:
            if policy_source is not None:
                raise PolicyResolutionError(
                    "built-in profiles do not accept a custom policy source"
                )
            try:
                source_path = self.profile_directory / _BUILTIN_PROFILE_FILES[selected]
            except KeyError as error:
                raise PolicyResolutionError(
                    f"no built-in policy exists for profile: {selected}"
                ) from error
            policy_source = source_path
            source_label = str(source_path)

        policy = load_policy(policy_source)
        if policy.profile is not None and policy.profile is not selected:
            raise PolicyResolutionError(
                f"policy profile does not match requested profile: {selected}"
            )
        return ResolvedPolicy(
            profile=selected,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            source=source_label,
            policy=policy,
        )


def resolve_profile(
    profile: PolicyProfile | str,
    policy_source: str | Path | Mapping[str, Any] | None = None,
    *,
    profile_directory: str | Path | None = None,
) -> ResolvedPolicy:
    return ProfileResolver(profile_directory).resolve(profile, policy_source)


__all__ = [
    "KOREAN_ASSET_TYPES",
    "KOREAN_EFFECTS",
    "KOREAN_OPERATIONS",
    "Operation",
    "PolicyDecision",
    "PolicyEffect",
    "PolicyEngine",
    "PolicyError",
    "PolicyEvaluation",
    "PolicyEvaluationError",
    "PolicyProfile",
    "PolicyResolutionError",
    "PolicyRule",
    "PolicySubject",
    "PolicyValidationError",
    "ProfileResolver",
    "ResolvedPolicy",
    "SecurityAssetPolicy",
    "SecurityAssetType",
    "evaluate_policy",
    "load_korean_policy",
    "load_policy",
    "load_policy_document",
    "normalize_command",
    "normalize_path",
    "POLICY_PROFILE_DISPLAY_NAMES",
    "resolve_profile",
]
