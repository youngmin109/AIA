# AIA EPIC-000 복구 핸드오프

## 문서 기준

- 확인일: 2026-09-16
- 프로젝트 루트: `C:\workspace\01_projects\aia-mvp`
- 확인된 브랜치: `codex/workbench-ui`
- 확인된 기준 커밋: `7f0855a fix: balance workbench terminal height`
- 기준 커밋 확인 당시 작업 트리: 변경 없음
- 프로젝트 버전: `pyproject.toml`의 `0.1.29`
- 이 문서는 현재 프로젝트 파일, Git 기록, 테스트 출력, 그리고 이 대화에서 확인 가능한 사실을 정리한다. 문서에 없는 실행이나 검증을 완료했다고 가정하지 않는다.

## 1. 현재 목표

이 세션에 남아 있는 현재 작업 목표는 **실제 사용자가 체감할 수 있도록 AIA의 UI/UX를 계속 개선하는 것**이다.

제품의 현재 고정 범위는 AIA Core 위에서 Codex CLI를 보호 실행하고, Hook Sensor·File Sensor·Process Sensor가 수집한 실행 증거와 정책·집행·복구·무결성 결과를 로컬 콘솔에서 확인하게 하는 것이다. 현재 대화에서는 이 범위를 넓히지 않고 Workbench의 사용성과 시각적 완성도를 개선하는 방향으로 진행됐다.

## 2. 지금까지 완료한 작업

현재 파일과 Git 기록에서 다음 작업을 확인할 수 있다.

### Core와 보호 실행

- Protected Run, 정책 고정, Workspace Lease, Safe Checkpoint 흐름이 `src/aia`와 `src/aia_app`에 구현되어 있다.
- Hook, File, Process Runtime Sensor와 Raw Evidence, Normalization, Attribution, Policy Evaluation, Enforcement, Recovery, Integrity, Finalization, Audit/Result Bundle 관련 모듈과 테스트가 존재한다.
- Codex CLI 실행을 위한 일반 실행과 Workbench용 `web_terminal` 실행 경로가 코드에 존재한다.
- 현재 제품 문서는 지원 범위를 Windows 11, Python 3.13, uv, Codex CLI 및 AIA가 직접 시작한 실행으로 설명한다.

### 로컬 콘솔과 Workbench

- 로컬 웹 콘솔의 대시보드, 새 보호 실행, 실행 기록, Live Run, Workbench, Incident, Result 화면이 존재한다.
- `/runs/{session_id}/workbench` 화면에 Workspace·정책·실행 상태, Codex 작업창, Hook·File·Process Sensor 상태, 이벤트, 차단 사건, Evidence 영역과 실행 요약이 배치되어 있다.
- Workbench의 브라우저 작업창은 `web_terminal`과 WebSocket 연결을 사용한다. 터미널 상태 API와 센서·실행 상태 갱신 코드도 존재한다.
- 기존 별도 Windows 터미널 실행 경로인 `new_terminal`을 유지하는 코드가 존재한다.
- 작업 중 상태, 연결 상태, 마지막 출력 시각, 응답 지연 및 중지 안내를 표시하는 UI 코드가 존재한다.

### UI/UX 개선

- 어두운 화면 중심의 기존 스타일에서 밝은 색상과 유리 패널을 사용하는 Glass-box 시각 스타일로 변경했다.
- 배경에 별·빛·궤도 형태의 ambient 효과와 모션 감소 설정을 추가했다.
- Workbench를 왼쪽 실행 정보, 가운데 Codex 작업창, 오른쪽 보안 관찰 패널, 아래 실행 요약 구조로 정리했다.
- 터미널 내부 CSS Grid가 빈 행을 늘리던 문제를 세로 Flex 구조로 변경해 `작업 예시`와 입력 영역 사이의 큰 공백을 제거했다.
- 이후 Workbench의 전체 행 높이에 맞춰 중앙 터미널 패널을 늘리고, Codex 출력 영역이 남은 높이를 채우도록 조정했다.
- 최근 UI 관련 기준 커밋은 다음과 같다.
  - `ef700f5 improve: refresh console with glassbox theme`
  - `dc57092 improve: balance workbench glass layout`
  - `5558f05 fix: reduce workbench terminal whitespace`
  - `83c44d1 fix: remove stretched terminal example area`
  - `28076b6 fix: remove workbench terminal blank space`
  - `7f0855a fix: balance workbench terminal height`

