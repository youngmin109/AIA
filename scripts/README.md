# scripts 길잡이

저장소 루트에서 실행합니다. Python 스크립트는 `uv run python scripts/<이름>.py`로,
PowerShell 스크립트는 `powershell -ExecutionPolicy Bypass -File scripts\<이름>.ps1`로
실행합니다. 이름에 `epic0xx`가 붙은 스크립트는 그 작업 묶음에서 만든 확인용입니다.

## 빌드와 배포

| 스크립트 | 하는 일 |
|---|---|
| `build-windows.ps1` | 화면을 빌드하고 `dist\windows`에 `AIA.exe`와 `aia-cli.exe`를 만듭니다. |
| `package-windows.ps1` | 위 빌드로 Inno Setup 설치 파일(`AIA-<버전>-Setup.exe`)을 만듭니다. |
| `verify-windows-package.ps1`, `windows-smoke.ps1`, `windows-installer-smoke.ps1` | 빌드·설치 파일을 해시와 실제 실행으로 확인합니다. |
| `sign-windows.ps1`, `inno-sign.ps1` | 코드 서명([안내](../docs/WINDOWS-SIGNING.md)) |
| `package-release.ps1`, `verify-release.ps1`, `release-gate.ps1`, `rollback-release.ps1` | 릴리스 묶음 만들기, 확인, 되돌리기 |
| `install-wheel.ps1` | 빌드한 wheel을 사용자 도구로 설치합니다. |
| `export-public-tree.ps1`, `verify-public-tree.ps1`, `package-public-source.ps1`, `create-public-repository.ps1` | 공개용 소스 사본을 만들고 확인합니다. |

## 실제 Codex로 확인 (Codex를 실제로 실행함)

일회용 작업 폴더를 씁니다. 일반 테스트에는 포함하지 않습니다.

| 스크립트 | 하는 일 |
|---|---|
| `actual_codex_pretool_smoke.py` | 실행 전 차단(PreToolUse)이 실제로 막는지 |
| `actual_codex_post_action_smoke.py`, `actual_codex_hook_lifecycle_smoke.py`, `actual_codex_abort_smoke.py` | 사후 관찰, 훅 수명 주기, 사용자 중지 |
| `codex_app_server_smoke.py`, `codex_workbench_e2e_smoke.py` | 앱 대화(app-server) 연결과 작업창 전체 흐름 |
| `product_e2e_smoke.py` | 명령줄 제품 경로 전체(`--scenario`로 고름) |
| `epic015_…`, `epic016_…`, `epic017_…`, `epic018_…`, `epic019_…` | 프로세스 관리, 복구, 결과 묶음, 실행, 콘솔 확인 |

## 평가와 성능

| 스크립트 | 하는 일 |
|---|---|
| `product_evaluation/` | AIA 끔·켬 전후 평가를 돌리고 보고서를 만듭니다([설명](product_evaluation/README.md)). |
| `benchmarks/` | 기준점·증거·기록 조회 성능 측정([설명](benchmarks/README.md)) |
| `epic018_secret_scan.py` | 결과물에 비밀값 표지가 남지 않았는지 검사합니다. |

## 개발 도우미

| 스크립트 | 하는 일 |
|---|---|
| `dev/ui_preview_server.py` | 가짜 Codex와 예시 기록으로 화면을 미리 봅니다(`--port 8899`). |
| `dev/ui_shot.py` | 화면 사진을 찍습니다. |
| `dev/make_app_icon.py` | 로고 원본으로 앱 아이콘(`aia.ico`)과 파비콘을 만듭니다. Pillow가 필요합니다(`uv run --no-project --with pillow python scripts/dev/make_app_icon.py`). |
| `docs/build_product_docs.py`, `docs/build_sensor_principles_pdf.py` | 사용자 가이드 docx, 센서 원리 PDF를 만듭니다. |
