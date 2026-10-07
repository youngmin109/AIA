# EPIC-021 진행 기록

세션마다 5줄 이하. 최신이 위.

## 2026-10-07 · TASK-110
- 서버: `turn/plan/updated`를 `plan.updated`(단계 최대 50개, 모르는 상태는 버림)로, 최신 계획은 스냅샷 `plan`에도.
- 화면: 대화 위 접히는 "작업 계획 n/N · 지금 · 단계" 줄, 펼치면 단계별 대기·진행 중·완료.
- 테스트: pytest 911, 프론트 48 통과.

## 2026-10-07 · TASK-109
- 모델 목록: `GET /api/codex/models`가 스레드를 열지 않는 임시 앱 서버로 `model/list`(숨김 제외)를 받아 10분 기억. 실패하면 빈 목록 → 고르는 칸을 숨기고 Codex 기본값.
- 생각 깊이는 `thread/start`가 받지 않아 요청마다 `turn/start`의 `effort`로. 덮어쓰기는 `model`·`effort` 두 키로만 만들고 이름 형식을 검사(`settings.changed` 이벤트, 스냅샷 `turn_settings`).
- 새 실행 요청에 `reasoning_effort`(소문자 단어) 추가, 대화가 열리면 적용. WebSocket `turn_settings`.
- 화면: 새 실행 시트 "3 모델과 생각 깊이", 작업창 모델 칩(다음 요청부터 적용). 테스트: pytest 910, 프론트 47 통과.

## 2026-10-07 · TASK-108
- 서버: 대화가 열리면 따로 `account/rateLimits/read`(실패하면 조용히 넘어감 = API 키 로그인). `account/rateLimits/updated`, `thread/tokenUsage/updated`를 `usage.limits`/`usage.tokens`로, 최신값은 스냅샷 `usage`에도.
- 화면: 작업창 위 칩 "5시간 한도 n% 남음"(가장 많이 쓴 창 기준, 20% 이하면 경고색), 누르면 창별 남은 비율·초기화까지 남은 시간·이번 대화 토큰. 정보가 없으면 숨김.
- 같이 고침: 여러 겹 배경에서 단색은 맨 아래 겹에만 쓸 수 있어 가디언 펫 말풍선 배경이 무시되던 문제(그라데이션으로 감쌈).
- 테스트: pytest 905, 프론트 46 통과.

## 2026-10-07 · TASK-107
- 서버: `item/permissions/requestApproval`을 `permissions.requested`로. 경로마다 작업 폴더 안/밖/확인 불가 표시(경로·패턴·특수 경로). 형식이 다르면 예전처럼 거절.
- 사용자 선택 그대로: 이번 요청만(`scope: turn`)·실행 내내(`session`)는 요청받은 권한을 그대로 돌려주고, 거절은 빈 권한.
- 허용하면 실행 기록 `permission_grants`에 남기고 실행 상태(진행 중·끝난 실행 모두)에 실음. 보호 패널과 ③ 결과에 "넓힌 권한"과 범위 밖 안내.
- 테스트: pytest 902, 프론트 45 통과.

## 2026-10-07 · TASK-106
- 서버: `mcpServer/elicitation/request`를 `elicitation.requested`로. form은 단순 칸(글자·숫자·정수·참거짓·고르기·여러 개 고르기)만, 그 밖은 `supported: false`(거절·취소만).
- url은 http/https만 받고 도메인(`url_host`)을 따로 줌. 응답은 `elicitation_response`(accept/decline/cancel), 값은 칸 형식대로 검사.
- 입력한 값은 Codex에만 전달. `elicitation.resolved`에는 action만. 질문과 같이 Codex 철회·세션 종료·비정상 종료 때 닫음.
- 화면: 외부 도구 입력 카드("AIA 보호 범위 밖" 표시). 테스트: pytest 897, 프론트 44 통과.
- 주의: 전체 pytest가 한 번 1건 실패했고, 그 뒤 연속 3번은 모두 통과(이름 미확인, 일시적). 실패를 보지 못한 채 커밋돼서, 이후로는 테스트를 확인한 뒤 따로 커밋함.

