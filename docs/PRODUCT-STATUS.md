# AIA 제품 상태

현재 AIA는 설치 후 바로 모든 Agent와 모든 도구를 보호하는 완성형 보안 제품이
아니다. 정확한 위치는 **제품 형태를 갖춘 0.1 Alpha**다. 사용자가 실제로 실행할
수 있는 보호 실행 경로와 로컬 콘솔은 있지만, 지원 범위와 검증된 주장도 함께
제한된다.

신규 실행의 기본 정책은 `PROTECTED_DEVELOPMENT` v1.1이다. `.env` 같은 비밀정보 읽기와
대표적인 파괴 명령은 기본 차단하고, Windows의 `Remove-Item`, `del`, `erase`,
`rd /s`, `Stop-Process`, `taskkill /f`도 실행 전에 차단한다. 일반 소스 변경은 기록한다. 기존의
`BASIC_DEVELOPMENT`, `CONSERVATIVE_SECURITY`, `FREE_DEVELOPMENT` 프로필은
호환성을 위해 그대로 제공하며 실행 시 명시적으로 선택할 수 있다.

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
제품 증명 명령에는 disposable Workspace의 `.env` 읽기 시도를 다루는
`block-env` 시나리오도 있으며, deny·부작용 없음·secret marker 비유출을 함께
확인한다.
비대화형 `aia protect --task` 경로에서는 Codex의 제한된 native block 결과와
PostToolUse 부재를 함께 확인한 경우 Result Bundle에도 `BLOCKED / SUCCEEDED`를
기록한다. 이때 Codex 출력 원문은 저장하지 않고 SHA-256과 판정 메타데이터만
보존한다.
설치된 wheel에서도 기본 한국어 정책 프로필을 패키지 데이터에서 해석할 수 있으며,
`aia hook verify`는 임시 Workspace의 실제 Codex 실행으로 Session-bound Hook
활성화를 점검한다.
정책을 실제 Agent 없이 확인하는 `aia policy evaluate`도 제공하므로, 사용자는
보호 실행 전에 특정 경로·명령이 어떤 Rule과 Effect로 판정되는지 확인할 수 있다.
웹 콘솔의 `정책 미리보기`에서도 같은 Resolved Policy 판정을 실행 없이 확인할 수
있다. 미리보기는 Codex를 시작하거나 Workspace에 접근하지 않고, 최종 판정·Effect·
보안 자산·적용 Rule만 보여준다.

일반 Protected Run은 실제 Codex Hook 연결 검증을 통과해야 시작한다. 즉 Hook 설정
파일이 존재하는 것만으로는 충분하지 않으며, `aia hook verify`가 Session-bound
Hook Event를 확인하고 현재 Hook 설정·Codex 실행 파일에 대한 검증 기록을 만든
뒤에만 `aia protect`와 콘솔 실행 버튼이 열리는 구조다. 검증 기록이 오래됐거나
실행 파일·Hook 설정이 바뀌면 다시 검증해야 한다.

처음 설치한 사용자는 `aia self-test`로 Codex를 실행하지 않고 Core 자체를 점검할
수 있다. 이 명령은 임시 Workspace에서 정책 프로필, Active Policy Freeze,
Workspace Lease, Safe Checkpoint, Raw Evidence Seal을 확인하고 기본 보호 프로필의
`.env READ → VIOLATION / DENY / SECRET` 판정도 확인한 뒤 임시 산출물을
삭제한다. `PASS`는 Core 정상 상태를 뜻하며 실제 Codex Hook 보호 증명은 별도로
`aia hook verify`에서 수행한다. `aia hook verify`는 Codex PreToolUse Trust가
`MODIFIED`, `UNTRUSTED` 또는 `NOT_VISIBLE`이면 Probe를 실행하지 않고 종료한다.

설치·Hook·최근 보호 실행에 문제가 생기면 `aia support-bundle --output <path>`로
비밀정보를 제외한 진단 JSON을 만들 수 있다. 이 번들은 전체 경로, Workspace 내용,
raw evidence, tool input과 명령 출력을 포함하지 않는다.

Process Manager 자체는 별도 Windows PowerShell smoke에서 `Root → Child →
Grandchild = TERMINATED / SUCCEEDED`, unrelated process = `LIVE_MATCH`로 확인했다.
추가로 실제 Codex가 생성한 동일한 트리를 사용자가 중지하는 경로에서도 세 프로세스
종료, unrelated 프로세스 보존, `user_abort_termination_result=SUCCEEDED`,
`verified_tree_gone=true`, Result Bundle `VALID`를 확인했다. 이 결과는 사용자 중지
계약의 증거이며, 정책 위반에 따른 자동 destructive PROCESS 집행까지 증명하는 결과는
아니다.

