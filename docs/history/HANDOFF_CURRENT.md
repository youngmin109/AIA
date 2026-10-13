# AIA 현재 상태 핸드오프

> 이 문서는 2026-09-22 기준 AIA 프로젝트의 다음 대화방용 공식 현재 상태 문서다.
> 새 작업자는 이 파일과 `AGENTS.md`를 먼저 읽고 작업을 시작한다.
>
> `HANDOFF_EPIC_000_RECOVERED.md`는 2026-09-16의 과거 복구 스냅샷이다. 현재
> 브랜치·커밋·작업 트리·테스트 결과와 다르므로 역사 기록으로만 보존하며,
> 현재 상태의 기준으로 사용하지 않는다.

## 1. 현재 목표와 작업 방향

현재 사용자는 AIA를 전체적으로 재설계하려고 한다. 지금 상태는 새 설계를 바로
구현하기 위한 작업 트리가 아니라, 새 대화방에서 비교하고 되돌릴 수 있는 재설계
전 기준선이다.

현재 제품 범위는 다음으로 고정되어 있다.

- Windows 11
- Codex CLI
- 사용자가 이미 만든 Workspace
- Hook Sensor
- File Sensor
- Process Sensor
- 정책 판정과 보호 실행
- Evidence·Recovery·Integrity 결과

현재 범위에서 제외된 항목은 MCP, Claude, 외부 Agent, 네트워크 보안, OS 전체
보호다. 새 대화방에서 범위를 넓히기 전에 현재 기준선과 보안 불변식을 먼저
검토해야 한다.

현재 사용자의 목표는 “기존 구현을 버리지 않고, 현재 상태를 안전하게 보존한 뒤
제품 구조를 다시 설계하는 것”이다. 이 문서는 그 기준선을 설명한다.

## 2. 현재 기준선 메타데이터

| 항목 | 현재 확인값 |
|---|---|
| 프로젝트 루트 | `C:\workspace\01_projects\aia-mvp` |
| 기준일 | 2026-09-22 |
| Python 요구 버전 | `>=3.13,<3.14` |
| 프로젝트 버전 | `0.1.29` |
| 작업을 시작한 원래 브랜치 | `codex/simple-ux-three-pages` |
| 원래 HEAD | `10a3fec42557d4bfbd767ec42ecc41c506025145` |
| 원래 HEAD 제목 | `fix: reconcile interrupted preparation runs` |
| 현재 안전 브랜치 | `codex/safepoint-aia-before-rework-2026-09-22` |
| Git 원격 | 현재 설정된 원격 없음 |
| 원래 작업 트리 | 추적 파일 18개가 미커밋 상태 |
| 기존 핸드오프 | `HANDOFF_EPIC_000_RECOVERED.md`, 2026-09-16 스냅샷 |

현재 안전 브랜치는 원래 작업 트리의 미커밋 변경을 포함한 상태에서 생성했다.
핸드오프 문서와 현재 소스 변경을 포함한 기준 커밋은 아래와 같다.

```text
안전 브랜치: codex/safepoint-aia-before-rework-2026-09-22
기준 커밋: b49e9fa (`docs: record current AIA handoff baseline`)
기준 태그: aia-pre-rework-2026-09-22
복귀 방법: git switch codex/safepoint-aia-before-rework-2026-09-22
```

## 3. 현재 아키텍처

현재 AIA Core의 보호 실행 흐름은 다음과 같다.

```text
Protected Run
  → Active Policy Freeze
  → Workspace Lease
  → Safe Checkpoint
  → Sensor Readiness
  → Protected Codex Launch
  → Raw Runtime Evidence
  → Normalization
  → Canonical Action
      ├→ Policy Evaluation
      └→ Attribution
  → Enforcement Gate
  → Enforcement Result
  → Recovery
  → Integrity Verification
  → Session Finalization
  → Audit / Result Bundle
```

주요 코드 영역은 다음과 같다.

