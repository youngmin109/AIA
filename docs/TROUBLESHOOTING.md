# AIA 문제 해결

저장소에서 실행하는 명령은 다음 형식을 권장한다. 생성된 `aia.exe`가 Windows
애플리케이션 제어 정책으로 차단되는 환경에서도 사용할 수 있다.

```powershell
uv run --isolated --project . python -m aia.cli <명령>
```

## `workspace must be an existing directory`

AIA는 입력한 Workspace를 자동으로 만들지 않는다. 사용자가 이미 존재하는
프로젝트 폴더를 선택해야 한다.

```powershell
New-Item -ItemType Directory -Force "C:\workspace\my-project"
uv run --isolated --project . python -m aia.cli protect "C:\workspace\my-project"
```

실제 프로젝트를 보호하기 전에는 복사본이나 disposable Workspace로 확인한다.

## `CODEX_HOOK_TRUST_REQUIRED`

Hook 파일은 설치됐지만 Codex가 AIA `PreToolUse` Hook을 아직 Trust하지 않은
상태다. Codex 화면에서:

```text
/hooks
→ AIA PreToolUse Hook 선택
→ 명령과 Matcher 검토
→ Trust
```

그 후 다시 실행한다.

```powershell
uv run --isolated --project . python -m aia.cli hook verify
```

AIA는 이 Trust를 자동으로 처리하지 않는다. `aia hook verify`가 이 상태에서
멈추는 대신 Probe를 시작하지 않고 즉시 안내하는 것이 정상 동작이다.

## `CODEX_PRETOOL_HOOK_NOT_VISIBLE`

Codex의 현재 Hook 목록에서 AIA PreToolUse Hook을 찾지 못한 상태다. 다음을
확인한다.

```powershell
uv run --isolated --project . python -m aia.cli hook install
```

그 다음 Codex `/hooks`를 다시 열어 AIA Hook이 보이는지 확인하고 Trust한다.

## `aia hook verify`가 `NOT_VERIFIED`인 경우

`NOT_VERIFIED`는 AIA가 보호를 증명하지 못했다는 뜻이다. 특히 다음 결과는
성공으로 해석하지 않는다.

- Hook Event가 0건
- Probe 파일은 생성됐지만 Hook이 관찰되지 않음
- Codex 실행 정책이 `read-only` 또는 `approval=never`로 강등됨
- Result Bundle이 `VALID`가 아님

```powershell
uv run --isolated --project . python -m aia.cli doctor
uv run --isolated --project . python -m aia.cli hook status
```

처음 설치했고 `/hooks`에서 무엇을 확인해야 하는지 모르겠으면 다음 명령을
실행한다.

```powershell
uv run --isolated --project . python -m aia.cli hook explain
```

두 명령의 `codex_hook_trust`, `hook_verification`, `activation_status`를 함께
확인한다.

## 실행 화면이 `READY`에서 오래 멈추는 경우

정상 준비에는 Workspace 검사, 정책 고정, Lease, Checkpoint, 센서 검사가
포함된다. 잠시 기다린 뒤 다른 PowerShell에서 상태를 확인한다.

```powershell
uv run --isolated --project . python -m aia.cli runs
uv run --isolated --project . python -m aia.cli status <SESSION_ID>
```

오류가 표시되면 실행 중인 명령을 `Ctrl+C`로 중지하고, 결과가 `FAILED` 또는
`ABORTED`로 정리됐는지 확인한다. 동일 Workspace에 남은 Lease가 있으면 이전
실행이 아직 끝나지 않았거나 종료 정리가 실패한 것일 수 있다.

## `aia` 명령을 찾지 못하는 경우

저장소에서 실행할 때는 다음처럼 `uv run`을 붙인다.

```powershell
cd "C:\workspace\01_projects\aia-mvp"
uv run --isolated --project . python -m aia.cli self-test
```

릴리스 wheel을 사용자 명령으로 설치한 경우에는 새 PowerShell 창을 열거나
사용자 PATH를 갱신한 뒤 `aia --version`을 실행한다.

## `os error 4551` 또는 애플리케이션 제어 정책 차단

`uv sync`는 성공하지만 `uv run aia` 또는 `uv run python`에서 다음 오류가
발생할 수 있다.

```text
애플리케이션 제어 정책에서 이 파일을 차단했습니다. (os error 4551)
```

이 경우 Windows 정책이 가상환경의 실행 파일을 AIA가 시작되기 전에 차단한
것이다. 저장소에서 실행하는 동안에는 콘솔 실행 파일 대신 uv의 격리 Python
호출을 사용할 수 있다.

```powershell
uv run --isolated python -m aia.cli setup
```

그 다음 Codex에서 `/hooks`를 열어 AIA `PreToolUse` Hook을 검토·신뢰하고,
같은 방식으로 연결을 검증한다.

