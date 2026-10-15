"""Small end-user CLI for starting a protected Codex run."""

from __future__ import annotations

import sys

# Codex starts `aia-cli.exe hook runtime` before and after every tool call, and
# that process only forwards the payload to the per-run AIA broker.  Leave
# before the AIA imports below, which cost about 0.4 s per call.  Any other
# invocation, including `main(["hook", "runtime"])`, keeps the full CLI path.
if __name__ == "__main__" and sys.argv[1:] == ["hook", "runtime"]:
    from aia_hook_client import main as hook_client_main

    raise SystemExit(hook_client_main())

import argparse
import json
import os
from pathlib import Path
import subprocess
import threading
from typing import Sequence
import webbrowser

from aia import (
    BundleVerificationStatus,
    CodexAdapter,
    CodexHookInstallationError,
    CodexHookInstaller,
    Operation,
    verify_evidence_bundle,
)
from aia import cli_policy
from aia.hook_verification import HookVerificationStore
from aia.codex_hook_trust import inspect_codex_hook_trust
from aia.capabilities import product_capabilities
from aia.diagnostics import build_support_bundle, write_support_bundle
from aia._version import __version__
from aia_app import ApplicationValidationError, RunApplicationService  # noqa: F401 - reached through this module
from aia_app.readers import ResultBundleReader  # noqa: F401 - reached through this module


_HOOK_VERIFICATION_PROBE_TOKEN_ENV = "AIA_HOOK_VERIFICATION_PROBE_TOKEN"


def _module_cli_prefix() -> str:
    """Return a launcher that does not depend on a generated ``aia.exe``."""

    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve(strict=False)
        if executable.name.casefold() in {"aia-cli.exe", "aia-cli"}:
            return subprocess.list2cmdline([str(executable)])
        candidates = (
            executable.parent / "aia-cli" / "aia-cli.exe",
            executable.parent.parent / "aia-cli" / "aia-cli.exe",
            executable.parent / "aia-cli.exe",
        )
        for candidate in candidates:
            if candidate.is_file():
                return subprocess.list2cmdline([str(candidate)])
        if executable.name.casefold() in {"aia.exe", "aia"}:
            return subprocess.list2cmdline([str(executable)])

    source = Path(__file__).resolve()
    project_root = next(
        (
            candidate
            for candidate in (source.parent, *source.parents)
            if (candidate / "pyproject.toml").is_file()
        ),
        None,
    )
    if project_root is not None:
        return subprocess.list2cmdline(
            [
                "uv",
                "run",
                "--isolated",
                "--project",
                str(project_root),
                "python",
                "-m",
                "aia.cli",
            ]
        )
    return subprocess.list2cmdline([sys.executable, "-m", "aia.cli"])


