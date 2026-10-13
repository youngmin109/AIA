# AIA 빠른 시작

AIA는 Codex를 대신하는 프로그램이 아니다. AIA가 먼저 보호 실행을 만들고,
그 안에서 Codex를 자식 프로세스로 시작한다. 사용자는 Codex 화면이 열린 뒤
평소처럼 작업을 입력한다.

## 데스크톱 앱으로 시작하기

설치 파일로 설치했다면 시작 메뉴나 바탕 화면의 `AIA`를 실행한다.

1. **홈 확인.** 오른쪽 위에 보호 연결 상태가 나온다.
2. **처음 한 번 연결.** 홈의 `보호 시작`을 누르면 새 보호 실행 창에 연결 점검
   세 가지(`Hook 연결`, `Codex 신뢰`, `요청 전달 확인`)가 보인다. Hook이 없으면
   설치하고, Codex에서 `/hooks`를 열어 AIA Hook을 직접 검토·신뢰한 뒤
   `연결 검증`을 누른다(최대 4분). AIA는 Hook을 대신 신뢰하지 않는다.
3. **보호 실행 준비.** 이미 있는 작업 폴더를 고르고(`폴더 바꾸기`), 정책(기본
   `표준 보호`)과 권한(기본 `승인 요청`)을 고른다. 지우면 안 되는 파일이 있으면
   꼭 지킬 파일로 추가한 뒤 `보호 시작`을 누른다. 시작할 때 작업 폴더의 기준점을
   저장한다.
4. **작업.** 작업창 아래 입력란에 요청을 쓴다. 인터넷 접속이나 작업 폴더 밖
   쓰기처럼 사람의 판단이 필요하면 승인 카드가 뜬다. 정책으로 금지한 일은 실행
   전에 막히며 카드에서 풀 수 없다. 오른쪽 보호 패널에서 검사, 차단, 프로세스,
   파일 변경을 본다.
5. **끝내기와 복구.** `작업 종료`를 누르면 결과 화면이 열린다. 되돌려야 하면
   `작업 폴더 되돌리기`로 기준점 상태로 복원하고 무결성 검증 결과를 확인한다.

다른 폴더에서 동시에 일하려면 작업창 위 `새 대화`를 누른다. 서로 다른 폴더라면
최대 네 개까지 열 수 있다. 화면별 설명은 [사용자 가이드](USER-GUIDE.md)에 있다.

## 명령줄로 시작하기

아래 1~7은 명령줄(`aia`)로 같은 보호 실행을 다루는 방법이다.

Windows에서 생성된 `aia.exe`가 애플리케이션 제어 정책으로 차단될 수 있으므로,
이 빠른 시작의 저장소 실행 명령은 Python 모듈 방식으로 작성한다. 저장소 루트에서
아래 형식으로 실행하면 현재 프로젝트와 연결된 AIA를 사용한다.

```powershell
uv run --isolated --project . python -m aia.cli <명령>
```

릴리스 wheel을 사용자 도구로 설치한 경우에는 `aia <명령>`을 사용할 수 있다.

처음 제품 흐름만 확인하려면 실제 프로젝트 경로 없이 다음부터 실행한다.

```powershell
uv run --isolated --project . python -m aia.cli demo
```

이 명령은 임시 Workspace에서 정책, Active Policy, Lease, Safe Checkpoint,
Evidence 봉인과 정리 흐름을 실행한다. 사용자의 Workspace나 Codex를 시작하지
않는다.

기본 정책은 `표준 보호`(PROTECTED_DEVELOPMENT, 정책 파일 `보호-우선-개발형`) v1.1이다. `.env` 같은 비밀정보
읽기와 대표적인 파괴 명령은 기본 차단하고, Windows의 `Remove-Item`, `del`,
`Stop-Process`, `taskkill /f`도 실행 전에 차단한다. 일반 소스 변경은 기록한다. 실행 시
`--profile BASIC_DEVELOPMENT` 또는 `--profile FREE_DEVELOPMENT`를 명시하면 다른
기본 정책을 선택할 수 있다.

## 1. AIA Core 확인

저장소 폴더에서 실행한다.

```powershell
uv run --isolated --project . python -m aia.cli self-test
```

`PASS`가 나오면 AIA의 정책·Workspace Lease·Checkpoint·Evidence 핵심 기능이
정상이다. 이 명령은 Codex를 실행하지 않는다.

현재 제품이 실제로 보호한다고 주장하는 범위를 먼저 확인하려면 다음 명령을
실행한다. 이 명령은 Workspace나 Codex를 실행하지 않는다.

```powershell
uv run --isolated --project . python -m aia.cli capabilities
```

출력의 `지원하지 않거나 주장하지 않는 범위`도 함께 확인한다. AIA는 지원되지
않는 도구를 보호했다고 표시하지 않는다.

설치나 실행에 문제가 생기면 다음 명령으로 민감한 실행 원문을 포함하지 않는
진단 파일을 만들 수 있다.

```powershell
uv run --isolated --project . python -m aia.cli support-bundle --output .\aia-support-bundle.json
```

## 2. Hook 설치

```powershell
uv run --isolated --project . python -m aia.cli setup
```

설치와 신뢰의 차이가 헷갈리면 다음 명령으로 AIA가 설치한 Hook의 검토 대상과
다음 단계를 먼저 확인한다.

```powershell
uv run --isolated --project . python -m aia.cli hook explain
```

그 다음 Codex에서 `/hooks`를 입력하고 AIA `PreToolUse` Hook의 명령과 Matcher를
검토한다. 내용을 확인한 뒤 직접 Trust한다. AIA가 대신 Trust하지 않는 이유는
사용자가 승인하지 않은 실행 경계를 AIA가 임의로 활성화하면 안 되기 때문이다.

