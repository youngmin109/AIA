# 변경 이력

이 파일은 공개 배포 버전의 사용자에게 보이는 변경 사항을 기록한다.

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
