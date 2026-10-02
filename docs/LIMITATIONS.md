# AIA MVP 제한사항

2026-10-02 개선 작업본의 복구 범위, 표시 인덱스 제한, 로컬 브라우저 경계와
미완료 검증은 [개선 작업 기록](PRODUCT-UPDATE-2026-10-02.md)에 별도로 명시한다.

EPIC-018 평가에서 확인한 제품의 범위와 한계다. 아래 항목을 해결된 보안 주장으로 표현하지 않는다.

- `PROCESS` 증거는 정확한 파일 Writer를 증명하지 않는다.
- 사후 파일시스템 감지는 사전 예방이 아니다.
- AIA에 연결되지 않은 Hook 우회 경로와 지원 범위 밖 도구는 보호되지 않는다.
  보호 실행에 바인딩된 동기식 PreToolUse Hook은 Broker·Capability 오류 시 Codex의
  documented blocking exit path를 사용하고 Broker가 사라진 실행은 검증 상태를
  유지하지 않지만, PostToolUse 오류는 이미 실행된 작업을 되돌릴 수 없고 Hook 우회
  경로를 OS 수준에서 차단하지 않는다.
- MCP 도구는 현재 MVP 지원 범위가 아니다. Hook으로 도착한 MCP 요청은
  `UNSUPPORTED_TOOL_PATH`로 거부하며, MCP 서버 등록·호출이나 구조화된 MCP READ
  보호를 제품 기능으로 주장하지 않는다.
- Codex 설정에서 켠 MCP 서버의 도구 호출은 보호 범위 밖이다. Codex 앱이 추가하는
  `node_repl` 같은 일부 MCP 도구는 PreToolUse Hook을 거치지 않아 AIA가 차단하거나
  기록하지 못한다. 사전 점검은 `config.toml`의 `[mcp_servers]`를 읽기만 해서 켜진
  서버를 경고하며, Codex 설정을 바꾸지 않는다.
- Windows Job Object와 프로세스 수명주기는 테스트 실행 환경에 영향을 줄 수 있다.
- Symlink/Junction/Reparse Point 범위는 거부 계약과 환경 독립 테스트로 검증했으며, 권한 없는 Windows 환경의 실제 Symlink 통합 테스트는 실행되지 않을 수 있다.
- OS 수준의 파일 Writer 귀속은 제공하지 않는다.
- File Sensor는 `modified` 이벤트가 온 파일의 크기와 SHA-256이 마지막으로 알려진 내용
  (실행 전 Checkpoint)과 같으면 권한·속성만 바뀐 것으로 보고, 원시 증거에
  `content_unchanged`로 남기되 MODIFY 행위로 판정하지 않는다(Codex 샌드박스의 ACL 추가 등).
  비교는 이벤트를 처리하는 시점의 내용 기준이므로, 그 전에 내용을 바꿨다 똑같이 되돌린 경우도
  수정으로 보지 않는다. Checkpoint에 없거나 32MB를 넘거나 읽을 수 없는 파일, 한 번이라도
  내용이 달라진 파일, 폴더 이벤트는 기존처럼 수정으로 판정한다.
- 보호 경계 실패 시 AIA가 관리 Root 트리 중지를 시도하지만, 종료 성공 자체를 보장하지 않는다.
- Network Security는 MVP 보호 범위가 아니다.
- Database state protection은 제공하지 않는다.
- ACL/ADS 메타데이터 복구를 보장하지 않는다.
- 전체 Workspace에 대한 원자적 트랜잭션은 제공하지 않는다.
- 외부 Writer race 및 TOCTOU는 제한사항이다.
- GB 단위 Workspace 성능 목표나 SLA를 주장하지 않는다.
- 정책 위반에 따른 Actual Codex의 자동 destructive `PROCESS` 집행은 아직 검증하지 않았다. 다만 실제 Codex 사용자 중지 경로에서는 등록된 Root → Child → Grandchild 트리 종료와 unrelated 프로세스 보존을 확인했다. 이 결과를 정책 위반 자동 집행의 성공으로 해석하지 않는다.

이 제한사항은 `docs/validation/CLAIM-MATRIX.md`의 허용 문구와 함께 읽어야 한다.
