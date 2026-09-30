"""Handlers for policy inspection and editing CLI commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from typing import Callable

from aia import (
    Operation,
    POLICY_PROFILE_DISPLAY_NAMES,
    PolicyProfile,
    ResolvedPolicy,
    load_policy,
    policy_content_sha256,
    resolve_profile,
)


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, indent=2)


def validate_policy(args: argparse.Namespace) -> int:
    """Validate a policy before a Protected Run freezes it."""

    try:
        policy = load_policy(args.path)
        resolved = ResolvedPolicy(
            profile=policy.profile or PolicyProfile.CUSTOM,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            source=str(args.path),
            policy=policy,
        )
    except (OSError, ValueError) as error:
        if args.json:
            print(_json_text({"valid": False, "path": str(args.path), "error": str(error)}))
        else:
            print(f"정책 검증 실패: {error}")
        return 2

    payload = {
        "valid": True,
        "path": str(args.path.expanduser().resolve(strict=False)),
        "policy_id": resolved.policy_id,
        "policy_version": resolved.policy_version,
        "profile": resolved.profile.value,
        "rule_count": len(resolved.policy.rules),
        "sha256": policy_content_sha256(resolved),
    }
    if args.json:
        print(_json_text(payload))
    else:
        print("정책 검증 성공")
        print(f"정책 ID: {payload['policy_id']}")
        print(f"버전: {payload['policy_version']}")
        print(f"Rule 수: {payload['rule_count']}")
        print(f"SHA-256: {payload['sha256']}")
    return 0


def policy_profiles(args: argparse.Namespace, cli_prefix: Callable[[], str]) -> int:
    descriptions = {
        PolicyProfile.PROTECTED_DEVELOPMENT: "민감정보와 대표적인 파괴 명령을 기본 차단하는 보호 우선 정책",
        PolicyProfile.BASIC_DEVELOPMENT: "일반적인 개발 작업과 기본적인 보호를 함께 제공",
        PolicyProfile.CONSERVATIVE_SECURITY: "중요 자산 변경을 더 보수적으로 제한",
        PolicyProfile.FREE_DEVELOPMENT: "개발 자유도를 우선하고 관찰 중심으로 운용",
        PolicyProfile.CUSTOM: "사용자가 직접 작성하고 Strict Validation을 통과한 정책",
    }
    profiles = [
        {
            "value": profile.value,
            "label": POLICY_PROFILE_DISPLAY_NAMES[profile],
            "description": descriptions[profile],
            "editable": profile is not PolicyProfile.CUSTOM,
        }
        for profile in (
            PolicyProfile.PROTECTED_DEVELOPMENT,
            PolicyProfile.BASIC_DEVELOPMENT,
            PolicyProfile.CONSERVATIVE_SECURITY,
            PolicyProfile.FREE_DEVELOPMENT,
            PolicyProfile.CUSTOM,
        )
    ]
    if args.json:
        print(_json_text({"profiles": profiles}))
        return 0
    prefix = cli_prefix()
    print("AIA 정책 프로필")
    for item in profiles:
        edit_hint = "복사 후 수정 가능" if item["editable"] else "직접 JSON 필요"
        print(f"- {item['value']} / {item['label']}: {item['description']} ({edit_hint})")
    print(f"기본 정책 파일 생성: {prefix} policy init C:\\workspace\\policies\\my-policy.json")
    return 0


def init_policy(args: argparse.Namespace, cli_prefix: Callable[[], str]) -> int:
    target = args.path.expanduser().resolve(strict=False)
    profile = PolicyProfile.from_value(args.profile)
    try:
        resolved = resolve_profile(profile)
        source = Path(resolved.source)
        if target.exists() and not args.force:
            print(f"정책 생성 실패: 파일이 이미 존재합니다: {target}")
            print("덮어쓰려면 --force를 사용하세요.")
            return 2
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    except (OSError, ValueError) as error:
        print(f"정책 생성 실패: {error}")
        return 2
    print("정책 파일을 생성했습니다.")
    print(f"프로필: {profile.value} ({profile.display_name})")
    print(f"경로: {target}")
    print(f"다음 단계: {cli_prefix()} policy validate \"{target}\"")
    return 0


def policy_evaluate(args: argparse.Namespace) -> int:
    """Preview one target against an already resolved policy object."""

    try:
        if args.policy is not None:
            resolved = resolve_profile(PolicyProfile.CUSTOM, args.policy)
        else:
            resolved = resolve_profile(PolicyProfile.from_value(args.profile))
        operation = Operation(args.operation)
        if operation is Operation.EXECUTE:
            if args.target_path is not None:
                raise ValueError("EXECUTE preview accepts --command, not --path")
            if not isinstance(args.raw_command, str) or not args.raw_command.strip():
                raise ValueError("EXECUTE preview requires --command")
            evaluation = resolved.evaluate_target(
                operation=operation,
                raw_command=args.raw_command,
            )
            target_kind = "COMMAND"
        else:
            if args.raw_command is not None:
                raise ValueError("file operation preview accepts --path, not --command")
            if not isinstance(args.target_path, str) or not args.target_path.strip():
                raise ValueError("file operation preview requires --path")
            evaluation = resolved.evaluate_target(
                operation=operation,
                path=args.target_path,
            )
            target_kind = "PATH"
    except (OSError, ValueError) as error:
        print(f"정책 미리보기 실패: {error}")
        return 2

    payload = {
        "policy_id": resolved.policy_id,
        "policy_version": resolved.policy_version,
        "profile": resolved.profile.value,
        "operation": operation.value,
        "target_kind": target_kind,
        "policy_decision": evaluation.policy_decision.value,
        "operation_effect": (
            evaluation.operation_effect.value
            if evaluation.operation_effect is not None
            else None
        ),
        "asset_type": (
            evaluation.asset_type.value if evaluation.asset_type is not None else None
        ),
        "matched_rule_ids": list(evaluation.matched_rule_ids),
        "audit_record": evaluation.audit_record,
        "reason": evaluation.reason,
        "limitation": evaluation.limitation,
    }
    if args.json:
        print(_json_text(payload))
    else:
        print("AIA 정책 미리보기")
        print(f"Policy: {resolved.policy_id} v{resolved.policy_version}")
        print(f"Profile: {resolved.profile.value}")
        print(f"Operation: {operation.value}")
        print(f"Decision: {evaluation.policy_decision.value}")
        print(f"Effect: {payload['operation_effect'] or 'DEFAULT'}")
        print(f"Asset Type: {payload['asset_type'] or 'NONE'}")
        print("Matched Rules: " + (", ".join(evaluation.matched_rule_ids) or "NONE"))
        if evaluation.reason:
            print(f"Reason: {evaluation.reason}")
        if evaluation.limitation:
            print(f"Limitation: {evaluation.limitation}")
        print("실제 Agent나 명령은 실행하지 않았습니다.")
    return 0
