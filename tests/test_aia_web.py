from __future__ import annotations

from fastapi.testclient import TestClient
import importlib

from aia_web.app import create_app
from aia_app.service import RunApplicationService


class FakeService:
    def __init__(self):
        self.created_payloads = []

    def policy_profiles(self):
        return [{"value": "BASIC_DEVELOPMENT", "label": "Basic Development"}]

    def preview_policy(self, payload):
        if payload.get("path") == "invalid":
            raise ValueError("policy preview failed")
        return {
            "policy_id": "basic",
            "policy_version": "1.0",
            "profile": payload.get("policy_profile", "BASIC_DEVELOPMENT"),
            "operation": payload["operation"],
            "target_kind": "COMMAND" if payload["operation"] == "EXECUTE" else "PATH",
            "policy_decision": "VIOLATION",
            "operation_effect": "DENY",
            "asset_type": "SECRET",
            "matched_rule_ids": ["secret-files"],
            "audit_record": False,
            "reason": None,
            "limitation": None,
        }

    def list_runs(self):
        return []

    def preflight(self):
        return {
            "ready": True,
            "readiness_code": "READY",
            "next_step": "Workspace와 정책을 선택해 보호 실행을 시작할 수 있습니다.",
            "checks": [
                {
                    "name": "codex_executable",
                    "label": "Codex 실행 파일",
                    "ok": True,
                    "detail": "codex.exe",
                }
            ],
            "hook_trust": {
                "status": "MANUAL_REVIEW_REQUIRED",
                "detail": "Codex에서 /hooks를 검토하세요.",
            },
            "hook_activation": {
                "status": "CURRENTLY_VERIFIED",
                "detail": "현재 Hook이 검증되었습니다.",
            },
            "codex_hook_trust": {
                "available": True,
                "hooks": [
                    {"event": "preToolUse", "trust_status": "MODIFIED"},
                    {"event": "postToolUse", "trust_status": "UNTRUSTED"},
                ],
            },
            "next_steps": [],
        }

    def create_protected_run(self, payload):
        self.created_payloads.append(payload)
        if payload.get("workspace") == "invalid":
            raise ValueError("workspace validation failed")
        return {"redirect_url": "/runs/run-1", "session_id": "run-1", "status": "CREATED"}

    def validate_workspace(self, path):
        if path == "invalid":
            raise ValueError("workspace validation failed")
        return {"valid": True, "exists": True, "is_directory": True, "canonical_path": path}

    def get_run_status(self, session_id):
        if session_id != "run-1":
            raise KeyError(session_id)
        return {
            "checkpoint": "READY",
            "error": None,
            "incident_count": 1,
            "latest_actions": [],
            "lease": "ACTIVE",
            "mode": "ENFORCE",
            "phase": "RUNNING",
            "protection": {"state": "ACTIVE_VERIFIED", "hook_events": 1, "hook_broker": "HEALTHY"},
            "stop": {"requested": False, "error": None},
            "policy": {"id": "basic", "profile": "BASIC_DEVELOPMENT", "version": "1.0"},
            "result_available": True,
            "evidence_summary": {
                "available": True,
                "filesystem_events": 2,
                "pretool_events": 1,
                "posttool_events": 1,
                "sensor_health_events": 1,
            },
            "sensor_health": {"FILESYSTEM_WATCHER": "HEALTHY"},
            "session": {"agent": "codex", "status": "RUNNING", "session_id": session_id, "workspace": "C:/workspace"},
        }

    def get_terminal_status(self, session_id):
        if session_id != "run-1":
            raise KeyError(session_id)
        return {
            "mode": "web_terminal",
            "status": "RUNNING",
            "pid": 1234,
            "rows": 32,
            "cols": 120,
            "started_at": None,
            "ended_at": None,
            "error": None,
        }

    def drain_terminal_output(self, session_id):
        if session_id != "run-1":
            raise KeyError(session_id)
        return []

    def read_terminal_output(self, session_id, *, after_sequence=0):
        if session_id != "run-1":
            raise KeyError(session_id)
        assert after_sequence >= 0
        return []

    def send_terminal_input(self, session_id, value):
        if session_id != "run-1":
            raise KeyError(session_id)
        return {"accepted": True, "session_id": session_id}

    def submit_terminal_input(self, session_id):
        if session_id != "run-1":
            raise KeyError(session_id)
        return {"accepted": True, "session_id": session_id}

    def resize_terminal(self, session_id, rows, cols):
        if session_id != "run-1":
            raise KeyError(session_id)
        return {"accepted": True, "session_id": session_id, "rows": rows, "cols": cols}

    def get_run_actions(self, session_id):
        return [
            {
                "action_id": "a1",
                "operation": "DELETE",
                "policy_effect": "VIOLATION",
                "attribution_class": "PROCESS",
                "enforcement_action": "REFUSE",
                "execution_result": "NOT_ATTEMPTED",
                "target": {"display": "C:/workspace/file.txt"},
            }
        ]

    def get_incidents(self, session_id):
        return [self.get_incident(session_id, "a1")]

    def get_incident(self, session_id, action_id):
        return {
            "action_id": action_id,
            "operation": "DELETE",
            "policy_effect": "VIOLATION",
            "attribution_class": "PROCESS",
            "enforcement_action": "REFUSE",
            "execution_result": "NOT_ATTEMPTED",
            "summary": "DELETE was classified as VIOLATION.",
            "reason": "Hook ingress is unverified.",
            "proof": "Normalized action and evidence identifiers are available.",
            "target": {"display": "C:/workspace/file.txt"},
        }

    def get_result(self, session_id):
        return {
            "bundle_status": "VALID",
            "launch_mode": "web_terminal",
            "session_status": "COMPLETED",
            "recovery_status": "RESTORED",
            "integrity_status": "VERIFIED",
            "policy_id": "basic",
            "policy_version": "1.0",
            "actions": self.get_run_actions(session_id),
            "sensor_summary": [
                {
                    "sensor": "AGENT_HOOK",
                    "runtime_health_before_stop": "HEALTHY",
                    "final_sensor_state": "STOPPED",
                },
                {
                    "sensor": "FILESYSTEM_WATCHER",
                    "runtime_health_before_stop": "HEALTHY",
                    "final_sensor_state": "STOPPED",
                },
                {
                    "sensor": "PROCESS_RUNTIME",
                    "runtime_health_before_stop": "HEALTHY",
                    "final_sensor_state": "STOPPED",
                },
            ],
            "limitations": ["Local console does not provide remote access."],
        }

    def get_report(self, session_id):
        return "# AIA Security Report\n"

    def get_result_json(self, session_id):
        return b'{"bundle_status":"VALID"}'

    def request_stop(self, session_id):
        if session_id != "run-1":
            raise KeyError(session_id)
        return {"accepted": True, "session_id": session_id, "status": "STOP_REQUESTED"}

    def reconcile_orphaned_run(self, session_id):
        if session_id != "run-1":
            raise KeyError(session_id)
        return {
            "reconciled": True,
            "session_id": session_id,
            "reason": "ORPHAN_RECONCILED_AFTER_ROOT_CHECK",
        }

    def get_raw_evidence(self, session_id):
        return [{"evidence_id": "e1", "payload_keys": ["operation"]}]

    def shutdown(self, wait=True):
        return None


