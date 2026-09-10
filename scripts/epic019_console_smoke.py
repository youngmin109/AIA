"""Smoke the Local Security Console against an existing valid Core bundle.

This is a read-only UI smoke. It does not start an Agent process or create a
new Protected Run. Pass the control root and session ID from an EPIC-018
artifact, or use the current evaluation defaults when they are available.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient

from aia_app.service import RunApplicationService
from aia_web.app import create_app


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def discover_latest_verified_bundle() -> tuple[Path, str] | None:
    """Find the newest successful Actual Codex bundle for the read-only smoke."""

    candidates = sorted(
        (REPOSITORY_ROOT / "evaluation" / "actual-codex").glob("**/run.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("scenario_realized") is not True or payload.get("proof_passed") is not True:
            continue
        control_root = payload.get("control_root")
        session_id = payload.get("session_id")
        if isinstance(control_root, str) and isinstance(session_id, str) and session_id:
            return Path(control_root), session_id
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--control-root", type=Path)
    parser.add_argument("--session-id")
    args = parser.parse_args()
    if args.control_root is None or args.session_id is None:
        discovered = discover_latest_verified_bundle()
        if discovered is None:
            parser.error(
                "no verified Actual Codex bundle found; pass --control-root and --session-id explicitly"
            )
        discovered_root, discovered_session_id = discovered
        control_root = args.control_root or discovered_root
        session_id = args.session_id or discovered_session_id
    else:
        control_root = args.control_root
        session_id = args.session_id
    control_root = control_root.expanduser().resolve()
    service = RunApplicationService(control_root)
    client = TestClient(create_app(service))
    try:
        responses = {
            "new_run": client.get("/"),
            "result": client.get(f"/runs/{session_id}/result"),
            "result_json": client.get(f"/runs/{session_id}/result.json"),
            "raw_evidence": client.get(f"/runs/{session_id}/raw-evidence"),
        }
        failed = {name: response.status_code for name, response in responses.items() if response.status_code >= 400}
        if failed:
            print(f"CONSOLE_SMOKE=FAILED {failed}")
            return 1
        print("CONSOLE_SMOKE=PASSED")
        print(f"CONTROL_ROOT={control_root}")
        print(f"SESSION_ID={session_id}")
        print(f"RESULT_CONTENT_TYPE={responses['result'].headers.get('content-type')}")
        print(f"RESULT_JSON_CONTENT_TYPE={responses['result_json'].headers.get('content-type')}")
        print(f"RAW_EVIDENCE_COUNT={len(responses['raw_evidence'].json().get('evidence', []))}")
        return 0
    finally:
        service.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
