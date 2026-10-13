# AIA 사용자 가이드

AIA는 Codex를 대신하는 프로그램이 아니다. AIA가 먼저 보호 실행을 시작하고,
그 안에서 Codex를 자식 프로세스로 실행한다. 사용자는 Codex 화면이 열린 뒤
평소처럼 작업을 입력한다.

이 가이드는 Windows에서 생성된 `aia.exe`가 차단되는 환경을 고려해 저장소 루트의
모든 AIA 명령을 다음 Python 모듈 실행 형식으로 표시한다.

## 처음 한 번만 준비

저장소 폴더에서 PowerShell을 연다.

```powershell
cd <AIA 저장소 폴더>
uv sync
uv run --isolated --project . python -m aia.cli self-test
uv run --isolated --project . python -m aia.cli setup
```

AIA의 현재 보호 범위와 지원하지 않는 경계를 확인하려면 다음을 실행한다.

```powershell
uv run --isolated --project . python -m aia.cli capabilities
```

이 명령은 실제 Workspace나 Codex를 실행하지 않는 읽기 전용 제품 계약 조회다.

`self-test`가 `결과: PASS`이면 AIA Core 자체가 정상이다. 이 명령은 Codex나
사용자 Workspace를 실행하지 않는다.

처음 제품 흐름을 직접 확인하려면 실제 프로젝트를 선택하기 전에 다음을 실행한다.

```powershell
uv run --isolated --project . python -m aia.cli demo
```

이 데모는 임시 Workspace에서 보호 준비와 정리까지 확인하고 사용자 파일이나
Codex를 건드리지 않는다. 실제 Codex 차단까지 확인하려면 `/hooks`에서 AIA Hook을
검토·신뢰한 뒤 다음을 실행한다.

```powershell
uv run --isolated --project . python -m aia.cli hook verify
uv run --isolated --project . python -m aia.cli demo --live
```

`--live`는 disposable Workspace에서 실제 Codex를 한 번 실행하는 선택적 증명이다.

`aia setup`은 Hook 파일을 설치한 뒤 현재 Codex가 보고한 PreToolUse Trust 상태도
함께 표시한다. `TRUSTED` 또는 `MANAGED`가 아니면 Codex에서 `/hooks`를 열어
AIA Hook의 명령과 Matcher를 확인하고 직접 신뢰해야 한다. `MODIFIED`,
`UNTRUSTED`, `NOT_VISIBLE`은 보호 실행이 준비된 상태가 아니다.

그 다음 Codex 화면에서 `/hooks`를 입력한다. AIA의 `PreToolUse` Hook 명령과
Matcher를 직접 확인하고 신뢰한다. AIA가 대신 신뢰하지 않는 이유는 사용자가
확인하지 않은 실행 경계를 자동으로 켜지 않기 위해서다.

데스크톱 앱에서는 신뢰 단계에 **터미널 열기** 버튼이 있다. 누르면 `codex`가
입력된(아직 실행하지 않은) PowerShell 창이 열린다. Enter를 누르고 `/hooks`에서
AIA Hook을 신뢰하면 몇 초 안에 자동으로 감지된다.

기록은 데이터베이스가 아니라 이 PC의 기록 폴더(기본값 `%USERPROFILE%\.aia\control`,
`AIA_CONTROL_ROOT`로 바꿀 수 있음)에 실행마다 파일로 저장된다. 실행 상태는
`run-status`, 실행별 증거·결과·감사 기록과 실행 전 기준점(작업 폴더 사본)은
`sessions/<실행 번호>`에 있다. 기준점 때문에 작업 폴더가 클수록 용량이 커진다.
설정에서 사용자가 정리를 확인하면 기준점 사본(복사한 작업 폴더)은 끝난 실행 중 최근 10개만 남긴다. 앱을 켜는 것만으로 사본을 삭제하지 않는다. 삭제한 실행은 복구할 수 없으며 감사 기록만 남는다.
감사 기록·증거·기준점 매니페스트는 지우지 않으므로 결과 검증은 그대로 되지만, 사본을 지운 실행은 되돌릴 수 없다
(결과 화면에 '저장 공간 정리로 사본을 지웠어요'로 표시). 설정의 '저장 공간'에서 크기를 보고 바로 정리할 수도 있다.
설정의 **기록 폴더 열기**나 기록 화면 아래 버튼으로 바로 열 수 있다.

