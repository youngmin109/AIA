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

저장소 폴더 안에서 `uv run aia`를 붙이지 않고 어느 Workspace에서든 `aia`를
사용하려면 다음처럼 사용자 도구로도 설치할 수 있다.

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -SetupHook -InstallTool
aia --version
```

`-InstallTool`은 현재 저장소 내용을 `uv` 사용자 도구로 설치한다. 저장소에서
개발을 계속하는 경우에는 기본 설치 명령과 `uv run aia` 경로를 사용한다.
새로 설치한 `aia`가 현재 PowerShell의 `PATH`에 아직 반영되지 않은 경우에도 설치
스크립트는 uv가 설치한 실행 파일을 직접 찾아 Hook 설정을 계속한다. 설치 후
`aia`를 직접 입력할 때는 새 PowerShell 창을 열거나 사용자 PATH를 갱신한다.

## Codex Hook 신뢰

설치 명령이 끝나면 Codex에서 `/hooks`를 열어 AIA Hook의 명령과 Matcher를 직접
검토하고 신뢰한다. 이 단계는 사용자가 검토해야 하며 AIA가 자동으로 대신하지
않는다.

그 다음 실제 Hook 연결을 확인한다. 이 명령은 임시 Workspace에서 무해한 Probe를
실행하고, Probe Workspace는 삭제한다.

```powershell
uv run aia hook verify
```

`VERIFIED`가 표시될 때 보호 실행을 시작한다. `NOT_VERIFIED`이면 Codex에서
`/hooks`를 열어 AIA Hook을 검토·신뢰한 뒤 다시 실행한다.

검증 명령은 먼저 Codex PreToolUse Trust를 확인한다. `MODIFIED`, `UNTRUSTED` 또는
`NOT_VISIBLE`이면 임시 Probe를 실행하지 않고 즉시 원인과 다음 단계를 출력한다.
Codex `/hooks`에서 AIA PreToolUse Hook을 직접 검토·신뢰한 뒤 다시 실행한다.

Codex를 실행하기 전에 AIA Core 자체를 확인하려면 다음을 실행한다. 임시 Workspace와
Control Root를 사용하고 모두 삭제하므로 사용자 Workspace와 Codex에는 영향을 주지
않는다.

```powershell
uv run aia self-test
```

이 명령의 `PASS`는 정책·Lease·Checkpoint·Raw Evidence 핵심 계약이 정상이라는
뜻이다. 실제 Codex Hook 연결은 별도로 `/hooks` 신뢰와 `uv run aia hook verify`가
필요하다.

`VERIFIED`가 표시된 뒤 다음 명령으로 전체 준비 상태가 `READY`인지 확인할 수
있다.

```powershell
uv run aia doctor
```

```powershell
uv run aia protect C:\workspace\my-project
```

보호 실행과 정책 미리보기의 기본값은 `PROTECTED_DEVELOPMENT`입니다. `.env` 같은
비밀정보 읽기와 대표적인 파괴 명령은 기본 차단하고 일반 소스 변경은 기록합니다.
더 넓은 개발 허용 범위가 필요하면 `--profile BASIC_DEVELOPMENT` 또는
`--profile FREE_DEVELOPMENT`를 명시하십시오.

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
uv run aia console --open
```

## Hook 제거

AIA가 추가한 Hook만 제거하려면 다음을 실행한다. 다른 사용자의 Hook은 보존한다.

```powershell
uv run aia hook uninstall
```

이 명령은 보호 실행을 종료하거나 기존 Result Bundle을 삭제하지 않는다.
