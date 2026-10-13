"""Disk use of the local record folder and clean-up of old runs' snapshot copies.

Every protected run keeps a copy of its work folder (the checkpoint) so it can
be restored.  Those copies are most of the record folder.  For finished runs
older than the newest KEEP_RECENT_RUNS, only the copied work folder inside each
checkpoint is removed: audit records, evidence and the checkpoint manifests
that the sealed bundle refers to stay, so the bundle still verifies, but that
run can no longer be restored.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
from typing import Any

KEEP_RECENT_RUNS = 10
PRUNED_MARKER = ".snapshots-pruned.json"
_FINISHED = {"COMPLETED", "ABORTED", "FAILED"}


def _tree_bytes(root: Path, seen: set[tuple[int, int]]) -> int:
    """Bytes under root, counting a hard-linked file once."""

    total = 0
    for directory, _dirs, files in os.walk(root, followlinks=False):
        for name in files:
            try:
                info = os.stat(os.path.join(directory, name), follow_symlinks=False)
            except OSError:
                continue
            key = (info.st_dev, info.st_ino)
            if key in seen:
                continue
            seen.add(key)
            total += info.st_size
    return total


def _is_plain_directory(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink() and not path.is_junction()


def _snapshot_copies(checkpoints_root: Path) -> list[Path]:
    """The copied work folders of a run's checkpoints (never links or junctions)."""

    if not _is_plain_directory(checkpoints_root):
        return []
    copies = []
    for checkpoint in checkpoints_root.iterdir():
        snapshot = checkpoint / "workspace"
        if not checkpoint.name.startswith(".") and _is_plain_directory(checkpoint) and _is_plain_directory(snapshot):
            copies.append(snapshot)
    return copies


def snapshots_pruned(checkpoints_root: Path) -> bool:
    return (checkpoints_root / PRUNED_MARKER).is_file()


class StorageMixin:
    def _finished_runs_newest_first(self) -> list[str]:
        runs = [run for run in self.list_runs() if isinstance(run.get("session_id"), str)]
        runs.sort(key=lambda run: str(run.get("created_at") or ""), reverse=True)
        live = {record.session_id for record in self.registry.snapshots() if record.status not in _FINISHED}
        return [
            run["session_id"] for run in runs
            if str(run.get("status") or "").upper() in _FINISHED and run["session_id"] not in live
        ]

    def storage_summary(self) -> dict[str, Any]:
        """Record folder size, snapshot copies, and what clean-up would free."""

        finished = self._finished_runs_newest_first()
        seen: set[tuple[int, int]] = set()
        snapshot_bytes = 0
        prunable_bytes = 0
        prunable_runs = 0
        for index, session_id in enumerate(finished):
            copies = _snapshot_copies(self.reader.session_directory(session_id) / "checkpoints")
            run_bytes = sum(_tree_bytes(copy, seen) for copy in copies)
            snapshot_bytes += run_bytes
            if index >= KEEP_RECENT_RUNS and copies:
                prunable_runs += 1
                prunable_bytes += run_bytes
        total_bytes = _tree_bytes(self.control_root, set()) if self.control_root.is_dir() else 0
        return {
            "path": str(self.control_root),
            "total_bytes": total_bytes,
            "snapshot_bytes": snapshot_bytes,
            "keep_recent_runs": KEEP_RECENT_RUNS,
            "prunable_runs": prunable_runs,
            "prunable_bytes": prunable_bytes,
        }

    def prune_old_snapshots(self) -> dict[str, Any]:
        """Remove snapshot copies of finished runs older than the newest KEEP_RECENT_RUNS."""

        pruned_runs = 0
        freed_bytes = 0
        for session_id in self._finished_runs_newest_first()[KEEP_RECENT_RUNS:]:
            checkpoints_root = self.reader.session_directory(session_id) / "checkpoints"
            copies = _snapshot_copies(checkpoints_root)
            if not copies:
                continue
            run_bytes = 0
            for copy in copies:
                run_bytes += _tree_bytes(copy, set())
                shutil.rmtree(copy, ignore_errors=True)
            marker = {"pruned_at": datetime.now(timezone.utc).isoformat(), "freed_bytes": run_bytes,
                      "reason": f"저장 공간 정리: 최근 {KEEP_RECENT_RUNS}개 실행만 기준점 사본을 보관"}
            try:
                (checkpoints_root / PRUNED_MARKER).write_text(json.dumps(marker, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
            pruned_runs += 1
            freed_bytes += run_bytes
        return {"pruned_runs": pruned_runs, "freed_bytes": freed_bytes, "keep_recent_runs": KEEP_RECENT_RUNS}