신뢰를 마친 뒤 PowerShell에서 다음을 실행한다.

```powershell
uv run --isolated --project . python -m aia.cli hook verify
uv run --isolated --project . python -m aia.cli doctor
```

PowerShell 대신 로컬 콘솔의 `새 보호 실행` 화면에서 `실제 Hook 연결 검증`을
눌러도 됩니다. 이 버튼은 기존 검증 경로를 실행할 뿐 Codex Hook Trust를 대신
승인하지 않습니다.

`aia doctor`의 마지막 결과가 `READY`여야 실제 보호 실행을 시작할 수 있다.
`MODIFIED`, `UNTRUSTED`, `NOT_READY`가 나오면 Codex `/hooks`에서 AIA Hook을
다시 확인하고 `uv run --isolated --project . python -m aia.cli hook verify`를 다시 실행한다.

웹 콘솔의 `실행 전 준비 상태`도 같은 `readiness_code`와 다음 조치를 표시한다.
예를 들어 `CODEX_HOOK_TRUST_REQUIRED`이면 콘솔에서 실행 버튼을 누르기 전에
Codex `/hooks`에서 AIA PreToolUse Hook을 검토·신뢰해야 한다.

자동화나 상태 확인 화면에서는 `uv run --isolated --project . python -m aia.cli doctor --json`의
`readiness_code`와 `next_step`을 사용한다. 예를 들어
`CODEX_HOOK_TRUST_REQUIRED`는 Codex `/hooks`에서 검토·신뢰한 뒤
`aia hook verify`를 실행해야 한다는 뜻이다. `READY`가 아닌 상태는 보호 실행을
시작할 수 있는 상태로 해석하지 않는다.

앱을 열면 홈에서 보호 연결 상태와 최근 실행을 확인할 수 있다. 홈의 `보호 시작`을
누르면 새 보호 실행 창에 연결 점검 세 가지(`Hook 연결`, `Codex 신뢰`,
`요청 전달 확인`)가 나온다. 준비되지 않은 항목이 있으면 `보호 시작`을 누르기 전에
표시된 다음 조치(설치, Codex `/hooks`에서 신뢰, `연결 검증`)를 먼저 완료한다.

`aia hook status`에서 `CURRENT_BUT_UNTRUSTED`가 나오면 과거 검증 지문은 남아
있지만 현재 Codex가 Hook을 신뢰하지 않는 상태다. Codex `/hooks`에서 다시 검토·신뢰한
뒤 `uv run --isolated --project . python -m aia.cli hook verify`를 실행한다.

## 정책을 먼저 확인하는 방법

앱의 `정책` 화면에서 정책을 고르면 그 정책의 규칙을 읽기 전용으로 볼 수 있다.
처리 방식은 색으로 구분한다: 허용은 초록, 허용하고 기록은 노랑, 금지는 빨강.

같은 화면 아래 `이 명령은 어떻게 판정될까?`에서 파일 경로나 명령을 넣고
`판정 보기`를 누르면 정책마다 결과를 보여준다. 예를 들어 행위 `읽기`, 경로 `.env`를
넣으면 기본 `표준 보호` 정책은 `차단`으로 나온다.

이 미리보기는 Codex를 시작하지 않고 파일도 읽지 않는다. 명령줄에서는
`aia policy evaluate --operation READ --path .env`로 같은 결과를 볼 수 있다.

## 보호 실행 시작

처음에는 실제 프로젝트 대신 복사본이나 테스트 폴더를 사용한다.

```powershell
uv run --isolated --project . python -m aia.cli protect C:\workspace\my-project
```

저장소 모듈 방식은 AIA 저장소 루트에서 실행하므로 Workspace 경로를 명시한다.

```powershell
cd <AIA 저장소 폴더>
uv run --isolated --project . python -m aia.cli start C:\workspace\my-project
```

실행이 시작되면 AIA는 실제로 보호하는 Workspace 절대 경로를 터미널에 표시합니다.

AIA는 다음 순서로 준비한다.