def test_console_routes_render_and_keep_raw_secrets_out_of_html() -> None:
    client = TestClient(create_app(FakeService()))
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert 'rel="icon" type="image/svg+xml"' in dashboard.text
    favicon = client.get("/static/favicon.svg")
    assert favicon.status_code == 200
    assert favicon.text.startswith("<svg")
    assert "보호 상태를 한눈에 확인하세요" in dashboard.text

    new_run = client.get("/new")
    assert new_run.status_code == 200
    assert "보호 실행 시작" in new_run.text
    assert "작업 폴더 선택" in new_run.text
    assert 'data-run-step="1"' in new_run.text
    assert 'data-run-step="4"' in new_run.text
    assert "updateRunProgress" in new_run.text
    assert "AIA는 실제 도구 요청을 관찰·통제합니다" in new_run.text
    assert "Codex 설정 Trust 상태" in new_run.text
    assert "실제 Hook 연결 검증" in new_run.text
    assert "현재 연결 증명" in new_run.text
    assert "현재 Protected Run에 Hook이 연결됐다는 증명과는 별개입니다" in new_run.text
    assert "preToolUse=MODIFIED" in new_run.text
    assert 'id="readiness-code">READY' in new_run.text
    assert "Workspace와 정책을 선택해 보호 실행을 시작할 수 있습니다." in new_run.text
    assert "빠른 정책 확인 예시" in new_run.text
    assert 'data-preview-target=".env"' in new_run.text
    assert "핵심 코드 삭제" in new_run.text
    assert "previewPresets" in new_run.text
    assert "현재 보호 범위" in new_run.text
    assert "MCP" in new_run.text
    assert "aliases=Edit, Write" in new_run.text
    assert "작업 방식" in new_run.text
    assert "Codex 화면" in new_run.text
    assert '<details class="panel policy-editor-panel">' in new_run.text
    assert '<details class="panel capability-panel">' in new_run.text
    assert "정책 만들기" in new_run.text
    assert "실행 설정" in new_run.text
    assert "terminalSurfaceInputs" in new_run.text
    assert "runSubmissionInProgress" in new_run.text
    assert 'id="workspace-status"' in new_run.text
    assert "validateWorkspacePath" in new_run.text
    assert "updateRunSubmitState" in new_run.text
    assert 'id="run-submit-hint"' in new_run.text
    assert "존재하는 Workspace 경로를 확인하면 실행할 수 있습니다" in new_run.text
    assert "보호 실행 준비 중" in new_run.text
    assert "is-busy" in new_run.text
    assert "new-run-page" in new_run.text
    assert 'id="jump-to-run"' in new_run.text
    assert 'id="run-settings"' in new_run.text
    assert 'id="preflight-next-steps"' in new_run.text
    assert 'id="preflight-refresh-status"' in new_run.text
    assert "setButtonBusy" in new_run.text
    assert "cache: 'no-store'" in new_run.text
    assert new_run.text.index('id="run-settings"') < new_run.text.index("정책 미리보기")
    assert new_run.text.index("정책 미리보기") < new_run.text.index("정책 만들기")
    assert "Strict Validation" in new_run.text
    assert "실제 Hook 연결 검증" in new_run.text
    assert "Hook 연결 다시 검증" in new_run.text
    assert "activationVerified" in new_run.text
    assert "verifyHookButton.dataset.idleLabel" in new_run.text
    assert 'id="preflight-sensor-summary"' in new_run.text
    assert 'id="preflight-sensor-hook-status"' in new_run.text
    assert "실행 시 시작" in new_run.text
    assert "별도 Windows 터미널에서 Codex 열기" in new_run.text
    assert client.get("/api/preflight").json()["ready"] is True
    assert client.get("/api/capabilities").json()["schema_version"] == "aia-capabilities-v1"
    assert client.get("/api/workspaces/validate", params={"path": "C:/workspace"}).json()["valid"] is True
    created = client.post("/api/runs", json={"workspace": "C:/workspace", "task": "inspect"})
    assert created.status_code == 202
    assert created.json()["redirect_url"] == "/runs/run-1"
    live = client.get("/runs/run-1")
    assert live.status_code == 200
    assert "보호 실행 상태" in live.text
    assert 'id="filesystem-event-count">2건' in live.text
    assert "Hook Broker" in live.text
    assert "실시간 센서 상태" in live.text
    assert 'id="event-timeline"' in live.text
    assert "HEALTHY" in live.text
    workbench = client.get("/runs/run-1/workbench")
    assert workbench.status_code == 200
    assert "page-shell-workbench" in workbench.text
    assert "Codex 작업창" in workbench.text
    assert "보안 관찰" in workbench.text
    assert 'id="protection-state-note"' in workbench.text
    assert "최근 이벤트" in workbench.text
    assert 'id="workbench-guidance"' in workbench.text
    assert 'id="workbench-guidance-title"' in workbench.text
    assert 'id="workbench-guidance-detail"' in workbench.text
    assert 'id="workbench-guidance-owner"' in workbench.text
    assert "현재 상태" in workbench.text
    assert 'aria-label="실행 요약"' in workbench.text
    assert workbench.text.index('aria-label="Workbench 바로가기"') < workbench.text.index('aria-label="실행 요약"')
    assert workbench.text.index('id="terminal-panel"') < workbench.text.index('aria-label="실행 요약"')
    assert 'aria-label="Workbench 바로가기"' in workbench.text
    assert 'data-workbench-jump="terminal-panel"' in workbench.text
    assert 'data-workbench-jump="security-panel"' in workbench.text
    assert 'data-workbench-jump="evidence-chain-panel"' in workbench.text
    assert 'data-workbench-jump="sensor-evidence-panel"' in workbench.text
    assert "IntersectionObserver" in workbench.text
    assert 'id="summary-protection"' in workbench.text
    assert 'id="summary-sensors"' in workbench.text
    assert 'id="summary-incidents"' in workbench.text
    assert "정상 관찰" in workbench.text
    assert "확인 필요" in workbench.text
    assert "Workspace 신뢰 확인이 필요합니다." in workbench.text
    assert "Codex가 요청을 처리하고 있습니다." in workbench.text
    assert "Codex가 다음 작업을 기다리고 있습니다." in workbench.text
    assert "실행이 끝났습니다. 결과를 확인하세요." in workbench.text
    assert "updateWorkbenchGuidance" in workbench.text
    assert "statusPollFailures >= 2" in workbench.text
    assert "updateWorkbenchGuidance();" in workbench.text
    assert "마지막 이벤트" in workbench.text
    assert "마지막 출력 수신" in workbench.text
    assert "화면 갱신" in workbench.text
    assert 'id="event-count"' in workbench.text
    assert "Glass-box" in workbench.text
    assert "실행 흐름" in workbench.text
    assert "보호 준비" in workbench.text
    assert 'id="workbench-flow"' in workbench.text
    assert 'data-flow-step="1"' in workbench.text
    assert 'data-flow-step="4"' in workbench.text
    assert "statusClass" in workbench.text
    assert "protectionClass" in workbench.text
    assert "protectionNote" in workbench.text
    assert "행위 관찰 전" in workbench.text
    assert "도구 요청 대기 중" in workbench.text
    assert "ABORTED_VERIFIED: '중지 · 검증됨'" in workbench.text
    assert "실행이 중지됐고 수집된 보호 증거와 결과를 검증했습니다." in workbench.text
    assert "현재 Workbench" in workbench.text
    assert 'id="terminal-input-proxy"' in workbench.text
    assert 'id="terminal-input-form"' in workbench.text
    assert 'id="terminal-send"' in workbench.text
    assert 'id="terminal-activity"' in workbench.text
    assert 'id="terminal-connection"' in workbench.text
    assert 'id="terminal-last-output"' in workbench.text
    assert "재연결 중" in workbench.text
    assert "terminalClosed" in workbench.text
    assert "formatOutputAge" in workbench.text
    assert "terminalInputForm" in workbench.text
    assert "activityMode" in workbench.text
    assert "awaitingResponse" in workbench.text
    assert "응답 대기 중" in workbench.text
    assert "updateTerminalInputState" in workbench.text
    assert "submitTerminalLine" in workbench.text
    assert "SUBMIT_SETTLE_MS = 250" in workbench.text
    assert "Codex에 질문을 제출하는 중입니다." in workbench.text
    assert 'id="terminal-action"' in workbench.text
    assert "신뢰하고 계속" in workbench.text
    assert "TRUST_DIRECTORY" in workbench.text
    assert "Workspace 신뢰 확인을 기다리고 있습니다." in workbench.text
    assert "차단 응답 전송" in workbench.text
    assert "실행 확인 중" in workbench.text
    assert "도구 실행 여부 확인 중" in workbench.text
    assert "실행 확인 전" in workbench.text
    assert "실행 여부 미확인" in workbench.text
    assert "센서가 관찰하면 여기에 표시됩니다" in workbench.text
    assert "eventSummaryLabel(incident.summary)" in workbench.text
    assert "statusPollFailures" in workbench.text
    assert "연결 확인 필요" in workbench.text
    assert 'id="refresh-status"' in workbench.text
    assert "상태 새로고침" in workbench.text
    assert "terminalSocketConnected" in workbench.text
    assert "terminalSocketEverConnected" in workbench.text
    assert "terminalScreen.reset()" in workbench.text
    assert "terminalOutput.classList.remove('terminal-closed')" in workbench.text
    assert "stopButton.hidden = terminalEnded || orphaned;" in workbench.text
    assert "button.classList.add('is-busy')" in workbench.text
    assert "button.setAttribute('aria-busy', 'true')" in workbench.text
    assert "Workbench 터미널 연결이 끊겨 다시 연결하는 중입니다." in workbench.text
    assert "중지 요청 중…" in workbench.text
    assert "STOPPING" in workbench.text
    assert "item.execution_result || ''" in workbench.text
    assert "item.execution_observed ? 'observed'" in workbench.text
    assert "execution_observed" in workbench.text
    assert "실행 관찰됨" in workbench.text
    assert 'id="incident-note"' in workbench.text
    assert "Codex의 설명만으로는 실제 실행 여부를 확정하지 않습니다." in workbench.text
    assert "실행 확인 중" in workbench.text
    assert 'data-event-filter="ALL"' in workbench.text
    assert 'data-event-filter="ACTION"' in workbench.text
    assert 'data-event-filter="SENSOR"' in workbench.text
    assert "현재 필터에 해당하는 이벤트가 없습니다." in workbench.text
    assert 'id="evidence-chain-panel"' in workbench.text
    assert '<details id="evidence-chain-panel"' in workbench.text
    assert '<details id="sensor-evidence-panel"' in workbench.text
    assert "workbench-details-summary" in workbench.text
    assert "if (target?.tagName === 'DETAILS') target.open = true" in workbench.text
    assert 'id="evidence-chains"' in workbench.text
    assert "renderEvidenceChains" in workbench.text
    assert "selectedItem && !recentItems.some" in workbench.text
    assert "· 선택됨" in workbench.text
    assert "원시 증거 → 표준 행위 → 정책 → 귀속 → 집행 → 복구 → 무결성" in workbench.text
    assert "Codex는 실행 중이며 Workbench 연결을 기다리고 있습니다." in workbench.text
    assert "AIA 보호 연결이 끊겼습니다." in workbench.text
    assert "고아 실행 정리 확인" in workbench.text
    assert "Codex 작업창 시작이 지연되고 있습니다. 연결 상태를 확인하세요." in workbench.text
    assert "terminalEnded && ['UNKNOWN', 'NOT_ATTACHED'].includes(value)" in workbench.text
    assert "setTerminalActivity('STOPPED', 'Codex 작업창이 종료되었습니다.')" in workbench.text
    assert "chain-sensor-link" in workbench.text
    assert "RUN_OBSERVED" in workbench.text
    assert "실행 관찰" in workbench.text
    assert "selectEvidenceChain" in workbench.text
    assert "if (panel) panel.open = true" in workbench.text
    assert 'id="sensor-evidence-panel"' in workbench.text
    assert 'id="sensor-evidence-timeline"' in workbench.text
    assert 'data-sensor-focus="AGENT_HOOK"' in workbench.text
    assert 'data-sensor-focus="FILESYSTEM_WATCHER"' in workbench.text
    assert 'data-sensor-focus="PROCESS_RUNTIME"' in workbench.text
    assert "focusSensorEvidence" in workbench.text
    assert "panel.scrollIntoView({behavior: 'smooth', block: 'start'})" in workbench.text
    assert "renderEvidenceTimeline" in workbench.text
    assert 'data-evidence-filter="ALL"' in workbench.text
    assert 'data-evidence-filter="AGENT_HOOK"' in workbench.text
    assert 'data-evidence-filter="FILESYSTEM_WATCHER"' in workbench.text
    assert 'data-evidence-filter="PROCESS_RUNTIME"' in workbench.text
    assert "lastRenderedChainKey" in workbench.text
    assert "lastRenderedEvidenceKey" in workbench.text
    assert "evidenceFilterButtons" in workbench.text
    assert "eventFilterButtons" in workbench.text
    assert "eventFilter === 'SENSOR'" in workbench.text
    assert "eventFilter === 'ACTION'" in workbench.text
    assert "bindChainSelectors" in workbench.text
    assert "sensor-evidence-row ${linked ? 'is-linked'" in workbench.text
    assert "data-chain-select" in workbench.text
    assert "responseStartedAt" in workbench.text
    assert "terminalAction !== 'TRUST_DIRECTORY'" in workbench.text
    assert "먼저 “신뢰하고 계속”을 눌러주세요." in workbench.text
    assert "응답 완료 · 다음 작업을 입력할 수 있습니다." in workbench.text
    assert "이번 작업에는 파일·명령 도구 요청이 없어 Hook 이벤트가 없습니다." in workbench.text
    assert "이번 작업에는 도구 요청이 없어 Hook Evidence가 없습니다." in workbench.text
    assert 'id="terminal-examples"' in workbench.text
    assert "예시를 눌러도 자동 실행되지 않습니다." in workbench.text
    assert "data-terminal-example" in workbench.text
    assert "terminalOutput.setAttribute('aria-busy'" in workbench.text
    assert "workingVisible" in workbench.text
    assert "composerVisible" in workbench.text
    assert "compositionstart" in workbench.text
    assert "compositionend" in workbench.text
    assert "cells[row]?.[col] ?? ' '" in workbench.text
    assert "submitAfterComposition" in workbench.text
    assert "pendingSubmission" in workbench.text
    assert "restorePendingSubmission" in workbench.text
    assert "입력 내용을 확인한 뒤 다시 시도하세요." in workbench.text
    assert "Codex 터미널이 연결되지 않아 전송하지 못했습니다." in workbench.text
    assert "data: value" in workbench.text
    assert "type:'submit'" in workbench.text
    assert "terminalScreen" in workbench.text
    assert "scrollTop" in workbench.text
    assert "scrollBottom" in workbench.text
    assert "reverseIndex" in workbench.text
    assert "insertLines" in workbench.text
    assert "deleteLines" in workbench.text
    assert "cellWidth" in workbench.text
    assert "codePointAt" in workbench.text
    assert "requestAnimationFrame" in workbench.text
    assert "SUPER_SECRET" not in workbench.text
    assert client.get("/api/runs/run-1").json()["phase"] == "RUNNING"
    assert client.post("/api/runs/run-1/stop").status_code == 202
    assert client.post("/api/runs/missing/stop").status_code == 404
    assert client.post("/api/runs/run-1/reconcile").status_code == 200
    assert client.post("/api/runs/missing/reconcile").status_code == 404
    assert client.get("/api/runs/run-1/actions").json()["actions"][0]["operation"] == "DELETE"
    incident = client.get("/runs/run-1/incidents/a1")
    assert incident.status_code == 200
    assert "PROCESS" in incident.text
    assert "정책 위반은 확인됐지만" in incident.text
    result = client.get("/runs/run-1/result")
    assert result.status_code == 200
    assert "VERIFIED" in result.text
    assert "런타임 센서 상태" in result.text
    assert "PROCESS_RUNTIME" in result.text
    assert "현재 Workbench" in result.text
    assert "Workbench로 돌아가기" in result.text
    assert "유효 · 검증됨" in result.text
    assert result.text.index("Hook Sensor") < result.text.index("File Sensor") < result.text.index("Process Sensor")
    assert "이번 보호 실행에서 확인된 내용" in result.text
    assert "보호 상태" in result.text
    assert "다음 작업" in result.text
    assert "새 보호 실행 시작" in result.text
    assert 'class="is-active" aria-current="page" href="/runs"' in result.text
    assert "정책 위반" in result.text
    assert "실행하지 않음" in result.text
    assert 'href="/new">새 보호 실행</a>' in result.text
    assert 'aria-label="결과 바로가기"' in result.text
    assert 'id="sensor-results"' in result.text
    assert 'id="event-timeline"' in result.text
    assert 'href="#evidence-chain">증거</a>' in result.text
    assert '<details id="evidence-chain" class="panel result-details">' in result.text
    assert '<details id="sensor-evidence-timeline" class="panel result-details">' in result.text
    assert '<details id="action-results" class="panel result-details">' in result.text
    assert "openResultDetailFromHash" in result.text
    assert 'id="evidence-chain"' in result.text
    assert "result-evidence-chains" in result.text
    assert "행위에 직접 연결된 센서와 같은 Run에서 독립적으로 관찰된 센서" in result.text
    assert "증거 상태 범례" in result.text
    assert "직접 연결" in result.text
    assert "실행 관찰" in result.text
    assert 'id="sensor-evidence-timeline"' in result.text
    assert 'id="decision-summary"' in result.text
    assert 'class="result-section-nav"' in result.text
    assert 'setResultSectionActive' in result.text
    assert 'resultSectionObserver' in result.text
    assert 'id="recovery-results"' in result.text
    assert 'id="action-results"' in result.text
    assert client.get("/runs/run-1/report").headers["content-type"].startswith("text/markdown")
    assert client.get("/runs/run-1/raw-evidence").json()["evidence"][0]["evidence_id"] == "e1"
    assert client.get("/runs/run-1/result.json").json()["bundle_status"] == "VALID"
    assert "SUPER_SECRET" not in result.text


