# AIA 배포 패키지

현재 저장소는 Windows 11, Python 3.13, `uv`, Codex CLI를 대상으로 하는 오픈소스
소스 배포와 Python wheel을 제공한다. AIA가 모든 Agent와 운영체제를 보호하는
범용 제품이라는 의미는 아니다. 지원 범위와 제한사항은
[PRODUCT-SUPPORT.md](PRODUCT-SUPPORT.md)와 [LIMITATIONS.md](LIMITATIONS.md)에
고정되어 있다.

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

공개하기 전에는 release bundle 자체도 검증한다. 이 명령은 wheel·source archive의
개수, release manifest의 패키지 목록, `SHA256SUMS.txt`와 실제 파일의 일치를
확인한다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify-release.ps1 `
  -BundlePath .\dist\release\aia-0.1.0
```

검증 결과가 `SHA-256: PASS`가 아닌 bundle은 배포하지 않는다.

## Wheel 설치

릴리스 디렉터리의 `INSTALL-FROM-WHEEL.md`에 기록된 순서를 따른다. 개인이 실제로
사용하는 설치 경로는 `uv tool install`이다. 이렇게 설치하면 저장소 폴더 안에서만
`uv run`을 붙여 실행하지 않아도 어느 Workspace에서든 `aia` 명령을 사용할 수 있다.

```powershell
uv tool install --force .\packages\aia_mvp-0.1.0-py3-none-any.whl
aia --version
aia setup
```

설치 뒤에는 반드시 Codex의 `/hooks`에서 AIA Hook을 검토·신뢰하고 `aia hook verify`를
실행한다. Hook이 실제로 검증되지 않은 실행은 보호 성공으로 표시하지 않는다.

업데이트는 다음처럼 수행한다.

```powershell
uv tool install --force .\packages\aia_mvp-0.1.0-py3-none-any.whl
```

제거는 다음처럼 수행한다.

```powershell
uv tool uninstall aia-mvp
```

## 아직 제공하지 않는 배포 기능

- 서명된 Windows MSI 또는 EXE 설치 관리자
- 자동 업데이트와 이전 버전 롤백
- 중앙 관리 서버나 원격 콘솔
- 모든 Agent와 모든 Codex 도구에 대한 보편적 보호

이 항목들은 현재 릴리스의 제공 기능으로 가장하지 않는다.
