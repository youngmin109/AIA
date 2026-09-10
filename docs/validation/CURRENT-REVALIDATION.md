# AIA 현재 재검증 기록

이 문서는 EPIC-018의 과거 평가 산출물을 수정하지 않고, 현재 코드와 배포 후보를
다시 확인한 결과를 기록한다.

## 기준

| 항목 | 값 |
|---|---|
| 검증일 | 2026-09-11 |
| 코드 기준 | `f09072c` |
| 제품 버전 | `0.1.0` |
| 운영체제 | Windows |
| Python | 3.13 |
| 실행 환경 | `uv` 잠금 환경 |

## 결과

| 검증 | 결과 |
|---|---|
| 전체 pytest | **499 passed, 3 skipped** |
| `uv lock --check` | **PASS** |
| `uv build` wheel/sdist | **PASS** |
| 릴리스 번들 생성 | **PASS** |
| 릴리스 wheel·sdist 개수 검증 | **PASS** |
| 릴리스 SHA-256 검증 | **PASS** |
| 설치된 wheel `aia self-test --json` | **PASS** |
| 실제 Codex proof 판정 | 실제 Codex Hook Trust가 준비된 환경에서 별도 실행 |

## 이번 재검증에서 확인한 제품 계약

- 보호 실행 종료 시 AIA가 살아 있는 관리 대상 Codex에 사용자 중지 요청을 보낸다.
- 실제 Codex 사전 차단 proof는 Gate `CONTAIN`만으로 통과하지 않는다.
- `BLOCKED / SUCCEEDED`, Canary 무부작용, 유효한 Result Bundle이 함께 확인되어야
  차단 proof를 PASS로 기록한다.
- `COMPLETED_VERIFIED`와 `ABORTED_VERIFIED`는 Hook Event만으로 결정하지 않으며,
  모든 런타임 센서가 실행 중 `HEALTHY`이고 종료 시 `STOPPED`여야 한다.
- 웹 콘솔에서 `CUSTOM` 정책을 선택하면 사용자 정책 JSON 경로를 입력할 수 있다.
- 로컬 콘솔은 `aia console --open`으로 기본 브라우저에서 열 수 있다.
- 보호 실행에 바인딩된 PreToolUse Hook은 Broker·Capability 오류와 내부 정규화
  실패를 빈 응답으로 통과시키지 않고 Codex blocking exit path로 처리한다.
- 실행 중 per-run Hook Broker가 사라지면 live 상태를 `DEGRADED`로 낮추고,
  종료 결과를 `*_VERIFIED`로 표시하지 않는다.
- Live Run 화면과 API에서 per-run Hook Broker 상태를 별도 표시한다.
- Actual Codex PreTool proof도 차단 판정에 종료 직전 Broker 생존 확인을 요구한다.

## 해석상 제한

- Symlink 통합 테스트는 Windows 권한이 없으면 skip될 수 있으며, 환경 독립적인
  거부 Unit Test는 항상 실행한다.
- Windows 테스트 실행기의 Job Object 영향 때문에 Process Manager 통합 테스트가
  skip될 수 있다.
- 실제 Codex proof는 사용자가 Codex `/hooks`에서 AIA Hook을 검토·신뢰하고,
  `aia hook verify`가 현재 Hook 설정에 대한 Session-bound Event를 확인한 뒤에만
  실행할 수 있다.
- 이 기록은 모든 Codex 도구·MCP·Agent를 보편적으로 보호한다는 증명이 아니다.

과거 EPIC-018 평가의 상세 수치와 당시 판정은
[ACCEPTANCE.md](ACCEPTANCE.md), [MVP-FINAL-VERDICT.md](MVP-FINAL-VERDICT.md),
[ACTUAL-CODEX-E2E.md](ACTUAL-CODEX-E2E.md)를 함께 확인한다.