```text
Workspace 확인
→ 정책 고정
→ Lease 준비
→ Checkpoint 생성
→ File / Hook / Process Sensor 준비
→ Codex 실행
```

터미널에 `Phase: READY`가 표시되면 준비가 끝났고 Codex를 시작하는 단계다. 잠시
후 Codex 화면이 열리면 작업을 입력한다. 30초 이상 계속되면 같은 실행의 Session
ID로 `uv run --isolated --project . python -m aia.cli status <SESSION_ID>`를 실행해 상태를 확인하고, 필요하면
`Ctrl+C`로 사용자 중지를 요청한다.

Codex 화면이 열리면 그 안에서 작업을 입력한다.

```text
README.md를 읽고 현재 프로젝트를 세 문장으로 요약해줘
```

세션을 끝내려면 Codex를 정상적으로 종료한다. 그러면 AIA가 Evidence, 정책
판정, Recovery, Integrity, Audit 결과를 확정한다.

한 번의 요청만 실행하려면 다음처럼 사용할 수 있다.

```powershell
uv run --isolated --project . python -m aia.cli protect C:\workspace\my-project --task "README.md를 읽고 한 문장으로 요약해줘"
```

## 차단 동작을 확인하는 방법

실제 Codex를 사용하는 차단 검증은 disposable Workspace를 자동으로 만들고
끝난 뒤 정리한다.

```powershell
uv run --isolated --project . python -m aia.cli proof
```

`.env` 비밀정보 읽기 차단과 secret marker 비유출을 확인하려면 다음을 실행한다.

```powershell
uv run --isolated --project . python -m aia.cli proof --scenario block-env
```

Windows 기본 정책의 `Remove-Item` 파일 삭제 차단은 다음으로 확인한다.

```powershell
uv run --isolated --project . python -m aia.cli proof --scenario block-windows-delete
```

이 명령들은 실제 Codex 실행을 사용한다. `permissionDecision=deny`만으로
성공시키지 않고, Codex가 도구를 실행하지 않았고 부작용이 없었는지까지 확인한다.
기본 출력은 사람이 읽는 한국어 요약이며, 전체 JSON 보고서가 필요하면
`uv run --isolated --project . python -m aia.cli proof --json`을 사용한다.

## 결과 확인

실행이 끝난 뒤 PowerShell에서 실행 목록을 확인한다.

```powershell
uv run --isolated --project . python -m aia.cli runs
uv run --isolated --project . python -m aia.cli status <SESSION_ID>
uv run --isolated --project . python -m aia.cli console --open
```

결과를 해석할 때는 다음을 함께 본다.

```text
Bundle: VALID
Hook Event: 확인됨
Policy: VIOLATION 또는 COMPLIANT
Enforcement: BLOCKED / NONE / TERMINATED
Execution Result: SUCCEEDED 또는 FAILED
Recovery: RESTORED
Integrity: VERIFIED
```

`COMPLETED`만으로 보호가 검증된 것은 아니다. `COMPLETED_VERIFIED`는 실제
Session-bound Hook Event와 센서 상태, 검증된 Result Bundle이 함께 확인된
경우에만 사용한다. `COMPLETED_DEGRADED`는 실행은 끝났지만 보호 경계에
제한이 있었음을 뜻한다.

감사 과정에서 Result Bundle을 다시 확인하려면 Result Bundle 디렉터리나 Session
디렉터리를 지정한다.

```powershell
uv run --isolated --project . python -m aia.cli verify-bundle <result-dir> [--json]
```

기계가 읽을 출력이 필요하면 `--json`을 추가한다. 검증 결과가 `VALID`이면
종료 코드 0을 반환하고, `INVALID` 등 `VALID`가 아닌 결과는 종료 코드 1을
반환한다. 이 명령은 Bundle 파일을 수정하지 않는다.

실행 중 Hook Broker가 사라져 보호 경계가 끊기면 `FAILED_DEGRADED`가 기록될 수
있습니다. 이 경우 AIA는 관리 Agent 트리 중지를 시도하지만, 종료 성공 여부는
결과의 `protection_failure_termination_result`에서 별도로 확인해야 합니다.
Live Run 화면의 `LAUNCHING`은 보호 준비가 끝난 뒤 Codex 프로세스와 Process Sensor를
등록하는 중이라는 뜻이다. 이 단계에서는 Session 상태가 아직 `READY`일 수 있으며,
Codex가 등록되고 실행 상태가 확인되면 `RUNNING`으로 전환된다.

