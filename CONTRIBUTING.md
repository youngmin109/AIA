# Contributing to AIA

AIA에 기여해 주셔서 고맙습니다. 문서와 리뷰는 주로 한국어로 진행합니다.
Contributions in English are welcome too.

## 개발 원칙

- 보안 계약과 Ground Truth를 임의로 완화하지 않는다.
- 새 기능은 지원 범위와 사용자에게 보이는 상태를 함께 정의한다.
- 제품 경로와 Fixture/평가 경로를 구분한다.
- 정책 판정, 귀속, 집행, 복구, 무결성 축을 하나의 상태로 합치지 않는다.
- 민감한 command, prompt, 환경변수, secret을 Result/Report에 복제하지 않는다.
- 필요 없는 의존성을 추가하지 않고, 과한 추상화보다 읽기 쉬운 구조를 고른다.
  자세한 규칙은 [AGENTS.md](AGENTS.md)를 따른다.

## 개발 환경 준비

필요한 것: Windows 11, Python 3.13, [uv](https://docs.astral.sh/uv/), Node.js 24,
로그인한 Codex CLI.

1. 의존성 설치: `uv sync --group dev`, `npm --prefix frontend ci`
2. 화면 미리보기: `uv run python scripts/dev/ui_preview_server.py --port 8899`
   (가짜 Codex와 예시 기록으로 http://127.0.0.1:8899 를 엽니다.)
3. 데스크톱 앱 빌드: `uv sync --group build` 후 `.\scripts\build-windows.ps1`
   (`dist\windows\AIA\AIA.exe`, `dist\windows\aia-cli\aia-cli.exe`)
4. 설치 파일: `.\scripts\package-windows.ps1` (Inno Setup 6 필요)

스크립트별 설명은 [scripts/README.md](scripts/README.md)에 있습니다. 앱 아이콘을
다시 만들 때는 `uv run --no-project --with pillow python scripts/dev/make_app_icon.py`를
씁니다. Pillow는 프로젝트 의존성이 아닙니다.

## 검증

변경 후 저장소 루트에서 다음 명령을 실행한다. 프론트엔드를 변경한 경우에는
빌드와 린트도 실행한다. 프론트엔드 단위 테스트는 `npm --prefix frontend test`로
실행한다.

```powershell
.venv\Scripts\python.exe -m pytest -q
uvx ruff@0.15.0 check
npm --prefix frontend run build
npm --prefix frontend run lint
```

Codex Hook 또는 Process Manager 변경은 disposable Workspace에서 실제 증명을
추가한다. 테스트가 실행 환경 제약으로 `skip`되는 경우에는 그 이유와 보안 주장
범위를 문서에 남긴다.

## 브랜치와 Pull Request

- `main`에서 새 브랜치를 만들어 작업하고, 작업 묶음 하나를 Pull Request 하나로
  올린다. 머지는 squash로 한다.
- Pull Request에는 변경 내용, 테스트 결과, 남은 위험과 지원 범위를 기록한다.
  템플릿은 [.github/pull_request_template.md](.github/pull_request_template.md)에 있다.
- 실제 Codex 동작을 검증하지 않은 경우 결정론적 Fixture 결과를 Actual Codex
  성공으로 표현하지 않는다.
- 사용자에게 보이는 변경은 [CHANGELOG.md](CHANGELOG.md)에 적는다.

## 행동 강령과 보안

참여하는 모든 사람은 [행동 강령](CODE_OF_CONDUCT.md)을 지킨다. 보안 문제는
공개 Issue 대신 [SECURITY.md](SECURITY.md)의 절차로 알린다.
