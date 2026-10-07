# 화면 명세 (EPIC-020)

목업 원본: `docs/ui-redesign/mockup/<화면>.dc.html` (색·간격·문구 참고용, 인라인 스타일은 옮기지 않는다).
작업 순서: `TASKS.md`. 진행 기록: `PROGRESS.md`.

## 0. 공통 규칙

### 구조
- 셸: 왼쪽 글래스 레일(AIA 로고 + 홈 / 작업창 / 정책 / 기록 / 설정) + 메인 영역 + 화면 위를 떠다니는 가디언 펫(끌어서 이동, 누르면 도움말, ⑩에서 끄기).
- 뷰 키(`ShellView`): `home`, `work`, `policy`, `history`, `settings`. 모든 뷰를 마운트한 채 숨긴다(`Shell.tsx`).
- 결과(③)와 복구(⑦)는 기록 뷰 안의 상세, 새 실행(④)은 전역 시트, 승인(⑥)은 작업창 위 대화상자.

### 스타일
- 토큰은 `frontend/src/styles/theme.css`에만 색을 둔다. 다크 글래스 하나, `html[data-tint="violet|indigo|teal"]`로 색상 테마 3종.
- 글래스 공통 클래스: `glass-panel`(유리 카드), `glass-hero`(큰 카드), `glossy-icon`(광택 아이콘 타일), `round-action`(빛나는 원형 버튼).
- 그래프는 CSS만: 도넛 `conic-gradient`, 막대 `div` 폭, 카운트다운 링 `conic-gradient`.
- `.tsx`에 `style={{` 금지. 값에 따라 바뀌는 폭·각도는 CSS 변수를 `data-*` 속성/클래스로 정할 수 없을 때만 `ref`로 `style.setProperty`를 쓴다.
- 움직임은 `html[data-motion]`과 `prefers-reduced-motion`을 따른다.

### 문구 규칙 (CLAIM-MATRIX·LIMITATIONS·HANDOFF §10)
- 차단: PreTool deny는 `CONTAIN`/`PRETOOL_BLOCK` 판정이다. 실행 확인(`BLOCKED`)이 없으면 "차단 판정 N건". "막았어요"는 확인된 차단에만.
- AIA 패널(홈·보호 패널·결과)에는 원문 명령을 쓰지 않는다. 규칙 분류명·대상 종류만 쓴다. (Codex 대화 기록의 명령 표시는 기존과 같다.)
- 승인 카운트다운은 `kind === 'aia_tool'`이고 `expires_at`/`timeout_seconds`가 있을 때만. Codex 명령·파일 승인은 "응답을 기다리는 중".
- 파일 변경 카드는 경로와 상태만. diff 없음.
- "감사 기록 확인됨"은 `bundle_status === 'VALID'`일 때만. "변조 불가" 금지.
- RESTORED(복구 수행)와 VERIFIED(무결성 확인)를 따로 표시.
- 실행 전에는 감시·복구 준비를 확인할 수 없다: "실행하면 시작돼요".
- 파일 목록은 "관찰된 변경"이지 작성자 증명이 아니다(`activity.attribution_note`).
- 결과의 제한 문구(`limitations`)는 접은 영역에 항상 남긴다.

## 1. 화면별 명세

### ① 홈 · 보호 시작 전 — `components/dashboard/`
- 히어로: 가디언(`GuardianAvatar` 상태는 `useGuardianState`), "에이전트 작업을 지켜볼 준비가 됐어요" / 미준비면 `readinessNextStep`. 작업 폴더·기본 정책 칩.
- 타일 3개(기둥):
  - 실행 전 차단: preflight `pretool_hook`·`codex_hook_trust`·`hook_verification` 모두 ok → "준비됨", 아니면 "설정 필요".
  - 실행 중 감시: "실행하면 시작돼요".
  - 실행 후 복구: `control_root` ok → "실행하면 기준점을 저장해요", 아니면 "설정 필요".
- 최근 실행 타일: `/api/runs[0]` 상태·시간 + "결과 보기" → 기록 뷰 상세.
- 원형 버튼 "보호 시작" → 새 실행 시트(④). 미준비면 시트 안에서 Hook 설정 단계부터.
- 데이터: `usePreflight`, `useRunList`, `useGuardianState`.