2026-09-11에는 Codex 0.154.0의 실제 Bash, `apply_patch`, `.env` 읽기 PreToolUse를
direct adapter smoke로 추가 확인했다. 세 시나리오 모두 AIA가
`VIOLATION → CONTAIN → PRETOOL_BLOCK`을 결정하고 Codex에 실제 `deny`를 반환했으며,
부작용 없이 `BLOCKED / SUCCEEDED`와 Bundle `VALID`를 기록했다. `.env` 시나리오에서는
Codex 출력과 Evidence/Result에 secret marker가 없었다. 이 자동화 검증은 disposable
Workspace와 일회성 inline Hook을 사용한 경로이며, 일반 사용자의 Hook Trust 절차를
생략하는 제품 사용 방식은 아니다.

Protected Run의 Process Sensor는 제품 경로에서 관찰한 프로세스 명령행을 선택적으로
Raw Evidence로 보존하고, 등록된 Command Rule의 lexical `EXECUTE` 판정에 사용할 수
있다. 이 정보는 프로세스가 실행됐다는 사실과 명령행 문자열만 보여 주며, 명령 내부의
파일 변경을 증명하지 않는다. 현재 `PROCESS` Attribution은 자동 종료 권한으로
승격되지 않으므로, 이 결과는 정책 위반 관찰·기록과 `REFUSE / NONE` 보수성으로
해석한다.

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

## AIA 비정상 종료 후 상태 복구

AIA 조정 프로세스가 강제 종료되면 이전 실행의 상태 파일이 남을 수 있다. 새 AIA
프로세스는 PID만 보지 않고 조정 프로세스의 PID와 생성 시각을 함께 검증한다. 조정
프로세스가 사라진 실행은 Session을 성공·완료로 바꾸지 않고
`ORPHANED_DEGRADED`로 표시한다.

같은 Workspace로 새 Protected Run을 시작할 때도 이 상태를 확인한다. 기록된 Agent
Root가 아직 살아 있거나 신원을 확인할 수 없으면 Workspace 재사용을 거부한다.
Agent Root가 사라졌다는 것이 확인된 뒤 `aia reconcile <SESSION_ID>`를 완료해야
새 실행이 해당 Workspace를 사용할 수 있다. 이 확인은 두 실행이 같은 Workspace를
동시에 변경하는 상황을 막기 위한 것이며, 이전 Agent를 자동 종료하는 기능은 아니다.

실행 중 Agent Root가 기록된 경우에도 같은 PID와 생성 시각을 확인한다. 기록된
Agent Root가 아직 살아 있거나 확인할 수 없으면 자동 종료하지 않는다. Agent Root가
사라진 것이 확인된 뒤에만 다음 명령으로 이전 실행의 정리 확인을 남길 수 있다.

```powershell
uv run aia reconcile <SESSION_ID>
```

`reconcile`은 Evidence와 Result Bundle을 삭제하지 않으며, 고아 실행을 성공한
보호 실행으로 바꾸지도 않는다. 사용자는 `aia status <SESSION_ID>` 또는 로컬
콘솔에서 AIA 조정 프로세스와 Agent Root 상태를 확인할 수 있다.

## 아직 제품으로서 부족한 부분

- 등록된 파일 읽기 MCP 도구 이름은 `READ`로 정규화하며, 실제 MCP 서버 시작부터
  Hook 차단까지의 Protected Launcher E2E를 `mcp-read` Canary로 검증했다. 등록되지
  않은 MCP 도구와 전체 Codex 도구 범위는 지원하지 않는다.
- 대화형 세션과 Codex 버전·출력 형식별 실행 결과 확인을 더 넓게 검증해야 한다.
- 정책 위반에 따른 Actual Codex destructive Process Tree 보상 집행은 개발자
  fault-injection 환경에서 실제 `PostToolUse → POST_ACTION → TERMINATED →
  RESTORED + VERIFIED`까지 검증했다. 정상 제품 경로의 기본 관문은 여전히
  `PreToolUse deny`이며, Hook이 도착하지 않는 실행은 보상 집행 성공으로
  주장하지 않는다.
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

1. 정상 제품 경로에서 Hook Trust를 통과한 Actual Codex 사전 차단과 보상 집행을
   한 번의 사용자 시나리오로 연결한다.
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
