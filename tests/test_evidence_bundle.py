from pathlib import Path

import pytest

from aia import (
    EvidenceBundleVerifier,
    FinalizationError,
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