### ② 보호 실행 중 — 홈 뷰의 실행 중 상태
- 조건: 활성 실행이 `ACTIVE_STATUSES`.
- 히어로 목록: 실행 전 검사 = `evidence_summary.pretool_events`, 감시 프로세스 = `activity.process_identity_count`, 파일 변경 = `activity.unique_file_count`, 차단 판정 = `/api/runs/{id}/actions`에서 `enforcement_decision === 'CONTAIN'` 수(폴링).
- 가디언: 차단 판정이 있으면 blocked, 아니면 normal.
- Codex 대화 미리보기(최근 메시지 2~3개 + "크게 보기 →" 작업창). 미리보기는 `codexActivity`/최근 이벤트 요약만, WebSocket은 작업창 뷰가 유지.
- 숫자 타일 + 최근 활동 막대(관찰 이벤트 시각을 `evidence_timeline`에서 1분 단위로 묶음, 최대 5개 막대, "관찰된 이벤트 기준").
- "종료" 원형 버튼 → 작업창으로 이동해 기존 세션 종료 확인을 연다.

### ③ 결과 — `components/results/ResultView.tsx` (기록 뷰 상세, 작업창 종료 후 화면)
- 히어로: 가디언(판정에 따라 normal/review/blocked/recovery), 배지("확인할 것 N개"), 제목은 `deriveVerdict`의 쉬운 문장. 버튼: 작업 폴더 되돌리기(복구 가능할 때) / 증거 보기(상세 펼침) / 홈으로.
- 도넛: `action_summary` → 허용 = compliant − audit, 기록 = audit, 차단 판정 = violation, 불확실 = indeterminate. 가운데 total.
- 숫자 타일: 차단 판정(`contain`), 파일 변경(`activity.unique_file_count` 또는 incidents 기반), 되돌리기(`/recovery.available`), 감사 기록(`bundle_status`).
- 파일 막대: `activity.files[].event_type` 생성/수정/삭제 (최대 200개 관찰 기준임을 표시).
- 접은 영역: 기존 ResultView 상세 전부(판정 배너, 실행 정책 경고, 읽는 법, 복구·무결성, 미지원 도구 결정, 귀속 등급, 행동 체인, 센서 요약, 사건, 원시 증거 로그, 제한 문구).

### ④ 새 보호 실행 — `components/settings/ProtectionSetupModal.tsx`, `HookStatusControl.tsx`
- 전체 글래스 시트. 1 작업 폴더(경로·검증·폴더 바꾸기, 끊긴 실행 복구 배너), 2 보호 정책 카드(`/api/profiles`), 3 연결 상태 알약(preflight 검사).
- 미준비면 연결 영역에 Hook 설정 3단계(설치·신뢰·확인)를 그대로 보여준다.
- 버튼: 취소 / 원형 "보호 시작" → `createProtectedRun` → 작업창으로 이동.

### ⑤ 작업창 — `components/terminal/CodexConversationPane.tsx`, `shell/ActiveRunPane.tsx`
- 왼쪽 큰 대화 카드: 머리줄(상태 점·정책·경과 시간·작업 종료), 말풍선(사용자 오른쪽), 명령 카드(실행 중/완료/실패, 출력 접기), 파일 변경 카드(경로 목록), 승인 대기 링크(⑥ 열기), 입력창.
- 오른쪽 보호 패널: 실행 전 검사·감시 프로세스·파일 변경 숫자, 최근 활동 막대, 프로세스 트리(`activity.processes` parent 관계), 센서 상태(`sensor_health`), 최근 이벤트(`events`), "기준점 준비됨"(`checkpoint === 'READY'`).
- 끝난 실행은 ③ 결과를 보여준다(기존 동작).

### ⑥ 승인 요청 — `ApprovalDialog` (CodexConversationPane 안)
- 어둡게 덮는 층 + 글래스 대화상자. 링: `aia_tool`이면 남은 초, 아니면 대기 아이콘.
- 명령/경로 코드 블록, 작업 위치·이유, "허용해도 AIA 정책 검사와 기록은 그대로 적용돼요".
- 버튼: 거절 / 이 세션 동안 허용 / 이번만 허용 (기존 decision 값 유지).

### ⑦ 복구 — `components/results/WorkspaceRestoreControl.tsx`
- 확인 단계(기존): 기준점 시각, 변경 수, 미리보기, 동의 체크.
- 완료 화면: 초록 링 + 회복 가디언, "작업 폴더를 되돌렸어요", 단계 목록(기준점 확인 → 파일 되돌리기 N개 → 무결성 확인 결과). 데이터는 `/result`의 `manual_recovery`/`recovery`/`integrity` 또는 restore 응답.
- RESTORED·VERIFIED 분리, 실패·불일치는 경고 색과 수치.