def test_result_page_explains_degraded_protection_separately_from_valid_bundle() -> None:
    service = FakeService()
    result_data = service.get_result("run-1")
    result_data["protection_state"] = "COMPLETED_DEGRADED"
    service.get_result = lambda session_id: result_data
    client = TestClient(create_app(service))

    result = client.get("/runs/run-1/result")

    assert result.status_code == 200
    assert "Evidence Bundle은 유효 · 검증됨이지만 보호 상태가 완전히 검증되지 않았습니다." in result.text
    assert "완료 · 일부 확인" in result.text


def test_workbench_terminal_socket_accepts_input_and_resize() -> None:
    client = TestClient(create_app(FakeService()))
    with client.websocket_connect("/api/runs/run-1/terminal") as websocket:
        first = websocket.receive_json()
        assert first["type"] == "status"
        assert first["status"] == "RUNNING"
        websocket.send_json({"type": "input", "data": "hello"})
        accepted = websocket.receive_json()
        assert accepted["type"] == "accepted"
        assert accepted["action"] == "input"
        websocket.send_json({"type": "submit"})
        accepted = websocket.receive_json()
        assert accepted["type"] == "accepted"
        assert accepted["action"] == "submit"
        websocket.send_json({"type": "resize", "rows": 40, "cols": 140})
        accepted = websocket.receive_json()
        assert accepted["type"] == "accepted"
        assert accepted["action"] == "resize"
        assert accepted["cols"] == 140


