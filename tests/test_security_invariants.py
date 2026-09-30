from dataclasses import replace

from aia import (
    NormalizationCompleteness,
    ObservationStage,
    Operation,
    ProcessIdentityStatus,
    SessionFinalizer,
)
from aia_app.presenters import action_view, incident_view
from tests.test_finalization import _session


def test_result_bundle_and_presenters_exclude_secret_and_full_tool_payload(tmp_path):
    session, store, action = _session(tmp_path)
    secret = "AIA_SECRET_CANARY=do-not-expose"
    tool_payload = f'{{"tool_name":"Read","content":"{secret}"}}'
    command_action = replace(
        action,
        action_id="secret-command-action",
        operation=Operation.EXECUTE,
        stage=ObservationStage.PRE_ACTION,
        target_kind="COMMAND",
        completeness=NormalizationCompleteness.COMPLETE,
        raw_command=tool_payload,
    )

    finalized = SessionFinalizer(evidence_store=store).finalize(
        session,
        process_end_status=ProcessIdentityStatus.PROCESS_GONE,
        actions=(command_action,),
    )
    bundle_text = "".join(
        path.read_text(encoding="utf-8")
        for path in finalized.bundle.result_directory.rglob("*")
        if path.is_file()
    )

    presenter_input = {
        "action_id": "secret-command-action",
        "operation": "EXECUTE",
        "policy_decision": "VIOLATION",
        "attribution_grade": "EXACT",
        "enforcement_action": "NONE",
        "execution_result": "NOT_ATTEMPTED",
        "target": {
            "target_kind": "COMMAND",
            "raw_command": tool_payload,
            "payload": tool_payload,
        },
    }
    presented = repr((action_view(presenter_input), incident_view(presenter_input)))

    assert secret not in bundle_text
    assert tool_payload not in bundle_text
    assert secret not in presented
    assert tool_payload not in presented