AIA가 비정상 종료되어 이전 실행이 `ORPHANED_DEGRADED`로 남으면 같은 Workspace로
새 보호 실행을 바로 시작할 수 없다. 기록된 Agent Root가 실제로 사라진 뒤 다음
명령으로 정리 확인을 남긴다.

```powershell
uv run --isolated --project . python -m aia.cli reconcile <SESSION_ID>
```

정리 확인 전에는 이전 Codex와 새 Codex가 같은 Workspace를 동시에 변경하지 않도록
새 실행이 거부된다. AIA는 살아 있는 이전 Agent를 자동으로 종료하지 않는다.

## 현재 보호 범위

현재 제품은 Windows 11, Codex CLI, AIA Protected Run, Codex 로컬 Hook 경로의
`PreToolUse`를 대상으로 한다. Hook matcher는 `*`지만 AIA가 의미를 해석하는
도구는 명시된 목록으로 제한하며, 목록 밖 도구는 `UNSUPPORTED_TOOL_PATH`로
거부한다. 모든 Codex 도구, 모든 MCP, 사용자가 직접 실행한 OS 작업, Hook을
우회한 경로까지 보호한다고 주장하지 않는다.
자세한 범위와 제한은 [PRODUCT-SUPPORT.md](PRODUCT-SUPPORT.md)와
[LIMITATIONS.md](LIMITATIONS.md)를 확인한다.

## 작업창에서 쓰는 Codex 기능

데스크톱 앱의 작업창은 Codex 앱에서 자주 쓰는 기능을 보호 실행 안에서 그대로 쓸 수 있게 한다
(EPIC-022). 모든 기능은 보호 폴더, 샌드박스, 승인 정책을 바꾸지 않는다.

- **시작 단계:** 시작하는 동안 "n/5단계 · 기준점 저장 중 · 파일 복사 n/N"처럼 지금 단계를 보여준다.
  - 새 실행 시트에서 파일이 1,000개 또는 50MB를 넘는 폴더를 고르면 시작이 오래 걸릴 수 있다고 미리 알린다.
- **Codex가 되묻는 요청**
  - **질문:** 선택지, 직접 입력, 가린 비밀 입력으로 답한다. 비밀 답은 Codex에만 전달되고 AIA 기록에 남지 않는다.
  - **외부 도구 입력:** 단순한 입력 양식이나 웹 주소 열기는 응답할 수 있다. 그릴 수 없는 양식은 거절·취소만 할 수 있다.
  - **권한 추가 요청:** "이번 요청만 / 이번 실행 내내 / 거절" 중에서 사용자가 고른다. 허용하면 보호 패널과 결과 화면에 "넓힌 권한"이 남는다.
- **사용량과 모델**
  - 작업창 위 칩에 Codex가 알려준 남은 한도를 보여준다.
  - 모델과 생각 깊이는 새 실행 시트나 작업창 칩에서 고르며, 다음 요청부터 적용된다.
- **작업 계획과 바뀐 내용**
  - Codex의 단계별 계획을 대화 위에 접어서 보여준다.
  - 요청마다 "바뀐 내용" 카드를 펼쳐 파일별 추가·삭제 줄을 본다.
- **빗금(/) 명령:** 요청 칸에서 `/`를 치면 명령 목록이 뜬다.
  - Codex 명령: `/model` `/status` `/diff` `/compact` `/review` `/goal 목표` `/resume` `/mcp`
  - AIA 명령: `/policy` `/why` `/restore` `/report`. `/why`는 마지막 차단 판정의 규칙과 단계만 보여주고 원문 명령은 보여주지 않는다.
  - 실행 전체의 보호를 바꾸는 `/approvals`, `/permissions`와 `/new`, `!` 셸 명령, `/logout`은 넣지 않았다.