def test_workbench_terminal_socket_replays_bounded_output_after_reconnect() -> None:
    class ReplayService(FakeService):
        _output = [
            {"type": "output", "sequence": 1, "data": "first", "recorded_at": "2026-01-01T00:00:00+00:00"},
            {"type": "output", "sequence": 2, "data": "second", "recorded_at": "2026-01-01T00:00:01+00:00"},
        ]

        def read_terminal_output(self, session_id, *, after_sequence=0):
            super().read_terminal_output(session_id, after_sequence=after_sequence)
            return [item for item in self._output if item["sequence"] > after_sequence]

    client = TestClient(create_app(ReplayService()))
    with client.websocket_connect("/api/runs/run-1/terminal") as first_connection:
        assert first_connection.receive_json()["sequence"] == 1
        assert first_connection.receive_json()["sequence"] == 2
        assert first_connection.receive_json()["type"] == "status"

    with client.websocket_connect("/api/runs/run-1/terminal") as second_connection:
        assert second_connection.receive_json()["sequence"] == 1
        assert second_connection.receive_json()["sequence"] == 2


def test_console_can_request_hook_verification_without_changing_trust(monkeypatch) -> None:
    def fake_verify(control_root, *, timeout=180.0):
        assert timeout == 180.0
        return {"verified": True, "reason": "SESSION_BOUND_HOOK_EVENT_OBSERVED"}, 200

    web_module = importlib.import_module("aia_web.app")
    monkeypatch.setattr(web_module, "_run_hook_verification", fake_verify)
    client = TestClient(create_app(FakeService()))

    response = client.post("/api/hook/verify")

    assert response.status_code == 200
    assert response.json()["verified"] is True