```powershell
uv run --isolated python -m aia.cli hook verify
uv run --isolated python -m aia.cli doctor
uv run --isolated python -m aia.cli console --open
```

AIA는 격리 환경의 임시 `python.exe`를 Hook 설정에 저장하지 않고, 프로젝트와
`uv.exe`를 가리키는 안정적인 실행 명령을 저장한다. 따라서 각 명령을 별도의
PowerShell에서 실행해도 Hook이 `미설치`로 오인되지 않는다. 이미 임시 경로가
저장된 경우에는 위 `setup`을 다시 실행하면 AIA가 자신의 이전 Hook 항목만
교체한다.

이 방식도 동일한 오류로 차단되면 Windows 애플리케이션 제어 정책이 Python
자식 프로세스 자체를 차단하는 상태다. 정책을 전체 해제하지 말고, 관리자에게
현재 프로젝트의 `.venv\\Scripts\\python.exe`와 `.venv\\Scripts\\aia.exe`를
허용할 수 있는지 확인한다.

PyInstaller로 만든 `dist\\windows\\AIA\\AIA.exe` 또는 설치된 `AIA.exe`가 같은
오류로 차단되는 경우에는 개발용 unsigned EXE가 Windows Code Integrity 정책을
통과하지 못한 것이다. 다음으로 서명 상태를 확인한다.

현재 제품 빌드에서는 `AIA.exe`가 Workbench 서버를 내부에서 시작하므로,
`AIA.exe`가 실행되고 이 창이 나타난 뒤의 `aia-cli.exe` 차단은 화면 시작
실패 원인이 아니다. `aia-cli.exe`는 Hook 검증과 명령줄 진단처럼 별도 CLI가
필요한 기능에서만 사용된다.

```powershell
Get-AuthenticodeSignature .\\dist\\windows\\AIA\\AIA.exe
Get-AuthenticodeSignature .\\dist\\windows\\aia-cli\\aia-cli.exe
```

`Status`가 `NotSigned`이면 제품 코드의 Workspace나 Codex 문제가 아니다. 공개
배포본은 Authenticode로 `AIA.exe`, `aia-cli.exe`, 설치 프로그램을 서명하고,
엄격한 정책에서는 bundled DLL/PYD까지 서명해야 한다. 학교·회사 PC에서는
관리자가 서명 게시자 또는 릴리스 파일을 허용 목록에 등록해야 할 수 있다.
개발용 unsigned 패키지는 다음 검증에서 서명 0건으로 표시되는 것이 정상이며,
공개 릴리스 검증은 의도적으로 실패한다.

```powershell
.\\scripts\\verify-windows-package.ps1
.\\scripts\\verify-windows-package.ps1 -RequireSignature -RequireNativeSignature
```

## 문제를 보고할 진단 파일

문제를 재현한 뒤 다음 명령을 실행한다.

```powershell
uv run --isolated --project . python -m aia.cli support-bundle --output .\aia-support-bundle.json
```

진단 파일에는 AIA·Python·Windows·Codex 버전, Hook Trust, Control Root 쓰기 가능
여부와 최근 보호 실행의 상태 요약만 들어간다. 전체 경로, Workspace 내용, raw
evidence, tool input, 명령 출력은 포함하지 않는다. 파일을 공유하기 전에 파일명과
추가로 넣은 메모에 비밀정보가 없는지 확인한다.

## `self-test`는 통과했지만 보호 실행이 시작되지 않는 경우

`self-test`는 AIA Core만 확인한다. 실제 Codex 보호를 증명하지 않으므로 다음
두 단계를 별도로 통과해야 한다.

```powershell
uv run --isolated --project . python -m aia.cli hook verify
uv run --isolated --project . python -m aia.cli doctor
```

`VERIFIED`와 `READY`가 확인된 뒤에만 `aia protect`를 실행한다.

## `ORPHANED_DEGRADED`가 표시되는 경우

AIA가 갑자기 종료되어 보호 실행의 상태 파일만 남은 경우다. 이 상태는 이전
실행이 계속 보호되고 있다는 뜻이 아니다. AIA는 조정 프로세스의 PID와 생성 시각을
확인하고, 기록된 Agent Root의 PID와 생성 시각도 함께 확인한다.

먼저 상태를 확인한다.

```powershell
uv run --isolated --project . python -m aia.cli status <SESSION_ID>
```

기록된 Agent Root가 아직 살아 있으면 기존 Codex를 먼저 종료한다. Agent Root가
사라진 것이 확인된 경우에만 다음 명령을 실행한다.

```powershell
uv run --isolated --project . python -m aia.cli reconcile <SESSION_ID>
```

이 명령은 기록을 삭제하거나 보호 성공으로 바꾸지 않는다. Agent Root가 살아
있거나 신원을 확인할 수 없으면 정리를 거부한다. 이후 새 Protected Run을 시작할
때 AIA가 Workspace Lease를 다시 확인한다.
