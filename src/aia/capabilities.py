"""User-facing, bounded AIA product capability contract."""

from __future__ import annotations

from typing import Any

from ._version import __version__
from .codex_installation import AIA_CODEX_HOOK_MATCHER, AIA_CODEX_SUPPORTED_MATCHERS


def product_capabilities() -> dict[str, Any]:
    """Return the current product contract without inspecting or running a Workspace."""

    return {
        "schema_version": "aia-capabilities-v1",
        "product": "AIA",
        "version": __version__,
        "support": {
            "operating_system": ["Windows 11"],
            "python": ["3.13"],
            "agent": ["Codex CLI"],
            "launch_boundary": "AIA Protected Run으로 직접 시작한 Codex 자식 프로세스",
            "modes": ["ENFORCE", "AUDIT"],
            "pretool_matcher": AIA_CODEX_HOOK_MATCHER,
            "pretool_matchers": list(AIA_CODEX_SUPPORTED_MATCHERS),
            "unsupported_tool_behavior": (
                "Hook으로 수신되지만 의미를 해석하지 못하는 도구는 "
                "UNSUPPORTED_TOOL_PATH로 거부하고 실행 성공으로 주장하지 않음"
            ),
            "mcp_policy": "명시적으로 등록된 MCP 도구만 의미를 해석하며, 알 수 없는 MCP 이름은 보호 성공으로 주장하지 않음",
        },
        "verified_behaviors": [
            "정책 위반 PreToolUse 요청의 Codex deny 응답",
            "Bash·apply_patch·등록된 파일 읽기 MCP의 실제 사전 차단 증명",
            "Workspace Lease·Safe Checkpoint·Evidence Bundle 무결성 검증",
            "사용자 중지 시 AIA가 등록한 Agent 프로세스 트리 종료 확인",
        ],
        "requires_user_action": [
            "Codex /hooks에서 AIA Hook을 검토하고 신뢰함",
            "aia hook verify로 현재 Codex와 Session-bound Hook을 검증함",
        ],
        "unsupported_or_unclaimed": [
            "모든 Codex 도구와 모든 MCP 경로의 보편적 차단",
            "Hook을 우회한 외부 Agent·수동 실행·OS 전체 Writer 통제",
            "PROCESS Evidence만으로 정확한 파일 Writer를 증명하는 것",
            "Network·Database·ACL/ADS 보안",
            "대규모 Workspace 성능 SLA",
        ],
        "claim_rule": "Hook Event와 센서 상태가 확인된 실행만 검증된 Protected Run으로 표시",
    }


__all__ = ["product_capabilities"]
