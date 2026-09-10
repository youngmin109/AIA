# AIA 0.1.0 Release Readiness

이 문서는 현재 저장소가 제공하는 제품 범위와 검증된 동작을 한 곳에서 확인하기 위한 릴리스 문서다. AIA를 모든 Agent와 모든 운영체제를 보호하는 범용 보안 제품으로 해석하지 않는다.

## 지원 계약

| 항목 | 현재 계약 |
|---|---|
| 운영체제 | Windows 11 |
| Agent | Codex CLI |
| 시작 방식 | AIA Protected Run에서 AIA가 실행한 Codex |
| 사전 통제 지점 | Codex `PreToolUse` Hook |
| 지원 matcher | Bash, `apply_patch`, Edit, Write 계열, 등록된 파일 읽기 MCP matcher |
| 저장 위치 | Workspace 밖의 사용자별 AIA Control Root |
| 결과 | 검증된 Evidence Bundle과 보안 결과 |

## 검증된 동작

다음 동작은 내부 단위 테스트가 아니라 실제 제품 경계 또는 실제 Codex 실행으로 확인했다.

- `uv run pytest`: 전체 회귀 테스트 통과
- `uv build`: source distribution과 wheel 생성
- 실제 Codex Bash Canary: `permissionDecision=deny`, Canary 파일 미생성
- 실제 Codex `type .env`: Secret 출력 없음, PostToolUse 성공 없음
- 실제 Hook Event: `tool_name`, 원문 command, `tool_use_id`와 AIA Session 연결
- 선택적 PostToolUse Event: 도구 출력 원문을 저장하지 않고 실행 확인용 digest만 보존
- 실제 `aia protect` CLI 경로: disposable Workspace에서 `COMPLETED`와 `Bundle VALID` 확인
- 명시적으로 등록된 파일 읽기 MCP 도구 이름은 `READ` 의미로 평가하며, 실제 MCP
  서버 시작·호출과 `.env` PreToolUse 차단을 `mcp-read` Canary로 검증했다. 등록되지
  않은 MCP 도구는 추측하지 않는다.
- `VIOLATION → CONTAIN → PRETOOL_BLOCK → BLOCKED/SUCCEEDED` 결과 기록
- 검증된 PreTool deny가 실제로 무시되어 PostToolUse가 들어온 경우의 별도
  `POST_ACTION → PROCESS_TERMINATION` 보상 경로와 실제 Process Manager 결과 기록
- Evidence Bundle `VALID`와 SHA-256 artifact 목록 생성
- 실행 종료 후 `COMPLETED_VERIFIED` 또는 `COMPLETED_DEGRADED` 상태 구분
- 실행 중 사용자 중지 요청과 `USER_ABORT` 결과 기록
- 별도 터미널에서 실행 중인 세션의 상태 조회와 중지 요청

실제 실행 증명 방법은 [ACTUAL-CODEX-PROOF.md](ACTUAL-CODEX-PROOF.md)에 있다. 자동화 증명 산출물은 `evaluation/actual-codex/pretool-block/<timestamp>/`에 생성한다.

## 사용 시작

Windows 소스 체크아웃에서는 [INSTALL.md](../INSTALL.md)의 설치 스크립트로
잠금된 환경을 준비할 수 있다. AIA가 추가한 Hook만 되돌릴 때는
`uv run aia hook uninstall`을 사용한다.

```powershell
uv sync
uv run aia hook install
uv run aia hook verify
uv run aia doctor
```

Codex에서 `/hooks`를 열어 AIA Hook을 검토·신뢰한 뒤 다음을 실행한다.

```powershell
uv run aia doctor
```

`READY`가 확인된 뒤에만 보호 실행을 시작한다.

```powershell
uv run aia protect C:\workspace\my-project
```

종료 후 기록을 확인한다.

```powershell
uv run aia runs
uv run aia status <SESSION_ID>
uv run aia-web
```

## 현재 미완료 검증

다음 항목은 실패를 숨기지 않고 현재 릴리스의 제한사항으로 남긴다.

- 실제 Codex destructive Process Tree termination의 성공 증명
- 지원 범위 밖 MCP·Hosted tool·외부 Agent·사용자 수동 실행
- Hook 장애가 발생한 모든 경로의 OS 수준 fail-closed 보장
- 대규모 Workspace 성능 SLA
- 사용자 중지 요청이 실패한 경우의 자동 복구 보장

이 항목을 통과하기 전에는 AIA를 해당 범위까지 보호한다고 광고하지 않는다. 자세한 금지 주장은 [LIMITATIONS.md](LIMITATIONS.md)와 [CLAIM-MATRIX.md](validation/CLAIM-MATRIX.md)를 따른다.

## 공개 배포 전 확인

- [ ] 공개 저장소 주소와 유지보수 담당자 지정
- [ ] Windows 11 신규 환경에서 `uv sync`, `aia doctor`, Hook trust 확인
- [ ] 실제 Codex Canary와 `.env` Shell 시나리오 재실행
- [ ] 지원 범위 밖 동작을 `PROTECTED`로 표시하지 않는지 확인
- [ ] 보안 문제는 [SECURITY.md](../SECURITY.md) 절차로 접수
- [ ] `scripts/package-release.ps1`로 wheel·sdist·SHA-256 manifest를 생성하고 압축 해제 검증