## 2026-10-07 · TASK-105
- 서버: `item/tool/requestUserInput`을 받아 `question.requested` 이벤트로. 모르는 형식이면 예전처럼 -32601 거절. 답은 `question_answer` WebSocket 메시지 → `{answers: {id: {answers: [...]}}}`.
- 비밀 답(`isSecret`)은 Codex에만 전달하고 이벤트에는 null로. `serverRequest/resolved`·세션 종료·비정상 종료 때 대기 질문을 닫음.
- 화면: 입력창 위 질문 카드(선택지, 직접 입력, 가린 비밀 입력, 자동 해결 남은 초, 건너뛰기). 대화 기록에 "Codex 질문 · 답 요약".
- 가짜 Codex에 `question`, `question-auto` 상황 추가. 테스트: pytest 893, 프론트 43 통과.

## 2026-10-07 · TASK-104
- 실제 사례(`e896b007`): 기준점 저장 중 창이 닫혀 상태 PREPARING·임대 ACTIVE로 남음. 서버는 이미 고아로 정리 확인함(STALE_PROCESS_GONE, NOT_STARTED, acknowledged).
- 저장된 상태를 ABORTED로 고쳐 쓰지 않음(마무리 절차를 거친 것처럼 기록되므로). 화면만 고침.
- 기록 목록·홈 최근 실행·기록 상세·가디언: "준비 중 중단 · Codex는 시작되지 않았어요". 그 밖의 고아 실행은 "연결 끊김".
- 테스트: 프론트 41개 통과.

## 2026-10-07 · TASK-103
- 실제 시작 흐름으로 측정(임시 기록 폴더, Codex에 요청은 안 보냄). 작은 폴더 34개: 기준점 0.5 · 감시 0.1 · 준비 0.2 · Codex 시작 0.6 · 대화 1.6초.
- 큰 폴더 3,211개(복사본, %TEMP%라 백신 영향 큼): 기준점 183 · 감시 6.2 · 준비 5.8 · Codex 시작 15.5 · 대화 0.6초.
- 원인: 시작 때 폴더 전체를 약 6번 해시함. 기준점 저장 4번, 준비 확인 1번, Codex 띄우기 직전 재확인(`revalidate_ready_context`) 1번. 확인과 사용 사이의 틈을 막는 보안 검사라 줄이지 않음(보안 불변식).
- 대신: 단계 이름을 "Codex 시작 전 최종 확인 중"으로, 새 실행 시트가 파일 수·크기를 세어(5,000개·1.5초 상한) 1,000개 또는 50MB 이상이면 미리 안내.
- 실패한 실행은 시작 단계를 닫도록 함. 테스트: pytest 889, 프론트 39 통과.

## 2026-10-07 · TASK-102
- 서버: 실행 기록에 `startup`(지금 단계, 단계별 시작·끝 시각, 기준점 진행률). 단계는 기준점 → 감시 시작 → 준비 확인 → Codex 시작 → 대화 연결.
- 기준점 저장(`aia.checkpoint`)에 표시 전용 `progress` 콜백을 추가. 콜백이 오류를 내도 저장은 계속되고, 콜백이 없으면 호출 모양이 예전과 같다.
- 화면: 작업창 대기 화면과 ② 홈에 "n/5단계 · 단계 이름 · 경과 초 · 파일 복사 n/N", 진행 막대, 1,000개 이상이면 큰 폴더 안내.
- 시험 폴더 측정(3,200개): 기준점 외에 감시 시작 약 10초, 준비 확인 약 10초. 실제 원인 측정은 이 단계 기록으로 TASK-103에서.
- 캡처 도구에 `init:` 단계(페이지 스크립트보다 먼저 실행) 추가. 테스트: pytest 888 통과, 프론트 38개 통과.

## 2026-10-07 · TASK-101
- 브랜치 `feature/codex-parity`(main `5ccc852`에서). 계획 문서 커밋. 푸시는 사용자가 말할 때만.
- AIA가 띄우는 Codex는 0.160.0(Codex 앱 번들). 스키마 188개, 계획 표의 메서드 17개 모두 있음(0.157.1과 목록 동일).
- 스키마 전체(3.4MB)는 저장소에 넣지 않음. 필요하면 `codex app-server generate-json-schema --out <폴더>`로 다시 뽑는다.
- 다음: TASK-102 시작 진행 단계 표시.
