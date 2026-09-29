from pathlib import Path
from dataclasses import replace
from threading import Lock
from time import sleep
from types import SimpleNamespace

import pytest

from aia import (
    EvidenceBundleVerifier,
    ResultAlreadyCommittedConflict,
    ProcessIdentityStatus,
    SessionFinalizer,
    verify_evidence_bundle,
)
from aia_app.readers import ResultBundleReader
from tests.test_finalization import _session


@pytest.mark.parametrize(
    "relative_path",
    [
        "result/result.json",
        "result/audit.jsonl",
        "result/security-report.md",
        "evidence/raw-evidence.jsonl",
        "result/evidence-manifest.json",
    ],
)
def test_committed_bundle_detects_each_artifact_tamper(tmp_path: Path, relative_path: str):
    session, store, _ = _session(tmp_path)
    final = SessionFinalizer(evidence_store=store).finalize(
        session,
        process_end_status=ProcessIdentityStatus.PROCESS_GONE,
    )
    path = final.bundle.result_directory.parent / relative_path
    original = path.read_bytes()
    path.write_bytes(original + b"tamper")
    assert not EvidenceBundleVerifier().verify(final.bundle.result_directory).is_valid


def test_history_scan_reuses_verified_result_bytes_and_rechecks_tampering(
    tmp_path: Path,
    monkeypatch,
):
    session, store, _ = _session(tmp_path)
    final = SessionFinalizer(evidence_store=store).finalize(
        session,
        process_end_status=ProcessIdentityStatus.PROCESS_GONE,
    )
    reader = ResultBundleReader(tmp_path / "control")
    result_path = final.bundle.result_directory / "result.json"
    raw_evidence_path = (
        final.bundle.result_directory.parent / "evidence" / "raw-evidence.jsonl"
    )
    original_read_bytes = Path.read_bytes
    result_byte_reads = 0
    raw_evidence_byte_reads = 0

    def read_bytes(path: Path) -> bytes:
        nonlocal result_byte_reads, raw_evidence_byte_reads
        if path == result_path:
            result_byte_reads += 1
        if path == raw_evidence_path:
            raw_evidence_byte_reads += 1
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)

    for _ in range(2):
        bundles = reader.list_completed()
        assert len(bundles) == 1
        assert bundles[0]["bundle_status"] == "VALID"
        assert "protected/main.py" not in repr(bundles)
    assert result_byte_reads == 2
    assert raw_evidence_byte_reads == 2

    artifact_path = raw_evidence_path
    artifact_path.write_bytes(original_read_bytes(artifact_path) + b"tamper")
    assert reader.list_completed() == []
    assert result_byte_reads == 2
    assert raw_evidence_byte_reads == 3


def test_history_scan_verifies_concurrently_and_preserves_order_and_content(
    tmp_path: Path,
    monkeypatch,
):
    reader = ResultBundleReader(tmp_path / "control")
    sessions_directory = reader.control_root / "sessions"
    sessions_directory.mkdir(parents=True)
    session_ids = ["session-a", "session-b", "session-c"]
    results = {}
    for index, session_id in enumerate(session_ids):
        (sessions_directory / session_id).mkdir()
        results[session_id] = {
            "session_status": "COMPLETED",
            "session_end_reason": None,
            "ended_at": f"2026-09-29T12:0{index}:00Z",
            "created_at": f"2026-09-29T11:0{index}:00Z",
            "workspace": f"/workspace/{session_id}",
            "agent": "codex",
            "launch_mode": "protected",
            "policy": {"policy_id": session_id},
            "run_classification": "PROTECTED",
            "limitations": [],
            "action_outcomes": (
                [{"policy_decision": "VIOLATION"}] if index == 1 else []
            ),
        }

    lock = Lock()
    active_verifications = 0
    max_active_verifications = 0
    verified_session_ids = []

    def read_verified_result(session_id: str):
        nonlocal active_verifications, max_active_verifications
        with lock:
            active_verifications += 1
            max_active_verifications = max(
                max_active_verifications, active_verifications
            )
            verified_session_ids.append(session_id)
        sleep(0.03)
        with lock:
            active_verifications -= 1
        verification = SimpleNamespace(
            status=SimpleNamespace(value="VALID")
        )
        return results[session_id], verification, None

    monkeypatch.setattr(reader, "_read_verified_result", read_verified_result)

    bundles = reader.list_completed()

    expected = [
        {
            "session_id": session_id,
            "status": "COMPLETED",
            "ended_at": results[session_id]["ended_at"],
            "created_at": results[session_id]["created_at"],
            "workspace": results[session_id]["workspace"],
            "agent": "codex",
            "launch_mode": "protected",
            "policy": {"policy_id": session_id},
            "run_classification": "PROTECTED",
            "bundle_status": "VALID",
            "protection_state": "COMPLETED_DEGRADED",
            "hook_event_count": 0,
            "posttool_event_count": 0,
            "incident_count": 1 if session_id == "session-b" else 0,
            "result_url": f"/runs/{session_id}/result",
        }
        for session_id in session_ids
    ]
    expected.sort(key=lambda item: item["ended_at"], reverse=True)

    assert max_active_verifications > 1
    assert sorted(verified_session_ids) == sorted(session_ids)
    assert bundles == expected


def test_bundle_verifier_accepts_session_directory_and_result_lineage_index(tmp_path: Path):
    session, store, action = _session(tmp_path)
    final = SessionFinalizer(evidence_store=store).finalize(
        session,
        process_end_status=ProcessIdentityStatus.PROCESS_GONE,
        actions=(action,),
    )
    assert verify_evidence_bundle(final.bundle.result_directory.parent).is_valid
    result_mapping = final.result.to_mapping()
    evidence_id = result_mapping["action_outcomes"][0]["evidence_ids"][0]
    index = (store.index_path).read_text(encoding="utf-8")
    assert evidence_id in index
    assert "line_number" in index


def test_same_content_reuses_and_different_content_conflicts_without_overwrite(tmp_path: Path):
    session, store, action = _session(tmp_path)
    finalizer = SessionFinalizer(evidence_store=store)
    first = finalizer.finalize(
        session,
        process_end_status=ProcessIdentityStatus.PROCESS_GONE,
        actions=(action,),
    )
    artifact_paths = (
        first.bundle.result_directory / "result.json",
        first.bundle.result_directory / "audit.jsonl",
        first.bundle.result_directory / "security-report.md",
        first.bundle.result_directory / "evidence-manifest.json",
        first.bundle.result_directory / "commit.json",
        store.path,
        store.seal_path,
        store.index_path,
    )
    before = {path: path.read_bytes() for path in artifact_paths}

    reused = finalizer.finalize(session, actions=(action,))
    assert reused.bundle.reused
    assert reused.result.to_json_bytes() == first.result.to_json_bytes()

    changed_action = replace(action, canonical_path="protected/other.py")
    with pytest.raises(ResultAlreadyCommittedConflict) as error:
        finalizer.finalize(session, actions=(changed_action,))
    assert error.value.code == "RESULT_ALREADY_COMMITTED_CONFLICT"
    assert {path: path.read_bytes() for path in artifact_paths} == before
