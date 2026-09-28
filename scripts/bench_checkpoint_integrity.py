"""Measure Safe Checkpoint creation and two-pass integrity verification."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
from time import perf_counter

from aia import (
    PolicyProfile,
    ProtectedRunSession,
    SessionMode,
    SessionStatus,
    WorkspaceLeaseManager,
    create_safe_checkpoint,
    prepare_protection,
    resolve_profile,
)
from aia.integrity import IntegrityVerifier


class _ProcessIdentity:
    def __call__(self, pid: int) -> float:
        if pid != 1:
            raise ProcessLookupError(pid)
        return 1.0


def main() -> None:
    repository = Path(__file__).resolve().parents[1]
    temporary_parent = repository / "tmp"
    temporary_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="checkpoint-integrity-", dir=temporary_parent) as raw:
        root = Path(raw)
        workspace = root / "workspace"
        workspace.mkdir()
        payload = bytes(range(256)) * 4
        for index in range(5000):
            directory = workspace / f"group-{index // 100:02d}"
            directory.mkdir(exist_ok=True)
            (directory / f"file-{index:04d}.bin").write_bytes(payload)

        profile = resolve_profile(PolicyProfile.BASIC_DEVELOPMENT)
        session = ProtectedRunSession(
            workspace=workspace,
            agent="codex",
            mode=SessionMode.ENFORCE,
            policy_id=profile.policy_id,
            policy_version=profile.policy_version,
        )
        session.transition(SessionStatus.PREPARING, at=datetime.now(timezone.utc))
        leases = WorkspaceLeaseManager(
            root / "control",
            process_identity_provider=_ProcessIdentity(),
        )
        context = prepare_protection(
            session,
            profile,
            root / "control",
            lease_manager=leases,
            owner_pid=1,
            owner_process_create_time=1.0,
        )

        started = perf_counter()
        checkpoint = create_safe_checkpoint(
            session,
            context,
            lease_manager=leases,
            checkpoint_id="benchmark",
        )
        checkpoint_seconds = perf_counter() - started

        started = perf_counter()
        result = IntegrityVerifier(two_pass=True).verify(checkpoint, workspace=workspace)
        verify_seconds = perf_counter() - started
        print(f"files: {checkpoint.file_count}")
        print(f"checkpoint: {checkpoint_seconds:.3f} s")
        print(f"two-pass verify: {verify_seconds:.3f} s ({result.integrity_status})")


if __name__ == "__main__":
    main()
