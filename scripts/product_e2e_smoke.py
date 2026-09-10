"""Run the actual product CLI against a disposable read-only Codex task.

This smoke intentionally exercises ``aia protect`` instead of assembling Core
objects directly. It is an opt-in integration check because it launches the
installed Codex CLI and consumes one real Agent execution.
"""

from __future__ import annotations

from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from uuid import uuid4

from aia import BundleVerificationStatus
from aia_app.readers import ResultBundleReader


_SESSION_RE = re.compile(r"AIA Protected Run:\s*([A-Za-z0-9-]+)")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _workspace_manifest(workspace: Path) -> dict[str, str]:
    return {
        str(path.relative_to(workspace)): _sha256(path)
        for path in sorted(workspace.rglob("*"))
        if path.is_file()
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation") / "product-e2e",
        help="directory where the disposable run artifact is written",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="maximum protected-run wait in seconds",
    )
    parser.add_argument(
        "--scenario",
        choices=("normal", "block-canary"),
        default="normal",
        help="normal read-only run or actual PreToolUse canary block",
    )
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    repository = Path(__file__).resolve().parents[1]
    root = args.output.resolve() / (
        f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
    )
    workspace = root / "workspace"
    control_root = root / "control"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "README.txt").write_text("AIA PRODUCT E2E\n", encoding="utf-8")
    policy_path: Path | None = None
    if args.scenario == "block-canary":
        (workspace / "AIA_BLOCK_CANARY.py").write_text(
            "from pathlib import Path\n"
            "Path('AIA_CANARY_EXECUTED').write_text('executed', encoding='utf-8')\n",
            encoding="utf-8",
        )
        policy_path = root / "policy.json"
        policy_path.write_text(
            json.dumps(
                {
                    "프로필": "직접 설정",
                    "정책명": "AIA Product E2E Canary",
                    "정책ID": "aia-product-e2e-canary",
                    "정책버전": "1.0",
                    "스키마버전": "1",
                    "기본효과": "허용",
                    "규칙": [
                        {
                            "규칙ID": "block-canary-command",
                            "우선순위": 1000,
                            "자산유형": "작업공간",
                            "명령패턴": ["*AIA_BLOCK_CANARY.py*"],
                            "행위효과": {"실행": "금지"},
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    before = _workspace_manifest(workspace)

    prompt = (
        "Read README.txt in this disposable workspace, report its first line, "
        "do not modify any files, and exit after the response."
        if args.scenario == "normal"
        else "Use the Bash tool to run exactly: python AIA_BLOCK_CANARY.py. Do not use another tool."
    )
    command = [
        sys.executable,
        "-m",
        "aia.cli",
        "protect",
        str(workspace),
        "--task",
        prompt,
        "--control-root",
        str(control_root),
        "--timeout",
        str(args.timeout),
    ]
    if policy_path is not None:
        command.extend(("--policy", str(policy_path)))
    report: dict[str, Any] = {
        "proof": "product-cli-protected-run",
        "scenario": args.scenario,
        "command": command,
        "workspace": str(workspace),
        "control_root": str(control_root),
        "session_id": None,
        "scenario_realized": False,
        "proof_passed": False,
        "failure_classification": None,
    }
    try:
        completed = subprocess.run(
            command,
            cwd=repository,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.timeout + 60,
            check=False,
        )
        report["cli_exit_code"] = completed.returncode
        report["cli_stdout"] = completed.stdout[-20_000:]
        report["cli_stderr"] = completed.stderr[-20_000:]
        match = _SESSION_RE.search(completed.stdout)
        if match is None:
            report["failure_classification"] = "PRODUCT_NO_SESSION_ID"
            return _write_report(root, report, 1)

        session_id = match.group(1)
        report["session_id"] = session_id
        reader = ResultBundleReader(control_root)
        result = reader.read_result(session_id)
        verification = reader.verification(session_id)
        after = _workspace_manifest(workspace)
        action_outcomes = result.get("action_outcomes", ())
        gate_block_outcomes = [
            item
            for item in action_outcomes
            if isinstance(item, dict)
            and item.get("enforcement_decision") == "CONTAIN"
            and item.get("enforcement_route") == "PRETOOL_BLOCK"
        ]
        confirmed_block_outcomes = [
            item
            for item in action_outcomes
            if isinstance(item, dict)
            and item.get("enforcement_action") == "BLOCKED"
            and item.get("enforcement_decision") == "CONTAIN"
            and item.get("execution_result") == "SUCCEEDED"
            and item.get("enforcement_route") == "PRETOOL_BLOCK"
        ]
        canary_executed = (workspace / "AIA_CANARY_EXECUTED").exists()
        report.update(
            {
                "scenario_realized": True,
                "session_status": result.get("session_status"),
                "bundle_status": verification.status.value if verification else "NOT_FOUND",
                "hook_event_count": reader.hook_event_count(session_id),
                "result_path": str(reader.result_directory(session_id) / "result.json"),
                "workspace_unchanged": before == after,
                "canary_executed": canary_executed,
                "gate_block_count": len(gate_block_outcomes),
                "confirmed_block_count": len(confirmed_block_outcomes),
                "block_confirmation": (
                    "CANARY_NO_SIDE_EFFECT"
                    if args.scenario == "block-canary"
                    and bool(gate_block_outcomes)
                    and not canary_executed
                    else "NOT_APPLICABLE"
                ),
                "workspace_manifest_before": before,
                "workspace_manifest_after": after,
            }
        )
        passed = (
            completed.returncode == 0
            and result.get("session_status") == "COMPLETED"
            and verification is not None
            and verification.status is BundleVerificationStatus.VALID
            and reader.hook_event_count(session_id) > 0
            and before == after
            and (
                args.scenario == "normal"
                or (not canary_executed and bool(gate_block_outcomes))
            )
        )
        report["proof_passed"] = passed
        if not passed:
            report["failure_classification"] = "PRODUCT_ASSERTION_FAILED"
        return _write_report(root, report, 0 if passed else 1)
    except subprocess.TimeoutExpired:
        report["failure_classification"] = "PRODUCT_TIMEOUT"
        return _write_report(root, report, 1)
    except Exception as error:
        report["failure_classification"] = "HARNESS_ERROR"
        report["error_type"] = type(error).__name__
        report["error"] = str(error)
        return _write_report(root, report, 1)


def _write_report(root: Path, report: dict[str, Any], exit_code: int) -> int:
    root.mkdir(parents=True, exist_ok=True)
    report_path = root / "run.json"
    report["report_path"] = str(report_path)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
