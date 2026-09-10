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
설치된 wheel에서도 기본 한국어 정책 프로필을 패키지 데이터에서 해석할 수 있으며,
`aia hook verify`는 임시 Workspace의 실제 Codex 실행으로 Session-bound Hook
활성화를 점검한다.
정책을 실제 Agent 없이 확인하는 `aia policy evaluate`도 제공하므로, 사용자는
보호 실행 전에 특정 경로·명령이 어떤 Rule과 Effect로 판정되는지 확인할 수 있다.

일반 Protected Run은 실제 Codex Hook 연결 검증을 통과해야 시작한다. 즉 Hook 설정
파일이 존재하는 것만으로는 충분하지 않으며, `aia hook verify`가 Session-bound
Hook Event를 확인하고 현재 Hook 설정·Codex 실행 파일에 대한 검증 기록을 만든
뒤에만 `aia protect`와 콘솔 실행 버튼이 열리는 구조다. 검증 기록이 오래됐거나
실행 파일·Hook 설정이 바뀌면 다시 검증해야 한다.

처음 설치한 사용자는 `aia self-test`로 Codex를 실행하지 않고 Core 자체를 점검할
수 있다. 이 명령은 임시 Workspace에서 정책 프로필, Active Policy Freeze,
Workspace Lease, Safe Checkpoint, Raw Evidence Seal을 확인하고 임시 산출물을
삭제한다. `PASS`는 Core 정상 상태를 뜻하며 실제 Codex Hook 보호 증명은 별도로
`aia hook verify`에서 수행한다. `aia hook verify`는 Codex PreToolUse Trust가
`MODIFIED`, `UNTRUSTED` 또는 `NOT_VISIBLE`이면 Probe를 실행하지 않고 종료한다.

Process Manager 자체는 별도 Windows PowerShell smoke에서 `Root → Child →
Grandchild = TERMINATED / SUCCEEDED`, unrelated process = `LIVE_MATCH`로 확인했다.
추가로 실제 Codex가 생성한 동일한 트리를 사용자가 중지하는 경로에서도 세 프로세스
종료, unrelated 프로세스 보존, `user_abort_termination_result=SUCCEEDED`,
`verified_tree_gone=true`, Result Bundle `VALID`를 확인했다. 이 결과는 사용자 중지
계약의 증거이며, 정책 위반에 따른 자동 destructive PROCESS 집행까지 증명하는 결과는
아니다.

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
--scenario block-canary`는 실제 제품 CLI 경로에서 이 두 결과를 확인하도록 구성되어
있으며,
`CANARY_NO_SIDE_EFFECT`와 `confirmed_block_count`를 함께 표시한다. Codex 출력이
지원되는 native block 문장을 제공하지 않거나 실행 확인이 모호하면 AIA는 Gate
결과만 남기고 `BLOCKED / SUCCEEDED`를 만들지 않는다. Hook 신뢰가 standalone
`codex exec`에 적용되지 않은 환경에서는 `hook_event_count=0`과
`COMPLETED_DEGRADED`가 기록되며, Canary 파일이 없어도 제품 차단 성공으로
인정하지 않는다.

같은 증명은 설치된 제품 CLI의 `uv run aia proof`로도 실행할 수 있다. 이 명령은
실제 시나리오 전에 현재 Hook Trust와 Session-bound Hook을 확인하고, 검증이 실패하면
Codex 도구를 실행하지 않는다. 결과 artifact에는 Hook 검증 결과와 실제 Protected Run
결과를 함께 남긴다.

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
- 정책 위반에 따른 Actual Codex destructive Process Tree 자동 집행은 아직 제품
  지원 주장으로 완료하지 않았다. 실제 Codex 사용자 중지 트리 종료는 검증했으며,
  검증된 PreTool deny 이후 실제 PostToolUse가 들어오는 우회 상황에 대한 별도
  POST_ACTION Gate와 보상적 Process Manager 경로의 Actual Codex 성공 증명은 남아 있다.
- Hook 신뢰 검토는 Codex 화면에서 사용자가 직접 수행해야 하며 AIA가 자동 증명하지
  못한다.
- 소스 체크아웃용 Windows 설치 스크립트와 릴리스 ZIP의 wheel 설치기를 제공하며,
  `uv tool install`로 어느 Workspace에서든 `aia`를 실행할 수 있다. 서명된 배포
  설치 파일·자동 업데이트·롤백 경로와 GUI 정책 작성은 아직 없다.
- 대규모 Workspace 성능 SLA와 OS 전체 Writer 통제는 제공하지 않는다.

따라서 현재 버전을 “개인 개발자가 제한된 지원 범위에서 실제 사용해 볼 수 있는
Alpha”라고 설명하는 것은 타당하지만, “어떤 Agent의 모든 파일·명령을 완전히
차단하는 제품”이라고 설명하면 안 된다.

## 다음 제품화 우선순위

1. 정책 위반에 따른 Actual Codex Process Tree 자동 집행과 Recovery/Integrity 연계를 검증한다.
2. 소스 설치를 넘어 서명된 배포 설치 파일과 업데이트·롤백 경로를 제공한다.
3. 대화형 세션과 간헐적인 Process Sensor 실패를 안정화한다.
4. 성능 평가 결과와 제한사항을 제품 화면에서 함께 보여준다.

현재 온보딩에는 `aia setup`, `aia doctor`, 웹 콘솔의 실행 전 사전 점검이 포함된다.
이 점검은 Hook 설치 여부를 확인하지만 Codex의 Hook 신뢰는 자동으로 증명하지 않으며,
사용자가 Codex `/hooks` 화면에서 직접 검토해야 한다.
웹 콘솔은 `대화형 보호 세션`을 기본 제공하므로 사용자가 작업 문장을 미리 입력하지
않고도 AIA가 먼저 보호된 Codex 세션을 연 뒤 그 안에서 작업을 시작할 수 있다. 한 번의
요청만 실행하는 `한 번의 작업 실행`도 별도로 선택할 수 있다.

Protected Launcher는 제품 실행에 `workspace-write` Sandbox와 `on-request`
Approval Policy를 요청하고, 바깥 Codex의 일시적인 세션·권한 환경값을 자식 Codex로
전달하지 않는다. 현재 Codex CLI의 비대화형 `exec`에서는 이 계약을 공식
`--approve-for-me` 실행 경로로 요청한다. 사용자가 검토한 Hook trust와 인증 설정은
유지하면서 보호 실행에 필요한 Sandbox와 Approval Policy를 명시적으로 요청한다. 실제 Codex가 보고한 실행
Sandbox와 Approval Policy는 Result Bundle에 제한된 메타데이터로 남긴다. 실행 환경이
`read-only`로 강등되거나 보호 설정이 제품 요청과 다르게 적용되면 실행은 성공으로 포장하지 않고
`COMPLETED_DEGRADED`와 제한사항을 남긴다.
