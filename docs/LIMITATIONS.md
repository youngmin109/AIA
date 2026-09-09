# AIA MVP 제한사항

EPIC-018 평가에서 확인한 제품의 범위와 한계다. 아래 항목을 해결된 보안 주장으로 표현하지 않는다.

- `PROCESS` 증거는 정확한 파일 Writer를 증명하지 않는다.
- 사후 파일시스템 감지는 사전 예방이 아니다.
- Hook 실패 시 Agent가 계속 실행될 수 있다.
- 현재 Actual Codex 경로에서는 구조화된 `READ .env → BLOCKED`를 검증하지 못했다. 실제 시험은 Shell `EXECUTE` 경로로 관찰됐다.
- Windows Job Object와 프로세스 수명주기는 테스트 실행 환경에 영향을 줄 수 있다.
- Symlink/Junction/Reparse Point 범위는 거부 계약과 환경 독립 테스트로 검증했으며, 권한 없는 Windows 환경의 실제 Symlink 통합 테스트는 실행되지 않을 수 있다.
- OS 수준의 파일 Writer 귀속은 제공하지 않는다.
- Network Security는 MVP 보호 범위가 아니다.
- Database state protection은 제공하지 않는다.
- ACL/ADS 메타데이터 복구를 보장하지 않는다.
- 전체 Workspace에 대한 원자적 트랜잭션은 제공하지 않는다.
- 외부 Writer race 및 TOCTOU는 제한사항이다.
- GB 단위 Workspace 성능 목표나 SLA를 주장하지 않는다.
- Actual Codex의 파괴적 `PROCESS` 시나리오와 Actual Codex 프로세스 트리 종료는 이번 평가에서 실행하지 않았다. 결정론적 Process Manager fixture만 검증했다.

이 제한사항은 `docs/validation/CLAIM-MATRIX.md`의 허용 문구와 함께 읽어야 한다.
