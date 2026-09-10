"""Small end-user CLI for starting a protected Codex run."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from typing import Sequence

from aia import CodexHookInstallationError, CodexHookInstaller
from aia_app import ApplicationValidationError, RunApplicationService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aia")
    commands = parser.add_subparsers(dest="command", required=True)
    hook = commands.add_parser("hook", help="manage the stable Codex Hook Adapter")
    hook_commands = hook.add_subparsers(dest="hook_command", required=True)
    install = hook_commands.add_parser("install", help="install the AIA Hook definition")
    install.add_argument("--path", type=Path, help="hooks.json path")

    protect = commands.add_parser(
        "protect",
        help="run Codex inside an AIA Protected Run",
    )
    protect.add_argument("workspace", type=Path)
    protect.add_argument("--task", required=True, help="Codex task prompt")
    protect.add_argument("--policy", type=Path, help="custom policy JSON path")
    protect.add_argument(
        "--profile",
        default="BASIC_DEVELOPMENT",
        help="policy profile name",
    )
    protect.add_argument("--model")
    protect.add_argument("--mode", default="ENFORCE", choices=("ENFORCE", "AUDIT"))
    protect.add_argument(
        "--control-root",
        type=Path,
        help="AIA control root outside the protected Workspace",
    )
    protect.add_argument(
        "--timeout",
        type=float,
        default=3600.0,
        help="maximum wait in seconds",
    )
    return parser


def _control_root(value: Path | None) -> Path:
    if value is not None:
        return value.expanduser().resolve(strict=False)
    configured = os.environ.get("AIA_CONTROL_ROOT")
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    return (Path.home() / ".aia" / "control").resolve(strict=False)


def _run_protected(args: argparse.Namespace) -> int:
    if args.timeout <= 0:
        raise ApplicationValidationError("timeout must be positive")
    service = RunApplicationService(_control_root(args.control_root))
    try:
        created = service.create_protected_run(
            {
                "workspace": str(args.workspace),
                "agent": "codex",
                "model": args.model,
                "policy_profile": "CUSTOM" if args.policy else args.profile,
                "custom_policy_path": str(args.policy) if args.policy else None,
                "mode": args.mode,
                "task": args.task,
            }
        )
        session_id = created["session_id"]
        print(f"AIA Protected Run: {session_id}")
        print(f"Control Root: {_control_root(args.control_root)}")
        deadline = time.monotonic() + args.timeout
        last_phase: str | None = None
        while True:
            status = service.get_run_status(session_id)
            phase = str(status.get("phase"))
            if phase != last_phase:
                print(f"Phase: {phase}")
                last_phase = phase
            if status.get("result_available") or status.get("status") in {
                "COMPLETED",
                "FAILED",
                "ABORTED",
            }:
                break
            if time.monotonic() >= deadline:
                print("Result: TIMEOUT")
                return 2
            time.sleep(0.5)
        status = service.get_run_status(session_id)
        print(f"Status: {status.get('status')}")
        if status.get("error"):
            print(f"Error: {status['error']}")
        if status.get("result_available"):
            result = service.get_result(session_id)
            print(
                json.dumps(
                    {
                        "bundle_status": result.get("bundle_status"),
                        "incident_count": len(result.get("incidents", [])),
                        "result_path": result.get("result_path"),
                        "session_status": result.get("session_status"),
                    },
                    ensure_ascii=False,
                )
            )
        return 0 if status.get("status") == "COMPLETED" else 1
    finally:
        service.shutdown()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "hook" and args.hook_command == "install":
            path = CodexHookInstaller(args.path).install()
            print(f"Codex Hook installed: {path}")
            print("Review and trust this Hook in Codex before starting a protected run.")
            return 0
        if args.command == "protect":
            return _run_protected(args)
        raise ApplicationValidationError("unknown command")
    except (ApplicationValidationError, CodexHookInstallationError, OSError, ValueError) as error:
        print(f"AIA error: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
