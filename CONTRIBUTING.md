# Contributing to AIA

## 개발 원칙

- 보안 계약과 Ground Truth를 임의로 완화하지 않는다.
- 새 기능은 지원 범위와 사용자에게 보이는 상태를 함께 정의한다.
- 제품 경로와 Fixture/평가 경로를 구분한다.
- 정책 판정, 귀속, 집행, 복구, 무결성 축을 하나의 상태로 합치지 않는다.
- 민감한 command, prompt, 환경변수, secret을 Result/Report에 복제하지 않는다.

## 검증

변경 후 다음을 실행한다.

```powershell
uv sync
uv run pytest
```

GitHub Actions는 동일한 Windows 기반 잠금 환경에서 이 회귀 테스트와 wheel·source
distribution 빌드를 자동으로 다시 실행한다. 로컬에서는 다음 Release Gate 하나로
배포 후보를 확인한다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\release-gate.ps1
```

Release Gate는 잠금 환경 동기화, 전체 pytest, 안전한 `aia demo`, 릴리스 패키지
생성, SHA-256·clean wheel·로컬 콘솔 asset 검증을 같은 순서로 실행한다. 이미 만든
Bundle만 다시 검사하려면 다음처럼 사용할 수 있다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\release-gate.ps1 `
  -SkipTests -SkipPackage -BundlePath .\dist\release\aia-0.1.17
```

Codex Hook 또는 Process Manager 변경은 disposable Workspace에서 실제 증명을
추가한다. 테스트가 실행 환경 제약으로 `skip`되는 경우에는 그 이유와 보안 주장
범위를 문서에 남긴다.

## 변경 보고

Pull Request에는 변경 내용, 테스트 결과, 남은 위험과 지원 범위를 기록한다.
실제 Codex 동작을 검증하지 않은 경우 결정론적 Fixture 결과를 Actual Codex
성공으로 표현하지 않는다.