def _configure_console_encoding() -> None:
    """Keep CLI diagnostics usable on Windows consoles with a legacy code page."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # Embedded callers and redirected streams may reject reconfiguration.
            # Their existing stream configuration remains usable in that case.
            continue


def _cli_prefix(installer: CodexHookInstaller) -> str:
    """Return a user-facing launcher that avoids a blocked console-script EXE."""

    # Keep the argument for callers that already pass the installer.  The
    # generated Windows console-script executable can be blocked by local
    # application-control policy even when the Python interpreter is allowed.
    # Always show the direct module path so setup/doctor guidance remains
    # executable in that environment as well.
    del installer
    return _module_cli_prefix()


def _json_text(value: object, *, default: object | None = None) -> str:
    options: dict[str, object] = {"ensure_ascii": True, "indent": 2}
    if default is not None:
        options["default"] = default
    return json.dumps(value, **options)


def _hidden_process_kwargs() -> dict[str, int]:
    """Prevent non-interactive diagnostic runs from opening Windows consoles."""

    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _self_cli_command(*arguments: str) -> list[str]:
    """Build a command that re-enters the current CLI in source or frozen mode."""

    if getattr(sys, "frozen", False):
        return [sys.executable, *arguments]
    return [sys.executable, "-m", "aia.cli", *arguments]


def _add_protected_run_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the shared interactive/one-shot Protected Run arguments."""

    parser.add_argument(
        "workspace",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Workspace directory; defaults to the current directory",
    )
    parser.add_argument(
        "--task",
        help="initial Codex task prompt; omit it to open an interactive protected session",
    )
    parser.add_argument("--policy", type=Path, help="custom policy JSON path")
    parser.add_argument(
        "--profile",
        default="PROTECTED_DEVELOPMENT",
        help="policy profile name",
    )
    parser.add_argument("--model")
    parser.add_argument("--mode", default="ENFORCE", choices=("ENFORCE", "AUDIT"))
    parser.add_argument(
        "--control-root",
        type=Path,
        help="AIA control root outside the protected Workspace",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3600.0,
        help="maximum wait in seconds",
    )
    parser.add_argument(
        "--_hook-verification-probe",
        action="store_true",
        help=argparse.SUPPRESS,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aia")
    parser.add_argument("--version", action="version", version=f"AIA {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    _add_overview_commands(commands)
    _add_run_history_commands(commands)
    _add_policy_commands(commands)
    _add_hook_commands(commands)
    _add_utility_commands(commands)
    _add_protected_run_commands(commands)
    return parser


def _add_overview_commands(commands: argparse._SubParsersAction) -> None:
    capabilities = commands.add_parser(
        "capabilities",
        help="show the bounded AIA support and claim contract",
    )
    capabilities.add_argument("--json", action="store_true", help="print machine-readable output")
    doctor = commands.add_parser(
        "doctor",
        help="check the local Codex/AIA protected-run setup",
    )
    doctor.add_argument("--json", action="store_true", help="print machine-readable output")
    doctor.add_argument("--hook-path", type=Path, help="hooks.json path")
    doctor.add_argument("--control-root", type=Path, help="AIA control root")
    self_test = commands.add_parser(
        "self-test",
        help="run a disposable AIA Core self-test without starting Codex",
    )
    self_test.add_argument("--json", action="store_true", help="print machine-readable output")
    demo = commands.add_parser(
        "demo",
        help="show the safe AIA product demo using a disposable Workspace",
    )
    demo.add_argument(
        "--live",
        action="store_true",
        help="after the Core demo, run the opt-in real Codex proof",
    )
    demo.add_argument(
        "--scenario",
        choices=(
            "normal",
            "block-canary",
            "block-apply-patch",
            "block-env",
            "block-windows-delete",
            "process-kill",
            "hook-block",
            "file-rollback",
        ),
        default="block-canary",
        help="live proof scenario or deterministic presentation scenario",
    )
    demo.add_argument(
        "--workspace",
        type=Path,
        help="dedicated Workspace for a deterministic presentation scenario",
    )
    demo.add_argument(
        "--control-root",
        type=Path,
        help="dedicated Control Root for a deterministic presentation scenario",
    )
    demo.add_argument(
        "--open",
        action="store_true",
        help="open the local Workbench console after a deterministic demo",
    )
    demo.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation") / "product-e2e",
        help="directory for live proof artifacts",
    )
    demo.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="maximum wait for the live proof in seconds",
    )


def _add_run_history_commands(commands: argparse._SubParsersAction) -> None:
    runs = commands.add_parser(
        "runs",
        help="list protected-run history from the local Control Root",
    )
    runs.add_argument("--json", action="store_true", help="print machine-readable output")
    runs.add_argument("--limit", type=int, default=20, help="maximum number of runs to show")
    runs.add_argument("--control-root", type=Path, help="AIA control root")
    status = commands.add_parser(
        "status",
        help="inspect one protected run, including completed runs",
    )
    status.add_argument("session_id")
    status.add_argument("--json", action="store_true", help="print machine-readable output")
    status.add_argument("--control-root", type=Path, help="AIA control root")
    stop = commands.add_parser(
        "stop",
        help="request a safe user abort for one running Protected Run",
    )
    stop.add_argument("session_id")
    stop.add_argument("--json", action="store_true", help="print machine-readable output")
    stop.add_argument("--control-root", type=Path, help="AIA control root")
    reconcile = commands.add_parser(
        "reconcile",
        help="acknowledge a crashed Protected Run after its Agent root is gone",
    )
    reconcile.add_argument("session_id")
    reconcile.add_argument("--json", action="store_true", help="print machine-readable output")
    reconcile.add_argument("--control-root", type=Path, help="AIA control root")


