# EPIC-018 Test Result

평가 ID: `eval-20260909T144119Z`
후보 코드 기준: `c5bd350`
환경: Windows 11 Pro `10.0.26200`, Python `3.13.5` (`uv run`), uv `0.12.5`, pytest `9.1.1`, 16 logical CPU, 32 GB RAM, NVMe SSD

## Regression

`uv run pytest -ra`: **360 passed, 3 skipped**, exit code 0.
`uv lock --check`, `compileall`, candidate diff check: **PASS**.

Skip 3건은 제품 실패로 분류하지 않는다.

- Windows Symlink 생성 권한 부족: WinError 1314
- Windows test-runner Job Object가 보호 root와 descendants에 영향을 줄 수 있음
- Recovery Symlink 생성 권한 부족: WinError 1314

원문은 `evaluation/mvp-1.0/eval-20260909T144119Z/regression/pytest-rA.txt`에 보존했다.

## 추가 검증

- 결정론적 선택 테스트 22건: PASS
- Containment chain smoke: `VIOLATION → EXACT → CONTAIN → TERMINATED/SUCCEEDED → RESTORED → VERIFIED → VALID`: PASS
- Recovery smoke: `RESTORED + VERIFIED`: PASS
- Evidence tamper tests 7건: PASS
- Secret scan: Result/Audit/Report/Manifest/Commit/Index에 marker 0건: PASS
- Process Manager disposable tree: root/child/grandchild 종료, unrelated process `LIVE_MATCH`, termination call 0: PASS

## 분류

최종 평가에서 확인된 실패가 제품 결함으로 판정된 것은 없다. 당시 Actual Codex
structured READ와 destructive PROCESS는 `EXTERNAL_INTERFACE_LIMITATION` 또는
`SCENARIO_NOT_REALIZED`로 기록했다. 후속 `mcp-read` Canary는 개발 이력으로
보존하지만 현재 제품 지원 범위에서 제외한다. 환경에 따른 Symlink/Job Object skip은
`ENVIRONMENT_LIMITATION`이다.

2026-09-11 후속 Actual Codex 사용자 중지 smoke는 실제 Codex가 만든 Root → Child →
Grandchild를 모두 종료하고 unrelated 프로세스를 보존했다. Result Bundle에
`user_abort_termination_result.status=SUCCEEDED`와 `verified_tree_gone=true`가
기록됐다. 정책 위반에 따른 자동 destructive PROCESS 집행은 여전히 별도
제한사항이다.
