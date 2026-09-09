"""Smoke the Local Security Console against an existing valid Core bundle.

This is a read-only UI smoke. It does not start an Agent process or create a
new Protected Run. Pass the control root and session ID from an EPIC-018
artifact, or use the current evaluation defaults when they are available.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from fastapi.testclient import TestClient

from aia_app.service import RunApplicationService
from aia_web.app import create_app


DEFAULT_CONTROL_ROOT = Path("evaluation/mvp-1.0/eval-20260909T144119Z/actual-codex/protected-normal/control")
DEFAULT_SESSION_ID = "b4ccbcac-6887-4e57-9f2c-c3008b5cbf7c"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--control-root", type=Path, default=DEFAULT_CONTROL_ROOT)
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    args = parser.parse_args()
    control_root = args.control_root.resolve()
    service = RunApplicationService(control_root)
    client = TestClient(create_app(service))
    try:
        responses = {
            "new_run": client.get("/"),
            "result": client.get(f"/runs/{args.session_id}/result"),
            "result_json": client.get(f"/runs/{args.session_id}/result.json"),
            "raw_evidence": client.get(f"/runs/{args.session_id}/raw-evidence"),
        }
        failed = {name: response.status_code for name, response in responses.items() if response.status_code >= 400}
        if failed:
            print(f"CONSOLE_SMOKE=FAILED {failed}")
            return 1
        print("CONSOLE_SMOKE=PASSED")
        print(f"CONTROL_ROOT={control_root}")
        print(f"SESSION_ID={args.session_id}")
        print(f"RESULT_CONTENT_TYPE={responses['result'].headers.get('content-type')}")
        print(f"RESULT_JSON_CONTENT_TYPE={responses['result_json'].headers.get('content-type')}")
        print(f"RAW_EVIDENCE_COUNT={len(responses['raw_evidence'].json().get('evidence', []))}")
        return 0
    finally:
        service.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