def _add_policy_commands(commands: argparse._SubParsersAction) -> None:
    policy = commands.add_parser("policy", help="validate and inspect a policy")
    policy_commands = policy.add_subparsers(dest="policy_command", required=True)
    profiles = policy_commands.add_parser(
        "profiles",
        help="list the built-in Korean policy profiles",
    )
    profiles.add_argument("--json", action="store_true", help="print machine-readable output")
    init_policy = policy_commands.add_parser(
        "init",
        help="create a copy of a built-in policy profile for editing",
    )
    init_policy.add_argument("path", type=Path)
    init_policy.add_argument(
        "--profile",
        default="PROTECTED_DEVELOPMENT",
        choices=(
            "PROTECTED_DEVELOPMENT",
            "BASIC_DEVELOPMENT",
            "CONSERVATIVE_SECURITY",
            "FREE_DEVELOPMENT",
        ),
        help="built-in profile to copy",
    )
    init_policy.add_argument("--force", action="store_true", help="replace an existing file")
    validate = policy_commands.add_parser(
        "validate",
        help="strictly validate a Korean or canonical policy JSON",
    )
    validate.add_argument("path", type=Path)
    validate.add_argument("--json", action="store_true", help="print machine-readable output")
    policy_evaluate = policy_commands.add_parser(
        "evaluate",
        help="preview a policy decision without starting an Agent",
    )
    policy_evaluate.add_argument(
        "--policy",
        type=Path,
        help="custom Korean or canonical policy JSON path",
    )
    policy_evaluate.add_argument(
        "--profile",
        default="PROTECTED_DEVELOPMENT",
        choices=(
            "PROTECTED_DEVELOPMENT",
            "BASIC_DEVELOPMENT",
            "CONSERVATIVE_SECURITY",
            "FREE_DEVELOPMENT",
        ),
        help="built-in profile used when --policy is omitted",
    )
    policy_evaluate.add_argument(
        "--operation",
        required=True,
        choices=tuple(operation.value for operation in Operation),
        help="mechanical operation to preview",
    )
    policy_evaluate.add_argument(
        "--path",
        dest="target_path",
        help="canonical path target for file operations",
    )
    policy_evaluate.add_argument(
        "--command",
        dest="raw_command",
        help="raw command target for EXECUTE; the command is not run",
    )
    policy_evaluate.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable output",
    )


def _add_hook_commands(commands: argparse._SubParsersAction) -> None:
    hook = commands.add_parser("hook", help="manage the stable Codex Hook Adapter")
    hook_commands = hook.add_subparsers(dest="hook_command", required=True)
    install = hook_commands.add_parser("install", help="install the AIA Hook definition")
    install.add_argument("--path", type=Path, help="hooks.json path")
    uninstall = hook_commands.add_parser(
        "uninstall",
        help="remove only the AIA Hook definition",
    )
    uninstall.add_argument("--path", type=Path, help="hooks.json path")
    hook_status = hook_commands.add_parser(
        "status",
        help="show Hook installation and last observed protected-run activation",
    )
    hook_status.add_argument("--json", action="store_true", help="print machine-readable output")
    hook_status.add_argument("--path", type=Path, help="hooks.json path")
    hook_status.add_argument("--control-root", type=Path, help="AIA control root")
    hook_explain = hook_commands.add_parser(
        "explain",
        help="explain the installed Hook review, trust, and verification steps",
    )
    hook_explain.add_argument("--json", action="store_true", help="print machine-readable output")
    hook_explain.add_argument("--path", type=Path, help="hooks.json path")
    hook_explain.add_argument("--control-root", type=Path, help="AIA control root")
    hook_verify = hook_commands.add_parser(
        "verify",
        help="verify the installed Hook with one disposable live Codex run",
    )
    hook_verify.add_argument("--json", action="store_true", help="print machine-readable output")
    hook_verify.add_argument("--path", type=Path, help="hooks.json path")
    hook_verify.add_argument("--control-root", type=Path, help="AIA control root")
    hook_verify.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="maximum wait in seconds",
    )
    hook_commands.add_parser(
        "runtime",
        help=argparse.SUPPRESS,
    )


