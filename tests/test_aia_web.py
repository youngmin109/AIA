from __future__ import annotations

from fastapi.testclient import TestClient
import importlib

from aia_web.app import _coalesce_terminal_output, _console_cli_prefix, _dashboard_run_view, create_app
from aia_app.service import RunApplicationService
from aia.codex_installation import CodexHookInstaller


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

    def preflight(self, *, runs=None):
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


def test_dashboard_run_view_prioritizes_user_runs_without_dropping_diagnostics() -> None:
    runs = [
        {
            "session_id": "diagnostic",
            "workspace": "C:\\Users\\tester\\AppData\\Local\\Temp\\aia-hook-verify-abcd",
        },
        {
            "session_id": "user-run",
            "workspace": "C:\\workspace\\my-project",
        },
    ]

    visible, diagnostic_count = _dashboard_run_view(runs)

    assert [run["session_id"] for run in visible] == ["user-run"]
    assert diagnostic_count == 1


def test_dashboard_run_view_falls_back_to_diagnostics_when_no_user_run_exists() -> None:
    runs = [
        {
            "session_id": "diagnostic",
            "workspace": "C:\\Users\\tester\\AppData\\Local\\Temp\\aia-hook-verify-abcd",
        },
    ]

    visible, diagnostic_count = _dashboard_run_view(runs)

    assert visible[0]["dashboard_diagnostic"] is True
    assert diagnostic_count == 1


class UnreadableRunService(FakeService):
    def get_run_status(self, session_id):
        raise ValueError("Evidence Bundle Integrity Failure")

    def get_result(self, session_id):
        raise ValueError("Evidence Bundle Integrity Failure")

    def get_run_actions(self, session_id):
        raise ValueError("Evidence Bundle Integrity Failure")


def test_unreadable_run_record_renders_actionable_integrity_state() -> None:
    client = TestClient(create_app(UnreadableRunService()))

    for path in ("/runs/run-1", "/runs/run-1/workbench", "/runs/run-1/result"):
        response = client.get(path)
        assert response.status_code == 409
        assert "실행 기록을 안전하게 표시할 수 없습니다" in response.text
        assert "Evidence 확인이 필요합니다" in response.text
        assert "확인되지 않은 기록을 정상 실행이나 유효한 결과로 표시하지 않았습니다" in response.text
        assert "Evidence Bundle 무결성 검증 실패" in response.text
        assert "Evidence Bundle Integrity Failure" not in response.text
        assert 'href="/runs"' in response.text
        assert 'href="/new"' in response.text

    actions = client.get("/api/runs/run-1/actions")
    assert actions.status_code == 409
    assert actions.json() == {"error": "Evidence Bundle 무결성 검증 실패"}


