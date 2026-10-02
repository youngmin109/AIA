# AIA UI Redesign Summary

## 목표

AIA의 기존 보호 실행 기능을 유지하면서, 개인 사용자가 자신의 로컬 Agent를 관리하는 AI 보안 콘솔로 재정리했다. 화면에 표시되는 실행 수치와 사건 수는 기존 로컬 API의 세션·증거 데이터에서 가져온다.

## 변경한 화면

- **보호 현황 / AI 보안 관측**: 상단 서브탭, 실제 세션 기반 KPI, 현재 관측 세션, 최근 보호 실행, 최근 감사 이벤트, 보호 준비 상태를 한 화면에 배치했다.
- **에이전트**: 현재 지원 런타임인 Codex CLI의 설치·Hook 준비·활성 실행 상태를 보여준다.
- **보호 실행**: 기존 Codex 대화와 Protected Run 동작을 그대로 유지한다.
- **정책**: 정책 현황, 템플릿, 실행 범위, 런타임 보호, 데이터 보호, 탐지 및 대응, 감사 기록, 맞춤 설정으로 재구성했다.
- **증거**: 기존 감사 기록과 Result Bundle 탐색 화면을 유지하면서 메뉴 명칭을 증거 중심으로 정리했다.
- **보고서**: 실제 실행 이력에서 전체 실행, 완료, 중단·실패, 정책 사건, 검증 번들을 집계한다.
- **설정**: 테마, Hook·보호 실행 연결, 로컬 데이터 범위, 지원 범위를 분리했다.

## 디자인 원칙

- 라이트 모드는 밝은 회백색 사이드바, 화이트 카드, 옅은 블루·민트·라벤더 포인트를 사용한다.
- 다크 모드는 기존 슬레이트·네이비 토큰을 유지하며 같은 정보 계층을 제공한다.
- 카드 반경, 얇은 보더, 낮은 그림자, 8~16px 간격 체계를 공통으로 사용한다.
- 상태는 색만으로 전달하지 않고 텍스트 배지를 함께 사용한다.
- 현재 지원 기능과 향후 기능을 같은 상태처럼 보이지 않도록 `지원`, `부분 지원`, `계획`으로 구분한다.
- 페이지 전환, 카드 등장, 버튼 반응, Guardian 상태 전환에 짧은 모션을 적용하고 `prefers-reduced-motion`을 지원한다.

## 테마 구조

- `frontend/src/styles/theme.css`: 전역 색상·간격·상태·내비게이션 토큰
- `frontend/src/styles/shell.css`: 기존 Protected Run·Terminal·Shell 레이아웃
- `frontend/src/styles/redesign.css`: 제품 페이지, 정책 콘솔, KPI, 표, 반응형 레이아웃
- `useTheme`: 사용자 선택을 로컬 저장소에 보존하고 `data-theme` 속성으로 전환

## 실제 데이터 연결

- `/api/preflight`: Codex·Hook 준비 상태와 점검 항목
- `/api/runs`: 실행 수, 상태, Workspace, 사건 수, Result Bundle 상태
- `/api/runs/{id}`: 선택된 세션의 Sensor·Evidence·Event 정보
- `/api/profiles`: 실제 AIA 엔진 정책 프로필과 설명

## 남은 작업

- Custom Mode 초안을 실제 정책 JSON으로 변환·검증·적용하는 백엔드 API
- 민감 데이터 분류, Oversharing, 알림 채널, 보존 기간 API
- Agent Registry와 추가 Agent Adapter
- 개인용 보고서 내보내기와 장기 추세 데이터

## 검증

- `npm run lint`
- `npm run build`
