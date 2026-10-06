# EPIC-020 TASK 목록

상태: TODO / DOING / DONE / BLOCKED. 한 세션에 1~2개, TASK당 diff 약 500줄 이하를 목표로 한다.
모든 TASK의 기본 검증: `npm --prefix frontend run build` · `npm --prefix frontend run lint` · `npm --prefix frontend test`.
화면이 바뀌는 TASK는 미리보기 캡처(TASK-002)로 목업과 비교한다.

## Phase 0 — 준비

### TASK-001 맥락 문서 · DONE
- 목표: EPIC-020, SCREEN-SPEC, TASKS, PROGRESS, 목업 사본을 저장소에 둔다.
- 수용: 문서 4개와 `docs/ui-redesign/mockup/*.dc.html` 10개가 있다.

### TASK-002 미리보기 기준선 · TODO
- 목표: 데모 결과로 화면을 캡처할 수 있게 한다.
- 할 일: `aia demo` 3개 시나리오를 별도 Control Root(`.tmp-ui/control`)에 만들고, 빌드된 콘솔을 띄워 headless Edge로 캡처하는 로컬 스크립트(`scripts/dev/ui-preview.ps1`)를 둔다.
- 수용: 스크립트 한 번으로 홈·기록·결과 캡처 PNG가 `.tmp-ui/shots/`에 생긴다. `.tmp-ui/`는 gitignore.

## Phase 1 — 기반

### TASK-003 글래스 토큰 · TODO
- 파일: `frontend/src/styles/theme.css`, `frontend/src/hooks/useTheme.ts`(색상 테마로 교체), `main.tsx`.
- 할 일: 라이트 토큰 제거. 배경 그라데이션·유리 채움/테두리/흐림·버튼/강조 그라데이션·센서 색·상태 색 토큰. `data-tint` 3종.
- 수용: 기존 화면이 다크 글래스 배경으로 그려지고 테스트 통과.

### TASK-004 공통 컴포넌트 · TODO
- 파일: `frontend/src/components/common/`(GlassPanel, GlossyIcon, RoundAction, Donut, BarList, RingTimer), `styles/glass.css`.
- 수용: 새 컴포넌트가 빌드되고 디자인 규칙 테스트 통과. 순수 계산(도넛 비율 등)은 `api/` 아래 `.ts`로 두고 node 테스트 추가.

### TASK-005 앱 셸 · TODO
- 파일: `state/shellStore.tsx`, `components/shell/Shell.tsx`, `Sidebar.tsx`→`Rail.tsx`, `Topbar`/`RightPanel`/`StatusBar` 정리, 관련 테스트.
- 할 일: 5아이콘 레일 + 가디언 도움말, 뷰 키 `home/work/policy/history/settings`, ThemeToggle 제거, agents/reports 메뉴 제거.
- 수용: 레일로 모든 뷰 이동 가능, WebSocket 유지 구조 유지, 테스트 갱신·통과.

## Phase 2 — 시연 흐름

### TASK-006 ① 홈 · TODO
### TASK-007 ④ 새 보호 실행 시트 · TODO
### TASK-008 ⑤ 작업창 (대화 카드 + 보호 패널) · TODO
### TASK-009 ⑥ 승인 대화상자 · TODO
### TASK-010 ② 실행 중 (홈의 실행 중 상태, 종료 흐름) · TODO
### TASK-011 ③ 결과 · TODO
### TASK-012 ⑦ 복구 확인·완료 · TODO

각 TASK의 데이터·문구는 SCREEN-SPEC 해당 절을 따른다. 수용: 목업과 같은 구조, 기존 기능 유지, 테스트 통과.

## Phase 3 — 관리 화면

### TASK-013 ⑧ 정책 · TODO
### TASK-014 ⑨ 기록 · TODO
### TASK-015 ⑩ 설정 (색상 테마 선택 포함) · TODO

## Phase 4 — 마무리

### TASK-016 문구 점검 + 죽은 CSS 정리 · TODO
- CLAIM-MATRIX 대조, 증거 검토 모달 새 스킨, 쓰지 않는 선택자 삭제(`shell.css`·`redesign.css`·`product-update.css`), SCREEN-SPEC 체크리스트 확인.

### TASK-017 굴절 강조 4곳 + 유리 효과 스위치 · TODO (시간 부족 시 제외)
- ① 히어로, ② 차단 카드, ③ 히어로, ⑥ 대화상자. 설정의 유리 효과로 끈다.

### TASK-018 데스크톱 빌드 + 시연 리허설 + PR · TODO
- `scripts/build-windows.ps1`, 시연 대본 3장면, 전체 pytest, PR(머지 금지, YM 검토).
