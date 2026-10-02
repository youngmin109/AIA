# AIA Policy Settings Structure

## 정책 정보 구조

1. **정책 현황**: 현재 기본 프로필, 엔진 템플릿 수, 정책 고정 상태, 직접 설정 정책 안내
2. **템플릿**: AIA 엔진의 실제 프로필을 조회하고 다음 실행 기본값으로 선택
3. **실행 범위**: Workspace 범위, Workspace 밖 쓰기(Codex 샌드박스가 제한), Tool·명령, 사용자 확인
4. **런타임 보호**: Active Policy Freeze, Lease, Checkpoint, Process Tree 관찰(사용자 중지 시 종료)
5. **데이터 보호**: 민감 경로, 증거 표시 제한
6. **탐지 및 대응**: Evidence 정규화·귀속, Gate 결정, 종료·복구·검증
7. **감사 기록**: 감사 기록, Result Bundle, 무결성 검증

각 영역에는 현재 엔진이 실제로 수행하는 동작만 `지원`, `부분 지원`으로 표시한다.

## 템플릿

화면은 `/api/profiles` 응답을 단일 근거로 사용한다. 현재 서버가 제공하는 프로필만 선택 가능하며, 이름과 설명도 서버 정의를 그대로 표시한다. UI에서 실제 정책 내용을 추측하거나 별도의 보안 수준을 덧붙이지 않는다.

## 직접 설정 정책

화면에는 정책을 직접 만드는 기능을 두지 않는다. 엔진에 적용되지 않는 설정 화면은 사용자가 보호가 켜졌다고 오해하게 만들기 때문이다. 직접 작성한 정책은 Strict Validation을 통과한 JSON을 실행할 때 CLI `--policy <json>`으로 지정한다.

## 관리자 콘솔 경험에서 참고한 시각 구조

- 설정을 기능별 카테고리로 나누는 계층형 탐색
- 템플릿과 적용 범위의 분리
- 데이터 보호와 감사 기록을 하나의 보호 경험으로 연결

Microsoft 브랜드, 문구, 화면을 복제하지 않았으며 AIA의 로컬 Runtime Assurance 구조에 맞게 다음처럼 재해석했다.

- 사용자·그룹 정책 → 개인 Agent의 Workspace·Tool 실행 범위
- Copilot/Agent 제어 → Hook·Process·File Sensor와 Enforcement Gate
- 데이터 거버넌스 → Evidence 마스킹·Result Bundle·무결성 검증
- 정책 적용 → 실행 전 정책 고정과 재현 가능한 감사 결과