- `src/aia/`: 보호 실행, 정책, 증거, 센서, 집행, 복구, 무결성, CLI Core
- `src/aia_app/`: 실행 서비스와 Workbench 터미널 세션
- `src/aia_web/`: FastAPI 로컬 콘솔, API, WebSocket, Jinja 템플릿, 정적 자원
- `src/aia_desktop/`: WebView2 기반 `AIA.exe` 데스크톱 셸
- `tests/`: Core·센서·웹·터미널·데스크톱·Actual Codex·평가 테스트
- `scripts/product_evaluation/`: Fixture 및 Actual Codex 평가 실행기와 보고서
- `policies/profiles/`: 예시 정책 프로필
- `docs/`: 제품 정의, 아키텍처, 설치, 평가, 기술 문서, 제한사항

웹 Workbench의 현재 인터페이스는 다음과 같다.

```text
GET /runs/{session_id}/workbench
GET /api/runs/{session_id}/terminal/status
WS  /api/runs/{session_id}/terminal
```

AIA는 웹 Workbench에서 센서·정책·사건 결과를 표시한다. 정책 권한은 UI가
가지며, Workbench는 Security Authority가 아니라 Evidence Viewer 역할을 한다.

## 4. 지금까지 완료한 기능

### AIA Core

- Protected Run 생성
- Policy Freeze
- Workspace Lease
- Safe Checkpoint
- Hook·File·Process Sensor 준비
- Codex 자식 프로세스 실행
- Raw Evidence 수집
- Normalization과 Canonical Action
- Policy Evaluation
- Attribution
- Enforcement Gate
- 실제 차단 결과와 실행 결과의 분리
- Recovery와 Integrity Verification의 분리
- Session Finalization
- Audit와 Result Bundle
- Evidence tamper 검증

### Hook·File·Process Sensor

- Codex PreToolUse Hook 설치·Trust 상태 확인·실시간 검증 경로
- Workspace 파일 변화를 관찰하는 File Sensor
- AIA가 시작한 Agent Root와 자식 프로세스를 관찰하는 Process Sensor
- Hook·File·Process Evidence를 Result Bundle과 연결
- 지원하지 않는 도구 경로를 보호 범위 밖으로 명시하는 처리

현재 문서에 기록된 Actual Codex 결과에서는 Codex 0.154.0의 Bash,
`apply_patch`, `.env` 읽기 시도에서 PreToolUse deny와 부작용 없음이 확인됐다.
이 결과는 과거 disposable 검증의 증거이며, 현재 Workbench의 최신 대화형 응답이
정상 전달된다는 증거와는 구분해야 한다.

Process Manager는 별도 Windows smoke에서 Root·Child·Grandchild 종료와
unrelated process 보존을 확인했다. 이것은 사용자 중지와 프로세스 트리 종료
계약의 증거이며, 모든 정책 위반에 대한 자동 destructive PROCESS 집행을 의미하지
않는다.

### 로컬 콘솔과 Workbench

- 로컬 FastAPI 콘솔
- 대시보드
- 새 보호 실행 화면
- 실행 기록
- Live Run
- Workbench
- Incident 및 Result 화면
- Workspace·정책·실행 상태 표시
- Hook·File·Process Sensor 상태 표시
- 안전한 이벤트 요약과 차단 사건 표시
- Evidence·Recovery·Integrity 상태 표시
- 브라우저와 Codex pseudo terminal 사이의 양방향 WebSocket
- 기존 별도 Windows 터미널 실행 경로 `new_terminal` 유지
- 작업 중·연결 중·입력 대기·응답 지연 상태 표시 시도

### Windows 제품화

- PyInstaller `onedir` 방식의 `AIA.exe`
- 진단용 `aia-cli.exe`
- Embedded Uvicorn 로컬 서버
- `127.0.0.1` 바인딩
- WebView2 기반 데스크톱 창
- 설치·실행·진단용 빌드 스크립트
- WebView2 Runtime과 Codex CLI를 별도 설치 대상으로 분리

### UI와 폰트

