from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from aia import (
    EvidenceError,
    EvidenceRecordType,
    EvidenceSource,
    EvidenceStoreError,
    ObservationStage,
    RawEvidenceRecord,
    RawEvidenceStore,
)


def make_record(session_id: str = "session-1", index: int = 0) -> RawEvidenceRecord:
    return RawEvidenceRecord(
        session_id=session_id,
        source=EvidenceSource.FILESYSTEM_WATCHER,
        record_type=EvidenceRecordType.FILESYSTEM_EVENT,
            captured_at=datetime(
                2026,
                1,
                1,
                1,
                0,
                microsecond=index * 1000,
                tzinfo=timezone.utc,
            ),
        observation_stage=ObservationStage.POST_ACTION,
        payload={
            "event_type": "created",
            "src_path": f"C:/workspace/file-{index}.txt",
            "is_directory": False,
        },
    )


def test_raw_evidence_record_is_immutable_and_utc_normalized() -> None:
    record = RawEvidenceRecord(
        session_id="session-1",
        source=EvidenceSource.FILESYSTEM_WATCHER,
        record_type=EvidenceRecordType.SENSOR_HEALTH,
        captured_at=datetime.fromisoformat("2026-01-01T10:00:00+09:00"),
        observation_stage=ObservationStage.POST_ACTION,
        payload={"sensor": "FILESYSTEM_WATCHER", "status": "HEALTHY"},
    )

    assert record.captured_at == datetime(
        2026, 1, 1, 1, 0, tzinfo=timezone.utc
    )
    assert record.payload["status"] == "HEALTHY"
    with pytest.raises(TypeError):
        record.payload["status"] = "FAILED"  # type: ignore[index]


def test_raw_evidence_rejects_unsafe_session_id_and_naive_timestamp() -> None:
    with pytest.raises(EvidenceError):
        make_record("../outside")
    with pytest.raises(EvidenceError):
        RawEvidenceRecord(
            session_id="session-1",
            source=EvidenceSource.FILESYSTEM_WATCHER,
            record_type=EvidenceRecordType.FILESYSTEM_EVENT,
            captured_at=datetime(2026, 1, 1),
            observation_stage=ObservationStage.POST_ACTION,
            payload={},
        )


def test_session_store_uses_control_root_session_scoped_jsonl_path(
    tmp_path: Path,
) -> None:
    store = RawEvidenceStore.for_session(tmp_path / "control", "session-1")

    assert store.path == (
        tmp_path / "control" / "sessions" / "session-1" / "evidence"
        / "raw-evidence.jsonl"
    ).resolve()
    store.append(make_record())
    assert store.path.is_file()
    assert store.records()[0].session_id == "session-1"


def test_store_is_append_only_and_does_not_rewrite_existing_jsonl(
    tmp_path: Path,
) -> None:
    store = RawEvidenceStore(tmp_path / "raw-evidence.jsonl", session_id="session-1")
    store.append(make_record(index=1))
    original_first_line = store.path.read_bytes().splitlines(keepends=True)[0]

    store.append(make_record(index=2))

    lines = store.path.read_bytes().splitlines(keepends=True)
    assert lines[0] == original_first_line
    assert len(lines) == 2
    assert all(json.loads(line) for line in lines)


def test_store_rejects_records_from_another_session(tmp_path: Path) -> None:
    store = RawEvidenceStore(tmp_path / "raw-evidence.jsonl", session_id="session-1")

    with pytest.raises(EvidenceStoreError):
        store.append(make_record("session-2"))
    assert not store.path.exists()


def test_store_appends_valid_jsonl_records_concurrently(tmp_path: Path) -> None:
    store = RawEvidenceStore(tmp_path / "raw-evidence.jsonl", session_id="session-1")

    with ThreadPoolExecutor(max_workers=8) as executor:
        tuple(executor.map(lambda index: store.append(make_record(index=index)), range(100)))

    lines = store.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 100
    values = [json.loads(line) for line in lines]
    assert len({value["evidence_id"] for value in values}) == 100
    assert all(value["session_id"] == "session-1" for value in values)


def test_raw_evidence_payload_preserves_raw_path_without_content() -> None:
    secret = "TOP_SECRET=must-not-be-collected"
    record = RawEvidenceRecord(
        session_id="session-1",
        source=EvidenceSource.FILESYSTEM_WATCHER,
        record_type=EvidenceRecordType.FILESYSTEM_EVENT,
        captured_at=datetime.now(timezone.utc),
        observation_stage=ObservationStage.POST_ACTION,
        payload={
            "event_type": "modified",
            "src_path": r"C:\workspace\config.env",
            "is_directory": False,
        },
    )

    assert record.payload["src_path"] == r"C:\workspace\config.env"
    assert secret not in json.dumps(record.to_mapping(), ensure_ascii=False)
