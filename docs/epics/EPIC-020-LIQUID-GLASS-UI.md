# EPIC-020 — Liquid Glass UI

## 목적

중간 시연 전에 AIA 데스크톱 화면을 확정된 리퀴드 글래스 디자인 10개 화면으로 바꾼다.
디자인 원본은 `docs/ui-redesign/mockup/*.dc.html`(Design 캔버스 사본)이다.
피드백(직관적·단순·그래프 중심·매우 쉬운 사용, CleanMyMac 참고)에 맞춰 글자를 줄이고 숫자·그래프·가디언으로 상태를 보여준다.

이 EPIC은 **화면 계층만** 바꾼다. Policy, Attribution, Enforcement, Recovery, Integrity 권한과
백엔드 API는 그대로 두고, 이미 있는 데이터를 새 화면에 연결한다.

## 실행 경계

- 변경 대상: `frontend/` (React 19 + Vite + TypeScript). 백엔드·CLI·`evaluation/`·`policies/`는 바꾸지 않는다.
- 새 의존성을 추가하지 않는다. 그래프(도넛·막대·링)는 CSS로 만든다.
- 다크 글래스 테마 하나만 둔다. 라이트 테마는 제거하고, 색상 테마(보라·남색·청록)만 고른다.
- 모든 화면은 마운트된 채 숨기는 구조를 유지해 Codex WebSocket이 화면 전환에 끊기지 않게 한다.
- 디자인 규칙 테스트(`frontend/tests/design-tokens.test.mjs`)를 지킨다: 색 리터럴은 `theme.css`에만, `.tsx`에 `style={{` 금지, 정의되지 않은 `var(--x)` 금지.
- 브랜치 `feature/liquid-glass-ui`, TASK 단위 커밋, 시연 전 PR 1개. 머지는 검토자가 한다.

## 화면

| # | 화면 | 메뉴 |
|---|---|---|
| ① | 홈 · 보호 시작 전 | 홈 |
| ② | 보호 실행 중 (홈의 실행 중 상태) | 홈 |
| ③ | 결과 · 한눈에 요약 | 기록에서 진입 |
| ④ | 새 보호 실행 (시트) | 홈의 "보호 시작" |
| ⑤ | 작업창 · 대화 크게 보기 | 작업창 |
| ⑥ | 승인 요청 (대화상자) | 작업창 위 |
| ⑦ | 복구 완료 | 결과에서 진입 |
| ⑧ | 정책 | 정책 |
| ⑨ | 기록 | 기록 |
| ⑩ | 설정 · 연결 준비 | 설정 |

화면별 데이터·문구 규칙은 `docs/ui-redesign/SCREEN-SPEC.md`, 작업 순서는 `docs/ui-redesign/TASKS.md`에 둔다.

## 안전한 표시 계약

`docs/validation/CLAIM-MATRIX.md`, `docs/LIMITATIONS.md`, HANDOFF §10 보안 불변식을 따른다.

- 확인되지 않은 차단을 "막았어요"라고 쓰지 않는다. Workbench 실행은 차단 확인이 없으므로 "차단 판정"으로 쓴다.
- AIA 패널에 원문 명령·비밀값·전체 payload·파일 내용을 보여주지 않는다.
- 실행 전 확인할 수 없는 감시·복구 준비를 "준비됨"으로 표시하지 않는다.
- RESTORED와 VERIFIED, 차단 판정과 차단 확인을 한 상태로 합치지 않는다.
- 결과 화면의 제한 문구(`result_view.limitations`)를 숨기지 않는다.
- "변조 불가", "모든 행위 차단" 같은 지원 범위 밖 주장을 하지 않는다.

## 범위 밖

- 백엔드 보강(시연 후 별도 EPIC): 기록 목록의 실행별 차단·파일 수, 실행 중 기준점 시각, Hook 마지막 확인 시각.
- 대화 항목과 AIA 판정을 잇는 키, 파일 diff 내용, Codex 승인 시간 제한, 복구 진행률 스트림.
- 새 보안 판단, 정책 저장 UI, 라이트 테마.

## 검증

- `npm --prefix frontend run build`, `npm --prefix frontend run lint`, `npm --prefix frontend test`
- 백엔드 회귀 확인: `.venv\Scripts\python.exe -m pytest -q`
- 데모 결과(`aia demo`)를 별도 Control Root에 만들고 빌드된 콘솔 화면을 캡처해 목업과 비교한다.
- 데스크톱 빌드(`scripts/build-windows.ps1`)로 시연 대본을 한 번 실행한다.
- `SCREEN-SPEC.md`의 "main 기능 보존 체크리스트"를 모두 확인한다.