- 밝은 Glass-box 스타일
- 별·빛·궤도 형태의 배경 효과
- Workbench의 좌측 실행 정보·중앙 작업창·우측 보안 패널·하단 요약 구조
- 터미널 높이와 빈 공간 조정
- Workbench 내부 웹 UI에 번들된 Pretendard Variable 폰트와 OFL 라이선스 파일
- 별도 Windows Terminal 창의 폰트는 변경하지 않음

### 평가·문서·배포

- 결정론적 Fixture 평가
- AIA OFF/AIA ON 비교 평가 구조
- Plotly 기반 오프라인 HTML 보고서
- 예시 정책 프로필
- 설치·지원·보안·기여·아키텍처 문서
- 기술 참고 HTML과 센서·정책 원리 PDF
- Windows 실행 파일 빌드와 릴리스 문서

## 5. 현재 미커밋 변경 사항

현재 원래 작업 트리에는 다음 18개 추적 파일의 변경이 있었다. 이 변경들은
안전 브랜치에 보존할 대상이다.

| 파일 | 현재 변경 목적 |
|---|---|
| `scripts/build-windows.ps1` | PyInstaller에 `winpty` 전체 수집을 추가해 패키지 터미널 런타임을 포함 |
| `src/aia/cli.py` | Frozen 환경에서 형제 `aia-cli.exe`를 우선 찾도록 CLI 경로 개선 |
| `src/aia/codex_installation.py` | 패키지 Hook command가 형제 `aia-cli.exe`를 우선 사용하도록 개선 |
| `src/aia_app/service.py` | 완료 실행 표시 캐시, 동시 런타임 상태 기록 충돌 방지, 임시 파일 고유화 |
| `src/aia_app/terminal.py` | 패키지 AIA에서 WinPTY backend 사용, 프로세스 종료 전 출력 drain 보장 |
| `src/aia_desktop/launcher.py` | 자식 서버 프로세스 대신 Embedded Uvicorn 사용, WebView freeze 방지, GUI stdio 처리 |
| `src/aia_web/__main__.py` | Frozen 서버 모드의 stdout/stderr 처리 |
| `src/aia_web/app.py` | 터미널 출력 batching, WebSocket send timeout, replay 제한, status polling 개선 |
| `src/aia_web/templates/live_run.html` | stale run·reconcile 상태 설명 개선 |
| `src/aia_web/templates/new_run.html` | stale run·reconcile 상태 설명 개선 |
| `src/aia_web/templates/setup.html` | stale run·reconcile 상태 설명 개선 |
| `src/aia_web/templates/workbench.html` | Codex 초기화 대기, 입력 제출 settle/echo 대기, 출력 chunk 렌더링, reconnect 안내 |
| `tests/test_aia_app.py` | 동시 runtime state write와 완료 실행 캐시 검증 |
| `tests/test_aia_desktop.py` | Embedded server lifecycle, GUI stdio, WebView bridge 검증 |
| `tests/test_aia_terminal.py` | WinPTY backend와 종료 출력 처리 검증 |
| `tests/test_aia_web.py` | Workbench terminal, WebSocket batching, status throttling, render chunk 검증 |
| `tests/test_cli.py` | Frozen 패키지의 형제 CLI 경로 검증 |
| `tests/test_codex_installation.py` | Frozen Hook command 경로 검증 |

이 목록은 “변경이 완전히 제품 요구를 만족했다”는 뜻이 아니다. 새 대화방에서는
각 diff를 먼저 검토하고, 실제 Codex 대화형 실행으로 동작을 다시 확인해야 한다.

## 6. 주요 문제와 작업 사건

아래는 사용자 대화와 프로젝트 파일에서 확인 가능한 사건이다. 원인과 해결 여부를
확정할 수 없는 항목은 그렇게 표시한다.

