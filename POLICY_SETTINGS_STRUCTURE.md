# AIA Policy Settings Structure

## 정책 정보 구조

1. **정책 현황**: 현재 기본 프로필, 엔진 템플릿 수, 정책 고정 상태, 맞춤 초안 상태
2. **템플릿**: AIA 엔진의 실제 프로필을 조회하고 다음 실행 기본값으로 선택
3. **실행 범위**: Workspace 경계, Tool·명령, 외부 경로, 사용자 확인
4. **런타임 보호**: Session, Active Policy Freeze, Lease, Checkpoint, Process Tree, 복구
5. **데이터 보호**: 민감 경로, Workspace 외부 접근, Evidence 마스킹, 분류
6. **탐지 및 대응**: Evidence 정규화·귀속, Gate 결정, 종료·복구·검증
7. **감사 기록**: 감사 기록, Result Bundle, 무결성 검증, 로컬 보존·내보내기
8. **맞춤 설정**: 템플릿 기반 세부 조정, 충돌 확인, 요약, 로컬 초안 저장

## 템플릿

화면은 `/api/profiles` 응답을 단일 근거로 사용한다. 현재 서버가 제공하는 프로필만 선택 가능하며, 이름과 설명도 서버 정의를 그대로 표시한다. UI에서 실제 정책 내용을 추측하거나 별도의 보안 수준을 덧붙이지 않는다.

## Custom Mode

현재 구현 범위:

- 기본 템플릿 선택
- Checkpoint, Active Policy Freeze, Workspace 외부 접근 설정
- 자식 프로세스, 민감 파일, 지원 범위 밖 Tool, 복구 방식 설정
- 구성 충돌과 보호 약화 항목 안내
- 정책 동작 요약과 변경 여부 표시
- 브라우저 로컬 저장소에 초안 저장 및 템플릿 초기화

현재 미구현 범위:

- 엔진 정책 JSON 생성·검증·적용
- 실제 세션에 Custom Draft 적용
- 실제 실행 시뮬레이션

따라서 화면은 로컬 초안을 `적용 중`으로 표시하지 않는다.

## 관리자 콘솔 경험에서 참고한 시각 구조

- 설정을 기능별 카테고리로 나누는 계층형 탐색
- 템플릿, 맞춤 정책, 적용 범위의 분리
- 설정을 기능별 카테고리로 나누는 계층형 탐색
- 데이터 보호와 감사 기록을 하나의 보호 경험으로 연결

Microsoft 브랜드, 문구, 화면을 복제하지 않았으며 AIA의 로컬 Runtime Assurance 구조에 맞게 다음처럼 재해석했다.

- 사용자·그룹 정책 → 개인 Agent의 Workspace·Tool 실행 범위
- Copilot/Agent 제어 → Hook·Process·File Sensor와 Enforcement Gate
- 데이터 거버넌스 → Evidence 마스킹·Result Bundle·무결성 검증
- 정책 적용 → 실행 전 정책 고정과 재현 가능한 감사 결과