- **이전 대화 이어하기**
  - 새 실행 시트의 "이전 대화 이어하기"나 `/resume`에서, 같은 작업 폴더에서 AIA로 연 대화만 골라 이어 쓴다.
  - Codex는 요청을 한 번도 보내지 않은 대화를 저장하지 않아서 이어할 수 없다. 이때는 새 대화로 시작하고 알린다.
- **커넥터:** `/mcp`와 보호 패널에서 연결된 외부 도구(MCP) 목록을 본다. 이번 실행에서 AIA가 끈 도구는 "보호 실행에서 꺼 둠"으로 보인다. 설치·로그인은 Codex 앱에서 한다.
- **여러 대화방:** 작업창 위 탭에서 대화방을 오가고, "+ 새 대화"로 다른 작업 폴더의 보호 실행을 하나 더 연다. 대화방마다 Codex, 실행 전 검사, 감시, 기준점이 따로 붙는다. 동시에 최대 4개까지 열 수 있고, 같은 폴더나 그 안팎의 폴더는 한 대화에서만 보호한다. 뒤에 있는 대화방이 승인·질문을 기다리면 탭에 "확인 필요"가 뜬다(응답 시간이 지나면 거절되니 바로 확인).
- **권한:** 기본값은 **승인 요청**이다. **나 대신 승인**은 Codex가 승인 요청을 대신 검토하고, **전체 권한**은 사용자가 명시적으로 선택할 때만 제한 없이 요청한다. 둘은 보호 범위 예외로 표시된다. AIA는 지원되는 Hook 요청만 검사하며 작업 폴더 밖 변경과 인터넷 사용은 복구 범위 밖이다. 작업창에서 바꾼 선택은 다음 새 요청에 예약된다. 전송 전 예외를 기록하며 Codex 접수와 실제 적용 검증을 구분한다. 진행 중인 작업의 권한은 바뀌지 않는다.
- **외부 도구 켜고 끄기:** 설정 › 외부 도구에서 도구마다 보호 실행에서 켤지 고른다. 기본은 모두 꺼짐이다. Hook을 거치지 않아 AIA가 막거나 기록하지 못할 수 있는 도구이기 때문이다. 다음 보호 실행부터 적용되고, Codex 설정 파일은 바꾸지 않아서 Codex 앱에서는 그대로 쓸 수 있다.

## 제품 화면에서 확인하는 것

데스크톱 앱(또는 `uv run --isolated --project . python -m aia.cli console --open`으로
연 브라우저)에서 `보호 시작`을 누르고 기존 작업 폴더, 정책, 권한을 고르면, 같은
화면에서 Codex 작업창과 AIA 보호 패널을 함께 사용할 수 있다. 작업창은 Codex
app-server와 대화를 주고받고, Hook·File·Process Sensor 상태는 API polling으로
갱신한다. 작업창 아래 입력란에 요청을 입력한 뒤 Enter를 누르면 Codex에 요청이
제출되며, 응답을 기다리는 동안 처리 중 표시가 나온다.

실행 중 화면에는 Hook·File·Process Sensor 카드, 최근 안전 이벤트, 차단 사건이
표시된다. 이벤트 요약에는 명령 원문, 비밀값, 파일 내용이 들어가지 않는다.
차단 사건은 정책 판정, AIA 결정, 실제 실행 결과, 부작용 확인을 따로 보여준다.
deny JSON을 만든 사실만으로 성공 처리하지 않으며, 실제 도구가 실행되지 않은
것이 확인된 경우에만 `BLOCKED / SUCCEEDED`를 표시한다.

실행 결과 화면에서는 센서 상태와 Evidence 건수를 먼저 확인한다. 그 아래에서
안전한 타임라인, 사건 상세, Recovery와 Integrity, Result Bundle을 확인할 수 있다.
`Evidence Chain`은 행위별로 Tool request, Process, File change, Policy decision,
Enforcement 관찰을 연결해 보여준다. Recovery는 개별 행위가 아니라 실행 단위 결과다.
단계가 `not observed`로 표시되면 해당 연결 증거를 관찰하지 못했다는 뜻이며,
그 행위가 발생하지 않았다는 뜻은 아니다. Process 증거만으로 특정 프로세스가
파일을 작성했다고 판단할 수도 없다.
`/runs`의 실행 기록에는 Workspace·상태·보호 상태·차단 여부·날짜 필터가 있다.
