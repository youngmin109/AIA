# EPIC-019 — Local Security Console

## 목적

EPIC-019는 AIA Core 위에 붙는 P1 로컬 애플리케이션 계층이다. 사용자가 보호 실행을 시작하고, 실행 중 보호 상태와 관찰된 행위를 확인하며, 완료된 Result Bundle과 Incident를 읽을 수 있는 로컬 콘솔을 제공한다.

이 EPIC은 Core의 Policy, Attribution, Enforcement, Recovery, Integrity 권한을 다시 구현하지 않는다. 콘솔은 기존 Core API를 호출하고 Core가 생성한 결과를 안전한 화면 DTO로 변환한다.

## 실행 경계

- 기본 HTTP bind: `127.0.0.1:8787`
- 외부 인증/로그인 없음
- 외부 네트워크 연동 없음
- HTTP polling 사용, WebSocket 미사용
- 저장소는 기존 Core의 Control Root와 Result Bundle을 사용
- 별도 Database를 추가하지 않음
- frontend framework 없이 Jinja2, vanilla JavaScript, CSS만 사용
- 공식 지원 Agent는 Codex이며 Claude UI/Adapter는 추가하지 않음

## 계층 구조

```text
Browser
  ↓ HTTP / polling
FastAPI + Jinja2 Local Security Console
  ↓ DTO / RunApplicationService
Existing AIA Core APIs
  ↓
Protected Run Session → Readiness → Protected Launcher
  ↓
Raw Evidence → Normalization → Attribution / Policy → Enforcement
  ↓
Session Finalizer → Result Bundle / Audit / Integrity Verification
```

`RunRegistry`는 진행 중인 실행의 화면 상태만 보관하는 in-memory registry다. 보안 판정의 권위 있는 원본은 Core 객체와 검증된 Result Bundle이다. 완료 후 화면이 Registry에 의존하지 못하면 `ResultBundleReader`가 `VALID` bundle만 읽는다.

서버가 재시작되면 진행 중인 Registry 상태는 복원하지 않는다. 이미 완료된 실행은 Session ID와 Control Root를 알고 있으면 Result Bundle에서 다시 읽을 수 있다. 완료 실행 전체 목록이나 active run 복원은 이번 EPIC 범위가 아니다.

## 화면

1. **New Protected Run** — Workspace, Codex, model, policy profile, ENFORCE/AUDIT, task prompt를 입력한다.
2. **Live Run** — Session/phase, checkpoint, lease, sensor health, action timeline을 1초 polling으로 표시한다.
3. **Incident Detail** — 무슨 일이 있었는지, 왜 분류했는지, AIA가 무엇을 입증할 수 있는지를 보여준다. `PROCESS + REFUSE`는 자동 종료를 거부한 사유를 표시한다.
4. **Result** — Session, Recovery, Integrity, Bundle 상태와 action 결과를 분리해 표시하고 report/evidence metadata/result JSON 링크를 제공한다.

## 안전한 표시 계약

- 화면 DTO는 canonical path, source/destination path, target kind, command fingerprint만 허용한다.
- raw command, tool payload, evidence payload 값은 화면 HTML에 넣지 않는다.
- Raw Evidence 화면은 `evidence_id`, source, record type, observation stage, payload key 목록만 표시한다.
- Result Bundle은 무결성 검증이 `VALID`일 때만 읽는다. 위반 시 `Evidence Bundle Integrity Failure`로 처리한다.
- Policy 판단과 Attribution 판단은 Web 계층에서 만들지 않는다.
- 사용자가 고른 Profile은 Run 생성 시 Core `resolve_profile`을 통해 한 번 해석하고, 실행 중에는 해당 resolved policy를 사용한다.

## HTTP 계약

```text
GET  /                         New Protected Run
POST /api/runs                 202 + redirect_url/session_id/status
GET  /runs/{session_id}        Live Run
GET  /api/runs/{session_id}    Live status JSON
GET  /api/runs/{session_id}/actions
GET  /runs/{session_id}/incidents/{action_id}
GET  /runs/{session_id}/result
GET  /runs/{session_id}/report
GET  /runs/{session_id}/raw-evidence
GET  /runs/{session_id}/result.json
```

입력 DTO는 허용된 key만 받고, workspace/agent/model/profile/mode/task의 타입과 크기를 검증한다. API는 잘못된 입력을 400으로 반환한다. Session ID는 Control Root 아래로 제한된 안전한 식별자만 허용한다.

## 실행 방법

```powershell
cd C:\workspace\01_projects\aia-mvp
uv sync
uv run aia-web
```

브라우저에서 [http://127.0.0.1:8787](http://127.0.0.1:8787)을 연다. Control Root를 바꾸려면 PowerShell에서 `AIA_CONTROL_ROOT`를 설정한다. host와 port는 각각 `AIA_WEB_HOST`, `AIA_WEB_PORT`로 바꿀 수 있지만, 기본값인 loopback bind를 제품 기본으로 유지한다.

## 범위 밖

이번 EPIC에서는 로그인/원격 접근, 다중 사용자 권한, Database persistence, WebSocket, GUI 기반 policy authoring, Network Security, Claude 지원, 새 Core 보안 기능을 구현하지 않는다. 대규모 Workspace 성능, 결과 bundle 보존 정책, 장기 실행 취소 UI는 후속 EPIC의 책임이다.

## 검증

- `tests/test_aia_app.py`: 입력 DTO, Registry 격리, 표시 DTO, bundle reader 경계
- `tests/test_aia_web.py`: New/Live/Incident/Result route와 secret 비노출
- `scripts/epic019_console_smoke.py`: EPIC-018의 실제 `VALID` Core Result Bundle을 읽는 read-only console smoke

실행 중인 Core run의 전체 Agent 동작은 Windows Codex 설치와 사용자가 지정한 Workspace에 의존한다. 콘솔이 Core 결과를 새로 해석하거나 보안 결정을 대신하지 않는다는 점이 이 EPIC의 핵심 경계다.