def _add_utility_commands(commands: argparse._SubParsersAction) -> None:
    setup = commands.add_parser(
        "setup",
        help="install the AIA Hook and print the remaining trust steps",
    )
    setup.add_argument("--path", type=Path, help="hooks.json path")
    setup.add_argument("--json", action="store_true", help="print machine-readable output")

    support_bundle = commands.add_parser(
        "support-bundle",
        help="create redacted diagnostics for troubleshooting",
    )
    support_bundle.add_argument(
        "--output",
        type=Path,
        help="write the redacted diagnostics JSON to this path",
    )
    support_bundle.add_argument("--hook-path", type=Path, help="hooks.json path")
    support_bundle.add_argument("--control-root", type=Path, help="AIA control root")
    support_bundle.add_argument("--json", action="store_true", help="print machine-readable output")

    verify_bundle = commands.add_parser(
        "verify-bundle",
        help="verify a committed Result Bundle without modifying it",
    )
    verify_bundle.add_argument(
        "result_directory",
        type=Path,
        help="Result Bundle or session directory",
    )
    verify_bundle.add_argument("--json", action="store_true", help="print machine-readable output")

    console = commands.add_parser(
        "console",
        help="start the local AIA Security Console",
    )
    console.add_argument(
        "--host",
        default=os.environ.get("AIA_WEB_HOST", "127.0.0.1"),
        help="bind address; localhost is the safe default",
    )
    console.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("AIA_WEB_PORT", "8787")),
        help="local HTTP port",
    )
    console.add_argument(
        "--open",
        action="store_true",
        help="open the local console in the default browser",
    )
    console.add_argument(
        "--control-root",
        type=Path,
        help="AIA control root to display in the local console",
    )
    console.add_argument(
        "--open-path",
        default="/",
        help="local console path to open when --open is used",
    )


def _add_protected_run_commands(commands: argparse._SubParsersAction) -> None:
    protect = commands.add_parser(
        "protect",
        help="run Codex inside an AIA Protected Run",
    )
    _add_protected_run_arguments(protect)
    start = commands.add_parser(
        "start",
        help="start an interactive AIA Protected Run; enter tasks after Codex opens",
    )
    _add_protected_run_arguments(start)
    proof = commands.add_parser(
        "proof",
        help="run an opt-in real Codex pretool proof in a disposable Workspace",
    )
    proof.add_argument(
        "--scenario",
        choices=(
            "normal",
            "block-canary",
            "block-apply-patch",
            "block-env",
            "block-windows-delete",
        ),
        default="block-canary",
        help="proof scenario; block-canary is the default safety demonstration",
    )
    proof.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation") / "product-e2e",
        help="directory where the disposable proof artifact is written",
    )
    proof.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="maximum wait in seconds",
    )
    proof.add_argument(
        "--json",
        action="store_true",
        help="print the complete machine-readable proof report",
    )


def _control_root(value: Path | None) -> Path:
    if value is not None:
        return value.expanduser().resolve(strict=False)
    configured = os.environ.get("AIA_CONTROL_ROOT")
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    return (Path.home() / ".aia" / "control").resolve(strict=False)