def test_console_dashboard_explains_readiness_scope_and_recent_runs() -> None:
    client = TestClient(create_app(FakeService()))

    dashboard = client.get("/dashboard")

    assert dashboard.status_code == 200
    assert "보호 상태를 한눈에 확인하세요" in dashboard.text
    assert "status-success" in dashboard.text
    assert "실행 준비" in dashboard.text
    assert "Codex Hook Trust" in dashboard.text
    assert 'id="dashboard-sensors"' in dashboard.text
    assert "Hook Sensor" in dashboard.text
    assert "File Sensor" in dashboard.text
    assert "Process Sensor" in dashboard.text
    assert "실행 시 활성화" in dashboard.text
    assert "실제 Session-bound Hook Event 확인됨" in dashboard.text
    assert "대화형 보호 세션" not in dashboard.text
    assert "준비 상태 확인" in dashboard.text
    assert "Workbench에서 작업" in dashboard.text
    assert "오른쪽 보안 관찰 · 결과 보기" in dashboard.text
    assert "현재 실행 중인 보호 세션이 없습니다" in dashboard.text
    assert 'aria-label="AIA 주요 메뉴"' in dashboard.text
    assert 'aria-current="page"' in dashboard.text
    assert 'id="dashboard-primary-action"' in dashboard.text
    assert 'id="dashboard-primary-action" class="button primary" href="/new">새 보호 실행</a>' in dashboard.text
    assert 'id="dashboard-current-run"' in dashboard.text
    assert 'id="dashboard-run-count"' in dashboard.text
    assert 'id="dashboard-sync-status"' in dashboard.text
    assert 'id="dashboard-recent-runs"' in dashboard.text
    assert 'id="dashboard-recent-empty"' in dashboard.text
    assert "refreshDashboard" in dashboard.text
    assert "renderDashboardRecentRuns" in dashboard.text
    assert "window.setInterval(refreshDashboard, 5000)" in dashboard.text
    assert "Bash" in dashboard.text
    assert "Edit·Write → apply_patch" in dashboard.text
    assert "아직 보호 실행 기록이 없습니다" in dashboard.text