| 사건 | 분류 | 현재 기록 |
|---|---|---|
| `uv run aia`가 Windows Application Control `os error 4551`로 실행되지 않음 | 확인됨 | README에 `python -m aia.cli` 우회 실행 경로가 기록됨. 정책 허용 여부는 환경 의존 |
| PyInstaller 실행 파일에서 상대 import 오류 | 사용자 보고·해결 시도 | 현재 데스크톱/CLI 패키지 구조와 경로 처리를 수정했고 최신 AIA.exe Smoke는 실행됨 |
| WebView2가 설치되어도 없다고 표시됨 | 사용자 보고·부분 검증 | 현재 환경의 공식 AIA.exe는 WebView2 창을 열었음. 미설치·다중 런타임 환경은 별도 검증 필요 |
| AIA Hook 자동 설정 버튼을 누르면 응답 없음 | 사용자 보고 | 과거 UI 사건. 현재 코드의 최신 자동 설정 전체 흐름은 새 사용자 환경에서 재검증하지 않음 |
| Codex Hook Trust는 되었으나 연결 검증 실패 | 사용자 보고 | Hook Trust와 Session-bound Event는 별도 개념. 최신 실제 사용자 흐름은 재검증 필요 |
| Workbench에서 Codex 응답이 보이지 않거나 늦게 보임 | 사용자 보고·현재 미검증 | WebSocket batching, WinPTY, render chunk, submit wait를 보강했지만 최신 실제 대화형 응답 성공은 증명하지 않음 |
| 한글 입력과 IME 조합 중 Enter 처리 문제 | 사용자 보고·현재 미검증 | Workbench 입력 경로에 관련 처리가 있으나 실제 IME 사용 검증이 필요 |
| `root_process_gone` | 사용자 보고 | 보호 실행의 Agent Root 상태 오류로 기록됨. Nox 등 보호 범위 밖 프로그램을 원인으로 단정하지 않음 |
| `STALE_PROCESS_GONE` | 확인됨 | 이전 실행 정리 상태. reconcile 흐름과 안내 문구가 존재하며 자동 강제 종료하지 않음 |
| `RECORDED_AGENT_ROOT_NOT_PROVEN_GONE` | 확인됨 | 기록된 Agent Root가 사라졌다고 증명되지 않으면 새 실행을 막는 보수적 상태 |
| Process Sensor가 고장난 것처럼 보임 | 사용자 보고·현재 미검증 | Process Manager의 별도 smoke는 통과했지만 최신 Workbench 실사용 표시는 재검증 필요 |
| 보호 실행 후 `LAUNCH_FAILED` | 사용자 보고·부분 검증 | 최신 공식 AIA.exe 단순 실행은 통과했지만 실제 Codex 보호 실행은 별도 확인 필요 |
| 터미널 작업창의 빈 공간과 높이 불균형 | 확인됨·수정됨 | Flex/Grid와 패널 높이 관련 UI 변경이 적용됨. 작은 화면과 실제 실행에서 재검증 필요 |
| UI가 복잡하고 난잡하다는 피드백 | 사용자 결정 | 쉬운 세팅·쉬운 사용·쉬운 결과 해석 방향으로 단순화했으나 현재 사용성은 재평가 대상 |
| Pretendard 적용 요청 | 확인됨 | 웹 콘솔 자원에 `PretendardVariable.woff2`와 `OFL.txt`가 존재한다. 별도 Windows Terminal은 제외 |
| 공식 Windows 빌드 실행 | 확인됨 | 2026-09-21 `dist/windows/AIA/AIA.exe`가 WebView2 창과 `127.0.0.1:8787` API를 열었음 |

## 7. 테스트와 빌드 증거

### 자동 테스트

마지막으로 기록된 전체 테스트 결과는 다음과 같다.

```text
702 passed, 3 skipped, 2 warnings
```

이 전체 결과는 마지막 Workbench 렌더 chunk 수정 직전의 전체 실행 결과다. 그 뒤
추가된 렌더 chunk 변경에 대해서는 다음 대상 테스트를 별도로 실행했고 통과했다.

```text
pytest -q tests/test_aia_web.py -k "workbench_terminal or web_terminal"
```

추가로 `git diff --check`는 통과했다. 줄바꿈 형식에 관한 Git 경고는 있었지만
diff 오류는 없었다.

### 공식 Windows 빌드 Smoke

마지막으로 확인한 빌드 산출물은 다음과 같다.

