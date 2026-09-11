# 변경 이력

이 파일은 공개 배포 버전의 사용자에게 보이는 변경 사항을 기록한다.

## [0.1.6] - 2026-09-11

### 결과 해석 명확화

- 보호 실행 결과에 전체 행위·정책 판정·정책 효과·집행·실행 결과 집계를 표시
- `COMPLIANT / VIOLATION` 정책 판정과 `ALLOW / AUDIT / DENY` 정책 효과를 분리
- Result Bundle에 행위별 `operation_effect`를 보존해 결과 화면과 JSON의 의미를 일치
- Recovery와 Integrity 상태를 CLI와 로컬 콘솔에서 독립적으로 표시

## [0.1.5] - 2026-09-11

### Workspace 재사용 안전성

- AIA가 비정상 종료된 이전 Protected Run의 Agent Root가 정리되지 않은 Workspace를
  새 Protected Run이 자동으로 재사용하지 않도록 차단
- 기록된 Agent Root가 사라진 것을 확인하고 `aia reconcile`한 뒤에만 Workspace 재사용 허용
- 고아 실행 상태와 새 실행 거부 사유를 CLI·로컬 콘솔에서 확인

## [0.1.4] - 2026-09-11

### 안정성 보강

- AIA 조정 프로세스의 PID와 생성 시각을 Protected Run 상태에 보존
- AIA 비정상 종료 뒤 이전 실행을 `ORPHANED_DEGRADED`로 명시
- 기록된 Agent Root의 PID와 생성 시각이 실제로 사라진 경우에만 `aia reconcile` 허용
- 고아 실행 정리 확인과 상태를 CLI·로컬 콘솔에서 확인

## [0.1.3] - 2026-09-11

### 운영 보강

- `aia support-bundle` 명령으로 비밀정보를 제외한 설치·Hook·최근 실행 진단 파일 생성
- 진단 번들에 전체 경로, Workspace 내용, raw evidence, tool input, 명령 출력 미포함

## [0.1.2] - 2026-09-11

### 사용성 보강

- 보호 실행 종료 시 `COMPLETED_VERIFIED`, `COMPLETED_DEGRADED`,
  `FAILED_DEGRADED`를 사람이 읽을 수 있는 결과 요약으로 표시
- Hook Event 수, Incident 수, Result Bundle 상태, Result 경로와 다음 조치를 CLI에 표시
- 보호 상태를 보안 성공으로 해석할 수 없는 경우 명시적으로 경고

## [0.1.1] - 2026-09-11

### 보강

- 보호 실행 준비 후 Codex 등록 중인 `LAUNCHING` 상태를 CLI와 로컬 콘솔에 표시
- 다른 터미널에서도 `LAUNCHING` 상태와 보호 상태를 일관되게 조회
- `LAUNCHING` 중 사용자 중지 시 검증된 Process Identity가 있는 관리 Root만 종료
- Hook Broker 손실 시 `PROTECTION_FAILURE`와 `FAILED_DEGRADED` 결과를 분리 기록
- 전체 회귀 540건과 깨끗한 wheel 설치·릴리스 번들 검증을 추가 확인

### 지원 범위

- 지원 범위와 보안 주장은 0.1.0과 동일하게 Windows 11, Codex CLI,
  지원되는 PreToolUse matcher로 제한한다.

## [0.1.0] - 2026-09-11

### 추가

- Windows 11에서 Codex CLI를 AIA Protected Run의 자식 프로세스로 실행
- `PROTECTED_DEVELOPMENT` 기본 정책과 한국어 정책 프로필
- PreToolUse 기반 정책 판정과 지원 matcher의 사전 차단
- Workspace Lease, Safe Checkpoint, File/Hook/Process Evidence
- Recovery와 SHA-256 Integrity Verification을 분리한 Result Bundle
- CLI, 로컬 보안 콘솔, `doctor`, `self-test`, `hook verify`, `proof` 명령
- wheel·source distribution·ZIP 릴리스 번들과 SHA-256 manifest
- 릴리스 설치 전 wheel SHA-256 검증과 변조 패키지 거부
- AIA 버전 업데이트 때 이전 Python 경로의 AIA Hook을 중복 없이 안전하게 교체
- Hook 지문이 남아 있어도 현재 Codex Trust가 해제되면 `aia hook status`가 READY로 표시하지 않음
- 실행 중 Hook Broker 손실 시 관리 트리 중지 시도와 `PROTECTION_FAILURE` 결과를 별도 기록
- 결정론적 제품 전후 평가와 오프라인 HTML 대시보드

### 검증된 범위

- Windows 11, Python 3.13, Codex CLI 0.154.0 환경
- Bash, `apply_patch`, Edit/Write 계열과 등록된 파일 읽기 MCP matcher
- 실제 PreToolUse deny, 부작용 없음, Evidence Bundle 검증
- 사용자 중지 시 managed process tree 종료와 unrelated process 보존

### 제한사항

- 모든 Codex 도구·MCP·외부 Agent·수동 실행을 보호한다고 주장하지 않는다.
- Hook Trust는 사용자가 Codex `/hooks`에서 직접 검토·신뢰해야 한다.
- 정책 위반에 따른 Actual Codex destructive Process 자동 집행은 정상 제품 경로의
  완료된 보장으로 주장하지 않는다.
- Network Security, Database state, ACL/ADS, 대규모 Workspace SLA는 지원 범위 밖이다.

자세한 지원 계약과 현재 재검증 결과는
[docs/RELEASE-0.1.0.md](docs/RELEASE-0.1.0.md)와
[docs/validation/CURRENT-REVALIDATION.md](docs/validation/CURRENT-REVALIDATION.md)를
참조한다.