### 평가와 배포 자료

- `scripts/product_evaluation` 아래에 Fixture 평가 실행기, Actual Codex 평가 실행기, 시나리오와 HTML 보고서 생성기가 있다.
- `policies/profiles` 아래에 한국어 예시 정책 프로필이 있다.
- 설치·릴리스·지원·보안·아키텍처·제한사항 문서와 EPIC 문서가 프로젝트에 포함되어 있다.
- `docs/PRODUCT-STATUS.md`에는 현재 제품을 `0.1 Alpha`로 설명하고, 결정론적 전후 평가와 Actual Codex 검증 결과를 별도로 기록한다.

## 3. 현재 구현 상태

### 실행 및 보안 Core

- 제품 정의와 아키텍처 문서에 따라 AIA는 에이전트의 내부 추론을 해석하지 않고 시스템에서 확인 가능한 Runtime Evidence를 수집·정규화·귀속·판정·집행·복구·무결성 검증·감사 결과로 연결한다.
- `AGENT_HOOK`는 Hook 입력과 PreToolUse 관련 Evidence를 다루고, `FILESYSTEM_WATCHER`는 Workspace 파일 변화를 다루며, `PROCESS_RUNTIME`은 관리 대상 프로세스 트리와 프로세스 Evidence를 다룬다.
- `Policy Violation`과 실제 차단·종료 결과가 별도 축으로 기록되도록 구현되어 있다. 결과 Bundle과 화면은 정책 판정과 실제 실행 결과를 분리해서 표시한다.
- 복구 `RESTORED`와 무결성 검증 `VERIFIED`가 별도 상태로 다뤄진다.

### 웹 UI 및 터미널

- FastAPI + Jinja2 + Vanilla JavaScript + CSS 구조다.
- 기본 로컬 바인드는 `127.0.0.1:8787`이다.
- 현재 코드에서 확인되는 Workbench 인터페이스는 다음과 같다.

  ```text
  GET  /runs/{session_id}/workbench
  GET  /api/runs/{session_id}/terminal/status
  WS   /api/runs/{session_id}/terminal
  ```

- `src/aia_app/terminal.py`의 `WinPtyTerminalSession`이 Workbench 터미널의 입력·출력·크기 변경·종료 상태를 담당한다.
- Workbench 화면은 센서·정책·사건을 표시하는 Evidence Viewer 역할을 하며, 코드상 정책 판단은 AIA Core 서비스가 담당한다.
- 현재 일반 UI의 폰트 선언은 `Inter` 우선 대체 목록이고, 터미널은 `Cascadia Mono` 우선 대체 목록이다. 프리텐다드 폰트 파일이나 `Pretendard` 선언은 현재 프로젝트에서 확인되지 않는다.

### Git 및 공개 상태

- 현재 Git 원격은 `git remote -v` 출력에서 확인되지 않았다.
- 현재 브랜치는 기본 브랜치가 아닌 `codex/workbench-ui`다.
- `.gitignore`에는 가상환경, Python 캐시, 로그·빌드 산출물, 일부 평가 실행 결과 경로가 포함되어 있다.
- 저장소에는 기존 평가 산출물과 문서가 이미 추적되어 있다. 공개 저장소에 다시 올릴 때는 기존 파일을 자동으로 안전하다고 간주하지 말고 별도 공개 검토가 필요하다.

## 4. 주요 설계 결정

