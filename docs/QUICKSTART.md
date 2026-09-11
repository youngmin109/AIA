# AIA 빠른 시작

AIA는 Codex를 대신하는 프로그램이 아니다. AIA가 먼저 보호 실행을 만들고,
그 안에서 Codex를 자식 프로세스로 시작한다. 사용자는 Codex 화면이 열린 뒤
평소처럼 작업을 입력한다.

처음 제품 흐름만 확인하려면 실제 프로젝트 경로 없이 다음부터 실행한다.

```powershell
uv run aia demo
```

이 명령은 임시 Workspace에서 정책, Active Policy, Lease, Safe Checkpoint,
Evidence 봉인과 정리 흐름을 실행한다. 사용자의 Workspace나 Codex를 시작하지
않는다.

기본 정책은 `보호 우선 개발형(PROTECTED_DEVELOPMENT) v1.1`이다. `.env` 같은 비밀정보
읽기와 대표적인 파괴 명령은 기본 차단하고, Windows의 `Remove-Item`, `del`,
`Stop-Process`, `taskkill /f`도 실행 전에 차단한다. 일반 소스 변경은 기록한다. 실행 시
`--profile BASIC_DEVELOPMENT` 또는 `--profile FREE_DEVELOPMENT`를 명시하면 다른
기본 정책을 선택할 수 있다.

## 1. AIA Core 확인

저장소 폴더에서 실행한다.

```powershell
uv run aia self-test
```

`PASS`가 나오면 AIA의 정책·Workspace Lease·Checkpoint·Evidence 핵심 기능이
정상이다. 이 명령은 Codex를 실행하지 않는다.

현재 제품이 실제로 보호한다고 주장하는 범위를 먼저 확인하려면 다음 명령을
실행한다. 이 명령은 Workspace나 Codex를 실행하지 않는다.

```powershell
uv run aia capabilities
```

출력의 `지원하지 않거나 주장하지 않는 범위`도 함께 확인한다. AIA는 지원되지
않는 도구를 보호했다고 표시하지 않는다.

설치나 실행에 문제가 생기면 다음 명령으로 민감한 실행 원문을 포함하지 않는
진단 파일을 만들 수 있다.

```powershell
uv run aia support-bundle --output .\aia-support-bundle.json
```

## 2. Hook 설치

```powershell
uv run aia setup
```

설치와 신뢰의 차이가 헷갈리면 다음 명령으로 AIA가 설치한 Hook의 검토 대상과
다음 단계를 먼저 확인한다.

```powershell
uv run aia hook explain
```

그 다음 Codex에서 `/hooks`를 입력하고 AIA `PreToolUse` Hook의 명령과 Matcher를
검토한다. 내용을 확인한 뒤 직접 Trust한다. AIA가 대신 Trust하지 않는 이유는
사용자가 승인하지 않은 실행 경계를 AIA가 임의로 활성화하면 안 되기 때문이다.

## 3. 실제 Hook 연결 확인

```powershell
uv run aia hook verify
```

이 명령은 임시 Workspace에서 무해한 Probe를 한 번 실행한다. 성공하면
`VERIFIED`가 표시된다. `MODIFIED`, `UNTRUSTED`, `NOT_VISIBLE`이면 Probe를
실행하지 않고 Codex `/hooks`에서 검토·Trust해야 할 내용을 알려준다.

설치된 제품 경로에서 실제 Bash 사전 차단을 한 번 확인하려면 다음을 실행한다.

```powershell
uv run aia proof
```

이 명령은 disposable Workspace에서 실제 Codex를 실행하고, Canary 미생성과
`Bundle VALID`까지 확인한다. Hook Trust가 확인되지 않으면 Codex 도구를 실행하지
않고 실패 원인과 artifact 경로만 남긴다. 실제 Codex 실행을 소비하므로 일반 회귀
테스트마다 반복하지 않는다.
기본 출력은 한국어 요약이다. 전체 기계 판독용 보고서가 필요하면
`uv run aia proof --json`을 사용한다.

`.env` 비밀정보 읽기 차단을 확인하려면 다음을 실행한다.

```powershell
uv run aia proof --scenario block-env
```

이 시나리오는 실제 PreToolUse 차단과 실행 확인뿐 아니라, `.env`의 secret marker가
Codex 출력·Evidence·Result에 나타나지 않는지도 확인한다.

Windows 기본 정책의 `Remove-Item` 실행 전 차단은 다음으로 확인한다.

```powershell
uv run aia proof --scenario block-windows-delete
```

실제 Agent를 시작하기 전에 정책 결과를 미리 확인할 수도 있습니다. 정책 미리보기는
대상 명령을 실행하지 않으며, 선택한 정책의 최종 판정과 매칭 Rule만 출력합니다.

```powershell
uv run aia policy evaluate --operation READ --path .env
uv run aia policy evaluate --operation EXECUTE --command "python build.py"
```

