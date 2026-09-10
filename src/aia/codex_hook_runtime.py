"""Command entry point for the actual Codex ``PreToolUse`` Hook."""

from __future__ import annotations

import json
import sys
from typing import Any

from .codex_runtime import send_hook_payload


def main() -> int:
    try:
        raw = sys.stdin.buffer.read()
        payload: Any = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Codex Hook stdin must be a JSON object")
        result = send_hook_payload(payload)
        if result:
            sys.stdout.write(json.dumps(dict(result), ensure_ascii=False))
            sys.stdout.write("\n")
        return 0
    except Exception as error:
        # Exit code 2 is Codex's documented blocking path for a PreToolUse
        # command hook.  It is used only when this Hook was actually attached
        # to an AIA Protected Run; an unbound Hook returns neutral output.
        import os

        if os.environ.get("AIA_CODEX_HOOK_ENDPOINT"):
            sys.stderr.write(f"AIA protection unavailable: {error}\n")
            return 2
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