- **AIA Core가 보안 권한의 주체다.** 웹 콘솔은 Core의 상태와 검증된 결과를 읽어 안전한 표시 DTO로 보여준다.
- **지원 Agent는 Codex CLI다.** MCP, Claude, 외부 Agent, 네트워크 보안, OS 전체 보호는 현재 MVP 지원 범위가 아니다.
- **UI는 모델의 내부 생각을 표시하지 않는다.** 확인 가능한 Hook·Process·File Evidence와 정책·집행·복구·무결성 결과만 표시한다.
- **Policy Violation alone != Kill**이다. `EXACT` Attribution만 자동 containment 권한과 연결할 수 있고, `PROCESS`·`TEMPORAL`·`UNKNOWN`은 자동 종료 권한으로 승격하지 않는다.
- **Checkpoint는 Containment prerequisite가 아니다.** Rollback은 유효한 Checkpoint가 있을 때만 수행하고, 복구 후 Integrity Verification을 필수로 한다.
- **실제 차단 결과를 추측하지 않는다.** Gate가 차단 결정을 냈다는 사실과 실제 도구가 실행되지 않았다는 확인을 별도로 기록한다.
- **Workspace는 사용자가 만든 기존 폴더를 선택한다.** AIA가 임의로 사용자 Workspace를 자동 생성하는 흐름으로 정의하지 않는다.
- **웹 Workbench와 별도 Windows 터미널을 함께 유지한다.** 이번 UI 개선은 Workbench 내부 화면을 대상으로 하며 별도 Windows 터미널 창은 대상에서 제외한다.
- **의존성은 최소화한다.** 현재 웹 콘솔은 별도 프론트엔드 프레임워크 없이 Jinja2·Vanilla JavaScript·CSS를 사용한다.
- **로컬 전용 경계**를 유지한다. 현재 EPIC 문서는 HTTP bind를 `127.0.0.1`로 제한하고 외부 인증·원격 접근·외부 네트워크 연동을 제공하지 않는다고 명시한다.

## 5. 생성/변경된 파일

### 이번 UI 작업에서 Git 기록으로 변경이 확인된 파일

- `src/aia_web/static/app.css` — Glass-box 스타일, ambient 배경, Workbench 레이아웃, 터미널 공백 제거와 높이 균형 조정.
- `src/aia_web/templates/base.html` — 정적 CSS 캐시 버전 갱신. 현재 `glassbox-ui-4`가 선언되어 있다.
- `src/aia_web/templates/workbench.html` — Workbench 화면과 터미널·센서·상태 표시 구조. 최근 UI 작업의 기준 화면이다.
- `tests/test_aia_web.py` — 콘솔·Workbench 렌더링과 CSS 캐시 버전 관련 검증.

### 현재 기능의 핵심 파일

- `src/aia_web/app.py` — 웹 라우트, 터미널 상태 API, Workbench WebSocket 라우트.
- `src/aia_app/service.py` — 실행 서비스와 터미널·센서 연결.
- `src/aia_app/terminal.py` — Workbench용 Windows pseudo terminal 연결.
- `src/aia_app/dto.py` — 실행 요청과 `web_terminal` 포함 입력 검증.
- `tests/test_aia_terminal.py` — 터미널 입력·출력·resize 관련 테스트.
- `tests/test_hook_sensor.py` — Hook Sensor 테스트.
- `tests/test_filesystem_sensor.py` — File Sensor 테스트.
- `tests/test_process_sensor.py` — Process Sensor 테스트.
- `scripts/product_evaluation/` — 제품 평가 실행·보고서 생성 스크립트.
- `policies/profiles/` — 예시 정책 프로필.

### 이 작업에서 새로 생성된 파일

- `HANDOFF_EPIC_000_RECOVERED.md` — 이 문서. 사용자의 요청에 따라 기존 파일은 수정하지 않고 새로 생성한다.

### 생성되지 않은 파일

- 프리텐다드 폰트 파일과 폰트 적용 변경은 아직 생성·적용되지 않았다. 프리텐다드 적용 요청 직후 대화가 중단되었고, 현재 파일에서 `Pretendard` 선언도 확인되지 않았다.

## 6. 테스트 상태

이 세션에서 확인 가능한 최근 테스트 결과는 다음과 같다.

- `uv run pytest tests/test_aia_web.py -q` → **19 passed**
- `uv run pytest --tb=no -rN` → **621 passed, 3 skipped, 2 warnings**
- `git diff --check` → 통과
- 최근 UI 수정 후 로컬 임시 서버에서 Workbench 페이지와 `app.css?v=glassbox-ui-4` 요청을 확인했고, 축소된 브라우저 화면에서 터미널 출력과 입력 영역 사이의 이전 큰 공백이 나타나지 않는 것을 확인했다.

테스트 결과의 범위는 자동 테스트와 로컬 Workbench 화면 확인이다. 이 핸드오프 생성 시점에 새 Actual Codex 보호 실행을 다시 수행한 것은 아니다.

## 7. 미완료 작업

