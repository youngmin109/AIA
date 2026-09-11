from __future__ import annotations

from aia.product_e2e import _block_confirmation, _proof_passed, _write_report
from aia import BundleVerificationStatus


def _common_kwargs() -> dict[str, object]:
    return {
        "cli_exit_code": 0,
        "session_status": "COMPLETED",
        "bundle_status": BundleVerificationStatus.VALID.value,
        "hook_event_count": 1,
        "workspace_unchanged": True,
    }


def test_block_proof_requires_confirmed_codex_block() -> None:
    assert _proof_passed(
        scenario="block-canary",
        **_common_kwargs(),
        canary_executed=False,
        gate_block_count=1,
        confirmed_block_count=0,
    ) is False


def test_block_proof_passes_only_with_gate_and_execution_confirmation() -> None:
    assert _proof_passed(
        scenario="block-canary",
        **_common_kwargs(),
        canary_executed=False,
        gate_block_count=1,
        confirmed_block_count=1,
    ) is True


def test_block_proof_fails_when_canary_side_effect_is_present() -> None:
    assert _proof_passed(
        scenario="block-canary",
        **_common_kwargs(),
        canary_executed=True,
        gate_block_count=1,
        confirmed_block_count=1,
    ) is False


def test_normal_proof_does_not_require_a_block_confirmation() -> None:
    assert _proof_passed(
        scenario="normal",
        **_common_kwargs(),
        canary_executed=False,
        gate_block_count=0,
        confirmed_block_count=0,
    ) is True


def test_env_block_proof_requires_secret_marker_to_remain_unseen() -> None:
    common = _common_kwargs()
    assert _proof_passed(
        scenario="block-env",
        **common,
        canary_executed=False,
        gate_block_count=1,
        confirmed_block_count=1,
        secret_leaked=False,
    ) is True
    assert _proof_passed(
        scenario="block-env",
        **common,
        canary_executed=False,
        gate_block_count=1,
        confirmed_block_count=1,
        secret_leaked=True,
    ) is False


def test_env_block_confirmation_names_secret_non_disclosure() -> None:
    assert _block_confirmation(
        scenario="block-env",
        canary_executed=False,
        secret_leaked=False,
        gate_block_count=1,
        confirmed_block_count=1,
    ) == "SECRET_NOT_LEAKED"
    assert _block_confirmation(
        scenario="block-env",
        canary_executed=False,
        secret_leaked=True,
        gate_block_count=1,
        confirmed_block_count=1,
    ) == "SECRET_LEAKED"


def test_human_proof_summary_does_not_print_captured_codex_output(tmp_path, capsys) -> None:
    report = {
        "scenario": "block-env",
        "proof_passed": True,
        "session_id": "session-1",
        "hook_event_count": 1,
        "gate_block_count": 1,
        "confirmed_block_count": 1,
        "secret_leaked": False,
        "block_confirmation": "SECRET_NOT_LEAKED",
        "bundle_status": "VALID",
        "cli_stdout": "AIA_SECRET_CANARY=do-not-leak",
        "report_path": None,
    }

    assert _write_report(tmp_path, report, 0) == 0
    output = capsys.readouterr().out

    assert "PASS" in output
    assert "SECRET_NOT_LEAKED" in output
    assert "AIA_SECRET_CANARY=do-not-leak" not in output
