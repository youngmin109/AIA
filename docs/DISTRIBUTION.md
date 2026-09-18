# AIA 배포 패키지

현재 저장소는 Windows 11, Python 3.13, `uv`, Codex CLI를 대상으로 하는 오픈소스
소스 배포와 Python wheel을 제공하며, Windows 데스크톱 설치 프로그램을 만드는
패키징 경로도 제공한다. 공개 Windows 릴리스는 코드 서명 게이트를 통과한
설치 프로그램만 배포한다. AIA가 모든 Agent와 운영체제를 보호하는
범용 제품이라는 의미는 아니다. 지원 범위와 제한사항은
[PRODUCT-SUPPORT.md](PRODUCT-SUPPORT.md)와 [LIMITATIONS.md](LIMITATIONS.md)에
고정되어 있다.

현재 작업 폴더에는 내부 재현·평가 기록이 함께 남을 수 있으므로 저장소 전체를
그대로 공개하지 않는다. 공개용 소스 트리는 선별 내보내기와 안전성 검사를 거쳐
만든다. 기존 평가 기록은 삭제하지 않고 내부 보관한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\export-public-tree.ps1 `
  -OutputPath .\dist\public-source -Force
```

이 명령은 `src`, `tests`, `scripts`, `policies`, `packaging`, `.github`, 공개 문서와
설정 파일만 복사한다. `.env`, API 키·개인 경로, 캐시, 로그, SQLite/DB, JSONL
감사·증거 기록, `evaluation` 실행 결과와 생성 문서는 제외하고,
`verify-public-tree.ps1`로 파일명·경로·내용을 검사한다. 검사에 실패한 트리는
GitHub에 올리지 않는다.

팀에 전달할 공개 소스 ZIP과 SHA-256 manifest가 필요하면 다음을 사용한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\package-public-source.ps1 `
  -OutputRoot .\dist\public-source-release -Force
```

이 명령은 먼저 같은 공개 트리 검사를 통과한 뒤
`aia-<version>-source.zip`과 `SHA256SUMS.txt`를 만든다. `source` 폴더에는 검토용
공개 트리도 함께 남기며, 내부 평가 실행 결과는 포함하지 않는다.

기존 내부 평가 이력을 가진 작업 폴더에서 GitHub 기본 브랜치에 올릴 공개 기준선을
만들 때는 별도 Git 저장소를 생성한다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\create-public-repository.ps1 `
  -OutputPath .\dist\public-repository -Force
```

생성된 폴더는 평가 기록이 없는 새 `main` 초기 커밋을 가진 독립 저장소다. 원본
작업 폴더의 Git 이력과 평가 산출물은 변경하지 않는다. 생성 후 원격 주소를 확인하고
해당 폴더에서만 GitHub 원격을 추가해 검토·업로드한다.

## 릴리스 패키지 생성

저장소 루트의 PowerShell에서 다음을 실행한다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package-release.ps1
```

생성 위치:

```text
dist/release/aia-<version>/
├─ packages/
│  ├─ aia_mvp-<version>-py3-none-any.whl
│  └─ aia_mvp-<version>.tar.gz
├─ install.ps1
├─ INSTALL-FROM-WHEEL.md
├─ SHA256SUMS.txt
├─ release-manifest.json
└─ docs/
```

같은 버전의 기존 결과를 다시 만들 때만 `-Force`를 사용한다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package-release.ps1 -Force
```

`SHA256SUMS.txt`는 패키지 파일의 SHA-256을 기록한다. 공개하기 전에 패키지와
문서에 사용자 Workspace 경로, 인증 정보, Secret이 포함되지 않았는지 확인한다.
릴리스 폴더의 `install.ps1`은 wheel을 설치하기 전에 이 manifest와 wheel의
SHA-256을 비교한다. manifest가 없는 외부 wheel을 `-PackagePath`로 지정하면
설치기는 해시를 자동으로 주장하지 않고 경고를 표시한다.

공개하기 전에는 다음 Release Gate로 제품 전체를 검증한다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\release-gate.ps1
```

Release Gate는 잠금 환경 동기화, 전체 pytest, 안전한 `aia demo`, 패키지 생성과
release bundle 자체 검증을 순서대로 실행한다. bundle만 다시 검증할 때는
`-SkipTests -SkipPackage -BundlePath <bundle-path>`를 사용할 수 있다.

개별 검증 스크립트인 `verify-release.ps1`은 wheel·source archive의
개수, release manifest의 패키지 목록, `SHA256SUMS.txt`와 실제 파일의 일치를
확인하고, 임시 Python 3.13 가상환경에 wheel을 실제 설치해 console entry point와
Core self-test까지 실행한다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify-release.ps1 `
  -BundlePath .\dist\release\aia-0.1.29
```

검증 결과에 `SHA-256: PASS`, `Clean wheel install: PASS`, `Local console assets: PASS`가
모두 없는 bundle은 배포하지 않는다. 검증이 끝나면 임시 가상환경은 자동으로
삭제된다.

## Windows 데스크톱 패키지

개발용 Windows 패키지는 다음으로 만든다. 이 결과는 서명되지 않을 수 있으므로
Enterprise Code Integrity가 적용된 PC의 공개 배포물로 사용하지 않는다.

```powershell
uv sync --locked
.\scripts\package-windows.ps1 -Clean
```

서명된 공개 릴리스는 Windows SDK의 `signtool.exe`와 릴리스 인증서가 필요하다.
PFX 비밀번호는 환경 변수로만 전달한다.

```powershell
$env:AIA_SIGNING_CERT_PASSWORD = Read-Host "PFX password"
.\scripts\package-windows.ps1 `
  -Clean `
  -CertificatePath C:\secure\aia-release.pfx `
  -SignRuntimeBinaries `
  -RequireSignature
