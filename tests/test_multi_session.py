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
