from pathlib import Path

from aia import IntegrityStatus
from aia.integrity import IntegrityVerifier

from tests.test_recovery import _fixture


def test_integrity_exact_baseline_is_verified(tmp_path: Path):
    workspace, session, _, _, checkpoint, _, _ = _fixture(tmp_path)

    result = IntegrityVerifier().verify(
        checkpoint,
        workspace=workspace,
        session=session,
    )

    assert result.integrity_status is IntegrityStatus.VERIFIED
    assert result.missing_paths == ()
    assert result.unexpected_paths == ()
    assert result.changed_paths == ()


def test_integrity_reports_missing_unexpected_and_hash_mismatch(tmp_path: Path):
    workspace, session, _, _, checkpoint, _, _ = _fixture(tmp_path)
    (workspace / "protected" / "deleted.txt").unlink()
    (workspace / "protected" / "modified.txt").write_text("changed", encoding="utf-8")
    (workspace / "unexpected.txt").write_text("created", encoding="utf-8")

    result = IntegrityVerifier().verify(checkpoint, workspace=workspace, session=session)

    assert result.integrity_status is IntegrityStatus.FAILED
    assert "protected/deleted.txt" in result.missing_paths
    assert "unexpected.txt" in result.unexpected_paths
    assert "protected/modified.txt" in result.changed_paths


def test_integrity_type_and_empty_directory_mismatch_fail(tmp_path: Path):
    workspace, session, _, _, checkpoint, _, _ = _fixture(tmp_path)
    (workspace / "protected" / "deleted.txt").unlink()
    (workspace / "protected" / "deleted.txt").mkdir()
    (workspace / "empty-dir").rmdir()
    (workspace / "empty-dir").write_text("wrong type", encoding="utf-8")

    result = IntegrityVerifier().verify(checkpoint, workspace=workspace, session=session)

    assert result.integrity_status is IntegrityStatus.FAILED
    assert "protected/deleted.txt" in result.type_mismatches
    assert "empty-dir" in result.type_mismatches


def test_integrity_rejects_tampered_checkpoint(tmp_path: Path):
    workspace, session, _, _, checkpoint, _, _ = _fixture(tmp_path)
    checkpoint.metadata_path.write_text("tampered", encoding="utf-8")

    result = IntegrityVerifier().verify(checkpoint, workspace=workspace, session=session)

    assert result.integrity_status is IntegrityStatus.FAILED
    assert "CHECKPOINT_INVALID" in result.verification_errors