def test_console_routes_render_and_keep_raw_secrets_out_of_html() -> None:
    client = TestClient(create_app(FakeService()))
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert 'rel="icon" type="image/svg+xml"' in dashboard.text
    favicon = client.get("/static/favicon.svg")
    assert favicon.status_code == 200
    assert favicon.text.startswith("<svg")
    css = client.get("/static/app.css")
    assert css.status_code == 200
    assert ".ambient-scene" in css.text
    assert "backdrop-filter" in css.text
    assert "prefers-reduced-motion" in css.text
    assert ".preflight-loading-elapsed" in css.text
    assert ".preflight-requirement-summary" in css.text
    assert ".hook-readiness-path" in css.text
    assert ".hook-readiness-step.is-attention" in css.text
    assert ".hook-readiness-step.is-current" in css.text
    assert ".dashboard-readiness-progress-steps span.is-current" in css.text
    assert ".history-view-preset.is-active" in css.text
    assert ".preflight-scope-complete" in css.text
    assert '.field textarea[aria-invalid="true"]' in css.text
    assert "glassbox-ui-30" in dashboard.text
    assert '@font-face' in css.text
    assert 'font-family: "Pretendard"' in css.text
    assert 'PretendardVariable.woff2' in css.text
    assert ".topbar { height: 60px; min-height: 60px;" in css.text
    assert ".workbench-jumpbar { margin-right: 0; flex-wrap: nowrap; overflow-x: auto; }" in css.text
    assert ".workbench-jumpbar-label { flex-basis: auto; }" in css.text
    assert ".history-table { display: block; min-width: 0; }" in css.text
    assert "content: attr(data-label)" in css.text
    assert ".result-event-toolbar" in css.text
    assert ".result-event-filter.is-active" in css.text
    assert ".result-event-row[hidden] { display: none; }" in css.text
    assert ".page-actions { flex-wrap: wrap; gap: 10px 14px; }" in css.text
    assert "#dashboard-recent-table > table { display: block; min-width: 0; }" in css.text
    assert "#dashboard-recent-table > table tbody > tr > td:nth-child(3)::before" in css.text
    pretendard = client.get("/static/fonts/PretendardVariable.woff2")
    assert pretendard.status_code == 200
    assert pretendard.content.startswith(b"wOF2")
    pretendard_license = client.get("/static/fonts/OFL.txt")
    assert pretendard_license.status_code == 200
    assert "SIL Open Font License" in pretendard_license.text
    assert 'class="ambient-scene"' in dashboard.text
    assert "보호 상태를 한눈에 확인하세요" in dashboard.text
    assert "dashboardCheckBlocksRun" in dashboard.text
    assert 'data-dashboard-readiness-step="codex_executable"' in dashboard.text
    assert 'data-dashboard-readiness-step="hook_verification"' in dashboard.text
    assert "dashboardReadinessStepElements" in dashboard.text
    assert "dashboardCheckMark" in dashboard.text
    assert "CODEX_HOOK_TRUST_REQUIRED" in dashboard.text
    assert "Python 모듈 실행 명령" in dashboard.text
    assert "생성된 <code>aia.exe</code>를 차단하는 환경에서도" in dashboard.text
    assert "dashboard-command-context" in dashboard.text
    assert "사용자 작업 실행을 우선 표시합니다" in dashboard.text
    assert 'href="/runs?origin=user"' in dashboard.text

    new_run = client.get("/new")
    assert new_run.status_code == 200
    assert "보호 실행 시작" in new_run.text
    assert 'id="run-next-action"' in new_run.text
    assert 'id="run-next-action-title"' in new_run.text
    assert 'id="run-next-action-detail"' in new_run.text
    assert 'id="run-next-action-link"' in new_run.text
    assert 'id="preflight-panel"' in new_run.text
    assert 'id="workspace-input"' in new_run.text
    assert 'aria-describedby="workspace-help workspace-status"' in new_run.text
    assert 'aria-invalid="false"' in new_run.text
    assert 'id="workspace-help"' in new_run.text
    assert "updateNextAction" in new_run.text
    assert "작업 폴더 선택" in new_run.text
    assert 'data-run-step="1"' in new_run.text
    assert 'data-run-step="4"' in new_run.text
    assert 'id="run-progress-status"' in new_run.text
    assert "updateRunProgress" in new_run.text
    assert "AIA는 실제 도구 요청을 관찰·통제합니다" in new_run.text
    assert "Codex 설정 Trust 상태" in new_run.text
    assert "실제 Hook 연결 검증" in new_run.text
    assert "현재 연결 증명" in new_run.text
    assert "현재 Protected Run에 Hook이 연결됐다는 증명과는 별개입니다" in new_run.text
    assert "preflightCheckBlocksRun" in new_run.text
    assert 'id="preflight-requirement-summary"' in new_run.text
    assert 'id="hook-readiness-path"' in new_run.text
    assert 'data-hook-step="installed"' in new_run.text
    assert 'data-hook-step="trusted"' in new_run.text
    assert 'data-hook-step="verified"' in new_run.text
    assert 'id="hook-readiness-path-summary"' in new_run.text
    assert "실행 차단" in new_run.text
    assert "필수" in new_run.text
    assert "preflight-scope-required" in new_run.text
    assert "preflight-scope-complete" in new_run.text
    assert "preflight-scope-optional" in new_run.text
    assert "updatePreflightRequirementSummary" in new_run.text
    assert "updateHookReadinessPath" in new_run.text
    assert "setAttribute('aria-current', 'step')" in new_run.text
    assert "CODEX_HOOK_TRUST_REQUIRED" in new_run.text
    assert "preflightCheckMark" in new_run.text
    assert "아래 설치 명령을 실행하세요." in new_run.text
    assert "아래 검증 명령을 실행해 실제 Hook 연결을 확인하세요." in new_run.text
    assert "PowerShell 권장 명령" in new_run.text
    assert "생성된 <code>aia.exe</code>를 거치지 않고" in new_run.text
    assert "preflight-command-context" in new_run.text
    assert "이 화면의 AIA 실행 기준 폴더" in new_run.text
    assert "Codex 설정에서 신뢰된 Hook이 확인되었습니다." in new_run.text
    assert "Codex Hook Trust 상태를 확인할 수 없습니다." in new_run.text
    assert "preflight-command-help" in new_run.text
    assert "python -m aia.cli setup" in new_run.text
    assert "python -m aia.cli hook verify" in new_run.text
    assert "data-copy-command" in new_run.text
    assert 'data-preflight-command="setup"' in new_run.text
    assert 'data-preflight-command="verify"' in new_run.text
    assert "표시된 명령을 PowerShell에 그대로 붙여넣어 실행하세요." in new_run.text
    assert "preflightCommandRows" in new_run.text
    assert "preflightCommandHelp.hidden" in new_run.text
    assert "확인 필요 · 입력한 경로" in new_run.text
    assert "경로 확인 필요" in new_run.text
    assert "준비 필요" in new_run.text
    assert "preToolUse=MODIFIED" not in new_run.text
    assert 'id="readiness-code" title="CHECKING">확인 중</span>' in new_run.text
    assert 'id="preflight-loading"' in new_run.text
    assert 'id="preflight-loading-elapsed"' in new_run.text
    assert 'id="verify-hook-elapsed"' in new_run.text
    assert "startPreflightLoading" in new_run.text
    assert "updatePreflightElapsed" in new_run.text
    assert "startVerifyHookProgress" in new_run.text
    assert "updateVerifyHookElapsed" in new_run.text
    assert 'id="preflight-checks"' in new_run.text
    assert "loadPreflight" in new_run.text
    assert "PREFLIGHT_TIMEOUT" in new_run.text
    assert "PREFLIGHT_REQUEST_TIMEOUT_MS = 30000" in new_run.text
    assert "preflightReadinessLabels" in new_run.text
    assert "preflightCheckDetailLabel" in new_run.text
    assert "preflightTrustStatusLabels" in new_run.text
    assert "hookVerificationResultLabel" in new_run.text
    assert "Codex가 아직 AIA Hook을 신뢰하지 않았습니다" in new_run.text
    assert "상태는 단계별로 표시됩니다" in new_run.text
    assert "if (name === 'pretool_hook') return check?.ok ? ['info', '설치됨'] : check?.stale ? ['attention', '갱신 필요'] : ['fail', '설치 필요'];" in new_run.text
    assert "if (name === 'codex_hook_trust') return check?.ok ? ['ok', '신뢰됨'] : blocksRun ? ['attention', '신뢰 필요'] : ['optional', '확인 전'];" in new_run.text
    assert "if (name === 'hook_verification') return check?.ok ? ['ok', '검증됨'] : ['attention', '검증 필요'];" in new_run.text
    assert 'id="readiness-config"' in new_run.text
    assert "현재 실행 설정: Workspace 입력 필요" in new_run.text
    assert "Workspace와 정책을 선택해 보호 실행을 시작할 수 있습니다." not in new_run.text
    assert "빠른 정책 확인 예시" in new_run.text
    assert 'data-preview-target=".env"' in new_run.text
    assert "핵심 코드 삭제" in new_run.text
    assert "previewPresets" in new_run.text
    assert "현재 보호 범위" in new_run.text
    assert "MCP" in new_run.text
    assert "aliases=Edit, Write" in new_run.text
    assert "작업 방식" in new_run.text
    assert "Codex 작업창" in new_run.text
    assert '<details class="panel policy-editor-panel">' in new_run.text
    assert '<details class="panel capability-panel">' in new_run.text
    assert "정책 만들기" in new_run.text
    assert "실행 설정" in new_run.text
    assert 'id="run-launch-summary"' in new_run.text
    assert "보호 실행 요약" in new_run.text
    assert "runSummaryWorkspace" in new_run.text
    assert "실행 가능" in new_run.text
    assert "terminalSurfaceInputs" in new_run.text
    assert "runSubmissionInProgress" in new_run.text
    assert 'id="workspace-status"' in new_run.text
    assert 'id="workspace-input"' in new_run.text
    assert 'id="run-next-action-link"' in new_run.text
    assert "autofocus" not in new_run.text
    assert 'list="recent-workspaces"' in new_run.text
    assert 'id="recent-workspaces"' in new_run.text
    assert 'id="recent-workspace-hint"' in new_run.text
    assert 'id="recent-workspace-actions"' in new_run.text
    assert 'id="recent-workspace-buttons"' in new_run.text
    assert 'id="clear-recent-workspaces"' in new_run.text
    assert "RECENT_WORKSPACES_KEY" in new_run.text
    assert "loadRecentWorkspaces" in new_run.text
    assert "renderRecentWorkspaces" in new_run.text
    assert "rememberWorkspace" in new_run.text
    assert "recent-workspace-button" in new_run.text
    assert "기록 지우기" in new_run.text
    assert "validateWorkspacePath" in new_run.text
    assert "workspaceValidationMessage" in new_run.text
    assert "이 경로에 존재하는 폴더가 없습니다" in new_run.text
    assert "workspace validation failed" not in new_run.text
    assert "workspaceValidationInProgress" in new_run.text
    assert "Workspace를 확인하는 중입니다." in new_run.text
    assert "updateRunSubmitState" in new_run.text
    assert 'id="run-submit-hint"' in new_run.text
    assert 'id="run-submit-help-link"' in new_run.text
    assert "taskMissing" in new_run.text
    assert "작업 요청으로 이동" in new_run.text
    assert "한 번의 작업 실행을 선택했습니다. Codex에 전달할 작업 요청을 입력하세요." in new_run.text
    assert 'id="run-launch-actions"' in new_run.text
    assert 'id="run-recovery-help"' in new_run.text
    assert 'id="reconcile-stale-run"' in new_run.text
    assert "showRunStartError" in new_run.text
    assert "이 Workspace는 이전 보호 실행이 정리되지 않아 시작할 수 없습니다" in new_run.text
    assert "runRecoveryHelp.scrollIntoView" in new_run.text
    assert "정리 확인 완료. 이제 보호 실행을 다시 시작할 수 있습니다." in new_run.text
    assert "존재하는 Workspace 경로를 확인하면 실행할 수 있습니다" in new_run.text
    assert "보호 실행 준비 중" in new_run.text
    assert "is-busy" in new_run.text
    assert "new-run-page" in new_run.text
    assert 'id="jump-to-run"' in new_run.text
    assert 'id="run-settings"' in new_run.text
    assert new_run.text.index('id="run-settings"') < new_run.text.index('id="preflight-panel"')
    assert new_run.text.index("} else if (workspaceValidationInProgress)") < new_run.text.index("} else if (!preflightLoaded || preflightRequestInFlight)")
    assert 'id="preflight-next-steps"' in new_run.text
    assert 'id="preflight-next-steps-title"' in new_run.text
    assert 'data-preflight-step="setup"' in new_run.text
    assert 'data-preflight-step="explain"' in new_run.text
    assert 'data-preflight-step="trust"' in new_run.text
    assert 'data-preflight-step="verify"' in new_run.text
    assert 'data-preflight-step="refresh"' in new_run.text
    assert "renderPreflightNextSteps" in new_run.text
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
    assert '<span>Hook Sensor</span><strong id="hook-broker-health" title="HEALTHY">정상</strong>' in live.text
    assert "실시간 센서 상태" in live.text
    assert '<div id="status-badge" class="status-badge" title="RUNNING">실행 중</div>' in live.text
    assert '<strong id="phase" title="RUNNING">Agent 실행 중</strong>' in live.text
    assert '<strong id="checkpoint" title="READY">생성됨 · 사용 가능</strong>' in live.text
    assert '<strong id="lease" title="ACTIVE">보호 실행에 연결됨</strong>' in live.text
    assert '<strong id="protection-state" aria-live="polite" title="ACTIVE_VERIFIED">보호 검증됨</strong>' in live.text
    assert '<strong id="hook-broker-health" title="HEALTHY">정상</strong>' in live.text
    assert '<span id="launch-mode" class="badge" title="inherit">기본 실행</span>' in live.text
    assert 'id="event-timeline"' in live.text
    assert 'id="run-refresh-status"' in live.text
    assert 'id="refresh-run"' in live.text
    assert "pollInFlight" in live.text
    assert "if (pollInFlight) return;" in live.text
    assert "stopPolling" in live.text
    assert "actionsError" in live.text
    assert "실행 행위 기록을 표시할 수 없습니다. Evidence Bundle 무결성 확인이 필요합니다." in live.text
    assert "renderIncident(status.events || [], terminal)" in live.text
    assert "최근 확인 필요 사건" in live.text
    assert "HEALTHY" in live.text
    workbench = client.get("/runs/run-1/workbench")
    assert workbench.status_code == 200
    assert "page-shell-workbench" in workbench.text
    assert "topbar-workbench" in workbench.text
    assert "Codex 작업창" in workbench.text
    assert "보안 관찰" in workbench.text
    assert 'class="workbench-card security-events-card"' in workbench.text
    assert workbench.text.index('id="incident-card"') < workbench.text.index('class="workbench-card security-events-card"')
    assert 'class="workbench-context"' in workbench.text
    assert "보호 중인 Workspace" in workbench.text
    assert "실행 ID 보기" in workbench.text
    assert 'id="run-status"' in workbench.text and ">실행 중</span>" in workbench.text
    assert '<dd id="phase" title="RUNNING">Agent 실행 중</dd>' in workbench.text
    assert '<dd id="checkpoint" title="READY">생성됨 · 사용 가능</dd>' in workbench.text
    assert '<dd id="lease" title="ACTIVE">보호 실행에 연결됨</dd>' in workbench.text
    assert '<span id="protection-state" class="badge" title="ACTIVE_VERIFIED" aria-live="polite">보호 검증됨</span>' in workbench.text
    assert '<strong id="summary-protection">보호 검증됨</strong>' in workbench.text
    assert '<strong id="summary-incidents">1건</strong>' in workbench.text
    assert '정책 사건 0건' in workbench.text
    assert "정책 사건 ${status.incident_count || 0}건" in workbench.text
    assert '차단 여부는 결과에서 확인' in workbench.text
    assert '<strong id="evidence-count">5건</strong>' in workbench.text
    assert '<strong id="file-count">2건</strong>' in workbench.text
    assert '<strong id="process-count">0건</strong>' in workbench.text
    assert "센서 카드를 누르면 해당 Evidence로 이동합니다." in workbench.text
    assert workbench.text.count("Evidence 보기 →") == 4
    assert 'id="security-panel-toggle"' in workbench.text
    assert 'id="security-panel-content"' in workbench.text
    assert "setSecurityPanelCollapsed" in workbench.text
    assert 'aria-expanded="true"' in workbench.text
    assert 'id="protection-state-note"' in workbench.text
    assert "최근 이벤트" in workbench.text
    assert 'id="workbench-guidance"' in workbench.text
    assert 'id="workbench-guidance-title"' in workbench.text
    assert 'id="workbench-guidance-detail"' in workbench.text
    assert 'id="workbench-guidance-owner"' in workbench.text
    assert 'id="workbench-system-alert"' in workbench.text
    assert "renderRuntimeAlert(status)" in workbench.text
    assert "RUNTIME_STATE_PERSIST_FAILED" in workbench.text
    assert 'id="workbench-alert"' in workbench.text
    assert 'id="workbench-alert-title"' in workbench.text
    assert 'id="workbench-alert-dismiss"' in workbench.text
    assert "announceNewSecurityEvents" in workbench.text
    assert "원문" not in workbench.text
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
    assert "Codex 응답을 수신하는 중입니다." in workbench.text
    assert "OUTPUTTING" in workbench.text
    assert "응답 수신 중" in workbench.text
    assert "interruptPending || !['SUBMITTING', 'WORKING', 'OUTPUTTING'].includes(activityMode)" in workbench.text
    assert "Codex가 다음 작업을 기다리고 있습니다." in workbench.text
    assert "Codex 작업창을 준비하고 있습니다." in workbench.text
    assert "입력창이 활성화될 때까지 잠시 기다려 주세요." in workbench.text
    assert "실행이 끝났습니다. 결과를 확인하세요." in workbench.text
    assert "updateWorkbenchGuidance" in workbench.text
    assert "statusPollFailures >= 2" in workbench.text
    assert "updateWorkbenchGuidance();" in workbench.text
    assert "statusPollTimer" in workbench.text
    assert "stopStatusPolling" in workbench.text
    assert "startStatusPolling" in workbench.text
    assert "if (ended || orphaned) stopStatusPolling();" in workbench.text
    assert "Boolean(latestStatus?.runtime_reconciliation?.orphaned)" in workbench.text
    assert "visibilitychange" in workbench.text
    assert "마지막 이벤트" in workbench.text
    assert "마지막 출력 수신" in workbench.text
    assert "화면 갱신" in workbench.text
    assert 'id="event-visibility-summary"' in workbench.text
    assert 'id="event-detail-link"' in workbench.text
    assert "전체 실행 흐름 보기 →" in workbench.text
    assert "최근 ${visibleEventCount}건 표시 · 전체 ${events.length}건" in workbench.text
    assert 'id="event-count"' in workbench.text
    assert "Glass-box 확장 영역" in workbench.text
    assert "실행 흐름" in workbench.text
    assert "보호 준비" in workbench.text
    assert 'id="workbench-flow"' in workbench.text
    assert 'id="workbench-flow-status"' in workbench.text
    assert "현재 단계를 확인하는 중입니다." in workbench.text
    assert "모든 단계 완료 · Evidence Bundle이 검증되었습니다." in workbench.text
    assert "File Sensor가 ${fileEvidence}건을 기록했습니다." in workbench.text
    assert 'data-flow-step="1"' in workbench.text
    assert 'data-flow-step="4"' in workbench.text
    assert "function updateFlow(status = {})" in workbench.text
    assert "summary.pretool_events" in workbench.text
    assert "summary.filesystem_events" in workbench.text
    assert "status?.bundle_status === 'VALID'" in workbench.text
    assert "let completedThrough = 0" in workbench.text
    assert "statusClass" in workbench.text
    assert "protectionClass" in workbench.text
    assert "protectionNote" in workbench.text
    assert "행위 관찰 전" in workbench.text
    assert "도구 요청 대기 중" in workbench.text
    assert "ABORTED_VERIFIED: '중지 · 검증됨'" in workbench.text
    assert "실행이 중지됐고 수집된 보호 증거와 결과를 검증했습니다." in workbench.text
    assert "현재 Workbench" in workbench.text
    assert 'id="workbench-howto-title"' in workbench.text
    assert 'id="workbench-howto-title"' in workbench.text
    assert 'id="workbench-howto-description"' in workbench.text
    assert 'id="workbench-howto-steps"' in workbench.text
    assert "function updateWorkbenchHowTo(status = latestStatus)" in workbench.text
    assert "이 실행은 끝났습니다. 결과와 센서 Evidence를 확인한 뒤 다음 작업을 시작하세요." in workbench.text
    assert "보호 연결이 끊긴 실행은 계속 보호되는 것으로 간주하지 않습니다." in workbench.text
    assert 'id="terminal-input-proxy"' in workbench.text
    assert 'aria-describedby="terminal-input-help"' in workbench.text
    assert "Enter 전송 · Shift+Enter 줄바꿈" in workbench.text
    assert 'id="terminal-input-form"' in workbench.text
    assert 'id="terminal-send"' in workbench.text
    assert 'id="stop-confirmation"' in workbench.text
    assert "stopConfirmationPending" in workbench.text
    assert "function armStopConfirmation()" in workbench.text
    assert "중지 확인" in workbench.text
    assert 'data-terminal-focus' in workbench.text
    assert '입력창으로 이동' in workbench.text
    assert 'class="terminal-focus-link" href="#terminal-input-proxy" data-terminal-focus' in workbench.text
    assert 'const terminalUnavailable = runEnded || protectionDisconnected || terminalClosed' in workbench.text
    assert '이 실행은 종료되었습니다 · 결과 보기에서 기록을 확인하세요.' in workbench.text
    assert 'Codex 작업창 연결 후 입력할 수 있습니다.' in workbench.text
    assert "terminalInput.scrollIntoView({behavior: 'smooth', block: 'center'})" in workbench.text
    assert 'id="terminal-activity"' in workbench.text
    assert 'class="terminal-output' in workbench.text
    assert 'id="terminal-placeholder"' in workbench.text
    assert "is-loading" in workbench.text
    assert 'id="terminal-connection"' in workbench.text
    assert 'id="terminal-last-output-meta"' in workbench.text
    assert 'id="terminal-last-output-label"' in workbench.text
    assert 'id="terminal-last-output"' in workbench.text
    assert "재연결 중" in workbench.text
    assert "terminalClosed" in workbench.text
    assert "terminalConnectionFailed" in workbench.text
    assert "formatOutputAge" in workbench.text
    assert "output-stale" in workbench.text
    assert "terminalInputForm" in workbench.text
    assert "activityMode" in workbench.text
    assert "awaitingResponse" in workbench.text
    assert "응답 대기 중" in workbench.text
    assert "updateTerminalInputState" in workbench.text
    assert "submitTerminalLine" in workbench.text
    assert "function resizeTerminalInput()" in workbench.text
    assert "event.key === 'Enter' && event.shiftKey" in workbench.text
    assert "event.isComposing && !event.shiftKey" in workbench.text
    assert "SUBMIT_SETTLE_MS = 250" in workbench.text
    assert "Codex에 질문을 제출하는 중입니다." in workbench.text
    assert 'id="terminal-action"' in workbench.text
    assert "신뢰하고 계속" in workbench.text
    assert "TRUST_DIRECTORY" in workbench.text
    assert "Workspace 신뢰 확인을 기다리고 있습니다." in workbench.text
    assert "차단 응답 전송" in workbench.text
    assert "실행 결과 대기" in workbench.text
    assert "도구 실행 여부 확인 중" in workbench.text
    assert "실행 확인 전" in workbench.text
    assert "실행 결과 증거 없음" in workbench.text
    assert "정책상 허용" in workbench.text
    assert "실행 Evidence가 없으면 성공으로 표시하지 않습니다" in workbench.text
    assert "센서가 관찰하면 여기에 표시됩니다" in workbench.text
    assert "eventTitleLabel(incident)" in workbench.text
    assert "eventTitleLabel(candidate)" in workbench.text
    assert "const observational = ['PROCESS_OBSERVATION', 'FILESYSTEM_OBSERVATION'].includes(event?.event_origin)" in workbench.text
    assert "const text = observational ? '센서 관찰' : decisionLabel(value)" in workbench.text
    assert "const sensorEventOrigins = new Set(['PROCESS_OBSERVATION', 'FILESYSTEM_OBSERVATION'])" in workbench.text
    assert "const isSensorEvent = (event) => event?.category === 'SENSOR' || sensorEventOrigins.has(event?.event_origin)" in workbench.text
    assert "allEvents.filter((event) => isSensorEvent(event))" in workbench.text
    assert "allEvents.filter((event) => !isSensorEvent(event))" in workbench.text
    assert "statusPollFailures" in workbench.text
    assert "연결 확인 필요" in workbench.text
    assert "function updateWorkbenchDocumentTitle(status = latestStatus)" in workbench.text
    assert "응답 지연 · AIA Workbench" in workbench.text
    assert "document.title = `${activityLabel} · AIA Workbench`;" in workbench.text
    assert 'id="refresh-status"' in workbench.text
    assert "상태 새로고침" in workbench.text
    assert "terminalSocketConnected" in workbench.text
    assert "terminalSocketEverConnected" in workbench.text
    assert "terminalProtocolError" in workbench.text
    assert "function handleTerminalProtocolError(message)" in workbench.text
    assert "터미널 연결 오류" in workbench.text
    assert "Workbench 터미널 응답에 문제가 있습니다." in workbench.text
    assert "typeof event.data !== 'string'" in workbench.text
    assert "try {\n      message = JSON.parse(event.data);" in workbench.text
    assert "알 수 없는 터미널 응답을 받았습니다." in workbench.text
    assert "terminalScreen.reset()" in workbench.text
    assert "transientProgressLine" in workbench.text
    assert "terminalScreen.refresh()" in workbench.text
    assert "function scheduleTerminalResize()" in workbench.text
    assert "function syncTerminalSize()" in workbench.text
    assert "new ResizeObserver(scheduleTerminalResize)" in workbench.text
    assert "terminalOutput.clientWidth" in workbench.text
    assert "terminalOutput.classList.remove('terminal-closed')" in workbench.text
    assert "terminalOutput.classList.remove('is-loading')" in workbench.text
    assert "function terminalRunEnded()" in workbench.text
    assert "if (terminalRunEnded())" in workbench.text
    assert "terminalOutput.classList.toggle('is-loading', !terminalRunEnded())" in workbench.text
    assert "if (ended) terminalOutput.classList.remove('is-loading');" in workbench.text
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
    assert 'id="incident-heading"' in workbench.text
    assert 'id="incident-status-badge"' in workbench.text
    assert "Number(status.incident_count || 0) > 0" in workbench.text
    assert "정책 사건 기록 확인 필요" in workbench.text
    assert "이 화면에서 부작용을 확정할 수 없음" in workbench.text
    assert "incidentCard.hidden = true" in workbench.text
    assert "최근 확인 필요 사건" in workbench.text
    assert "Codex의 설명만으로는 실제 실행 여부를 확정하지 않습니다." in workbench.text
    assert "실행 결과 대기" in workbench.text
    assert 'data-event-filter="ALL"' in workbench.text
    assert 'data-event-filter="ACTION"' in workbench.text
    assert 'data-event-filter="SENSOR"' in workbench.text
    assert "button.textContent = `${label} ${count}건`;" in workbench.text
    assert "전체 ${allEvents.length}건 · 행위 ${actionEventCount}건 · 센서 ${sensorEventCount}건" in workbench.text
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
    assert 'id="terminal-closed-card"' in workbench.text
    assert 'id="terminal-closed-result"' in workbench.text
    assert 'href="/new">새 보호 실행</a>' in workbench.text
    assert workbench.text.index('id="terminal-closed-card"') < workbench.text.index('id="terminal-output"')
    assert "updateTerminalClosedCard" in workbench.text
    assert "Codex 작업창 출력은 보안을 위해 저장하지 않습니다." in workbench.text
    assert "작업창 출력" in workbench.text
    assert "terminal-ended" in workbench.text
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
    assert "const eventCategoryLabel = (event)" in workbench.text
    assert "event?.display_summary" in workbench.text
    assert "event?.origin_label" in workbench.text
    assert "event?.display_target_label" in workbench.text
    assert "const toolNameLabel = (value)" in workbench.text
    assert "const contextLabel = [" in workbench.text
    assert "event.tool_name" in workbench.text
    assert "eventFilterCounts" in workbench.text
    assert "증거 흐름 보기 →" in workbench.text
    assert 'class="event-category-label"' in workbench.text
    assert "const orderedEvents = (items) => items" in workbench.text
    assert "eventDetailLink?.addEventListener" in workbench.text
    assert "전체 센서 Evidence 보기 →" in workbench.text
    assert "eventFilter === 'ALL'" in workbench.text
    assert "전체 ${allEvents.length}건 · 행위 ${actionEventCount}건 · 센서 ${sensorEventCount}건" in workbench.text
    assert "현재 필터 결과" in workbench.text
    assert "bindChainSelectors" in workbench.text
    assert "sensor-evidence-row ${linked ? 'is-linked'" in workbench.text
    assert "data-chain-select" in workbench.text
    assert "responseStartedAt" in workbench.text
    assert "const hadPendingResponse = awaitingResponse" in workbench.text
    assert "!responseStartedAt" in workbench.text
    assert "terminalAction !== 'TRUST_DIRECTORY'" in workbench.text
    assert "먼저 “신뢰하고 계속”을 눌러주세요." in workbench.text
    assert "응답 완료 · 다음 작업을 입력할 수 있습니다." in workbench.text
    assert "이번 작업에는 파일·명령 도구 요청이 없어 Hook 이벤트가 없습니다." in workbench.text
    assert "이번 작업에는 도구 요청이 없어 Hook Evidence가 없습니다." in workbench.text
    assert 'id="terminal-examples"' in workbench.text
    assert "예시를 눌러도 자동 실행되지 않습니다." in workbench.text
    assert "data-terminal-example" in workbench.text
    assert "terminalOutput.setAttribute('aria-busy'" in workbench.text
    assert "workingAtTail" in workbench.text
    assert "composerAtTail" in workbench.text
    assert "composerVisible" in workbench.text
    assert 'id="terminal-scroll-latest"' in workbench.text
    assert "terminalFollowingOutput" in workbench.text
    assert "최신 출력으로 이동" in workbench.text
    assert "terminalIsAtBottom" in workbench.text
    assert 'id="terminal-interrupt"' in workbench.text
    assert "interruptTerminalRequest" in workbench.text
    assert "현재 Codex 요청을 중지하는 중입니다." in workbench.text
    assert "data: '\\u0003'" in workbench.text
    assert "window.clearTimeout(pendingSubmission.timer)" in workbench.text
    assert 'id="terminal-reconnect"' in workbench.text
    assert "reconnectTerminal" in workbench.text
    assert "다시 연결하는 중" in workbench.text
    assert "terminalReconnectPending" in workbench.text
    assert "statusPollPromise" in workbench.text
    assert "statusPollBusyTimer" in workbench.text
    assert "STATUS_REQUEST_TIMEOUT_MS = 7000" in workbench.text
    assert "new AbortController()" in workbench.text
    assert "controller.abort()" in workbench.text
    assert "응답 시간 초과 · 재시도 중" in workbench.text
    assert "lastRefreshTime.classList.add('is-refreshing')" in workbench.text
    assert "갱신 중…" in workbench.text
    assert 'id="workbench-sticky-status"' in workbench.text
    assert "updateStickyStatus" in workbench.text
    assert "Codex 응답 처리 중" in workbench.text
    assert "terminalActivityIsDelayed" in workbench.text
    assert "응답 지연 확인 필요" in workbench.text
    assert "Codex 응답이 지연되고 있습니다." in workbench.text
    assert "더 기다리거나 “현재 요청 중지”를 선택할 수 있습니다." in workbench.text
    assert 'id="sensor-hook-update"' in workbench.text
    assert 'id="sensor-file-update"' in workbench.text
    assert 'id="sensor-process-update"' in workbench.text
    assert "showSensorUpdate" in workbench.text
    assert "updateSensorCount" in workbench.text
    assert "sensor-updated" in workbench.text
    assert "+${delta} 새 증거" in workbench.text
    assert "정상 종료 · 관찰 없음" in workbench.text
    assert "sensorLabel = (value, ended = false, orphaned = false, evidenceCount = null)" in workbench.text
    assert "securityEventKey" in workbench.text
    assert "eventHighlightKeys" in workbench.text
    assert "scheduleEventHighlightClear" in workbench.text
    assert "highlightAdded" in workbench.text
    assert "새로 관찰" in workbench.text
    assert "event-new" in workbench.text
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
    assert "프로세스 수준" in incident.text
    assert "자동 조치 보류" in incident.text
    assert "실행 결과 증거 없음" in incident.text
    assert "삭제 사건" in incident.text
    assert "사건 ID 보기" in incident.text
    assert "개별 시각 미확인" in incident.text
    assert "이 사건의 개별 시각은 확인되지 않습니다." in incident.text
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
    assert 'aria-label="실행 정보"' in result.text
    assert "Workspace" in result.text
    assert "basic · 1.0" in result.text
    assert "Workbench 내 터미널" in result.text
    assert 'class="technical-meta"' in result.text
    assert "실행 ID 보기" in result.text
    assert 'aria-label="결과 읽는 순서"' in result.text
    assert "실행 Evidence" in result.text
    assert "보호 검증" in result.text
    assert "보호 상태" in result.text
    assert "다음 작업" in result.text
    assert "새 보호 실행 시작" in result.text
    assert 'class="is-active" aria-current="page" href="/runs"' in result.text
    assert "정책 위반" in result.text
    assert "실행 결과 증거 없음" in result.text
    assert "도구가 실행되지 않았다는 뜻이 아닙니다" in result.text
    assert "집행 조치 없음" in result.text
    assert 'href="/new">새 보호 실행</a>' in result.text
    assert 'aria-label="결과 바로가기"' in result.text
    assert 'id="sensor-results"' in result.text
    assert '<span>정책 사건</span><strong>0건</strong><small>정책 판정 기록 기준</small>' in result.text
    assert '<span>차단 사건</span><strong>0건</strong>' not in result.text
    assert 'id="event-timeline"' in result.text
    assert "button.textContent = `${buttonLabel} ${count}건`;" in result.text
    assert 'href="#evidence-chain">증거</a>' in result.text
    assert 'href="#execution-policy">실행 정책</a>' in result.text
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