def _control_root_write_check(control_root: Path) -> tuple[bool, str]:
    """Check that AIA can create and remove a small control-root marker."""

    try:
        control_root.mkdir(parents=True, exist_ok=True)
        probe = control_root / ".aia-write-check"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as error:
        return False, f"Control Root is not writable: {type(error).__name__}"
    return True, "Control Root is writable"


from aia.cli_diagnostics import (
    _demo,
    _self_test,
    _doctor,
    _recent_run_diagnostic,  # noqa: F401 - reached through this module
)


def _capabilities(args: argparse.Namespace) -> int:
    """Print the support contract without touching a protected Workspace."""

    payload = product_capabilities()
    if args.json:
        print(_json_text(payload))
        return 0

    support = payload["support"]
    print("AIA 지원 범위")
    print(f"제품: {payload['product']} {payload['version']}")
    print(
        "환경: "
        f"{', '.join(support['operating_system'])} / "
        f"Python {', '.join(support['python'])} / "
        f"{', '.join(support['agent'])}"
    )
    print(f"실행 경계: {support['launch_boundary']}")
    print(f"보호 모드: {', '.join(support['modes'])}")
    print(f"Hook matcher: {support['pretool_matcher']}")
    print("지원 PreToolUse: " + ", ".join(support["pretool_matchers"]))
    aliases = support.get("pretool_aliases") or {}
    if aliases:
        print(
            "Codex matcher 별칭: "
            + ", ".join(
                f"{alias} → {canonical}"
                for canonical, values in aliases.items()
                for alias in values
            )
        )
    print(f"미지원 도구 처리: {support['unsupported_tool_behavior']}")
    print("실제 확인된 동작:")
    for item in payload["verified_behaviors"]:
        print(f"  - {item}")
    print("사용 전 필수 단계:")
    for item in payload["requires_user_action"]:
        print(f"  - {item}")
    print("지원하지 않거나 주장하지 않는 범위:")
    for item in payload["unsupported_or_unclaimed"]:
        print(f"  - {item}")
    print(f"보호 성공 판정: {payload['claim_rule']}")
    return 0


def _support_bundle(args: argparse.Namespace) -> int:
    """Create or print diagnostics without exposing protected content."""

    bundle = build_support_bundle(
        control_root=_control_root(args.control_root),
        hook_path=args.hook_path,
    )
    written: Path | None = None
    if args.output is not None:
        written = write_support_bundle(args.output, bundle)

    if args.json:
        output: dict[str, object] = dict(bundle)
        if written is not None:
            output["output_path"] = str(written)
        print(_json_text(output))
        return 0

    print("AIA 지원 진단 번들")
    print(f"Version: {bundle['product']['version']}")
    runtime = bundle["runtime"]
    print(
        "환경: "
        f"Python {runtime['python']} / {runtime['platform']} {runtime['platform_release']}"
    )
    codex = bundle["codex"]
    print(
        "Codex: "
        f"{'확인됨' if codex['available'] else '없음'}"
        f" / {codex['version']}"
    )
    hook = bundle["hook"]
    trust_events = hook["trust"].get("events", [])
    trust_summary = ", ".join(
        f"{item.get('event')}={item.get('trust_status')}"
        for item in trust_events
        if isinstance(item, dict)
    ) or "확인할 수 없음"
    print(
        "Hook: "
        f"PreToolUse={'설치됨' if hook['pretool_installed'] else '없음'} / "
        f"PostToolUse={'설치됨' if hook['posttool_installed'] else '없음'} / "
        f"Trust={trust_summary}"
    )
    print(f"실시간 검증: {'CURRENT' if hook['verification_current'] else '필요'}")
    control = bundle["control_root"]
    print(f"Control Root 쓰기: {'가능' if control['writable'] else '불가'}")
    print(f"최근 보호 실행: {len(bundle['recent_runs'])}건 요약 포함")
    print("개인정보: 전체 경로·Workspace 내용·raw evidence·명령 출력은 포함하지 않음")
    if written is not None:
        print(f"저장 경로: {written}")
    else:
        print("JSON 파일로 저장하려면 --output <path>를 사용하세요.")
    return 0


