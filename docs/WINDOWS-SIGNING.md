# AIA Windows 코드 서명

AIA의 Windows 제품은 다음 순서로 배포한다.

~~~
PyInstaller onedir 빌드
→ AIA.exe·aia-cli.exe 코드 서명
→ Inno Setup 설치 프로그램 생성 및 내부 언인스톨러 서명
→ 설치 프로그램 코드 서명
→ SHA-256 manifest 생성
~~~

<code>AIA.exe</code>와 <code>aia-cli.exe</code>를 만드는 것만으로는 제품 배포가
끝나지 않는다. Windows SmartScreen과 조직의 Code Integrity 정책이 신뢰할 수
있는 게시자를 확인할 수 있도록 Authenticode 인증서로 서명해야 한다. 학교·회사
PC의 Enterprise 정책은 공개 인증서만으로 충분하지 않을 수 있으며, 이 경우
관리자가 인증서 또는 릴리스 파일을 허용 목록에 추가해야 한다.

## 인증서 파일로 서명

Windows SDK의 <code>signtool.exe</code>가 필요하다. PFX 비밀번호는 명령 줄에
직접 쓰지 않고 현재 PowerShell 세션의 환경 변수로 전달한다.

~~~
$env:AIA_SIGNING_CERT_PASSWORD = Read-Host "PFX password"
.\scripts\package-windows.ps1 -Clean -CertificatePath C:\secure\aia-release.pfx -RequireSignature
~~~

서명 대상은 기본적으로 <code>AIA.exe</code>, <code>aia-cli.exe</code>, 설치
프로그램과 설치 프로그램에 포함되는 언인스톨러다. Code Integrity 정책이 로딩되는 native runtime 파일까지 서명을
요구할 수 있으므로 공개 릴리스 workflow에서는 다음 옵션도 사용한다.

~~~
.\scripts\package-windows.ps1 -Clean -CertificatePath C:\secure\aia-release.pfx -SignRuntimeBinaries -RequireSignature
~~~

## 인증서 저장소의 인증서로 서명

현재 사용자 인증서 저장소 <code>My</code>에 인증서가 설치되어 있다면 지문을
사용한다.

~~~
.\scripts\package-windows.ps1 -Clean -CertificateThumbprint "인증서지문" -RequireSignature
~~~

## 개발 빌드

인증서가 없는 개발 환경에서는 서명 단계를 생략할 수 있다.

~~~
.\scripts\package-windows.ps1 -Clean
~~~

이 빌드는 실행 파일을 만들지만 unsigned 상태이므로 공개 배포용으로 사용하지
않는다. <code>-RequireSignature</code>를 사용하면 인증서 또는 서명 도구가 없을
때 빌드가 실패한다.

패키지 산출물의 해시와 실행 파일 상태는 다음으로 확인할 수 있다.

~~~powershell
.\scripts\verify-windows-package.ps1
~~~

공개 릴리스 게이트에서는 서명까지 필수로 검사한다.

~~~powershell
.\scripts\verify-windows-package.ps1 -RequireSignature
~~~

이 검사는 `AIA.exe`, `aia-cli.exe`, 설치 프로그램과 선택된 native runtime의
Authenticode 상태 및 SHA-256 manifest를 확인하고, 기본적으로 패키지된
`aia-cli self-test`도 실행한다. 공개 릴리스 workflow는
`-RequireNativeSignature`까지 사용한다.

GitHub Actions에서는 `v<pyproject.toml 버전>` 태그 또는 수동 실행으로 서명
릴리스 workflow를 시작할 수 있다. 저장소 Secrets에 다음 두 값을 등록해야 한다.

- `AIA_SIGNING_CERT_BASE64`: 릴리스용 PFX를 Base64로 인코딩한 값
- `AIA_SIGNING_CERT_PASSWORD`: PFX 비밀번호

서명 인증서가 없는 상태에서 태그를 만들면 workflow는 의도적으로 실패한다. 이를
통과하지 않은 unsigned artifact는 Windows 제품 릴리스로 배포하지 않는다.

패키지 결과는 다음에 생성된다.

~~~
dist\windows\AIA\AIA.exe
dist\windows\aia-cli\aia-cli.exe
dist\windows\installer\AIA-&lt;version&gt;-Setup.exe
dist\windows\installer\AIA-SHA256SUMS.txt
~~~