def test_run_history_and_dashboard_link_workbench_runs_to_workbench() -> None:
    service = FakeService()
    service.list_runs = lambda: [{
        "session_id": "run-1",
        "status": "RUNNING",
        "workspace": "C:/workspace",
        "policy": {"id": "basic", "version": "1.0"},
        "incident_count": 0,
        "bundle_status": "PENDING",
        "protection_state": "ACTIVE_UNVERIFIED",
        "launch_mode": "web_terminal",
        "result_url": "/runs/run-1/result",
        "created_at": "2026-01-01T00:00:00+00:00",
    }]
    client = TestClient(create_app(service))

    dashboard = client.get("/")
    history = client.get("/runs")

    assert 'href="/runs/run-1/workbench"' in dashboard.text
    assert 'href="/runs/run-1/workbench"' in history.text
    assert "보호 실행이 진행 중입니다" in dashboard.text
    assert "Workbench 열기" in dashboard.text
    assert 'id="dashboard-primary-action" class="button primary" href="/runs/run-1/workbench">Workbench 열기</a>' in dashboard.text
    assert "결과 검증" in dashboard.text
    assert "행위 관찰 전" in dashboard.text
    assert "사건" in dashboard.text
    assert "Workbench 열기" in history.text
    assert "전체 실행" in history.text
    assert 'href="/runs"' in history.text
    assert 'class="is-active" aria-current="page" href="/runs"' in history.text
    assert 'id="history-result-count"' in history.text
    assert "정상 완료" in history.text
    assert "완료 · 검증됨" in history.text
    assert "필터 초기화" in history.text
    assert "filterIds" in history.text
    assert "1건 표시 / 1건 전체" in history.text
    assert "실행 기록 요약" in history.text
    assert "현재 진행 중" in history.text
    assert "시작 시각" in history.text
    assert "history-time" in history.text
    assert "Result Bundle VALID" in history.text
    assert "중지 처리 중" in history.text
    assert "보호 실패" in history.text
    assert "READY_UNVERIFIED" in history.text
    assert "실행 중 · 행위 관찰 전" in history.text
    assert 'id="history-pagination"' in history.text
    assert 'id="history-prev"' in history.text
    assert 'id="history-next"' in history.text
    assert "historyPageSize = 20" in history.text
    assert "/runs/run-1/result" not in history.text