```

생성 결과는 `dist\windows\installer\AIA-<version>-Setup.exe`이며, 설치 후
`AIA.exe`, `aia-cli.exe`, 문서, 언인스톨러를 포함한다. 릴리스 전에는 다음을
순서대로 실행한다.

```powershell
.\scripts\verify-windows-package.ps1 -RequireSignature -RequireNativeSignature
.\scripts\windows-smoke.ps1 -RequireSignature -RequireNativeSignature
.\scripts\windows-installer-smoke.ps1 -RequireSignature -RequireNativeSignature
```

자세한 인증서와 GitHub Actions Secrets 설정은
[Windows 코드 서명 가이드](WINDOWS-SIGNING.md)를 따른다.

## Wheel 설치

릴리스 디렉터리의 `INSTALL-FROM-WHEEL.md`에 기록된 순서를 따른다. 개인이 실제로
사용하는 설치 경로는 `uv tool install`이다. 이렇게 설치하면 저장소 폴더 안에서만
`uv run`을 붙여 실행하지 않아도 어느 Workspace에서든 `aia` 명령을 사용할 수 있다.
릴리스 폴더의 `install.ps1 -SetupHook`은 새 `aia`가 현재 PowerShell의 `PATH`에
아직 반영되지 않은 경우에도 uv의 실행 파일 경로를 직접 찾아 첫 Hook 설정을
완료한다. 설치 후 터미널에서 `aia`를 직접 입력할 때는 새 PowerShell 창을 연다.

```powershell
uv tool install --force .\packages\aia_mvp-0.1.29-py3-none-any.whl
aia --version
aia setup
```

설치된 AIA Core 계약을 Codex 실행 없이 확인하려면 다음을 실행한다.

```powershell
aia self-test
```

처음 설치한 사용자는 실제 프로젝트를 건드리지 않고 다음으로 제품 흐름을
확인할 수 있다.

```powershell
aia demo
```

실제 Codex 증명은 Hook을 검토·신뢰하고 `aia hook verify`를 완료한 뒤 다음을
실행한다.

```powershell
aia demo --live
```

설치 뒤에는 반드시 Codex의 `/hooks`에서 AIA Hook을 검토·신뢰하고 `aia hook verify`를
실행한다. Hook이 실제로 검증되지 않은 실행은 보호 성공으로 표시하지 않는다.

실제 Codex의 Bash 사전 차단을 disposable Workspace에서 확인하려면 다음을 실행한다.

```powershell
aia proof
```

이 명령은 현재 Hook Trust와 Session-bound Hook을 먼저 검증하며, 검증에 실패하면
Codex 도구를 실행하지 않는다.
기본 출력은 한국어 요약이며, 전체 JSON 보고서가 필요하면 `aia proof --json`을
사용한다.

`.env` 읽기 차단과 secret marker 비유출을 별도로 확인하려면 다음을 사용한다.

```powershell
aia proof --scenario block-env
```

업데이트는 다음처럼 수행한다.

```powershell
uv tool install --force .\packages\aia_mvp-0.1.29-py3-none-any.whl
```

재설치 과정에서 AIA가 설치한 이전 Python 경로의 Hook이 남아 있으면 새 AIA
Hook으로 교체한다. AIA가 아닌 사용자의 다른 Hook과 matcher 그룹은 보존한다.
Hook 명령이 바뀐 경우 Codex의 `/hooks`에서 변경 내용을 다시 검토·신뢰한 뒤
`aia hook verify`를 실행한다.

이전 릴리스 번들로 되돌릴 때는 현재 설치 버전보다 낮은 릴리스 폴더를 지정한다.
이 명령은 먼저 대상 번들의 manifest·SHA-256·깨끗한 wheel 설치를 검증하고, 실제
설치 뒤에는 Hook을 다시 검토해야 한다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\rollback-release.ps1 `
  -BundlePath C:\releases\aia-0.1.5 -SetupHook
```

대상 버전이 현재 버전보다 낮지 않거나 검증에 실패하면 설치하지 않는다. AIA가
자동으로 업데이트하거나 임의의 이전 버전을 선택하지 않는다.

제거는 다음처럼 수행한다.

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1
```

Hook와 사용자 수준 AIA 도구를 모두 제거하려면 `-RemoveTool`을 추가한다.

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 -RemoveTool
```

두 명령 모두 Protected Run 결과와 AIA Control Root는 삭제하지 않는다.

## 아직 제공하지 않는 배포 기능

- 자동 업데이트와 자동 롤백. 이전 릴리스 번들을 사용자가 지정하는 검증된 수동
  롤백만 제공한다.
- 중앙 관리 서버나 원격 콘솔
- 모든 Agent와 모든 Codex 도구에 대한 보편적 보호

이 항목들은 현재 릴리스의 제공 기능으로 가장하지 않는다.
