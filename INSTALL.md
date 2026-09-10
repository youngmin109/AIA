# AIA 설치 및 첫 실행

AIA 0.1은 Windows 11과 Python 3.13 환경을 지원한다. Codex CLI와 `uv`를 먼저
설치해야 한다.

## 소스 저장소에서 설치

PowerShell에서 저장소 폴더로 이동한 뒤 다음을 실행한다.

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -SetupHook
```

이 명령은 `uv.lock`에 고정된 환경을 만들고 AIA Hook 설정을 추가한다. 기존 Codex
Hook을 덮어쓰지 않는다. Hook을 추가하지 않고 Python 환경만 준비하려면
`-SetupHook`을 생략한다.

실행 중인 `aia-web` 또는 AIA Python 프로세스가 있으면 Windows가 `.venv` 파일을
잠글 수 있다. 이 경우 해당 프로세스를 종료한 뒤 설치 명령을 다시 실행한다.

## Codex Hook 신뢰

설치 명령이 끝나면 Codex에서 `/hooks`를 열어 AIA Hook의 명령과 Matcher를 직접
검토하고 신뢰한다. 이 단계는 사용자가 검토해야 하며 AIA가 자동으로 대신하지
않는다.

그 다음 준비 상태를 확인한다.

```powershell
uv run aia doctor
```

`READY`가 표시되면 보호 실행을 시작할 수 있다.

```powershell
uv run aia protect C:\workspace\my-project
```

실행 중 Codex 화면에서 작업을 입력하고 Codex를 종료하면 AIA가 결과 Bundle을
확정한다. 한 번의 요청만 전달하려면 `--task`를 사용한다.

```powershell
uv run aia protect C:\workspace\my-project --task "테스트를 실행하고 결과를 설명해줘"
```

## 정책 선택

기본 정책을 확인하고 편집 가능한 JSON을 만든다.

```powershell
uv run aia policy profiles
uv run aia policy init C:\workspace\policies\my-policy.json --profile CONSERVATIVE_SECURITY
uv run aia policy validate C:\workspace\policies\my-policy.json
```

## 실행 기록 확인

```powershell
uv run aia runs
uv run aia status <SESSION_ID>
uv run aia-web
```

## Hook 제거

AIA가 추가한 Hook만 제거하려면 다음을 실행한다. 다른 사용자의 Hook은 보존한다.

```powershell
uv run aia hook uninstall
```

이 명령은 보호 실행을 종료하거나 기존 Result Bundle을 삭제하지 않는다.