def test_dashboard_does_not_present_orphaned_runtime_as_current_run() -> None:
    service = FakeService()
    service.list_runs = lambda: [{
        "session_id": "stale-run",
        "status": "RUNNING",
        "workspace": "C:/workspace",
        "policy": {"id": "basic", "version": "1.0"},
        "incident_count": 0,
        "bundle_status": "PENDING",
        "protection_state": "ORPHANED_DEGRADED",
        "run_classification": "LIVE_PROTECTED_RUN",
        "runtime_reconciliation": {
            "status": "STALE_PROCESS_GONE",
            "orphaned": True,
            "action": "REVIEW_AND_RESTART",
        },
        "launch_mode": "web_terminal",
        "created_at": "2026-01-01T00:00:00+00:00",
    }]
    client = TestClient(create_app(service))

    dashboard = client.get("/")

    assert "현재 실행 중인 보호 세션이 없습니다" in dashboard.text
    assert "보호 실행이 진행 중입니다" not in dashboard.text
    assert "이전 보호 실행이 현재 연결되어 있지 않습니다" in dashboard.text
    assert 'id="dashboard-stale-run"' in dashboard.text
    assert 'href="/runs/stale-run"' in dashboard.text


def test_console_maps_validation_errors_to_bad_request() -> None:
    client = TestClient(create_app(FakeService()))
    response = client.post("/api/runs", json={"workspace": "invalid", "task": "inspect"})
    assert response.status_code == 400
    assert "workspace validation failed" in response.json()["error"]