- 현재 문서 상태는 `0.1 Alpha`이며, 프로젝트 문서 자체가 완성형 보안 제품이라고 선언하지 않는다.
- 이 대화에서 사용자가 보고한 “Codex 응답이 Workbench로 들어오지 않는 문제”는 과거에 여러 차례 제기됐다. 현재 코드에는 WebSocket·ConPTY·상태 표시가 있지만, 이 핸드오프 생성 시점에 실제 새 Codex 세션의 정상 응답 전달을 재검증하지 않았다.
- 실제 사용자가 느끼는 Workbench UI/UX 개선은 계속 진행 중이다. 현재는 레이아웃·공백·높이 균형을 조정한 상태이며, 완성 여부를 뜻하지 않는다.
- 프리텐다드 폰트의 프로젝트 포함·적용·라이선스 확인·브라우저 표시 검증이 남아 있다. 별도 Windows 터미널 창은 해당 작업 범위에서 제외한다.
- `docs/epics/EPIC-019-LOCAL-SECURITY-CONSOLE.md`는 HTTP polling 사용과 WebSocket 미사용을 명시하지만, 현재 코드에는 `WS /api/runs/{session_id}/terminal`이 존재한다. 문서와 구현의 정합성 확인이 필요하다.
- 현재 `0.1.29` 코드 기준으로 최신 Actual Codex End-to-End 결과를 이 작업에서 새로 만들지 않았다.
- GitHub 원격은 현재 확인되지 않았다. 기본 브랜치 공개나 팀 공유가 완료된 상태라고 볼 근거가 없다.
- MCP, Claude, 외부 Agent, 네트워크 보안, OS 전체 Writer 통제 등은 현재 MVP의 미지원 범위다.
- 대규모 Workspace 성능 SLA, 서명된 설치 파일, 자동 업데이트, GUI 정책 작성 등은 제품 문서의 미완료·범위 밖 항목으로 남아 있다.

## 8. 다음 작업 순서

현재 목표와 범위를 유지할 때의 다음 순서는 다음과 같다.

1. `7f0855a` 기준선과 현재 작업 트리를 확인하고, Workbench UI 변경을 이 기준선에서 별도 커밋으로 관리한다.
2. 새 disposable Workspace에서 로컬 콘솔을 시작하고, `web_terminal`의 Codex 입력·출력·연결 상태를 실제 사용자 흐름으로 재검증한다.
3. 응답이 보이지 않는 경우 CSS보다 먼저 WebSocket 연결, ConPTY 출력 수신, 세션 ID, 브라우저 재연결과 상태 polling을 순서대로 확인한다.
4. 정상 응답 전달이 확인된 뒤 Hook·File·Process Sensor 이벤트가 같은 Workbench에서 갱신되는지 확인한다.
5. 프리텐다드 파일을 적용할 때는 사용자가 제공한 파일 또는 검토된 배포 파일을 정적 자산으로 넣고, 웹 UI와 Workbench 내부 터미널 표시 영역에만 적용한다. 별도 Windows 터미널 설정은 변경하지 않는다.
6. 데스크톱 해상도에서 중앙 터미널 하단이 좌우 정보 열과 맞는지, 작은 화면에서 세로 배치와 가로 overflow가 사용 가능한지 시각 검증한다.
7. UI 변경마다 `tests/test_aia_web.py`와 전체 `pytest`를 실행하고 `git diff --check`를 수행한다.
8. UI가 안정된 뒤에만 현재 지원 범위 안의 Glass-box Timeline·Evidence 연결을 추가한다. 새로운 보안 권한이나 새로운 Agent 지원은 이 순서에 포함하지 않는다.

## 9. 주의사항