def _verify_bundle(args: argparse.Namespace) -> int:
    """Verify a Result Bundle using the read-only Evidence Bundle verifier."""

    result = verify_evidence_bundle(args.result_directory)
    if args.json:
        print(
            _json_text(
                {
                    "status": result.status.value,
                    "session_id": result.session_id,
                    "result_id": result.result_id,
                    "reason": result.reason,
                    "verified_artifact_count": result.verified_artifact_count,
                }
            )
        )
    else:
        print(f"Status: {result.status.value}")
        print(f"Reason: {result.reason or 'NONE'}")
        print(f"Verified artifacts: {result.verified_artifact_count}")
    return 0 if result.status is BundleVerificationStatus.VALID else 1


def _setup(args: argparse.Namespace) -> int:
    from aia.cli_hook import _setup as hook_setup

    return hook_setup(args)


def _run_console(args: argparse.Namespace) -> int:
    """Start the local console through the same product CLI as other commands."""

    if args.control_root is not None:
        os.environ["AIA_CONTROL_ROOT"] = str(
            Path(args.control_root).expanduser().resolve(strict=False)
        )
    from aia_web.__main__ import run, validate_local_bind

    try:
        validate_local_bind(args.host, args.port)
    except ValueError as error:
        raise ApplicationValidationError(str(error)) from error

    open_path = getattr(args, "open_path", "/") or "/"
    if not open_path.startswith("/"):
        open_path = "/" + open_path
    url = f"http://{args.host}:{args.port}{open_path}"
    print(f"AIA 로컬 보안 콘솔: {url}")
    if args.open:
        # Let uvicorn bind the loopback port before asking the browser to load
        # the page; otherwise the first navigation can race server startup.
        browser_timer = threading.Timer(0.5, webbrowser.open, args=(url,), kwargs={"new": 2})
        browser_timer.daemon = True
        browser_timer.start()
        print("서버가 시작되면 기본 브라우저에서 콘솔을 엽니다.")
    print("종료하려면 Ctrl+C를 누르세요.")
    run(host=args.host, port=args.port)
    return 0


def _hook_status(args: argparse.Namespace) -> int:
    from aia.cli_hook import _hook_status as hook_status

    return hook_status(args)


def _hook_explain(args: argparse.Namespace) -> int:
    from aia.cli_hook import _hook_explain as hook_explain

    return hook_explain(args)


def _extract_session_id(output: str) -> str | None:
    from aia.cli_hook import _extract_session_id as extract_session_id

    return extract_session_id(output)


def _live_hook_proof_is_valid(
    *,
    hook_event_count: object,
    protection_state: object,
    bundle_status: object,
) -> bool:
    from aia.cli_hook import _live_hook_proof_is_valid as live_hook_proof_is_valid

    return live_hook_proof_is_valid(
        hook_event_count=hook_event_count,
        protection_state=protection_state,
        bundle_status=bundle_status,
    )


def _hook_verify_installation_failure(
    args: argparse.Namespace, installer: CodexHookInstaller
) -> bool:
    from aia.cli_hook import _hook_verify_installation_failure as verify_installation_failure

    return verify_installation_failure(args, installer)


def _hook_verify_codex_executable(args: argparse.Namespace) -> Path | None:
    from aia.cli_hook import _hook_verify_codex_executable as verify_codex_executable

    return verify_codex_executable(args)


def _hook_verify_codex_trust(
    args: argparse.Namespace, installer: CodexHookInstaller, executable: Path
) -> dict[str, object] | None:
    from aia.cli_hook import _hook_verify_codex_trust as verify_codex_trust

    return verify_codex_trust(args, installer, executable)


