# Security Policy

## 지원 범위

보안 문제는 Windows 11, Codex CLI, AIA Protected Run, 그리고 지원되는
PreToolUse Hook 경로를 기준으로 재현해 보고한다. 보호 실행 밖의 수동 실행이나
지원되지 않는 도구 경로는 현재 제품의 보안 경계 밖이다.

## 보고할 내용

가능하면 다음을 포함한다.

- AIA 버전 또는 Git commit
- Windows와 Codex CLI 버전
- 사용한 정책 프로필 또는 정책 파일의 민감정보 제거본
- disposable Workspace에서의 재현 절차
- Session ID와 Result Bundle 경로
- secret, token, 개인 파일 내용이 포함되지 않은 오류 요약

진단 파일이 필요하면 다음 명령을 사용한다.

```powershell
uv run aia support-bundle --output .\aia-support-bundle.json
```

이 명령은 전체 경로·Workspace 내용·raw evidence·tool input·명령 출력을 포함하지
않는 요약만 저장한다. 그래도 공유 전에 생성 파일을 직접 확인한다.

비밀정보와 전체 Workspace 내용을 Issue나 공개 채널에 올리지 않는다. 먼저
Repository 관리자가 지정한 비공개 보안 연락처로 보고한다.

## 안전한 재현

실제 프로젝트 대신 disposable Workspace를 사용한다.

```powershell
uv run python scripts/actual_codex_pretool_smoke.py
```

이 증명 스크립트는 결과를 `evaluation/actual-codex/` 아래에 저장할 수 있으며,
Checkpoint에 테스트용 `.env`가 포함될 수 있다. 해당 산출물을 외부에 공유하기
전에 secret marker와 사용자 Workspace 경로를 확인한다.