- `AGENTS.md` 규칙에 따라 현재 EPIC 범위만 수정하고, Security Invariant와 Ground Truth를 임의로 변경하지 않는다.
- `Policy Violation`만으로 프로세스를 종료하거나 `BLOCKED`·`TERMINATED`를 표시하지 않는다. 실제 실행 결과 Evidence가 있는지 확인해야 한다.
- UI에서 raw command, secret, 전체 tool payload, 전체 파일 내용을 노출하지 않는다.
- `PROCESS` Evidence는 프로세스 실행 사실과 명령행을 보여줄 수 있지만, 그 프로세스가 특정 파일을 실제로 썼다는 사실을 단독으로 증명하지 않는다.
- 기존 평가 산출물과 문서를 삭제하거나 재작성하지 않는다. 평가 결과를 새로 만들 때는 원본과 현재 코드 버전을 구분한다.
- `new_terminal`과 `web_terminal`을 혼동하지 않는다. 별도 Windows 터미널은 CSS로 제어되지 않으며 이번 프리텐다드 적용 대상도 아니다.
- 로컬 서버를 새로 띄워 화면을 확인할 때 기존 AIA 서버와 다른 프로세스가 될 수 있다. 다른 프로세스에서 읽은 실행 상태를 실제 사용자 세션의 정상 동작 증거로 해석하지 않는다.
- 현재 브랜치에는 원격이 설정되어 있지 않으므로, 이 문서 생성만으로 GitHub 공유가 되었다고 판단하지 않는다.
- 이 문서 생성 전 작업 트리는 깨끗했다. 문서 생성 후에는 이 새 파일 하나가 추적되지 않은 상태로 나타날 수 있으며, 기존 파일 변경으로 해석하지 않는다.

## 10. 이 복구된 세션에서 다음 작업자가 반드시 알아야 할 점

1. 현재 기준선은 `codex/workbench-ui`의 `7f0855a`다. 여기서 UI 작업을 이어가면 기존 공백 수정과 터미널 높이 균형 수정이 포함된 상태에서 시작한다.
2. 사용자가 말한 현재 제품 방향은 “실제 사용자가 체감하는 UI/UX를 계속 개선”하는 것이며, 기능 범위를 넓히는 것이 아니다.
3. AIA의 보안 권한은 Core에 있고 Workbench는 표시 계층이다. UI 편의를 위해 정책·Attribution·Enforcement 규칙을 우회하지 않는다.
4. 현재 Workbench 내부 터미널은 브라우저 WebSocket과 Windows pseudo terminal을 연결하는 구조다. Codex 응답 문제를 다시 다룰 때는 실제 연결과 출력 전달을 먼저 확인한다.
5. 최근 공백 문제는 `.workbench-terminal-panel`의 Grid stretch 문제에서 시작했고, 현재 `app.css`는 패널을 Flex column으로 두고 Workbench 행을 stretch하도록 되어 있다. 이 구조를 바꿀 때는 공백과 높이 균형을 함께 확인한다.
6. 프리텐다드 적용은 아직 시작되지 않았다. 폰트 파일이 없으므로 현재 화면이 프리텐다드로 고정되어 있다고 설명하면 안 된다.
7. 현재 자동 테스트는 넓은 Core·UI 계약을 검증하지만, `621 passed`가 최신 Actual Codex 실사용 세션의 정상 응답까지 증명하는 것은 아니다.
8. `docs/PRODUCT-STATUS.md`와 `docs/LIMITATIONS.md`의 제한사항을 제품 주장보다 우선해서 확인한다. 문서에 기록된 과거 평가 결과와 현재 코드의 새 검증 결과를 섞지 않는다.
9. EPIC-019 문서의 WebSocket 미사용 문구와 현재 코드의 WebSocket 구현은 불일치한다. 다음 제품화 단계에서 문서 또는 구현의 기준을 명시적으로 정리해야 한다.
10. 이번 요청에서 기존 파일은 수정하지 않았고, 루트에 이 핸드오프 문서만 새로 생성했다.

## 후속 상태 메모

이 문서는 2026-09-16 13:58경의 복구 시점 스냅샷으로 생성됐다. 이후 같은 날짜에 다음 변경이 추가됐다.

- `src/aia_web/static/fonts/PretendardVariable.woff2`를 공식 Pretendard v1.3.9 배포 파일로 추가했다.
- `src/aia_web/static/fonts/OFL.txt`에 해당 폰트의 SIL Open Font License를 포함했다.
- `src/aia_web/static/app.css`에서 웹 콘솔과 Workbench 내부 터미널 표시 영역의 폰트를 번들된 Pretendard로 연결했다.
- `src/aia_web/templates/base.html`의 CSS 캐시 버전을 `glassbox-ui-5`로 올렸다.
- `tests/test_aia_web.py`에 폰트 CSS·정적 파일·WOFF2 시그니처·라이선스 제공 검사를 추가했다.
- 이 후속 변경은 별도 Windows 터미널 창의 폰트 설정에는 적용하지 않는다.
