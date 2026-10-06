# EPIC-020 TASK 목록

상태: TODO / DOING / DONE / BLOCKED. 한 세션에 1~2개, TASK당 diff 약 500줄 이하를 목표로 한다.
모든 TASK의 기본 검증: `npm --prefix frontend run build` · `npm --prefix frontend run lint` · `npm --prefix frontend test`.
화면이 바뀌는 TASK는 미리보기 캡처(TASK-002)로 목업과 비교한다.

## Phase 0 — 준비

### TASK-001 맥락 문서 · DONE
- 목표: EPIC-020, SCREEN-SPEC, TASKS, PROGRESS, 목업 사본을 저장소에 둔다.
- 수용: 문서 4개와 `docs/ui-redesign/mockup/*.dc.html` 10개가 있다.

### TASK-002 미리보기 기준선 · DONE
- `scripts/dev/ui_preview_server.py`: `.tmp-ui/control`(gitignore)에 `aia demo` 3개 시나리오(hook-block, process-kill, file-rollback) 결과를 모으고, 가짜 Codex app-server로 실시간 실행 1개(`preview-live`)를 붙여 빌드된 콘솔을 띄운다.
- 사용: `npm --prefix frontend run build` → `.venv\Scripts\python.exe scripts\dev\ui_preview_server.py --port 8899 [--reset]` → 브라우저로 `http://127.0.0.1:8899/`.
- 실시간 실행 대화창에 `run`(명령 승인), `patch`(파일 승인), `hello`(답장)를 입력하면 해당 화면을 볼 수 있다.

## Phase 1 — 기반

### TASK-003 글래스 토큰 · DONE
- 파일: `frontend/src/styles/theme.css`, `frontend/src/hooks/useTheme.ts`(색상 테마로 교체), `main.tsx`.
- 할 일: 라이트 토큰 제거. 배경 그라데이션·유리 채움/테두리/흐림·버튼/강조 그라데이션·센서 색·상태 색 토큰. `data-tint` 3종.
- 수용: 기존 화면이 다크 글래스 배경으로 그려지고 테스트 통과.

### TASK-004 공통 컴포넌트 · DONE
- 파일: `frontend/src/components/common/`(GlassPanel, GlossyIcon, RoundAction, Donut, BarList, RingTimer), `styles/glass.css`.
- 수용: 새 컴포넌트가 빌드되고 디자인 규칙 테스트 통과. 순수 계산(도넛 비율 등)은 `api/` 아래 `.ts`로 두고 node 테스트 추가.
- 결과: `common/Glass.tsx`(GlossyIcon, TileCorner, RoundAction, StatTile, StatusDot), `common/Charts.tsx`(DonutChart, ChartLegend, BarList, MiniBars, RingTimer — SVG 속성으로 그려 인라인 스타일 없음), `api/chartMath.ts` + `tests/glass-ui.test.mjs`, `styles/glass.css`.

### TASK-005 앱 셸 · DONE
- 파일: `state/shellStore.tsx`, `components/shell/Shell.tsx`, `Sidebar.tsx`→`Rail.tsx`, `Topbar`/`RightPanel`/`StatusBar` 정리, 관련 테스트.
- 할 일: 5아이콘 레일 + 가디언 도움말, 뷰 키 `home/work/policy/history/settings`, ThemeToggle 제거, agents/reports 메뉴 제거.
- 수용: 레일로 모든 뷰 이동 가능, WebSocket 유지 구조 유지, 테스트 갱신·통과.
- 결과: `shell/Rail.tsx`, `shell/GuardianGuide.tsx`(사이드바 도움말 이전), 셸 상태 `newRunOpen`·`endRequest`. Sidebar/Topbar/RightPanel/StatusBar/AgentsView/ReportsView 삭제. 화면 캡처는 `scripts/dev/ui_shot.py out.png click:기록 wait:1`.

## Phase 2 — 시연 흐름