def test_new_run_shows_launcher_fallback_only_when_paths_differ(monkeypatch) -> None:
    web_module = importlib.import_module("aia_web.app")
    monkeypatch.setattr(web_module, "_console_cli_prefix", lambda: "uv run aia")
    monkeypatch.setattr(
        web_module,
        "_console_module_cli_prefix",
        lambda: "uv run --isolated python -m aia.cli",
    )

    response = TestClient(create_app(FakeService())).get("/new")

    assert response.status_code == 200
    assert "Windows 실행 파일 오류가 나면" in response.text
    assert "uv run --isolated python -m aia.cli doctor" in response.text
    assert "uv run --isolated python -m aia.cli setup" in response.text
    assert "uv run --isolated python -m aia.cli hook verify" in response.text


def test_new_run_hides_redundant_launcher_fallback(monkeypatch) -> None:
    web_module = importlib.import_module("aia_web.app")
    monkeypatch.setattr(web_module, "_console_cli_prefix", lambda: "same command")
    monkeypatch.setattr(web_module, "_console_module_cli_prefix", lambda: "same command")

    response = TestClient(create_app(FakeService())).get("/new")

    assert response.status_code == 200
    assert "Windows 실행 파일 오류가 나면" not in response.text


def test_dashboard_shows_launcher_fallback_only_when_paths_differ(monkeypatch) -> None:
    web_module = importlib.import_module("aia_web.app")
    monkeypatch.setattr(web_module, "_console_cli_prefix", lambda: "uv run aia")
    monkeypatch.setattr(
        web_module,
        "_console_module_cli_prefix",
        lambda: "uv run --isolated python -m aia.cli",
    )

    response = TestClient(create_app(FakeService())).get("/")

    assert response.status_code == 200
    assert "Windows에서 aia.exe가 차단되면" in response.text
    assert "uv run --isolated python -m aia.cli doctor" in response.text
    assert "uv run --isolated python -m aia.cli setup" in response.text
    assert "uv run --isolated python -m aia.cli hook verify" in response.text


