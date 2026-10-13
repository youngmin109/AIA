# AIA Windows Desktop

AIA Desktop is the Windows 11 shell for the existing local Workbench. It starts
the FastAPI console on `127.0.0.1`, opens it in WebView2, and closes the local
server when the window closes. Policy evaluation, Hook Sensor, File Sensor,
Process Sensor, Evidence, and enforcement remain in AIA Core.

The Workbench conversation runs through Codex `app-server`: the browser connects
to `/api/runs/{session_id}/codex` over WebSocket, and the local FastAPI service
bridges conversation messages and events to the app-server process. Run status
and action history continue to use HTTP polling. The conversation UI does not
make policy or enforcement decisions.

## 사용자 실행

설치 후 시작 메뉴 또는 바탕 화면의 `AIA`를 실행합니다.

첫 화면에서 다음 순서로 진행합니다.

1. 홈의 `보호 시작`을 누르고 이미 존재하는 작업 폴더를 선택합니다.
2. 연결 점검(`Hook 연결`, `Codex 신뢰`, `요청 전달 확인`) 결과를 확인합니다.
3. 정책(기본 `표준 보호`)과 권한(기본 `승인 요청`)을 확인합니다.
4. `.env`, 중요 소스, DB 파일처럼 꼭 지킬 파일을 추가합니다(선택).
5. `보호 시작`을 누릅니다.

Codex Hook은 AIA가 대신 신뢰하지 않습니다. 화면의 안내에 따라 Codex에서
`/hooks`를 열고 AIA Hook을 직접 검토·신뢰한 뒤 `hook verify`가 성공해야
보호 실행을 시작할 수 있습니다.

실행이 끝나면 결과 화면에서 전체 Workspace 복구 가능 여부를 확인합니다.
복구를 실행하면 실행 시작 전 Checkpoint로 되돌아가며, 최종 상태는
`Recovery: RESTORED`와 `Integrity: VERIFIED`를 각각 확인해야 합니다.

## 개발 빌드

개발 환경에서 다음 명령으로 PyInstaller onedir 산출물을 만듭니다.

```powershell
uv sync --group build
.\scripts\build-windows.ps1 -Clean
```

산출물은 다음 위치에 생성됩니다.

```text
dist\windows\AIA\AIA.exe
dist\windows\aia-cli\aia-cli.exe
```

패키지된 `AIA.exe`는 로컬 FastAPI Workbench를 허용된 `AIA.exe --server`
자식 프로세스에서 시작합니다. 서버를 GUI 프로세스와 분리해 보호 실행 준비와
Checkpoint 작업이 화면을 멈추게 하지 않도록 하면서, Windows 애플리케이션
제어 정책에 막힐 수 있는 unsigned `aia-cli.exe`를 Workbench 시작에 사용하지
않습니다. `aia-cli.exe`는 명령줄 진단과 Hook 검증을 위한 별도 도구로
포함됩니다.

패키지 해시·Core self-test와 실제 `AIA.exe` 기동을 한 번에 확인하려면 다음을
실행합니다. 이 검사는 보호 실행이나 Workspace 변경을 시작하지 않고, 잠시 뒤
AIA와 그 테스트 하위 프로세스를 정리합니다.

```powershell
.\scripts\windows-smoke.ps1
```

서명된 릴리스의 실행 파일과 native runtime 서명까지 확인하려면 다음처럼
실행합니다.

```powershell
.\scripts\windows-smoke.ps1 `
  -RequireSignature `
  -RequireNativeSignature
```

설치 프로그램까지 확인하려면 다음 smoke를 추가로 실행합니다. 임시 사용자
폴더에 설치하고 `aia-cli self-test`를 실행한 뒤 자동으로 제거합니다.

```powershell
.\scripts\windows-installer-smoke.ps1
```

서명된 릴리스 산출물을 검사할 때는 다음처럼 서명과 native runtime 서명을 함께
필수로 지정합니다.

```powershell
.\scripts\windows-installer-smoke.ps1 `
  -RequireSignature `
  -RequireNativeSignature
```

Enterprise Code Integrity가 적용된 PC에서 unsigned 개발 패키지를 검사하면
설치 프로그램이 임시 setup 프로세스를 시작하는 단계에서 차단될 수 있습니다.
그 경우에는 제품 버그가 아니라 서명 게이트가 아직 충족되지 않은 것이며,
서명된 패키지로 다시 실행해야 합니다.

Inno Setup이 설치된 환경에서는 다음으로 사용자 권한 설치 프로그램을
생성할 수 있습니다. 개발용 unsigned 패키지는 다음으로 만듭니다.

```powershell
.\scripts\package-windows.ps1 -Clean
```

Inno Setup Compiler(`ISCC.exe`)가 없으면 실행 파일 빌드는 가능하지만 설치
프로그램 생성은 중단됩니다. WebView2 Runtime은 설치 프로그램에 포함하지
않으며, 없을 때 AIA가 공식 설치 안내를 표시합니다.

## 범위와 제한

공개 배포용 코드 서명과 SHA-256 manifest 생성은
[Windows 코드 서명 가이드](WINDOWS-SIGNING.md)를 따른다. 인증서가 없는 개발
환경에서는 unsigned 빌드를 사용할 수 있지만, 릴리스 빌드에는
<code>-RequireSignature</code>를 사용한다.

- Windows 11 x64와 기존 Codex CLI를 대상으로 합니다.
- MCP, Claude, 외부 Agent, 네트워크 보안은 포함하지 않습니다.
- AIA는 Workspace를 자동 생성하지 않습니다.
- 복구는 첫 제품 버전에서 전체 Workspace 단위로만 수행합니다.
- 서명되지 않은 실행 파일은 Windows SmartScreen 경고가 발생할 수 있습니다.
