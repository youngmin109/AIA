# AIA 제품 상태

현재 AIA는 설치 후 바로 모든 Agent와 모든 도구를 보호하는 완성형 보안 제품이
아니다. 정확한 위치는 **제품 형태를 갖춘 0.1 Alpha**다. 사용자가 실제로 실행할
수 있는 보호 실행 경로와 로컬 콘솔은 있지만, 지원 범위와 검증된 주장도 함께
제한된다.

## 현재 실제로 사용할 수 있는 것

Windows 11에서 다음 순서로 Codex를 AIA Protected Run 안에서 시작할 수 있다.

```text
Workspace 선택
→ 정책 검증·고정
→ Workspace Lease 준비
→ Safe Checkpoint 생성
→ File / Hook / Process Sensor 준비
→ Codex를 AIA 자식 프로세스로 실행
→ 지원되는 PreToolUse 관문 평가
→ Evidence Bundle 생성
→ 결과·무결성 검증
```

현재 검증된 지원 계약은 Windows 11, Codex CLI, AIA가 직접 시작한 실행, 그리고
`Bash`, `apply_patch`, `Edit`, `Write` 계열과 등록된 파일 읽기 MCP 경로의
PreToolUse다. 실제 Codex Bash, `apply_patch`, MCP 파일 읽기 Canary에 대해
`permissionDecision=deny`와 파일 미생성을 확인했고,
정상 읽기 실행에 대해서는 실제 Hook Evidence와 `Bundle VALID`를 확인했다.
비대화형 `aia protect --task` 경로에서는 Codex의 제한된 native block 결과와
PostToolUse 부재를 함께 확인한 경우 Result Bundle에도 `BLOCKED / SUCCEEDED`를
기록한다. 이때 Codex 출력 원문은 저장하지 않고 SHA-256과 판정 메타데이터만
보존한다.

Process Manager 자체는 Codex 실행 환경의 Job Object 영향을 피한 별도 Windows
PowerShell smoke에서도 `Root → Child → Grandchild = TERMINATED / SUCCEEDED`,
unrelated process = `LIVE_MATCH`로 확인했다. 이 결과는 관리된 프로세스 종료 계약의
증거이며, Actual Codex가 생성한 트리의 종료까지 자동으로 증명하는 결과는 아니다.

## 현재 결과를 읽는 방법

차단 결과는 두 층으로 기록한다.

```text
Enforcement Gate
→ VIOLATION / CONTAIN / PRETOOL_BLOCK

실제 실행 결과 확인
→ BLOCKED / SUCCEEDED
```

첫 번째는 AIA가 실행 전에 차단 결정을 내렸다는 뜻이다. 두 번째는 실제 도구가
실행되지 않았다는 확인까지 연결됐다는 뜻이다. `scripts/product_e2e_smoke.py
--scenario block-canary`는 실제 제품 CLI 경로에서 이 두 결과를 모두 확인하고,
`CANARY_NO_SIDE_EFFECT`와 `confirmed_block_count`를 함께 표시한다. Codex 출력이
지원되는 native block 문장을 제공하지 않거나 실행 확인이 모호하면 AIA는 Gate
결과만 남기고 `BLOCKED / SUCCEEDED`를 만들지 않는다.

이 분리는 결과를 약하게 보이게 하려는 것이 아니라, “차단 응답을 만들었다”와
“도구가 실행되지 않았다”를 같은 사실로 잘못 기록하지 않기 위한 제품 계약이다.

사용자 중지 결과도 정책 집행 결과와 분리한다. `USER_ABORT` 세션에서는
`user_abort_termination_result`가 등록된 Agent Root 트리의 종료 검증을 담고,
정책 Gate가 실행되지 않았으므로 이를 `CONTAIN` 또는 정책용
`process_termination_result`로 기록하지 않는다.

## 아직 제품으로서 부족한 부분

- 등록된 파일 읽기 MCP 도구 이름은 `READ`로 정규화하며, 실제 MCP 서버 시작부터
  Hook 차단까지의 Protected Launcher E2E를 `mcp-read` Canary로 검증했다. 등록되지
  않은 MCP 도구와 전체 Codex 도구 범위는 지원하지 않는다.
- 대화형 세션과 Codex 버전·출력 형식별 실행 결과 확인을 더 넓게 검증해야 한다.
- Actual Codex destructive Process Tree termination은 아직 제품 지원 주장으로
  완료하지 않았다.
- Hook 신뢰 검토는 Codex 화면에서 사용자가 직접 수행해야 하며 AIA가 자동 증명하지
  못한다.
- 소스 체크아웃용 Windows 설치 스크립트와 정책 프로필 초기화는 제공하지만,
  서명된 배포 설치 파일·업데이트·롤백 경로와 GUI 정책 작성은 아직 없다.
- 대규모 Workspace 성능 SLA와 OS 전체 Writer 통제는 제공하지 않는다.

따라서 현재 버전을 “개인 개발자가 제한된 지원 범위에서 실제 사용해 볼 수 있는
Alpha”라고 설명하는 것은 타당하지만, “어떤 Agent의 모든 파일·명령을 완전히
차단하는 제품”이라고 설명하면 안 된다.

## 다음 제품화 우선순위

1. Actual Codex Process Tree termination과 Recovery/Integrity 연계를 검증한다.
2. 소스 설치를 넘어 서명된 배포 설치 파일과 업데이트·롤백 경로를 제공한다.
3. 대화형 세션과 간헐적인 Process Sensor 실패를 안정화한다.
4. 성능 평가 결과와 제한사항을 제품 화면에서 함께 보여준다.

현재 온보딩에는 `aia setup`, `aia doctor`, 웹 콘솔의 실행 전 사전 점검이 포함된다.
이 점검은 Hook 설치 여부를 확인하지만 Codex의 Hook 신뢰는 자동으로 증명하지 않으며,
사용자가 Codex `/hooks` 화면에서 직접 검토해야 한다.