```text
dist/windows/AIA/AIA.exe
dist/windows/aia-cli/aia-cli.exe
```

확인된 동작:

- `AIA.exe`가 눈에 보이는 WebView2 창을 열었다.
- 창 제목은 `AIA · Protected Workbench`였다.
- `127.0.0.1:8787`에서 로컬 API가 `200`을 반환했다.
- `/api/runs` 첫 요청은 약 906ms, 반복 요청은 약 116ms였다.
- Smoke 종료 후 AIA 프로세스는 정리됐다.

이 결과는 패키지·서버 시작 증거다. 실제 Codex 입력, 정상 응답, 차단, 센서
이벤트 전달까지 성공했다는 증거로 해석하지 않는다.

### 과거 Actual Codex 검증

문서에 기록된 과거 검증에는 Codex 0.154.0의 Bash·`apply_patch`·`.env` 읽기
차단, deny, 부작용 없음, Bundle VALID가 포함되어 있다. 또한 Hook verify와
Process Manager smoke 결과가 있다. 이 결과들은 각각 실행 당시의 disposable
환경과 조건을 가진 증거이며, 현재 최신 작업 트리의 모든 대화형 UI 동작을
자동으로 보증하지 않는다.

## 8. 생성물·무시 파일·개인 실행 상태

다음은 소스 기준선과 구분해야 하는 로컬 생성물이다.

- `dist/`
- `.tmp-build/`
- `.venv/`
- `evaluation/` 실행 결과
- `tmp/`
- `.pytest_cache/`
- `.verify-*` 및 Debug 검증 폴더
- `__pycache__/`
- 로그·SQLite/DB·JSONL 감사 기록
- 개인 Workspace와 `.aia`·`.codex` 상태

이 항목들은 새 대화방에서 제품 소스의 최신 구현으로 해석하지 않는다. 평가 결과를
확인할 때는 실행 시각·코드 버전·Fixture/Actual Codex 여부를 함께 확인한다.

## 9. 현재 문서의 불일치와 해석 주의

- 기존 `HANDOFF_EPIC_000_RECOVERED.md`는 현재 브랜치와 HEAD를 반영하지 않는다.
- 기존 핸드오프는 작업 트리가 clean이라고 기록했지만 현재 기준선에는 추적 파일
  18개의 미커밋 변경이 있었다.
- 기존 핸드오프의 테스트 수 `621 passed`와 `19 passed`는 최신 전체 테스트 수가
  아니다.
- `docs/epics/EPIC-019-LOCAL-SECURITY-CONSOLE.md`는 WebSocket 미사용으로 설명하지만
  현재 Workbench는 `WS /api/runs/{session_id}/terminal`을 구현한다.
- Pretendard 관련 과거 기록은 “미적용”과 “번들 추가”가 함께 있어 현재 파일을
  기준으로 판단해야 한다.
- 과거 평가 산출물과 현재 코드·패키지 Smoke 결과를 하나의 결과로 합치지 않는다.
- 현재 문서와 테스트가 통과해도 실제 최신 Codex 대화형 응답 전달까지 증명된 것은
  아니다.

## 10. 보안 불변식과 절대 변경 금지 사항

새 대화방에서 구조를 재설계하더라도 다음 원칙은 별도 결정 없이 변경하지 않는다.

- `Policy Violation alone != Kill`
- `EXACT` Attribution만 자동 containment 권한과 연결할 수 있다.
- `PROCESS`, `TEMPORAL`, `UNKNOWN` Attribution은 자동 종료 권한으로 승격하지 않는다.
- Checkpoint는 Containment의 선행 조건이 아니다.
- 유효한 Checkpoint가 있을 때만 Recovery를 수행한다.
- Recovery 결과 `RESTORED`와 Integrity 결과 `VERIFIED`는 별도 상태다.
- UI와 Workbench는 Security Authority가 아니다.
- raw command, secret, 전체 tool payload, 전체 파일 내용을 UI에 노출하지 않는다.
- Ground Truth를 임의로 바꾸지 않는다.
- 지원 범위 밖 도구를 보호한다고 주장하지 않는다.
- `PROCESS` Evidence만으로 특정 파일 Writer를 증명하지 않는다.
- Hook deny 응답만으로 실제 실행 차단을 확정하지 않는다. 실제 부작용 없음과
  실행 결과 확인이 필요하다.