def test_dashboard_hides_redundant_launcher_fallback(monkeypatch) -> None:
    web_module = importlib.import_module("aia_web.app")
    monkeypatch.setattr(web_module, "_console_cli_prefix", lambda: "same command")
    monkeypatch.setattr(web_module, "_console_module_cli_prefix", lambda: "same command")

    response = TestClient(create_app(FakeService())).get("/")

    assert response.status_code == 200
    assert "Windows에서 aia.exe가 차단되면" not in response.text


def test_dashboard_reuses_one_run_snapshot_for_readiness_and_history() -> None:
    service = FakeService()
    original_list_runs = service.list_runs
    calls = 0

    def counted_list_runs():
        nonlocal calls
        calls += 1
        return original_list_runs()

    service.list_runs = counted_list_runs
    response = TestClient(create_app(service)).get("/")

    assert response.status_code == 200
    assert calls == 1


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
    assert 'class="result-hero-status" aria-label="결과 상태"' in result.text
    assert 'class="status-badge status-success" title="VALID">Bundle 유효</div>' in result.text
    assert 'class="status-badge status-warning" title="COMPLETED_DEGRADED">보호 상태 확인 필요</div>' in result.text
    assert "유효 · 보호 확인 필요" not in result.text


def test_result_page_localizes_known_policy_name_but_keeps_identifier_in_title() -> None:
    service = FakeService()
    result_data = service.get_result("run-1")
    result_data.update({"policy_id": "aia-protected-development", "policy_version": "1.1"})
    service.get_result = lambda session_id: result_data

    result = TestClient(create_app(service)).get("/runs/run-1/result")

    assert result.status_code == 200
    assert 'title="aia-protected-development · 1.1">보호 우선 개발형 · 1.1</span>' in result.text


