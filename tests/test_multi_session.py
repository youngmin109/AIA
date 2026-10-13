"""Several conversations at once: each in its own folder, up to the worker count."""

import pytest

from aia_app.protected_run import ApplicationValidationError
from aia_app.service import RunApplicationService


@pytest.fixture
def service(tmp_path):
    service = RunApplicationService(tmp_path / "control", max_workers=2)
    service._run = lambda record: None  # the worker would start Codex; not needed here
    yield service
    service.shutdown()


def _folder(tmp_path, *parts):
    path = tmp_path.joinpath("work", *parts)
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _start(service, workspace):
    return service.create_protected_run({"workspace": workspace, "task": "inspect"})["session_id"]


def test_two_folders_run_at_once_but_the_same_or_a_nested_folder_is_refused(service, tmp_path) -> None:
    first = _start(service, _folder(tmp_path, "shop"))
    assert _start(service, _folder(tmp_path, "blog"))

    for busy in (_folder(tmp_path, "shop"), _folder(tmp_path, "shop", "src"), _folder(tmp_path)):
        with pytest.raises(ApplicationValidationError, match="다른 대화"):
            _start(service, busy)
    # The folder check tells the new-run sheet before anything starts.
    assert service.validate_workspace(_folder(tmp_path, "shop", "src"))["busy"]["session_id"] == first
    assert service.validate_workspace(_folder(tmp_path, "docs"))["busy"] is None


def test_a_finished_run_frees_its_folder_and_its_slot(service, tmp_path) -> None:
    first = _start(service, _folder(tmp_path, "shop"))
    _start(service, _folder(tmp_path, "blog"))
    with pytest.raises(ApplicationValidationError, match="최대 2개"):
        _start(service, _folder(tmp_path, "docs"))

    service.registry.get(first).status = "COMPLETED"
    assert _start(service, _folder(tmp_path, "shop"))


def test_a_brief_windows_lock_on_the_status_file_does_not_degrade_the_run(service, tmp_path, monkeypatch) -> None:
    import aia_app.service as service_module

    session_id = _start(service, _folder(tmp_path, "shop"))
    record = service.registry.get(session_id)
    real_replace = service_module.os.replace
    calls = []

    def locked_twice(source, target):
        calls.append(target)
        if len(calls) <= 2:
            raise PermissionError("the file is being used by another process")
        return real_replace(source, target)

    monkeypatch.setattr(service_module.os, "replace", locked_twice)
    monkeypatch.setattr(service_module.time, "sleep", lambda seconds: None)
    service._persist_runtime_state(record)
    assert len(calls) == 3
    assert record.error is None and record.protection_state != "DEGRADED"

    calls.clear()
    monkeypatch.setattr(service_module.os, "replace", lambda source, target: (_ for _ in ()).throw(PermissionError("locked")))
    service._persist_runtime_state(record)
    assert record.error == "RUNTIME_STATE_PERSIST_FAILED"  # a lasting lock is still reported