## 3. 실제 Hook 연결 확인

```powershell
uv run --isolated --project . python -m aia.cli hook verify
```

데스크톱 앱에서는 새 보호 실행 창의 `연결 검증` 버튼으로 같은 검증을 실행할 수
있습니다. Codex `/hooks` Trust는 먼저 사용자가 직접
완료해야 하며, 버튼은 Trust를 변경하지 않습니다.

이 명령은 임시 Workspace에서 무해한 Probe를 한 번 실행한다. 성공하면
`VERIFIED`가 표시된다. `MODIFIED`, `UNTRUSTED`, `NOT_VISIBLE`이면 Probe를
실행하지 않고 Codex `/hooks`에서 검토·Trust해야 할 내용을 알려준다.

설치된 제품 경로에서 실제 Bash 사전 차단을 한 번 확인하려면 다음을 실행한다.

```powershell
uv run --isolated --project . python -m aia.cli proof
```

이 명령은 disposable Workspace에서 실제 Codex를 실행하고, Canary 미생성과
`Bundle VALID`까지 확인한다. Hook Trust가 확인되지 않으면 Codex 도구를 실행하지
않고 실패 원인과 artifact 경로만 남긴다. 실제 Codex 실행을 소비하므로 일반 회귀
테스트마다 반복하지 않는다.
기본 출력은 한국어 요약이다. 전체 기계 판독용 보고서가 필요하면
`uv run --isolated --project . python -m aia.cli proof --json`을 사용한다.

`.env` 비밀정보 읽기 차단을 확인하려면 다음을 실행한다.

```powershell
uv run --isolated --project . python -m aia.cli proof --scenario block-env
```

이 시나리오는 실제 PreToolUse 차단과 실행 확인뿐 아니라, `.env`의 secret marker가
Codex 출력·Evidence·Result에 나타나지 않는지도 확인한다.

Windows 기본 정책의 `Remove-Item` 실행 전 차단은 다음으로 확인한다.

```powershell
uv run --isolated --project . python -m aia.cli proof --scenario block-windows-delete
```

실제 Agent를 시작하기 전에 정책 결과를 미리 확인할 수도 있습니다. 정책 미리보기는
대상 명령을 실행하지 않으며, 선택한 정책의 최종 판정과 매칭 Rule만 출력합니다.

```powershell
uv run --isolated --project . python -m aia.cli policy evaluate --operation READ --path .env
uv run --isolated --project . python -m aia.cli policy evaluate --operation EXECUTE --command "python build.py"
```

데스크톱 앱에서는 `정책` 화면의 `이 명령은 어떻게 판정될까?`에서 행위 종류와 파일
경로 또는 명령을 넣고 `판정 보기`를 누르면 정책마다 차단·기록·허용 결과를
보여줍니다. 이 단계에서는 Codex·파일·명령을 실행하지 않습니다.

## 4. 보호 실행 시작

먼저 실제 프로젝트 대신 복사본이나 테스트 프로젝트를 사용한다.

```powershell
uv run --isolated --project . python -m aia.cli protect "C:\workspace\my-project"
```

저장소 모듈 방식은 AIA 저장소 루트에서 실행하므로 Workspace 경로를 명시한다.

```powershell
cd <AIA 저장소 폴더>
uv run --isolated --project . python -m aia.cli start "C:\workspace\my-project"
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

저장소에서 `uv run`을 사용하는 경우에는 `uv run --isolated --project . python -m aia.cli start
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
계속되면 별도 PowerShell에서 `uv run --isolated --project . python -m aia.cli status <SESSION_ID>`로 확인할 수 있고,
필요하면 `Ctrl+C`로 사용자 중지를 요청한다.

```powershell
uv run --isolated --project . python -m aia.cli protect "C:\workspace\my-project" --task "README.md를 읽고 한 문장으로 요약해줘"
```

데스크톱 앱과 웹 콘솔(`uv run --isolated --project . python -m aia.cli console --open`)에서는
보호 준비가 끝나면 앱 안 작업창에서 Codex와 바로 대화한다.

## 5. 결과 확인

`AIA Protected Run: ...` 뒤에 표시된 Session ID를 사용한다.

```powershell
uv run --isolated --project . python -m aia.cli runs
uv run --isolated --project . python -m aia.cli status <SESSION_ID>
uv run --isolated --project . python -m aia.cli console --open
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
uv run --isolated --project . python -m aia.cli setup
```

그 다음 Codex의 `/hooks`에서 AIA Hook을 검토·신뢰하고 아래를 실행한다.

```powershell
uv run --isolated --project . python -m aia.cli hook verify
uv run --isolated --project . python -m aia.cli demo --live
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

## 7. 브라우저에서 같은 화면 쓰기

```powershell
uv run --isolated --project . python -m aia.cli console --open
```

데스크톱 앱과 같은 화면이 브라우저에서 열린다. 사용 순서는 위의
[데스크톱 앱으로 시작하기](#데스크톱-앱으로-시작하기)와 같다. 결과 화면에서는
센서 상태, 증거, 이벤트 흐름, 복구·무결성, 결과 묶음을 확인한다. `BLOCKED`는
deny 응답 생성만으로 표시되지 않으며 실제 도구 미실행이 확인된 경우에만
`BLOCKED / SUCCEEDED`가 된다.

정책을 직접 만들려면 `정책` 화면에서 `사용자 지정`을 고르고 규칙을 고친 뒤
`규칙 검증하고 저장`을 누른다. 검증을 통과한 정책만 저장되며, 다음 보호 실행의
정책에서 `사용자 지정`으로 고른다.