def test_result_page_labels_policy_events_without_claiming_confirmed_block() -> None:
    service = FakeService()
    result_data = service.get_result("run-1")
    result_data["incidents"] = [service.get_incident("run-1", "a1")]
    service.get_result = lambda session_id: result_data

    result = TestClient(create_app(service)).get("/runs/run-1/result")

    assert result.status_code == 200
    assert "정책 사건 상세" in result.text
    assert "실제 차단 여부는 각 행의 실행 결과로 확인하세요." in result.text
    assert "차단·주의 사건" not in result.text


def test_result_page_surfaces_degraded_codex_policy_before_the_summary() -> None:
    service = FakeService()
    result_data = service.get_result("run-1")
    result_data.update(
        {
            "execution_policy_status": "DEGRADED",
            "requested_sandbox": "workspace-write",
            "effective_sandbox": "danger-full-access",
        }
    )
    service.get_result = lambda session_id: result_data
    client = TestClient(create_app(service))

    result = client.get("/runs/run-1/result")

    assert result.status_code == 200
    assert 'aria-label="Codex 실행 정책 경고"' in result.text
    assert "보호 수준이 낮아진 상태로 실행되었습니다." in result.text
    assert "Evidence Bundle이 유효해도" in result.text
    assert 'class="status-badge status-success" title="VALID">Bundle 유효</div>' in result.text
    assert 'class="status-badge status-warning" title="DEGRADED">실행 정책 확인 필요</div>' in result.text
    assert "유효 · 보호 확인 필요" not in result.text
    assert 'href="#execution-policy"' in result.text
    assert result.text.index("Codex 실행 정책 경고") < result.text.index("이번 보호 실행에서 확인된 내용")


def test_result_summary_does_not_claim_full_verification_when_codex_policy_is_unobserved() -> None:
    service = FakeService()
    result_data = service.get_result("run-1")
    result_data.update(
        {
            "execution_policy_status": "NOT_OBSERVED",
            "requested_sandbox": "workspace-write",
            "requested_approval_policy": "on-request",
        }
    )
    service.get_result = lambda session_id: result_data
    client = TestClient(create_app(service))

    result = client.get("/runs/run-1/result")

    assert result.status_code == 200
    assert "센서 증거와 Result Bundle은 확인했지만" in result.text
    assert "실행 정책의 실제 적용 상태는 완전히 확인되지 않았습니다." in result.text
    assert "작업이 끝났고, AIA가 수집한 보호 증거와 결과 Bundle의 검증이 완료되었습니다." not in result.text


