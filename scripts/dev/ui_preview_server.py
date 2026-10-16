"""Local preview server for UI work (EPIC-020).

Serves the built console against a throw-away Control Root that holds:
- completed runs from the deterministic ``aia demo`` scenarios, and
- one live run whose Codex conversation is the fake app-server used by tests
  (type ``run`` for a command approval, ``patch`` for a file approval,
  ``hello`` for a plain reply), and
- one finished run with a real Safe Checkpoint whose Workspace changed
  afterwards, so the restore flow (⑦) can run end to end.

Nothing here touches the user's real Control Root or Codex configuration.

    .venv\\Scripts\\python.exe scripts\\dev\\ui_preview_server.py [--port 8899] [--reset]
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys

import uvicorn

from aia_app.codex_app_server import CodexAppServerSession
from aia_app.registry import RunRecord
from aia_app.service import RunApplicationService
from aia_web.app import create_app

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))  # reuse the test fixtures below
PREVIEW = ROOT / ".tmp-ui"
CONTROL = PREVIEW / "control"
FAKE_SERVER = ROOT / "tests" / "fake_codex_app_server.py"
SCENARIOS = ("hook-block", "process-kill", "file-rollback")


def prepare_completed_runs() -> None:
    # Each demo resets the sessions of its Control Root, so build them apart and gather them.
    sessions = CONTROL / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    for scenario in SCENARIOS:
        demo_root = PREVIEW / f"demo-{scenario}"
        subprocess.run(
            [sys.executable, "-m", "aia.cli", "demo", "--scenario", scenario,
             "--workspace", str(PREVIEW / f"ws-{scenario}"), "--control-root", str(demo_root)],
            cwd=ROOT, check=True, stdout=subprocess.DEVNULL,
        )
        for session in (demo_root / "sessions").iterdir():
            shutil.copytree(session, sessions / session.name, dirs_exist_ok=True)


def add_restorable_run() -> None:
    """Same steps as tests/test_product_update.py's manual restore test."""
    from aia import ProcessIdentityStatus, RawEvidenceStore, SessionFinalizer, SessionStatus, create_safe_checkpoint
    from aia_app.service import process_create_time
    from tests.test_checkpoint import _prepared_workspace

    workspace, session, context, manager = _prepared_workspace(
        PREVIEW, owner_pid=os.getpid(), owner_create_time=process_create_time(os.getpid())
    )
    (workspace / 'orders.csv').write_text('id,total\n1,1200\n', encoding='utf-8')
    (workspace / 'README.md').write_text('# shop\n', encoding='utf-8')
    checkpoint = create_safe_checkpoint(session, context, lease_manager=manager)
    store = RawEvidenceStore.for_session(CONTROL, session.session_id)
    session.transition(SessionStatus.READY)
    session.transition(SessionStatus.RUNNING)
    SessionFinalizer(evidence_store=store).finalize(
        session, process_end_status=ProcessIdentityStatus.PROCESS_GONE,
        checkpoint=checkpoint, active_policy=context.active_policy,
        workspace_lease=context.workspace_lease, lease_manager=manager,
    )
    (workspace / 'orders.csv').unlink()
    (workspace / 'README.md').write_text('# shop (edited after the run)\n', encoding='utf-8')
    (workspace / 'notes.txt').write_text('added later', encoding='utf-8')


def add_live_run(service: RunApplicationService) -> CodexAppServerSession:
    workspace = PREVIEW / "ws-live"
    workspace.mkdir(parents=True, exist_ok=True)
    record = RunRecord(
        session_id="preview-live",
        workspace=workspace,
        agent="codex",
        model=None,
        policy_profile="PROTECTED_DEVELOPMENT",
        policy_id="protected-development",
        policy_version="1.0.0",
        mode="ENFORCE",
        task="",
        interactive=True,
        launch_mode="codex_app_server",
        created_at=datetime.now(timezone.utc),
    )
    record.status = "RUNNING"
    session = CodexAppServerSession(
        [sys.executable, "-u", str(FAKE_SERVER)], cwd=workspace, env=dict(os.environ), client_version="preview"
    )
    session.start()
    session.open()
    record.runtime["codex_session"] = session
    record.codex_thread_id = session.snapshot()["thread_id"]
    service.registry.add(record)
    return session


def add_failed_start_run(service: RunApplicationService) -> None:
    """A run whose checkpoint failed on an unreadable folder; the Work view must explain it."""

    workspace = PREVIEW / "ws-unreadable"
    workspace.mkdir(parents=True, exist_ok=True)
    record = RunRecord(
        session_id="preview-failed-start",
        workspace=workspace,
        agent="codex",
        model=None,
        policy_profile="PROTECTED_DEVELOPMENT",
        policy_id="protected-development",
        policy_version="1.0.0",
        mode="ENFORCE",
        task="",
        interactive=True,
        launch_mode="codex_app_server",
        created_at=datetime.now(timezone.utc),
    )
    record.status = "FAILED"
    record.phase = "FAILED"
    record.protection_state = "FAILED"
    record.error = (
        "CheckpointCreationError: Workspace directory cannot be read: "
        f"{workspace / 'tmp' / 'pf08-after-8syit7pa'}"
    )
    service.registry.add(record)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument("--reset", action="store_true", help="rebuild the preview Control Root")
    parser.add_argument("--no-live", action="store_true", help="skip the fake live run")
    args = parser.parse_args()

    if args.reset and PREVIEW.exists():
        shutil.rmtree(PREVIEW)
    if not (CONTROL / "sessions").exists():
        prepare_completed_runs()
        add_restorable_run()

    service = RunApplicationService(CONTROL)
    session = None if args.no_live else add_live_run(service)
    add_failed_start_run(service)
    try:
        uvicorn.run(create_app(service), host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        if session is not None:
            session.close(force=True)
        service.shutdown()


if __name__ == "__main__":
    main()
