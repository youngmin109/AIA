"""End-to-end check of a protected Workbench run over the Codex app-server.

This is a developer validation tool, not the normal product runtime.  It uses
the real ``RunApplicationService`` path the local console uses: protected
launch, Workspace lease and checkpoint, Hook broker, sensors, the app-server
conversation, and finalization into a Result Bundle.

It needs an installed, user-trusted AIA Codex Hook and a current Hook
verification record in the chosen control root (``aia hook verify``).  It runs
one small real Codex turn in a disposable workspace, then ends the
conversation and waits for the Result Bundle.  Only statuses, counts, and
timings are printed.

When the trusted Hook points at a packaged ``aia-cli.exe`` (the usual case on
a machine that also runs the desktop build), pass ``--installed-aia-cli`` so
this source-tree process resolves the same Hook command instead of asking to
rewrite ``hooks.json`` and re-trust it.  Only this validation process is
affected; the Hook runtime must be unchanged between the two trees, which the
Hook verification record's runtime hash still enforces.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
from typing import Any

from aia_app.service import RunApplicationService


def _wait(predicate, timeout: float, interval: float = 0.2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-root", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--model")
    parser.add_argument("--policy-profile", default="PROTECTED_DEVELOPMENT")
    parser.add_argument("--installed-aia-cli", type=Path)
    args = parser.parse_args(argv)
    if args.installed_aia_cli is not None:
        if not args.installed_aia_cli.is_file():
            parser.error("--installed-aia-cli must point to an existing aia-cli.exe")
        sys.frozen = True  # type: ignore[attr-defined]
        sys.executable = str(args.installed_aia_cli.resolve())

    workspace = Path(tempfile.mkdtemp(prefix="aia-workbench-e2e-"))
    (workspace / "README.md").write_text("disposable AIA Workbench e2e workspace\n", encoding="utf-8")
    service = RunApplicationService(args.control_root)
    result: dict[str, Any] = {"workspace_removed": False}
    checks: dict[str, bool] = {}
    session_id = None
    try:
        started = time.monotonic()
        created = service.create_protected_run(
            {
                "workspace": str(workspace),
                "interactive": True,
                "launch_mode": "codex_app_server",
                "policy_profile": args.policy_profile,
                **({"model": args.model} if args.model else {}),
            }
        )
        session_id = created["session_id"]
        result["redirect_url_is_workbench"] = created["redirect_url"].endswith("/workbench")
        ready = _wait(
            lambda: service.get_codex_status(session_id)["status"] in {"READY", "FAILED", "EXITED"}
            and service.get_codex_status(session_id),
            args.timeout,
        )
        result["ready_seconds"] = round(time.monotonic() - started, 3)
        result["codex_status_at_ready"] = (ready or {}).get("status")
        result["codex_error"] = (ready or {}).get("error")
        result["effective"] = (ready or {}).get("effective")
        checks["conversation_ready"] = (ready or {}).get("status") == "READY"
        if not checks["conversation_ready"]:
            raise RuntimeError("conversation did not become ready")

        cursor = service.get_codex_status(session_id)["last_sequence"]
        turn_started = time.monotonic()
        service.send_codex_message(
            session_id,
            "Run the shell command `echo aia-e2e` in the current folder, then reply with its output only.",
        )
        events: list[dict[str, Any]] = []
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            batch = service.wait_codex_events(session_id, after_sequence=cursor, timeout=1.0)
            if batch:
                cursor = batch[-1]["sequence"]
                events.extend(batch)
            if any(e["type"] in {"turn.completed", "session.exited"} for e in events):
                break
        result["turn_seconds"] = round(time.monotonic() - turn_started, 3)
        result["turn_event_counts"] = dict(Counter(e["type"] for e in events))
        completed = next((e for e in events if e["type"] == "turn.completed"), {})
        checks["turn_completed"] = completed.get("status") == "completed"
        checks["command_ran"] = any(e["type"] == "command.completed" and e.get("status") == "completed" for e in events)
        checks["hook_runs_visible"] = {"preToolUse", "postToolUse"} <= {
            e.get("event_name") for e in events if e["type"] == "hook"
        }

        live = service.get_run_status(session_id)
        summary = live.get("evidence_summary") or {}
        result["live_evidence_summary"] = {
            key: summary.get(key)
            for key in ("pretool_events", "posttool_events", "process_observed", "filesystem_events")
        }
        checks["aia_received_pretool"] = (summary.get("pretool_events") or 0) >= 1

        end_started = time.monotonic()
        service.end_codex_session(session_id)
        final = _wait(
            lambda: (status := service.get_run_status(session_id)).get("bundle_status") in {"VALID", "INVALID"}
            and status,
            args.timeout,
            interval=0.5,
        )
        result["finalize_seconds"] = round(time.monotonic() - end_started, 3)
        final = final or service.get_run_status(session_id)
        result["final"] = {
            "session_status": (final.get("session") or {}).get("status"),
            "bundle_status": final.get("bundle_status"),
            "protection_state": (final.get("protection") or {}).get("state"),
            "end_reason": (final.get("session") or {}).get("end_reason"),
            "limitations": final.get("limitations"),
        }
        checks["bundle_valid"] = final.get("bundle_status") == "VALID"
        checks["agent_exited_normally"] = (final.get("session") or {}).get("end_reason") in {None, "AGENT_EXITED"}
    except Exception as error:  # noqa: BLE001 - report every failure shape
        result["error"] = f"{type(error).__name__}: {error}"
        if session_id is not None:
            try:
                service.request_stop(session_id)
            except Exception:  # noqa: BLE001
                pass
    finally:
        service.shutdown()
        shutil.rmtree(workspace, ignore_errors=True)
        result["workspace_removed"] = not workspace.exists()
    result["session_id"] = session_id
    result["checks"] = checks
    result["passed"] = bool(checks) and all(checks.values()) and "error" not in result
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