def test_result_event_timeline_localizes_enforcement_decisions() -> None:
    service = FakeService()
    result_data = service.get_result("run-1")
    result_data["events"] = [
        {
            "severity": "WARNING",
            "summary": "EXECUTE 행위 관찰",
            "target_label": "명령 실행",
            "sensor": "AGENT_HOOK",
            "decision": "CONTINUE",
            "execution_result": "NOT_ATTEMPTED",
            "observed_at": "2026-09-16T10:20:08+09:00",
        }
    ]
    service.get_result = lambda session_id: result_data
    client = TestClient(create_app(service))

    result = client.get("/runs/run-1/result")

    assert result.status_code == 200
    assert '<span class="badge" title="CONTINUE">계속 진행</span>' in result.text
    assert 'class="result-event-time" datetime="2026-09-16T10:20:08+09:00"' in result.text
    assert "result-event-time" in result.text
    assert 'data-result-event-filter="ALL"' in result.text
    assert 'data-result-event-filter="ACTION"' in result.text
    assert 'id="result-event-toggle"' in result.text
    assert "updateResultEventTimeline" in result.text


def test_result_event_timeline_shows_latest_event_first() -> None:
    service = FakeService()
    result_data = service.get_result("run-1")
    result_data["events"] = [
        {
            "severity": "INFO",
            "display_summary": "오래된 관찰",
            "target_label": "초기 대상",
            "event_origin": "PROCESS_OBSERVATION",
            "sensor": "PROCESS_RUNTIME",
            "decision": "OBSERVED",
            "observed_at": "2026-09-16T10:20:01+09:00",
        },
        {
            "severity": "WARNING",
            "display_summary": "최신 차단 사건",
            "target_label": "위험 대상",
            "event_origin": "FILESYSTEM_OBSERVATION",
            "sensor": "FILESYSTEM_WATCHER",
            "decision": "OBSERVED",
            "observed_at": "2026-09-16T10:20:08+09:00",
        },
    ]
    service.get_result = lambda session_id: result_data

    result = TestClient(create_app(service)).get("/runs/run-1/result")

    assert result.status_code == 200
    assert result.text.index("최신 차단 사건") < result.text.index("오래된 관찰")
    assert "최신 이벤트부터 표시합니다." in result.text


def test_result_event_timeline_labels_sensor_observations_separately() -> None:
    service = FakeService()
    result_data = service.get_result("run-1")
    result_data["events"] = [
        {
            "severity": "INFO",
            "summary": "EXECUTE 행위 관찰",
            "display_summary": "프로세스 실행 관찰",
            "display_target_label": "프로세스",
            "event_origin": "PROCESS_OBSERVATION",
            "origin_label": "프로세스 관찰",
            "sensor": "PROCESS_RUNTIME",
            "decision": "CONTINUE",
            "display_decision": "OBSERVED",
            "execution_result": "NOT_ATTEMPTED",
            "observed_at": "2026-09-16T10:20:08+09:00",
        }
    ]
    service.get_result = lambda session_id: result_data
    client = TestClient(create_app(service))

    result = client.get("/runs/run-1/result")

    assert result.status_code == 200
    assert '<span class="badge" title="OBSERVED">센서 관찰</span>' in result.text
    assert "정책상 허용" not in result.text
    assert 'data-result-event-category="SENSOR"' in result.text


def test_result_page_does_not_show_success_when_bundle_is_invalid() -> None:
    service = FakeService()
    result_data = service.get_result("run-1")
    result_data["bundle_status"] = "INVALID"
    result_data["protection_state"] = "COMPLETED_VERIFIED"
    service.get_result = lambda session_id: result_data
    client = TestClient(create_app(service))

    result = client.get("/runs/run-1/result")

    assert result.status_code == 200
    assert 'class="panel result-overview result-overview-success"' not in result.text
    assert "검증 실패" in result.text
    assert "정상 작업이 끝났고, AIA가 수집한 보호 증거와 결과 Bundle의 검증이 완료되었습니다." not in result.text
    assert "추가 확인 필요" in result.text


def test_result_page_distinguishes_verified_user_abort_from_normal_completion() -> None:
    service = FakeService()
    result_data = service.get_result("run-1")
    result_data["session_status"] = "ABORTED"
    result_data["protection_state"] = "ABORTED_VERIFIED"
    result_data["incidents"] = []
    service.get_result = lambda session_id: result_data
    client = TestClient(create_app(service))

    result = client.get("/runs/run-1/result")

    assert result.status_code == 200
    assert "실행 중지됨" in result.text
    assert "종료·보호 증거 검증이 완료되었습니다" in result.text
    assert "정상 작업이 끝났고 보호 증거와 Result Bundle 검증이 완료되었습니다." not in result.text


def test_incident_page_prioritizes_policy_uncertainty_over_empty_enforcement_action() -> None:
    service = FakeService()
    incident_data = service.get_incident("run-1", "a1")
    incident_data.update({"policy_decision": "INDETERMINATE", "enforcement_action": "NONE"})
    service.get_incident = lambda session_id, action_id: incident_data
    client = TestClient(create_app(service))

    incident = client.get("/runs/run-1/incidents/a1")

    assert incident.status_code == 200
    assert 'title="INDETERMINATE">판정 불가</div>' in incident.text
    assert "독립 Evidence가 부족해 정책 판정을 확정하지 못했습니다." in incident.text


def test_incident_page_labels_recovery_failure_as_recovery() -> None:
    service = FakeService()
    incident_data = service.get_incident("run-1", "a1")
    incident_data.update(
        {
            "operation": "RECOVERY",
            "policy_effect": None,
            "policy_decision": None,
            "enforcement_action": "NONE",
            "recovery_status": "FAILED",
            "integrity_status": "NOT_ATTEMPTED",
            "summary": "복구 작업 · 실패",
        }
    )
    service.get_incident = lambda session_id, action_id: incident_data
    client = TestClient(create_app(service))

    incident = client.get("/runs/run-1/incidents/a1")

    assert incident.status_code == 200
    assert "복구 사건" in incident.text
    assert 'title="FAILED">복원 작업 실패</div>' in incident.text


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