## 11. 다음 대화방 작업 시작 절차

새 작업자는 다음 순서를 지킨다.

```text
1. AGENTS.md 읽기
2. HANDOFF_CURRENT.md 읽기
3. git status --short --branch 확인
4. 현재 브랜치와 안전 기준 커밋 확인
5. 기존 미커밋 변경과 안전 브랜치 diff 검토
6. 새로 갈아엎을 범위와 보존할 보안 불변식 결정
7. 기준선 전체 테스트 재실행
8. disposable Workspace에서 실제 실행이 필요한 항목을 분리 검증
9. 새 설계 문서 작성
10. 설계가 합의된 뒤에만 Core·UI·패키지 코드를 변경
```

새 대화방에서 가장 먼저 해야 할 일은 `AIA.exe`를 바로 다시 빌드하는 것이
아니다. 먼저 현재 기준선의 변경 목록과 테스트 결과를 확인하고, 새 설계가
무엇을 유지·삭제·대체하는지 결정해야 한다.

실제 검증이 필요하면 반드시 disposable Workspace와 별도 Control Root를 사용한다.
개인 Workspace, 기존 고객 DB, 실제 `.env`, 기존 `.aia` 상태를 실험 대상으로
사용하지 않는다.

## 12. 안전 기준선과 복귀 방법

현재 상태는 다음 로컬 브랜치에 보존한다.

```text
codex/safepoint-aia-before-rework-2026-09-22
```

새 설계가 실패하거나 방향이 마음에 들지 않으면 다음처럼 돌아온다.

```powershell
cd C:\workspace\01_projects\aia-mvp
git switch codex/safepoint-aia-before-rework-2026-09-22
```

이 브랜치는 현재 미커밋 소스 변경과 핸드오프 문서를 포함하는 로컬 기준선이다.
`dist`, `.venv`, 로그, DB, JSONL, 평가 실행 결과는 기준선 커밋에 포함하지
않는다.

## 13. 이 복구된 세션에서 다음 작업자가 반드시 알아야 할 점

1. 현재의 공식 기준 문서는 이 파일이며, 과거 `HANDOFF_EPIC_000_RECOVERED.md`가
   아니다.
2. 현재 상태는 완성된 보안 제품이라고 단정할 수 없다. 프로젝트 문서의 표현은
   제품 형태를 갖춘 `0.1 Alpha`다.
3. AIA Core는 많은 결정론적 테스트와 일부 Actual Codex 검증을 갖고 있지만,
   Workbench의 최신 Codex 대화형 응답 전달은 반드시 다시 확인해야 한다.
4. 현재 작업 트리는 원래 `codex/simple-ux-three-pages`에서 18개 파일이 수정된
   상태였고, 이 변경들은 새 설계 전에 검토해야 한다.
5. 공식 AIA.exe가 실행된 것은 확인했지만 이것만으로 Hook·File·Process Sensor의
   최신 실사용 성공을 의미하지 않는다.
6. `root_process_gone`은 보호 실행의 Agent Root 상태 문제로 다뤄야 하며, 보호
   범위 밖 프로그램을 원인으로 단정하지 않는다.
7. stale Protected Run은 자동으로 강제 종료하지 않는다. Agent Root가 사라졌다는
   증거와 reconcile 절차를 확인해야 한다.
8. 새 기능을 추가하기 전에 `Policy Violation alone != Kill`과 Attribution·Recovery·
   Integrity 분리를 보존해야 한다.
9. UI를 단순화하더라도 보안 Core의 판정·증거·검증 절차를 UI 편의 때문에 우회하지
   않는다.
10. 새 대화방의 첫 결과물은 코드 수정이 아니라 현재 기준선과 새 설계의 차이를
    정리한 결정 문서여야 한다.
