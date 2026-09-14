from pathlib import Path
from dataclasses import replace

import pytest

from aia import (
    EvidenceBundleVerifier,
    ResultAlreadyCommittedConflict,
    ProcessIdentityStatus,
    SessionFinalizer,
    verify_evidence_bundle,
)
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