def _hook_probe_payload(
    args: argparse.Namespace,
    installer: CodexHookInstaller,
    executable: Path,
    control_root: Path,
    probe_workspace: Path,
    codex_hook_trust: dict[str, object],
) -> tuple[Path, list[str], dict[str, str], dict[str, object]]:
    from aia.cli_hook import _hook_probe_payload as hook_probe_payload

    return hook_probe_payload(
        args, installer, executable, control_root, probe_workspace, codex_hook_trust
    )


def _classify_live_hook_result(
    payload: dict[str, object],
    *,
    installer: CodexHookInstaller,
    executable: Path,
    control_root: Path,
    marker: Path,
) -> None:
    from aia.cli_hook import _classify_live_hook_result as classify_live_hook_result

    classify_live_hook_result(
        payload,
        installer=installer,
        executable=executable,
        control_root=control_root,
        marker=marker,
    )


def _run_hook_verification_probe(
    args: argparse.Namespace,
    installer: CodexHookInstaller,
    executable: Path,
    codex_hook_trust: dict[str, object],
) -> dict[str, object]:
    from aia.cli_hook import _run_hook_verification_probe as run_hook_verification_probe

    return run_hook_verification_probe(
        args, installer, executable, codex_hook_trust
    )


def _print_hook_verification_result(
    args: argparse.Namespace, payload: dict[str, object]
) -> None:
    from aia.cli_hook import _print_hook_verification_result as print_hook_verification_result

    print_hook_verification_result(args, payload)


def _hook_verify(args: argparse.Namespace) -> int:
    from aia.cli_hook import _hook_verify as hook_verify

    return hook_verify(args)


def _protected_run_preflight(
    control_root: Path | None = None,
    *,
    hook_verification_probe: bool = False,
) -> tuple[bool, list[str]]:
    """Return actionable local checks before creating a Protected Run."""

    failures: list[str] = []
    try:
        CodexAdapter().discover()
    except Exception:
        failures.append("Codex executable을 찾을 수 없습니다. Codex 설치를 확인하세요.")
    installer = CodexHookInstaller()
    cli_prefix = _cli_prefix(installer)
    if not installer.is_installed():
        failures.append(
            f"AIA PreToolUse Hook이 설치되지 않았습니다. 먼저 '{cli_prefix} setup'을 실행하세요."
        )
    elif not hook_verification_probe:
        resolved_control_root = control_root or _control_root(None)
        try:
            executable = CodexAdapter().discover()
        except Exception:
            executable = None
        trust_status = None
        if executable is not None:
            try:
                inspection = inspect_codex_hook_trust(
                    executable,
                    hook_path=installer.path,
                    cwd=Path.cwd(),
                    timeout=8.0,
                ).to_mapping()
                trust_status = next(
                    (
                        item.get("trust_status")
                        for item in (inspection.get("hooks") or [])
                        if isinstance(item, dict) and item.get("event") == "preToolUse"
                    ),
                    None,
                )
            except (OSError, ValueError):
                trust_status = None
        if executable is None or not HookVerificationStore(resolved_control_root).is_current(
            installer,
            executable,
        ):
            if trust_status not in {None, "TRUSTED", "MANAGED"}:
                failures.append(
                    f"Codex PreToolUse Hook Trust={trust_status}. Codex /hooks에서 AIA Hook을 검토·신뢰한 뒤 '{cli_prefix} hook verify'를 실행하세요."
                )
            else:
                failures.append(
                    f"실제 Codex Hook 검증이 없습니다. 먼저 '{cli_prefix} hook verify'를 실행하세요."
                )
    return not failures, failures


def _print_protected_run_summary(
    session_id: str,
    status: dict[str, object],
    result: dict[str, object] | None,
) -> None:
    from aia.cli_runs import _print_protected_run_summary as print_summary

    print_summary(session_id, status, result)

