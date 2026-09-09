import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ["AIA_MVP_SRC"])
from aia import EnforcementGate, PreToolEnforcementAdapter
from aia.adapters import CodexHookAdapter, CodexPreToolPayload
from tests.test_enforcement import _gate_input

payload = json.load(sys.stdin)
native_payload = CodexPreToolPayload.from_mapping(payload)
with tempfile.TemporaryDirectory(prefix="aia-hook-gate-") as temp:
    gate_input, lease_manager = _gate_input(Path(temp))
    decision = PreToolEnforcementAdapter(EnforcementGate(lease_manager=lease_manager)).evaluate(gate_input)
    record = {
        "native_tool_name": native_payload.tool_name,
        "native_tool_use_id": native_payload.tool_use_id,
        "product_policy_decision": decision.gate_result.policy_decision.value,
        "product_attribution_grade": decision.gate_result.attribution_grade.value,
        "product_gate_decision": decision.gate_result.decision.value,
        "product_route": decision.gate_result.route.value,
        "product_action_before_confirmation": decision.gate_result.action.value,
        "product_execution_result_before_confirmation": decision.gate_result.execution_result.value,
        "response": decision.response.to_mapping(),
    }
    Path(os.environ["AIA_HOOK_LOG"]).write_text(json.dumps(record, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(decision.response.to_mapping(), ensure_ascii=False), flush=True)
