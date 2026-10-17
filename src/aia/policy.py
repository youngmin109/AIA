"""User-defined security policy domain and deterministic evaluation."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatchcase
from functools import lru_cache
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
    PROTECTED_DEVELOPMENT = "PROTECTED_DEVELOPMENT"
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
        PolicyProfile.PROTECTED_DEVELOPMENT: "보호 우선 개발형",
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


# A shell wrapper around a script: powershell/pwsh/cmd [flags] -Command|/c <script>.
_SHELL_WRAPPER = re.compile(
    r'^\s*(?:"[^"]*?(?:powershell|pwsh|cmd)(?:\.exe)?"|[^\s"\']*?(?:powershell|pwsh|cmd)(?:\.exe)?)'
    r'(?:\s+-(?:noprofile|nologo|noninteractive|executionpolicy\s+\S+))*'
    r'\s+(?:-command|-c|/c|/k)\s+(.+)$',
    re.IGNORECASE | re.DOTALL,
)
_STATEMENT_SEPARATORS = frozenset(";|&\n\r{}()")
# powershell/pwsh -EncodedCommand <base64 of UTF-16LE script>, under any prefix
# PowerShell accepts for the parameter (-e, -ec, -enc, ... -EncodedCommand).
_ENCODED_COMMAND = re.compile(
    r'(?:powershell|pwsh)(?:\.exe)?["\']?(?:\s+[^\s|;&]+)*?\s+[-/]{1,2}'
    r'(?:e|ec|en(?:c(?:o(?:d(?:e(?:d(?:c(?:o(?:m(?:m(?:a(?:n(?:d)?)?)?)?)?)?)?)?)?)?)?)?)'
    r'\s+["\']?([A-Za-z0-9+/]{4,}={0,2})(?![A-Za-z0-9+/=])',
    re.IGNORECASE,
)
_ENCODED_DEPTH = 3


def _encoded_scripts(raw_command: str, depth: int = 0) -> tuple[str, ...]:
    """Scripts hidden as -EncodedCommand in a command, decoded (nested ones too).

    A value that is not valid base64 of UTF-16LE text is left alone: the
    command is then judged by its visible text as before.
    """

    if depth >= _ENCODED_DEPTH:
        return ()
    scripts: list[str] = []
    for match in _ENCODED_COMMAND.finditer(raw_command):
        try:
            script = base64.b64decode(match.group(1), validate=True).decode("utf-16-le")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if script.strip():
            scripts.append(script)
            scripts.extend(_encoded_scripts(script, depth + 1))
    return tuple(scripts)


def _split_statements(text: str) -> list[str]:
    """Split a script on statement separators that are outside quotes."""

    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for char in text:
        if quote is not None:
            current.append(char)
            if char == quote:
                quote = None
        elif char in "\'\"":
            quote = char
            current.append(char)
        elif char in _STATEMENT_SEPARATORS:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


@lru_cache(maxsize=512)
def command_segments(raw_command: str) -> tuple[str, ...]:
    """The whole command and each statement in it, normalized.

    Lexical only.  A powershell/cmd wrapper is opened and the script is split
    on ``;``, ``|``, ``&``, newlines, braces and parentheses outside quotes, so
    a command pattern also matches a statement in the middle of a script
    (``$t = 'x'; Remove-Item $t``), not only the start of the whole command.
    A script passed as ``-EncodedCommand`` is decoded and judged the same way.
    """

    segments = [normalize_command(raw_command)]
    pending = [raw_command, *_encoded_scripts(raw_command)]
    while pending and len(segments) < 200:
        text = pending.pop()
        wrapped = _SHELL_WRAPPER.match(text)
        if wrapped is not None:
            inner = wrapped.group(1).strip()
            if len(inner) > 1 and inner[0] == inner[-1] and inner[0] in "\'\"":
                inner = inner[1:-1]
            pending.append(inner)
            continue
        statements = _split_statements(text)
        if len(statements) == 1 and statements[0] == text.strip():
            segments.append(normalize_command(text))
            continue
        pending.extend(reversed(statements))
    return tuple(dict.fromkeys(segments))


def _command_pattern_matches(command: str, pattern: str) -> bool:
    normalized_pattern = normalize_command(pattern)
    for normalized_command in command_segments(command):
        if any(char in normalized_pattern for char in "*?["):
            if fnmatchcase(normalized_command, normalized_pattern):
                return True
        elif normalized_command == normalized_pattern or normalized_command.startswith(
            f"{normalized_pattern} "
        ):
            return True
    return False


# Shell verbs and inline Python file calls that visibly delete, move, rename or
# overwrite a path the same command names.  Reading needs no verb: any command
# that names a read-denied path can print, copy or send it (see
# command_path_denials).
_COMMAND_FILE_VERBS: Mapping[Operation, re.Pattern[str]] = MappingProxyType(
    {
        Operation.DELETE: re.compile(
            r"(?<![\w-])(?:remove-item|ri|rm|del|erase|rd|rmdir|unlink|shred)(?![\w-])"
            r"|::delete\(|\.delete\("
            r"|os\.(?:remove|removedirs)\(|shutil\.rmtree\("
        ),
        Operation.MOVE: re.compile(r"(?<![\w-])(?:move-item|mi|mv|move)(?![\w-])|::move\(|os\.replace\("),
        Operation.RENAME: re.compile(r"(?<![\w-])(?:rename-item|rni|ren|rename)(?![\w-])"),
        Operation.MODIFY: re.compile(
            r"(?<![\w-])(?:set-content|add-content|clear-content|clc|out-file|tee-object|truncate)(?![\w-])"
            r"|::(?:write|append)\w*\("
            # open(path, "w"/"a"/"x"/"r+"...), Path.open("w") and Path.write_text/write_bytes
            r"|(?<!\w)open\([^)]*,\s*(?:mode\s*=\s*)?['\"](?:[wax]|r\+)[^'\"]*['\"]"
            r"|\.open\(\s*(?:mode\s*=\s*)?['\"](?:[wax]|r\+)"
            r"|\.write_(?:text|bytes)\("
        ),
    }
)
_REDIRECT_TARGET = re.compile(r"(?<![\w>=-])>{1,2}\s*['\"]?([^\s'\";|&<>]+)")
_PATH_TOKEN_SPLIT = re.compile(r"[\s'\";|&(){}=,]+")


def _command_path_tokens(raw_command: str) -> tuple[str, ...]:
    tokens = (token for token in _PATH_TOKEN_SPLIT.split(raw_command) if len(token) > 1)
    return tuple(token for token in tokens if not token.startswith(("-", "$", "@")))


def _token_names_path(token: str, pattern: str) -> bool:
    """A command token names the pattern's path: absolute, deeper, or its tail.

    ``C:/w/shop/data/a.db`` and ``data/a.db`` both name ``shop/data/a.db``
    (the command may run in a sub-folder); a same-named file elsewhere is
    named too, which errs on the side of blocking.
    """

    try:
        normalized_token = normalize_path(token)
        normalized_pattern = normalize_path(pattern)
    except PolicyEvaluationError:
        return False
    parts = normalized_token.lstrip("/").split("/")
    if any(fnmatchcase("/".join(parts[index:]), normalized_pattern) for index in range(len(parts))):
        return True
    literal = not any(char in normalized_pattern for char in "*?[")
    return literal and (normalized_pattern == normalized_token or normalized_pattern.endswith("/" + normalized_token))


def command_path_denials(rules: Sequence[PolicyRule], raw_command: str) -> list[PolicyRule]:
    """File rules that DENY what a shell command visibly does to a path it names.

    Lexical, like command patterns: the command must name a path the rule
    protects and use a verb for an operation the rule denies (a redirect
    counts as modifying its own target only).  A rule that denies READ needs
    no verb: naming the path is enough, because ``gc``, ``rg``, ``Copy-Item``,
    ``python -c "open(...)"`` or ``curl -d @.env`` all read it.  Only DENY
    effects are derived, so this can block more but never allows anything a
    rule would not.  A script hidden as ``-EncodedCommand`` is checked too, and
    an ``apply_patch`` text is judged by the files its headers add, update,
    move or delete.
    """

    denied: list[PolicyRule] = []
    for source in (raw_command, *_encoded_scripts(raw_command)):
        for rule in _visible_path_denials(rules, source):
            if rule not in denied:
                denied.append(rule)
    return denied


# Codex's apply_patch tool names every file it touches in a header line.
_PATCH_HEADER = re.compile(
    r"^\*\*\* (Add|Update|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$",
    re.MULTILINE,
)
_PATCH_OPERATIONS = MappingProxyType(
    {"Add": Operation.CREATE, "Update": Operation.MODIFY, "Delete": Operation.DELETE}
)


def _patch_file_operations(raw_command: str) -> tuple[tuple[Operation, str], ...]:
    """The file operations an ``apply_patch`` text declares in its headers.

    ``*** Update File: a`` followed by ``*** Move to: b`` modifies and moves
    ``a`` and creates ``b``.  Anything that is not a patch declares nothing.
    """

    if "*** Begin Patch" not in raw_command:
        return ()
    operations: list[tuple[Operation, str]] = []
    for match in _PATCH_HEADER.finditer(raw_command):
        destination = match.group(3)
        if destination is None:
            operations.append((_PATCH_OPERATIONS[match.group(1)], match.group(2)))
            continue
        if operations and operations[-1][0] is Operation.MODIFY:
            operations.append((Operation.MOVE, operations[-1][1]))
        operations.append((Operation.CREATE, destination))
    return tuple(operations)


def _visible_path_denials(rules: Sequence[PolicyRule], raw_command: str) -> list[PolicyRule]:
    text = normalize_command(raw_command)
    patched = _patch_file_operations(raw_command)
    tokens = _command_path_tokens(raw_command)
    # curl and similar tools read a file given as @path.
    read_tokens = tokens + tuple(
        token[1:] for token in _PATH_TOKEN_SPLIT.split(raw_command) if token.startswith("@") and len(token) > 2
    )
    redirected = tuple(match.group(1) for match in _REDIRECT_TARGET.finditer(raw_command))
    denied: list[PolicyRule] = []
    for rule in rules:
        if not rule.path_patterns:
            continue
        if rule.operation_effects.get(Operation.READ) is PolicyEffect.DENY and any(
            _token_names_path(token, pattern) for token in read_tokens for pattern in rule.path_patterns
        ):
            denied.append(rule)
            continue
        if any(
            rule.operation_effects.get(operation) is PolicyEffect.DENY
            and any(_token_names_path(path, pattern) for pattern in rule.path_patterns)
            for operation, path in patched
        ):
            denied.append(rule)
            continue
        for operation, verb in _COMMAND_FILE_VERBS.items():
            if rule.operation_effects.get(operation) is not PolicyEffect.DENY:
                continue
            named = verb.search(text) is not None and any(
                _token_names_path(token, pattern) for token in tokens for pattern in rule.path_patterns
            )
            overwritten = operation is Operation.MODIFY and any(
                _token_names_path(token, pattern) for token in redirected for pattern in rule.path_patterns
            )
            if named or overwritten:
                denied.append(rule)
                break
    return denied


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
        if bool(normalized_paths) == bool(normalized_commands):
            raise PolicyValidationError(
                "a rule must define exactly one non-empty target: "
                "path_patterns or command_patterns"
            )
        if normalized_commands and any(
            operation is not Operation.EXECUTE for operation in effects
        ):
            raise PolicyValidationError(
                "a command rule may define only an EXECUTE effect"
            )
        if normalized_paths:
            if not effects:
                raise PolicyValidationError(
                    "a file rule must define at least one file operation effect"
                )
            if any(operation not in _FILE_OPERATIONS for operation in effects):
                raise PolicyValidationError(
                    "a file rule may define only file operation effects"
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
    asset_type: SecurityAssetType | None
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

    def evaluate_target(
        self,
        *,
        operation: Operation | str,
        path: str | None = None,
        raw_command: str | None = None,
    ) -> PolicyEvaluation:
        """Evaluate a mechanical target and derive asset type from matching rules."""

        return PolicyEngine(self).evaluate_target(
            operation=operation,
            path=path,
            raw_command=raw_command,
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
        """Evaluate the already resolved immutable policy object."""

        return self.policy.evaluate(
            subject,
            asset_type=asset_type,
            operation=operation,
            path=path,
            raw_command=raw_command,
            command=command,
        )

    def evaluate_target(
        self,
        *,
        operation: Operation | str,
        path: str | None = None,
        raw_command: str | None = None,
    ) -> PolicyEvaluation:
        """Evaluate a target against this already resolved policy."""

        return self.policy.evaluate_target(
            operation=operation,
            path=path,
            raw_command=raw_command,
        )


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

        matches = [
            (rule, rule.operation_effects[subject.operation])
            for rule in self.policy.rules
            if rule.matches(subject)
        ]
        if subject.operation is Operation.EXECUTE:
            matches += [
                (rule, PolicyEffect.DENY)
                for rule in command_path_denials(self.policy.rules, subject.raw_command)
                if rule.asset_type is subject.asset_type
            ]
        if matches:
            highest_priority = max(rule.priority for rule, _effect in matches)
            highest = [
                (rule, effect) for rule, effect in matches if rule.priority == highest_priority
            ]
            effects = {effect for _rule, effect in highest}
            matched_rule_ids = tuple(dict.fromkeys(rule.rule_id for rule, _effect in highest))
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

    def evaluate_target(
        self,
        *,
        operation: Operation | str,
        path: str | None = None,
        raw_command: str | None = None,
    ) -> PolicyEvaluation:
        """Evaluate operation/path/command without caller-supplied asset type.

        Runtime Actions carry mechanical target facts. This adapter checks each
        frozen rule with its declared asset type, applies the same priority and
        conflict rules, and derives the result asset type only when the winning
        rules identify one unambiguously. A no-match result uses the policy
        default effect and has no invented asset type.
        """

        normalized_operation = _enum_value(
            operation,
            Operation,
            label="operation",
        )
        normalized_command: str | None = None
        if raw_command is not None and raw_command.strip():
            normalized_command = normalize_command(raw_command)
        if normalized_operation in _FILE_OPERATIONS and (
            path is None or not path.strip()
        ):
            return PolicyEvaluation(
                policy_decision=PolicyDecision.INDETERMINATE,
                matched_rule_ids=(),
                asset_type=None,
                operation=normalized_operation,
                operation_effect=None,
                audit_record=False,
                reason="MISSING_PATH_EVIDENCE",
                limitation="path evidence is required for file operations",
                path=path,
                raw_command=raw_command,
                normalized_command=normalized_command,
            )
        if normalized_operation is Operation.EXECUTE and (
            raw_command is None or not raw_command.strip()
        ):
            return PolicyEvaluation(
                policy_decision=PolicyDecision.INDETERMINATE,
                matched_rule_ids=(),
                asset_type=None,
                operation=normalized_operation,
                operation_effect=None,
                audit_record=False,
                reason="MISSING_COMMAND_EVIDENCE",
                limitation="raw command evidence is required for EXECUTE",
                path=path,
                raw_command=raw_command,
                normalized_command=normalized_command,
            )

        matches = [
            (rule, rule.operation_effects[normalized_operation])
            for rule in self.policy.rules
            if rule.matches(
                PolicySubject(
                    asset_type=rule.asset_type,
                    operation=normalized_operation,
                    path=path,
                    raw_command=raw_command,
                )
            )
        ]
        if normalized_operation is Operation.EXECUTE:
            # A command that visibly deletes, moves, renames or overwrites a
            # protected path is judged by that path's DENY rule as well.
            matches += [
                (rule, PolicyEffect.DENY)
                for rule in command_path_denials(self.policy.rules, raw_command)
            ]
        if matches:
            highest_priority = max(rule.priority for rule, _effect in matches)
            highest = [
                (rule, effect) for rule, effect in matches if rule.priority == highest_priority
            ]
            matched_rule_ids = tuple(dict.fromkeys(rule.rule_id for rule, _effect in highest))
            effects = {effect for _rule, effect in highest}
            winning_asset_types = {
                rule.asset_type
                for rule, _effect in highest
            }
            asset_type = (
                next(iter(winning_asset_types))
                if len(winning_asset_types) == 1
                else None
            )
            if len(effects) > 1:
                return PolicyEvaluation(
                    policy_decision=PolicyDecision.INDETERMINATE,
                    matched_rule_ids=matched_rule_ids,
                    asset_type=asset_type,
                    operation=normalized_operation,
                    operation_effect=None,
                    audit_record=False,
                    reason="POLICY_CONFLICT",
                    limitation="same-priority rules have conflicting effects",
                    path=path,
                    raw_command=raw_command,
                    normalized_command=normalized_command,
                )
            effect = next(iter(effects))
        else:
            matched_rule_ids = ()
            asset_type = None
            effect = self.policy.default_effect

        decision = (
            PolicyDecision.VIOLATION
            if effect is PolicyEffect.DENY
            else PolicyDecision.COMPLIANT
        )
        return PolicyEvaluation(
            policy_decision=decision,
            matched_rule_ids=matched_rule_ids,
            asset_type=asset_type,
            operation=normalized_operation,
            operation_effect=effect,
            audit_record=effect is PolicyEffect.AUDIT,
            path=path,
            raw_command=raw_command,
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

_TOP_LEVEL_KEYS = frozenset(
    {
        "프로필",
        "정책명",
        "정책ID",
        "정책버전",
        "스키마버전",
        "기본효과",
        "규칙",
        "profile",
        "policy_name",
        "policy_id",
        "policy_version",
        "schema_version",
        "default_effect",
        "rules",
    }
)
_RULE_KEYS = frozenset(
    {
        "규칙ID",
        "우선순위",
        "자산유형",
        "경로패턴",
        "명령패턴",
        "행위효과",
        "rule_id",
        "priority",
        "asset_type",
        "path_patterns",
        "command_patterns",
        "operation_effects",
    }
)
_EFFECT_KEYS = frozenset(KOREAN_OPERATIONS) | frozenset(
    operation.value for operation in Operation
)


def _validate_object_keys(
    document: Mapping[str, Any],
    *,
    label: str,
    allowed: frozenset[str],
    alias_groups: tuple[tuple[str, ...], ...] = (),
) -> None:
    unknown = [key for key in document if key not in allowed]
    if unknown:
        raise PolicyValidationError(
            f"unknown {label} key(s): {', '.join(map(repr, unknown))}"
        )
    for aliases in alias_groups:
        present = [key for key in aliases if key in document]
        if len(present) > 1:
            raise PolicyValidationError(
                f"duplicate {label} field aliases: {', '.join(present)}"
            )


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
    _validate_object_keys(
        raw_rule,
        label="rule",
        allowed=_RULE_KEYS,
        alias_groups=(
            ("규칙ID", "rule_id"),
            ("우선순위", "priority"),
            ("자산유형", "asset_type"),
            ("경로패턴", "path_patterns"),
            ("명령패턴", "command_patterns"),
            ("행위효과", "operation_effects"),
        ),
    )
    path_keys = ("경로패턴", "path_patterns")
    command_keys = ("명령패턴", "command_patterns")
    has_path_key = any(key in raw_rule for key in path_keys)
    has_command_key = any(key in raw_rule for key in command_keys)
    if has_path_key == has_command_key:
        raise PolicyValidationError(
            "a rule must declare exactly one target key: "
            "경로패턴 or 명령패턴"
        )
    raw_effects = _document_value(
        raw_rule,
        "행위효과",
        "operation_effects",
    )
    if not isinstance(raw_effects, Mapping):
        raise PolicyValidationError("행위효과 must be an object")
    _validate_object_keys(
        raw_effects,
        label="operation effect",
        allowed=_EFFECT_KEYS,
    )
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
    _validate_object_keys(
        document,
        label="policy",
        allowed=_TOP_LEVEL_KEYS,
        alias_groups=(
            ("프로필", "profile"),
            ("정책명", "policy_name"),
            ("정책ID", "policy_id"),
            ("정책버전", "policy_version"),
            ("스키마버전", "schema_version"),
            ("기본효과", "default_effect"),
            ("규칙", "rules"),
        ),
    )
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
        PolicyProfile.PROTECTED_DEVELOPMENT: "보호-우선-개발형.ko.json",
        PolicyProfile.BASIC_DEVELOPMENT: "기본-개발형.ko.json",
        PolicyProfile.CONSERVATIVE_SECURITY: "보수적-보안형.ko.json",
        PolicyProfile.FREE_DEVELOPMENT: "자유-개발형.ko.json",
    }
)


class ProfileResolver:
    """Resolve a profile selection into one traceable SecurityAssetPolicy."""

    def __init__(self, profile_directory: str | Path | None = None) -> None:
        if profile_directory is not None:
            self.profile_directory = Path(profile_directory)
        else:
            repository_profiles = Path(__file__).resolve().parents[2] / "policies" / "profiles"
            packaged_profiles = Path(__file__).resolve().parent / "data" / "profiles"
            self.profile_directory = (
                repository_profiles
                if repository_profiles.is_dir()
                else packaged_profiles
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