def test_large_terminal_replay_is_coalesced_without_losing_order() -> None:
    items = [
        {
            "type": "output",
            "sequence": index,
            "data": f"chunk-{index}",
            "recorded_at": f"2026-01-01T00:00:{index:02d}+00:00",
        }
        for index in range(1, 41)
    ]

    batches = _coalesce_terminal_output(items)

    assert len(batches) < len(items)
    assert [batch["sequence"] for batch in batches] == [40]
    assert "".join(batch["data"] for batch in batches) == "".join(item["data"] for item in items)


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
    assert "저장소에서는" in dashboard.text
    expected_cli_prefix = _console_cli_prefix()
    assert f"{expected_cli_prefix} doctor" in dashboard.text
    assert "현재 실행 중인 보호 세션이 없습니다" in dashboard.text
    assert 'aria-label="AIA 주요 메뉴"' in dashboard.text
    assert 'aria-current="page"' in dashboard.text
    assert 'id="dashboard-primary-action"' in dashboard.text
    assert 'id="dashboard-primary-action" class="button primary" href="#dashboard-readiness">준비 상태 확인 중…</a>' in dashboard.text
    assert 'id="dashboard-readiness-label">실행 준비</span>' in dashboard.text
    assert '<small id="dashboard-readiness-code" title="CHECKING">확인 중</small>' in dashboard.text
    assert '<strong id="dashboard-hook-trust-value" title="CHECKING">확인 중</strong>' in dashboard.text
    assert 'id="dashboard-readiness-title">보호 실행 준비를 확인하는 중입니다.</h2>' in dashboard.text
    assert 'id="dashboard-preflight-loading"' in dashboard.text
    assert 'id="dashboard-preflight-loading-elapsed"' in dashboard.text
    assert 'id="dashboard-preflight-retry"' in dashboard.text
    assert 'id="dashboard-preflight-checks"' in dashboard.text
    assert "dashboardCheckBlocksRun(check, readinessStatus)" in dashboard.text
    assert "dashboardCheckMark(check, readinessStatus)" in dashboard.text
    assert "dashboardCheckDetailLabel(check)" in dashboard.text
    assert "상태는 단계별로 표시됩니다" in dashboard.text
    assert "if (name === 'pretool_hook') return check?.ok ? ['info', '설치됨'] : check?.stale ? ['attention', '갱신 필요'] : ['fail', '설치 필요'];" in dashboard.text
    assert "if (name === 'codex_hook_trust')" in dashboard.text
    assert "['attention', '신뢰 필요']" in dashboard.text
    assert "if (name === 'hook_verification') return check?.ok ? ['ok', '검증됨'] : ['attention', '검증 필요'];" in dashboard.text
    assert 'id="dashboard-readiness-progress"' in dashboard.text
    assert 'data-state="checking"' in dashboard.text
    assert 'role="progressbar" aria-label="보호 실행 준비 단계"' in dashboard.text
    assert "renderDashboardReadinessProgress(data.checks, dashboardReadinessCode)" in dashboard.text
    assert "renderDashboardReadinessChecking()" in dashboard.text
    assert "aria-valuetext', '보호 실행 준비 확인 중'" in dashboard.text
    assert "${completed}/${stages.length} 단계 완료" in dashboard.text
    assert "다음: ${firstPending?.[1] || '확인 필요'}" in dashboard.text
    assert "renderDashboardPreflightChecks(data.checks, dashboardReadinessCode)" in dashboard.text
    assert "dashboardPreflightRetry" in dashboard.text
    assert "dashboardPreflightTransientFailure" in dashboard.text
    assert "loadDashboardPreflight" in dashboard.text
    assert "function updateDashboardDocumentTitle(run = dashboardCurrentActiveRun)" in dashboard.text
    assert "준비 확인 중 · AIA 대시보드" in dashboard.text
    assert "document.title = dashboardReadinessOk ? '준비 완료 · AIA 대시보드' : '확인 필요 · AIA 대시보드';" in dashboard.text
    assert "startDashboardPreflightLoading" in dashboard.text
    assert "updateDashboardPreflightElapsed" in dashboard.text
    assert "PREFLIGHT_TIMEOUT" in dashboard.text
    assert "DASHBOARD_PREFLIGHT_REQUEST_TIMEOUT_MS = 30000" in dashboard.text
    assert "PREFLIGHT_UNAVAILABLE" in dashboard.text
    assert "dashboardReadinessLabels" in dashboard.text
    assert "HOOK_VERIFICATION_REQUIRED: '확인 필요'" in dashboard.text
    assert 'id="dashboard-readiness-ready-notice"' in dashboard.text
    assert 'data-dashboard-copy-command' in dashboard.text
    assert dashboard.text.count('class="text-button dashboard-command-copy"') == 3
    assert 'data-dashboard-step="setup"' in dashboard.text
    assert 'data-dashboard-step="trust"' in dashboard.text
    assert 'id="dashboard-next-steps-title"' in dashboard.text
    assert 'id="dashboard-command-status"' in dashboard.text
    assert "copyDashboardCommand" in dashboard.text
    assert "renderDashboardNextSteps" in dashboard.text
    assert "renderDashboardEmptyAction" in dashboard.text
    assert "checkByName('pretool_hook')" in dashboard.text
    assert 'id="dashboard-current-run"' in dashboard.text
    assert 'id="dashboard-current-meta"' in dashboard.text
    assert 'id="dashboard-run-count"' in dashboard.text
    assert '전체 Session ID:' in dashboard.text
    assert "sessionId.slice(0, 8)" in dashboard.text
    assert 'id="dashboard-sync-status"' in dashboard.text
    assert 'id="dashboard-sync-label"' in dashboard.text
    assert 'dashboardSyncStatus.classList.add(\'is-refreshing\')' in dashboard.text
    assert "dashboardRefreshBusyTimer" in dashboard.text
    assert "dashboardRefreshTime" in dashboard.text
    assert "자동 갱신됨 · ${dashboardRefreshTime()}" in dashboard.text
    assert '상태 확인 중…' in dashboard.text
    assert 'id="dashboard-recent-runs"' in dashboard.text
    assert 'id="dashboard-recent-empty"' in dashboard.text
    assert "refreshDashboard" in dashboard.text
    assert "renderDashboardRecentRuns" in dashboard.text
    assert "scheduleDashboardRefresh" in dashboard.text
    assert "const delay = dashboardCurrentActiveRun ? 5000 : 15000" in dashboard.text
    assert "dashboardRefreshTimer = window.setTimeout(refreshDashboard, delay)" in dashboard.text
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
    assert 'class="table-wrap history-table-wrap"' in history.text
    assert 'class="history-table"' in history.text
    assert 'data-label="작업 폴더"' in history.text
    assert "보호 실행이 진행 중입니다" in dashboard.text
    assert "Workbench 열기" in dashboard.text
    assert 'id="dashboard-primary-action" class="button primary" href="/runs/run-1/workbench">Workbench 열기</a>' in dashboard.text
    assert 'id="dashboard-readiness-label">현재 보호 실행</span>' in dashboard.text
    assert 'id="dashboard-readiness-value">실행 중</strong>' in dashboard.text
    assert 'id="dashboard-readiness-code" title="ACTIVE">보호 실행 중</small>' in dashboard.text
    assert 'id="dashboard-readiness-title">현재 보호 세션이 실행 중입니다.</h2>' in dashboard.text
    assert 'id="dashboard-readiness-status" class="status-badge status-active" title="ACTIVE">현재 실행 중</span>' in dashboard.text
    assert "active ? '현재 보호 실행' : '실행 준비'" in dashboard.text
    assert "active ? '실행 중' : (dashboardReadinessOk ? '준비 완료' : '확인 필요')" in dashboard.text
    assert "dashboardReadinessCodeElement.textContent = active ? dashboardReadinessLabels.ACTIVE" in dashboard.text
    assert 'id="dashboard-readiness-active-link" class="text-link" href="/runs/run-1/workbench">Workbench 열기 →</a>' in dashboard.text
    assert '현재 작업은 Workbench에서 계속하세요.' in dashboard.text
    assert 'id="dashboard-sensor-hook-status"' in dashboard.text
    assert 'id="dashboard-sensor-file-status" class="status-badge status-active">관찰 중</span>' in dashboard.text
    assert 'id="dashboard-sensor-file-detail" class="hint">현재 Workbench에서 Workspace 변화를 확인합니다.</span>' in dashboard.text
    assert 'id="dashboard-sensor-process-status" class="status-badge status-active">관찰 중</span>' in dashboard.text
    assert 'id="dashboard-sensor-process-detail" class="hint">현재 Workbench에서 실행 트리를 확인합니다.</span>' in dashboard.text
    assert "결과 검증" in dashboard.text
    assert "행위 관찰 전" in dashboard.text
    assert "정책 사건" in dashboard.text
    assert "Workbench 열기" in history.text
    assert "전체 실행" in history.text
    assert 'class="history-diagnostic-note"' not in history.text
    assert 'href="/runs"' in history.text
    assert 'class="is-active" aria-current="page" href="/runs"' in history.text
    assert 'id="history-result-count"' in history.text
    assert 'id="refresh-history"' in history.text
    assert 'id="history-sync-status"' in history.text
    assert 'id="history-sync-time"' in history.text
    assert "최신 상태 확인 중…" in history.text
    assert "historyStorageKey" in history.text
    assert "restoreHistoryView" in history.text
    assert "정상 완료" in history.text
    assert "완료 · 검증됨" in history.text
    assert "필터 초기화" in history.text
    assert "filterIds" in history.text
    assert "1건 표시 / 1건 전체" in history.text
    assert "실행 기록 요약" in history.text
    assert '<label class="field">작업 폴더<input id="filter-workspace"' in history.text
    assert "<th>작업 폴더</th>" in history.text
    assert "<th>정책 사건</th>" in history.text
    assert "현재 진행 중" in history.text
    assert 'data-history-quick-filter="active"' in history.text
    assert "정책 사건 실행" in history.text
    assert "실제 차단은 결과에서 확인" in history.text
    assert "data-active=" in history.text
    assert "activeOnly" in history.text
    assert "현재 실행 중인 보호 실행만 보기" in history.text
    assert "시작 시각" in history.text
    assert "history-time" in history.text
    assert "Result Bundle 무결성 확인" in history.text
    assert 'id="filter-origin"' in history.text
    assert 'data-history-quick-filter="all"' in history.text
    assert 'data-history-quick-filter="user"' in history.text
    assert 'data-history-quick-filter="diagnostic"' in history.text
    assert "history-view-presets" in history.text
    assert "noFilters" in history.text
    assert "new URLSearchParams(window.location.search)" in history.text
    assert "window.history.replaceState" in history.text
    assert 'id="history-results-heading"' in history.text
    assert 'id="history-results-hint"' in history.text
    assert "const viewHeading = origin === 'user'" in history.text
    assert "사용자 작업" in history.text
    assert "Bundle 유효" in history.text
    assert "유효한 Result Bundle 실행만 보기" in history.text
    assert "중지 처리 중" in history.text
    assert "보호 실패" in history.text
    assert "READY_UNVERIFIED" in history.text
    assert "실행 중 · 행위 관찰 전" in history.text
    assert 'id="history-pagination"' in history.text
    assert 'id="history-prev"' in history.text
    assert 'id="history-next"' in history.text
    assert "historyPageSize = 20" in history.text
    assert "/runs/run-1/result" not in history.text