웹 콘솔을 사용하는 경우에도 `정책 미리보기`에서 행위 종류와 파일 경로 또는 명령을
입력해 같은 확인을 할 수 있습니다. `차단 대상`, `허용·기록 대상`, `판정 불가` 중
하나의 결과와 적용된 Rule을 보여주며, 이 단계에서는 Codex·파일·명령을 실행하지
않습니다. 정책을 바꾼 뒤에는 실행 화면의 미리보기 결과도 다시 확인하세요.

## 4. 보호 실행 시작

먼저 실제 프로젝트 대신 복사본이나 테스트 프로젝트를 사용한다.

```powershell
uv run aia protect "C:\workspace\my-project"
```

현재 PowerShell이 보호할 프로젝트 폴더라면 경로를 생략할 수 있습니다.

```powershell
cd "C:\workspace\my-project"
uv run aia start
```

AIA는 실행 시작 시 실제 보호 Workspace 절대 경로를 표시합니다.

실행 중 화면의 `파일 관찰` 수치는 File Sensor가 관찰한 이벤트 건수입니다. 원문
payload는 화면에 노출하지 않으며, 이 수치만으로 정확한 파일 Writer를 주장하지
않습니다.

사용자 관점에서 “AIA가 먼저 보호 세션을 열고, 그 안에서 작업한다”는 흐름으로
실행하려면 다음 명령을 사용한다.

```powershell
aia start "C:\workspace\my-project"
```

저장소에서 `uv run`을 사용하는 경우에는 `uv run aia start
"C:\workspace\my-project"`로 실행한다. `start`와 `protect`는 같은 보안 경로이며,
`start`는 대화형 세션 진입점이라는 의미를 명확히 표현한다.

이 명령은 다음 순서로 동작한다.

```text
Workspace 확인
→ 정책 고정
→ Workspace Lease 준비
→ Safe Checkpoint 생성
→ File / Hook / Process Sensor 준비
→ Codex 자식 프로세스 시작
→ Codex 화면에서 작업 입력
→ Evidence와 결과 Bundle 저장
```

화면에 `Protected Codex session is active.`가 표시되면 그때 Codex 세션 안에서
작업을 입력한다. 한 번의 요청만 자동으로 전달하려면 다음처럼 `--task`를 붙인다.

`Phase: READY`는 보호 준비가 끝나고 Codex를 시작하는 중이라는 뜻이다. 30초 이상
계속되면 별도 PowerShell에서 `uv run aia status <SESSION_ID>`로 확인할 수 있고,
필요하면 `Ctrl+C`로 사용자 중지를 요청한다.

```powershell
uv run aia protect "C:\workspace\my-project" --task "README.md를 읽고 한 문장으로 요약해줘"
```

웹 콘솔(`uv run aia console --open`)에서도 작업 시작 방식을 선택할 수 있다. 기본값인
`대화형 보호 세션`을 선택하면 AIA가 먼저 보호된 Codex 세션을 열고, 열린 Codex
화면에서 사용자가 작업을 입력한다. `한 번의 작업 실행`을 선택하면 작업 요청을
미리 입력해 보호 준비가 끝난 뒤 한 번 전달한다.

## 5. 결과 확인

`AIA Protected Run: ...` 뒤에 표시된 Session ID를 사용한다.

```powershell
uv run aia runs
uv run aia status <SESSION_ID>
uv run aia console --open
```

보호 실행은 `COMPLETED`만으로 충분하지 않다. `Bundle VALID`, Hook Event, 센서
상태를 함께 확인해야 한다. 차단은 AIA가 `deny` 응답을 만들었다는 사실과 Codex가
실제로 실행하지 않았다는 확인을 모두 갖춘 경우에만 `BLOCKED / SUCCEEDED`로
기록한다.

## 지원 범위

현재 첫 제품 범위는 Windows 11, Codex CLI, AIA Protected Run, 그리고 AIA가
연결한 PreToolUse matcher다. 지원 범위 밖의 도구나 Hook을 우회한 실행은 AIA가
`PROTECTED` 또는 `BLOCKED`라고 주장하지 않는다. 전체 제한사항은
[LIMITATIONS.md](LIMITATIONS.md)에서 확인한다.

실제 Codex 차단까지 확인하려면 먼저 다음을 실행한다.

```powershell
uv run aia setup
```

그 다음 Codex의 `/hooks`에서 AIA Hook을 검토·신뢰하고 아래를 실행한다.

```powershell
uv run aia hook verify
uv run aia demo --live
```

`--live`는 disposable Workspace에서 실제 Codex를 한 번 실행한다. Hook Trust가
확인되지 않으면 Codex 도구를 실행하지 않고 원인과 증거 경로만 남긴다.

## 6. 제거

AIA Hook만 제거하려면 릴리스 또는 저장소 폴더에서 다음을 실행한다.

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1
```

사용자 수준 AIA 도구까지 제거하려면 `-RemoveTool`을 추가한다. 두 경우 모두
Protected Run 결과와 AIA Control Root는 보존된다.