def _validate_policy(args: argparse.Namespace) -> int:
    return cli_policy.validate_policy(args)


def _policy_profiles(args: argparse.Namespace) -> int:
    return cli_policy.policy_profiles(args, lambda: _cli_prefix(CodexHookInstaller()))


def _init_policy(args: argparse.Namespace) -> int:
    return cli_policy.init_policy(args, lambda: _cli_prefix(CodexHookInstaller()))


def _policy_evaluate(args: argparse.Namespace) -> int:
    return cli_policy.policy_evaluate(args)


def _list_runs(args: argparse.Namespace) -> int:
    from aia.cli_runs import _list_runs as list_runs

    return list_runs(args)

def _show_status(args: argparse.Namespace) -> int:
    from aia.cli_runs import _show_status as show_status

    return show_status(args)

def _stop_run(args: argparse.Namespace) -> int:
    from aia.cli_runs import _stop_run as stop_run

    return stop_run(args)

def _reconcile_run(args: argparse.Namespace) -> int:
    from aia.cli_runs import _reconcile_run as reconcile_run

    return reconcile_run(args)

def _run_protected(args: argparse.Namespace) -> int:
    from aia.cli_runs import _run_protected as run_protected

    return run_protected(args)

def main(argv: Sequence[str] | None = None) -> int:
    _configure_console_encoding()
    args = _parser().parse_args(argv)
    try:
        if args.command == "capabilities":
            return _capabilities(args)
        if args.command == "doctor":
            return _doctor(args)
        if args.command == "self-test":
            return _self_test(args)
        if args.command == "demo":
            return _demo(args)
        if args.command == "runs":
            return _list_runs(args)
        if args.command == "status":
            return _show_status(args)
        if args.command == "stop":
            return _stop_run(args)
        if args.command == "reconcile":
            return _reconcile_run(args)
        if args.command == "policy" and args.policy_command == "validate":
            return _validate_policy(args)
        if args.command == "policy" and args.policy_command == "evaluate":
            return _policy_evaluate(args)
        if args.command == "policy" and args.policy_command == "profiles":
            return _policy_profiles(args)
        if args.command == "policy" and args.policy_command == "init":
            return _init_policy(args)
        if args.command == "hook" and args.hook_command == "install":
            path = CodexHookInstaller(args.path).install()
            print(f"Codex Hook installed: {path}")
            print("Review and trust this Hook in Codex before starting a protected run.")
            return 0
        if args.command == "hook" and args.hook_command == "uninstall":
            path = CodexHookInstaller(args.path).uninstall()
            print(f"AIA Codex Hook removed (other Hooks preserved): {path}")
            return 0
        if args.command == "hook" and args.hook_command == "runtime":
            from aia.codex_hook_runtime import main as hook_runtime_main

            return hook_runtime_main()
        if args.command == "setup":
            return _setup(args)
        if args.command == "support-bundle":
            return _support_bundle(args)
        if args.command == "verify-bundle":
            return _verify_bundle(args)
        if args.command == "console":
            return _run_console(args)
        if args.command == "hook" and args.hook_command == "status":
            return _hook_status(args)
        if args.command == "hook" and args.hook_command == "explain":
            return _hook_explain(args)
        if args.command == "hook" and args.hook_command == "verify":
            return _hook_verify(args)
        if args.command in {"protect", "start"}:
            return _run_protected(args)
        if args.command == "proof":
            if args.timeout <= 0:
                raise ApplicationValidationError("timeout must be positive")
            from aia.product_e2e import main as product_e2e_main

            return product_e2e_main(
                [
                    "--scenario",
                    args.scenario,
                    "--output",
                    str(args.output),
                    "--timeout",
                    str(args.timeout),
                ]
                + (["--json"] if args.json else [])
            )
        raise ApplicationValidationError("unknown command")
    except (ApplicationValidationError, CodexHookInstallationError, OSError, ValueError) as error:
        print(f"AIA error: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
