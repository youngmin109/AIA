"""Measure which Codex lifecycle Hook events arrive in a real Codex run.

This is a developer validation tool, not the normal product runtime.  It uses
an inline diagnostic command Hook and Codex's explicit hook-trust bypass so a
developer can distinguish a missing PostToolUse event from an AIA evaluation
bug without changing the user's persistent Codex configuration.

Only event names, tool names, byte counts, and SHA-256 output digests are
retained.  Codex stdout/stderr and the diagnostic workspace are removed after
the report is written.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any
from uuid import uuid4

from aia import CodexAdapter, ProtectedLaunchRequest


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_hook(path: Path, log_path: Path) -> None:
    encoded_log = json.dumps(str(log_path))
    path.write_text(
        "from __future__ import annotations\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "payload = json.loads(sys.stdin.buffer.read().decode('utf-8'))\n"
        "event = {'hook_event_name': payload.get('hook_event_name'), "
        "'tool_name': payload.get('tool_name')}\n"
        f"with Path({encoded_log}).open('a', encoding='utf-8') as stream:\n"
        "    stream.write(json.dumps(event, sort_keys=True) + '\\n')\n"
        "sys.stdout.write('{}\\n')\n",
        encoding="utf-8",
    )


def _output_metadata(data: bytes) -> dict[str, Any]:
    return {"bytes": len(data), "sha256": _sha256(data)}


def _codex_version(executable: Path) -> str:
    try:
        completed = subprocess.run(
            [str(executable), "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    first_line = completed.stdout.decode("utf-8", errors="replace").splitlines()
    return first_line[0][:200] if first_line else "unknown"


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation") / "actual-codex" / "hook-lifecycle",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--model")
    args = parser.parse_args(argv)
    if os.name != "nt":
        print("SKIP: this runner is intended for Windows Actual Codex integration")
        return 2
    if args.timeout <= 0:
        parser.error("timeout must be positive")

    run_root = args.output.resolve() / (
        f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
    )
    run_root.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="aia-codex-hook-lifecycle-"))
    log_path = run_root / "hook-events.jsonl"
    hook_path = run_root / "diagnostic-hook.py"
    stdout_path = run_root / "codex.stdout.txt"
    stderr_path = run_root / "codex.stderr.txt"
    report_path = run_root / "run.json"
    result: dict[str, Any] = {
        "schema_version": "aia-actual-codex-hook-lifecycle-v1",
        "proof": "actual-codex-hook-lifecycle",
        "created_at": _now(),
        "scenario_realized": False,
        "proof_passed": False,
        "failure_classification": None,
        "report_path": str(report_path),
    }
    process: subprocess.Popen[bytes] | None = None
    try:
        (workspace / "README.md").write_text("AIA Hook lifecycle smoke\n", encoding="utf-8")
        _write_hook(hook_path, log_path)
        hook_command = subprocess.list2cmdline([sys.executable, str(hook_path)])
        adapter = CodexAdapter(
            hook_command=hook_command,
            allow_hook_trust_bypass=True,
        )
        executable = adapter.discover()
        request = ProtectedLaunchRequest(
            aia_session_id="actual-codex-hook-lifecycle",
            workspace=workspace,
            agent="codex",
            model=args.model,
            prompt=(
                "Use the Bash tool to run exactly: "
                "python -c \"print('AIA_HOOK_LIFECYCLE_SMOKE')\". "
                "Do not use another tool."
            ),
            adapter_options={
                "approve_for_me": True,
                "skip_git_repo_check": True,
            },
        )
        spec = adapter.build_launch(request, executable)
        environment = os.environ.copy()
        for key in (
            "AIA_CODEX_HOOK_ENDPOINT",
            "AIA_CODEX_HOOK_CAPABILITY",
            "AIA_SESSION_ID",
            "AIA_LAUNCH_ID",
            "AIA_CONTROL_ROOT",
        ):
            environment.pop(key, None)
        process = subprocess.Popen(
            list(spec.argv),
            cwd=str(workspace),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        stdout, stderr = process.communicate(spec.stdin_bytes, timeout=args.timeout)
        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
        events: list[dict[str, str | None]] = []
        if log_path.exists():
            for line in log_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                value = json.loads(line)
                if isinstance(value, dict):
                    events.append(
                        {
                            "hook_event_name": (
                                str(value.get("hook_event_name"))
                                if value.get("hook_event_name") is not None
                                else None
                            ),
                            "tool_name": (
                                str(value.get("tool_name"))
                                if value.get("tool_name") is not None
                                else None
                            ),
                        }
                    )
        event_names = [item["hook_event_name"] for item in events]
        result.update(
            {
                "codex_version": _codex_version(executable),
                "exit_code": process.returncode,
                "hook_event_count": len(events),
                "hook_events": events,
                "pretool_event_count": event_names.count("PreToolUse"),
                "posttool_event_count": event_names.count("PostToolUse"),
                "codex_stdout": _output_metadata(stdout),
                "codex_stderr": _output_metadata(stderr),
                "scenario_realized": len(events) > 0,
                "proof_passed": event_names.count("PreToolUse") > 0
                and event_names.count("PostToolUse") > 0,
            }
        )
        if result["proof_passed"]:
            result["failure_classification"] = None
        elif result["scenario_realized"]:
            result["failure_classification"] = "EXTERNAL_INTERFACE_LIMITATION"
        else:
            result["failure_classification"] = "EXTERNAL_INTERFACE_LIMITATION"
        _write_report(report_path, result)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["proof_passed"] else 1
    except subprocess.TimeoutExpired as error:
        if process is not None:
            process.kill()
            stdout, stderr = process.communicate()
            stdout_path.write_bytes(stdout)
            stderr_path.write_bytes(stderr)
        result.update(
            {
                "failure_classification": "EXTERNAL_INTERFACE_LIMITATION",
                "error_type": type(error).__name__,
            }
        )
        _write_report(report_path, result)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    except Exception as error:
        result.update(
            {
                "failure_classification": "HARNESS_ERROR",
                "error_type": type(error).__name__,
                "error": str(error),
            }
        )
        _write_report(report_path, result)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    finally:
        for path in (stdout_path, stderr_path, log_path, hook_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