### TASK-006 ① 홈 · DONE
- `components/home/HomeView.tsx`: 실행 전(①)과 실행 중(②)을 한 뷰에서 나눈다. `api/homeStatus.ts`(기둥 상태·경과 시간), `hooks/useRunActions.ts`(CONTAIN 수), `hooks/useProfiles.ts`, `styles/home.css`.
### TASK-007 ④ 새 보호 실행 시트 · DONE
- `settings/ProtectionSetupModal.tsx`(NewRunSheet): 폴더·정책 카드·연결 알약·시작. 준비 여부는 preflight `READY`에서 계산. `HookStatusControl`은 글래스 3단계로 다시 그림. `styles/sheet.css`.
### TASK-008 ⑤ 작업창 (대화 카드 + 보호 패널) · DONE
- `work/WorkView.tsx`(빈 상태·끝난 실행은 결과), `work/ProtectionPanel.tsx`(숫자·5분 막대·프로세스 트리·바뀐 파일·센서·기준점), `CodexConversationPane` 말풍선·명령/파일 카드·입력창. `styles/work.css`. ActiveRunPane·WorkspaceActivity·EventFeed·SensorHealthRow 삭제.
### TASK-009 ⑥ 승인 대화상자 · DONE
- 글래스 대화상자 + RingTimer. 카운트다운은 `timeout_seconds`가 있을 때(AIA 도구 검토)만, Codex 승인은 "답할 때까지 기다려요". Esc로 닫히지 않음 유지.
### TASK-010 ② 실행 중 (홈의 실행 중 상태, 종료 흐름) · DONE
- 화면은 TASK-006. 홈 "종료" → `requestEnd` → 작업창이 글래스 종료 확인(window.confirm 대체)을 연다.
### TASK-011 ③ 결과 · DONE
- `results/ResultView.tsx`: 히어로(가디언·쉬운 문장·도넛), 숫자 타일 4개, 바뀐 파일 막대, 접은 상세(사건·귀속·센서·복구·증거 흐름·도구 검토·읽는 법/제한 사항). 문장은 `api/resultSummary.ts`(차단 판정/막음 확인/종료/복구 분리, 테스트). 파일 수는 `hooks/useRunSnapshot.ts`. `styles/result.css`.
### TASK-012 ⑦ 복구 확인·완료 · DONE
- `results/WorkspaceRestoreControl.tsx`: `RestoreDialog`(기준점·미리보기·동의) → `RestoreComplete`(초록 링·단계: 기준점/되돌리기/무결성, 실패 경로). RESTORED·VERIFIED 분리. 미리보기 데이터에는 기준점이 없어 완료 화면은 TASK-018 실제 실행으로 확인.

각 TASK의 데이터·문구는 SCREEN-SPEC 해당 절을 따른다. 수용: 목업과 같은 구조, 기존 기능 유지, 테스트 통과.

## Phase 3 — 관리 화면

### TASK-013 ⑧ 정책 · DONE
- `policy/PolicyView.tsx`: 템플릿 카드(기본값 저장), `PolicyPreview`(행동 종류 + 대상 → 모든 정책 판정 비교, 사용 중 정책 규칙), "AIA가 실제로 하는 일"(기존 분류 설명을 접어서 유지).
### TASK-014 ⑨ 기록 · DONE
- `audit/AuditView.tsx`: 필터(전체/확인 필요/정상)·요약 타일·행 목록 → 상세(③)와 "기록 목록" 뒤로 가기. 분류는 `api/historyFilter.ts`(테스트). 증거 검토 모달도 글래스로(Esc는 표시하지 않음). `styles/manage.css`.
### TASK-015 ⑩ 설정 (색상 테마 선택 포함) · DONE
- `settings/SettingsView.tsx`: 연결 신호등 3개(`api/settingsStatus.ts`, 테스트), 다시 확인, MCP 경고, Hook 3단계(미준비 시), 색상 테마·유리 효과(`api/glassPreference.ts`, `html[data-glass]`)·움직임, AIA 정보(버전·Codex·데이터 위치)·진단 정보·개인정보. HookStatusControl은 모르는 준비 코드일 때 점검 항목으로 단계를 정함.

## Phase 4 — 마무리

### TASK-016 문구 점검 + 죽은 CSS 정리 · TODO
- CLAIM-MATRIX 대조, 증거 검토 모달 새 스킨, 쓰지 않는 선택자 삭제(`shell.css`·`redesign.css`·`product-update.css`), SCREEN-SPEC 체크리스트 확인.

### TASK-017 굴절 강조 4곳 + 유리 효과 스위치 · TODO (시간 부족 시 제외)
- ① 히어로, ② 차단 카드, ③ 히어로, ⑥ 대화상자. 설정의 유리 효과로 끈다.

### TASK-018 데스크톱 빌드 + 시연 리허설 + PR · TODO
- `scripts/build-windows.ps1`, 시연 대본 3장면, 전체 pytest, PR(머지 금지, YM 검토).
