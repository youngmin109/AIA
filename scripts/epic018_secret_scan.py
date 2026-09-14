"""EPIC-018 secret safety scan across finalized product artifacts."""

from __future__ import annotations

from pathlib import Path
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aia import (
    EvidenceRecordType,
    EvidenceSource,
    NormalizedAction,
    NormalizationCompleteness,
    ObservationStage,
    Operation,
    ProcessIdentityStatus,
    SessionFinalizer,
)
from aia.evidence import RawEvidenceRecord
from tests.test_finalization import _session


MARKER = "FAKE_AIA_SECRET_018=unique-marker-018"


def main() -> int:
    evaluation_root = Path(os.environ["AIA_EPIC018_EVALUATION_ROOT"]).resolve()
    root = evaluation_root / "evidence" / "secret-scan"
    root.mkdir(parents=True, exist_ok=True)
    session, store, action = _session(root / "fixture")
    secret_record = store.append(
        RawEvidenceRecord(
            session_id=session.session_id,
            source=EvidenceSource.AGENT_HOOK,
            record_type=EvidenceRecordType.COMMAND_OBSERVED,
            captured_at=action.observed_at,
            observation_stage=ObservationStage.PRE_ACTION,
            payload={"raw_command": MARKER},
            evidence_id="secret-command-evidence",
        )
    )
    command_action = NormalizedAction(
        action_id="secret-command-action",
        aia_session_id=session.session_id,
        operation=Operation.EXECUTE,
        stage=ObservationStage.PRE_ACTION,
        target_kind="COMMAND",
        observed_at=action.observed_at,
        evidence_ids=(secret_record.evidence_id,),
        evidence_sources=(EvidenceSource.AGENT_HOOK,),
        completeness=NormalizationCompleteness.COMPLETE,
        normalizer_version="canonical-v1",
        raw_command=MARKER,
    )
    final = SessionFinalizer(evidence_store=store).finalize(
        session,
        process_end_status=ProcessIdentityStatus.PROCESS_GONE,
        actions=(command_action,),
    )
    files = {
        "result.json": final.bundle.result_directory / "result.json",
        "audit.jsonl": final.bundle.result_directory / "audit.jsonl",
        "security-report.md": final.bundle.result_directory / "security-report.md",
        "evidence-manifest.json": final.bundle.result_directory / "evidence-manifest.json",
        "commit.json": final.bundle.result_directory / "commit.json",
        "evidence-index.json": store.index_path,
    }
    counts = {name: path.read_text(encoding="utf-8").count(MARKER) for name, path in files.items()}
    raw_count = store.path.read_text(encoding="utf-8").count(MARKER)
    output = {
        "marker": MARKER,
        "product_artifact_counts": counts,
        "raw_evidence_count": raw_count,
        "secret_free_product_artifacts": all(value == 0 for value in counts.values()),
        "raw_evidence_path": str(store.path),
    }
    (root / "result.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    return 0 if output["secret_free_product_artifacts"] and raw_count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