### ⑧ 정책 — `components/policy/`
- 프로필 카드(`/api/profiles` 5종, 기본값은 localStorage `aia.defaultPolicyProfile`), 선택 카드 "사용 중".
- "이 명령은 어떻게 판정될까?": 행동 종류(읽기·수정·삭제·실행) + 대상 입력 → `/api/policy/preview`, 프로필별 비교 칩(허용/기록/차단).
- 규칙 칩 데이터는 없으므로 카드에는 `description`만.

### ⑨ 기록 — `components/audit/AuditView.tsx`
- 필터: 전체 / 확인 필요(`incident_count > 0` 또는 `bundle_status !== 'VALID'` 또는 끊긴 실행) / 정상.
- 요약 타일(목록에서 계산): 전체 실행 수, 확인 필요 수, 실행 중 수.
- 행: 상태 점, 작업 폴더 이름, 시간·정책, 사건 수 칩, 상태 알약 → 상세(③). 실행 중 행은 작업창으로.
- 사이드바에 있던 세션 목록 기능을 여기서 대신한다.

### ⑩ 설정 — `components/settings/SettingsView.tsx`
- 연결 준비: 신호등 3개(Hook 연결 `pretool_hook`, Codex 신뢰 `codex_hook_trust`, 실제 요청 전달 `hook_verification`), "다시 확인"(preflight 새로고침 + `/api/hook/verify`), MCP 경고(`mcp_tools` status ENABLED/UNKNOWN, servers).
- 화면: 색상 테마 3종, 움직임(기존), 유리 효과(굴절 켜기/끄기).
- 정보: 버전(`/api/console-info`), 데이터 위치, 진단 내보내기(기존), 지원 범위(기존), 에이전트 정보(Codex 실행 파일 상태).

## 2. main 기능 보존 체크리스트

TASK-016에서 코드로 확인함(2026-10-06). TASK-018에서 빌드한 앱으로 다시 확인한다.

- [x] Codex 대화: 메시지, 생각, 명령+출력, 파일 변경, 도구, Hook, 알림, 마크다운, IME 입력, 중단, 세션 종료, 재연결, 기록 끊김 안내 → ⑤
- [x] 승인 대화상자: 명령/파일/AIA 도구, 시간 제한, 3버튼, Esc로 닫히지 않음 → ⑥
- [x] 결과 상세 전체(판정, 실행 정책 경고, 읽는 법, 번들 상태, 복구·무결성, 미지원 도구 결정, 귀속 등급, 행동 체인, 센서 요약, 사건, 원시 증거 로그, 제한 문구) → ③
- [x] 복구 확인(기준점, 변경 미리보기, 동의 체크) + 복구 여정 → ⑦
- [x] 새 실행: Hook 설정 3단계, 폴더 선택(네이티브), 끊긴 실행 복구, 정책 선택 → ④
- [x] 정책: 템플릿, 판정 미리보기, 프로필 비교 → ⑧ (분류별 고정 설명 목록은 카드 설명으로 축소)
- [x] 증거 탐색: 실행 목록, 끊긴 실행·실행 중 안내 → ⑨ → ③
- [x] 대시보드: 가디언, 실행 중 세션, 준비 상태, 최근 실행 → ①/② (최근 실행 전체 목록은 ⑨, 이벤트 피드는 ② "최근 관찰"과 ③ 증거 연결 흐름)
- [x] 파일 목록·프로세스 트리, 센서 상태·이벤트 피드 → ⑤ 보호 패널
- [x] 세션 목록·현재 작업 폴더 → ⑨ / ①
- [x] 상태바 정보(Hook 신뢰, 서버 연결) → 연결 끊김 배너 / ⑩
- [x] 가디언 도움말 팝오버(이슈 초안 링크) → 가디언 펫, ⑩ 설정의 도움말 버튼
- [x] 증거 검토 모달 → 전역 오버레이(새 스킨)
- [x] 설정: 움직임, 연결 상태, 데이터·개인정보, 진단 내보내기, 지원 범위, 실행 요약 → ⑩
- [x] 연결 끊김 배너, 오류 화면, 데스크톱 하트비트 → 그대로
- 제거: 라이트 테마·테마 토글. 메뉴에서 제거: 에이전트·보고서 화면(정보는 ⑩/⑨로 흡수).