def test_run_history_labels_aia_diagnostic_runs_without_hiding_them() -> None:
    service = FakeService()
    service.list_runs = lambda: [{
        "session_id": "diagnostic-run",
        "status": "ABORTED",
        "workspace": "C:/Users/tester/AppData/Local/Temp/aia-hook-verify-demo",
        "policy": {"id": "basic", "version": "1.0"},
        "incident_count": 0,
        "bundle_status": "VALID",
        "protection_state": "ABORTED_VERIFIED",
        "launch_mode": "new_terminal",
        "result_url": "/runs/diagnostic-run/result",
        "created_at": "2026-01-01T00:00:00+00:00",
    }]

    response = TestClient(create_app(service)).get("/runs")

    assert response.status_code == 200
    assert "AIA 자체 진단 실행 1건이 포함되어 있습니다." in response.text
    assert "Hook 연결 검증용 임시 Workspace" in response.text
    assert 'data-diagnostic="yes"' in response.text
    assert 'id="filter-origin"' in response.text


def test_history_surfaces_orphaned_runs_with_quick_filter() -> None:
    service = FakeService()
    service.list_runs = lambda: [{
        "session_id": "orphaned-run",
        "status": "RUNNING",
        "workspace": "C:/workspace",
        "policy": {"id": "basic", "version": "1.0"},
        "incident_count": 0,
        "bundle_status": "PENDING",
        "protection_state": "ORPHANED_DEGRADED",
        "runtime_reconciliation": {"orphaned": True},
        "run_classification": "LIVE_PROTECTED_RUN",
        "launch_mode": "web_terminal",
        "created_at": "2026-01-01T00:00:00+00:00",
    }]

    history = TestClient(create_app(service)).get("/runs")

    assert history.status_code == 200
    assert "정리 검토가 필요한 실행이 1건 있습니다." in history.text
    assert 'data-history-quick-filter="orphaned"' in history.text
    assert 'id="history-filters"' in history.text
    assert "ORPHANED_DEGRADED" in history.text


def test_ended_valid_runs_open_result_bundle_from_primary_session_link() -> None:
    service = FakeService()
    service.list_runs = lambda: [{
        "session_id": "ended-run",
        "status": "COMPLETED",
        "workspace": "C:/workspace",
        "policy": {"id": "basic", "version": "1.0"},
        "incident_count": 0,
        "bundle_status": "VALID",
        "protection_state": "COMPLETED_VERIFIED",
        "launch_mode": "web_terminal",
        "result_url": "/runs/ended-run/result",
        "created_at": "2026-01-01T00:00:00+00:00",
    }]
    client = TestClient(create_app(service))

    dashboard = client.get("/")
    history = client.get("/runs")

    assert 'href="/runs/ended-run/result" title="전체 Session ID: ended-run"' in dashboard.text
    assert 'href="/runs/ended-run/result" title="결과 보기"' in history.text
    assert 'title="전체 Session ID: ended-run">결과 Bundle</span>' in history.text
    assert "Workbench 열기" not in history.text
    assert "결과 보기" in dashboard.text


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
    history = client.get("/runs")

    assert "현재 실행 중인 보호 세션이 없습니다" in dashboard.text
    assert "보호 실행이 진행 중입니다" not in dashboard.text
    assert "이전 보호 실행이 현재 연결되어 있지 않습니다" in dashboard.text
    assert 'id="dashboard-stale-run"' in dashboard.text
    assert 'href="/runs/stale-run"' in dashboard.text
    assert "연결 끊김" in dashboard.text
    assert "보호 경계 끊김 · 정리 필요" in dashboard.text
    assert '<a href="/runs/stale-run">정리 검토</a>' in dashboard.text
    assert 'href="/runs/stale-run/workbench"' not in dashboard.text
    assert "연결 끊김: 보호 경계가 종료되어 정리 검토 필요" in history.text
    assert '<option value="ORPHANED_DEGRADED">보호 연결 끊김 · 정리 필요</option>' in history.text
    assert "보호 경계 끊김 · 정리 필요" in history.text
    assert '<a href="/runs/stale-run">정리 검토</a>' in history.text
    assert 'href="/runs/stale-run/workbench"' not in history.text


def test_live_run_prioritizes_orphaned_state_over_stale_running_snapshot() -> None:
    service = FakeService()
    original_get_run_status = service.get_run_status

    def orphaned_status(session_id):
        status = original_get_run_status(session_id)
        status["runtime_reconciliation"] = {
            "status": "STALE_PROCESS_GONE",
            "orphaned": True,
            "action": "REVIEW_AND_RESTART",
        }
        return status

    service.get_run_status = orphaned_status
    client = TestClient(create_app(service))

    run = client.get("/runs/run-1")

    assert run.status_code == 200
    assert 'title="ORPHANED">연결 끊김 · 정리 필요</div>' in run.text
    assert 'title="ORPHANED">AIA 연결 끊김 · 정리 필요</strong>' in run.text
    assert 'title="ORPHANED">연결 끊김 · 정리 필요</strong>' in run.text
    assert "연결 끊김 · 최종 기록 확인 필요" in run.text
    assert 'id="interactive-instructions" class="notice success" hidden' in run.text
    assert "AIA 보호 연결이 종료되어 현재 보호를 확인할 수 없습니다." in run.text
    assert "이전 보호 실행의 Agent Root가 종료되어 AIA 보호 연결이 끊겼습니다." in run.text
    assert "The AIA coordinator is no longer live" not in run.text


def test_workbench_disables_input_and_marks_sensors_when_runtime_is_orphaned() -> None:
    service = FakeService()
    original_get_run_status = service.get_run_status

    def orphaned_status(session_id):
        status = original_get_run_status(session_id)
        status["protection"] = {**status["protection"], "state": "ORPHANED_DEGRADED"}
        status["runtime_reconciliation"] = {
            "status": "STALE_PROCESS_GONE",
            "orphaned": True,
            "action": "REVIEW_AND_RESTART",
        }
        return status

    service.get_run_status = orphaned_status
    client = TestClient(create_app(service))

    workbench = client.get("/runs/run-1/workbench")

    assert workbench.status_code == 200
    assert "AIA 보호 연결이 끊겨 작업창을 사용할 수 없습니다." in workbench.text
    assert "연결 끊김 · 정리 필요" in workbench.text
    assert '>연결 끊김 · 정리 필요</span>' in workbench.text
    assert 'AIA 연결 끊김 · 정리 필요</dd>' in workbench.text
    assert 'id="terminal-output" class="terminal-output' in workbench.text
    assert "AIA 보호 연결이 끊겨 작업창을 사용할 수 없습니다. 실행 기록에서 상태를 확인하세요." in workbench.text
    assert "eventDecisionBadge" in workbench.text
    assert "마지막 기록 · ${text}" in workbench.text
    assert 'id="terminal-input-proxy"' in workbench.text
    assert 'placeholder="AIA 보호 연결이 끊겨 작업창을 사용할 수 없습니다."' in workbench.text
    assert "sensor-disconnected" in workbench.text
    assert "!protectionDisconnected" in workbench.text


def test_workbench_hides_input_navigation_when_run_is_ended() -> None:
    service = FakeService()
    original_get_run_status = service.get_run_status

    def ended_status(session_id):
        status = original_get_run_status(session_id)
        status["phase"] = "ABORTED"
        status["session"] = {**status["session"], "status": "ABORTED"}
        status["protection"] = {**status["protection"], "state": "ABORTED_DEGRADED"}
        return status

    service.get_run_status = ended_status
    client = TestClient(create_app(service))

    workbench = client.get("/runs/run-1/workbench")

    assert workbench.status_code == 200
    assert 'class="terminal-focus-link" href="#terminal-input-proxy" data-terminal-focus hidden' in workbench.text
    assert 'id="terminal-input-proxy"' in workbench.text
    assert 'disabled></textarea>' in workbench.text
    assert 'id="terminal-send" class="button primary terminal-send" type="submit" disabled' in workbench.text
    assert 'id="workbench-howto-title">다음 단계</h2>' in workbench.text
    assert 'id="workbench-context-title">실행 정보</h2>' in workbench.text
    assert 'data-howto-title>결과 확인</strong>' in workbench.text
    assert 'data-howto-title>정책 사건 검토</strong>' in workbench.text


def test_workbench_changes_next_steps_when_runtime_is_orphaned() -> None:
    service = FakeService()
    original_get_run_status = service.get_run_status

    def orphaned_status(session_id):
        status = original_get_run_status(session_id)
        status["protection"] = {**status["protection"], "state": "ORPHANED_DEGRADED"}
        status["runtime_reconciliation"] = {
            "status": "STALE_PROCESS_GONE",
            "orphaned": True,
            "action": "REVIEW_AND_RESTART",
        }
        return status

    service.get_run_status = orphaned_status
    client = TestClient(create_app(service))

    workbench = client.get("/runs/run-1/workbench")

    assert workbench.status_code == 200
    assert 'id="workbench-howto-title">복구 검토</h2>' in workbench.text
    assert 'id="workbench-context-title">실행 정보</h2>' in workbench.text
    assert 'data-howto-title>정리 상태 확인</strong>' in workbench.text
    assert 'data-howto-title>실행 기록 검토</strong>' in workbench.text
    assert 'data-howto-title>새 보호 실행</strong>' in workbench.text


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