def test_console_policy_preview_is_non_executing_and_returns_decision() -> None:
    client = TestClient(create_app(FakeService()))

    response = client.post(
        "/api/policy/preview",
        json={"operation": "READ", "path": ".env"},
    )

    assert response.status_code == 200
    assert response.json()["policy_decision"] == "VIOLATION"
    assert response.json()["asset_type"] == "SECRET"

    invalid = client.post(
        "/api/policy/preview",
        json={"operation": "READ", "path": "invalid"},
    )
    assert invalid.status_code == 400
    assert "policy preview failed" in invalid.json()["error"]


def test_console_supports_session_first_interactive_run() -> None:
    service = FakeService()
    client = TestClient(create_app(service))

    page = client.get("/new")
    assert page.status_code == 200
    assert "대화형 보호 세션" in page.text
    assert "세션 안에서 원하는 작업을 입력합니다" in page.text

    created = client.post(
        "/api/runs",
        json={"workspace": "C:/workspace", "interactive": True},
    )
    assert created.status_code == 202
    assert service.created_payloads[-1]["interactive"] is True


def test_console_reveals_custom_policy_path_for_custom_profile() -> None:
    service = FakeService()
    service.policy_profiles = lambda: [
        {"value": "BASIC_DEVELOPMENT", "label": "Basic Development"},
        {"value": "CUSTOM", "label": "사용자 정책"},
    ]
    client = TestClient(create_app(service))

    page = client.get("/new")

    assert page.status_code == 200
    assert 'option value="CUSTOM"' in page.text
    assert "updateCustomPolicyField" in page.text
    assert "CUSTOM" in page.text
    assert "정책 미리보기" in page.text
    assert "/api/policy/preview" in page.text


def test_console_policy_editor_api_validates_and_saves_strict_document(tmp_path) -> None:
    service = RunApplicationService(tmp_path / "control")
    client = TestClient(create_app(service))
    document = {
        "정책명": "웹 사용자 정책",
        "정책ID": "web-policy",
        "정책버전": "1.0",
        "스키마버전": "1",
        "기본효과": "기록",
        "규칙": [
            {
                "규칙ID": "secret-read",
                "우선순위": 100,
                "자산유형": "비밀정보",
                "경로패턴": [".env"],
                "행위효과": {"읽기": "금지"},
            }
        ],
    }
    try:
        validated = client.post("/api/policy/validate", json={"document": document})
        assert validated.status_code == 200
        assert validated.json()["rule_count"] == 1
        saved = client.post(
            "/api/policy/save",
            json={"document": document, "path": str(tmp_path / "web-policy.json")},
        )
        assert saved.status_code == 200
        assert saved.json()["path"].endswith("web-policy.json")
        invalid = client.post(
            "/api/policy/validate",
            json={"document": {**document, "알수없는키": True}},
        )
        assert invalid.status_code == 400
    finally:
        service.shutdown()
