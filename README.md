# AIA MVP

AIA는 Codex와 같은 Agent의 보호 실행을 위한 독립적인 제품형 MVP Repository다. MVP는 실행 증거를 수집하고, 정규화·귀속·정책 평가·집행·복구·무결성 검증·감사를 연결한다.

EPIC-018 평가 결과는 [MVP 최종 판정](docs/validation/MVP-FINAL-VERDICT.md)과 [제한사항](docs/LIMITATIONS.md)에 기록되어 있다. 이 릴리스 후보는 결정론적 핵심 흐름을 검증했으며, Actual Codex의 구조화된 READ 차단과 파괴적 PROCESS 시나리오는 외부 인터페이스 제약으로 제한된다.

제품 정의와 개발 규칙은 [PROJECT.md](PROJECT.md), [ARCHITECTURE.md](ARCHITECTURE.md), [AGENTS.md](AGENTS.md)를 참조한다.

현재 배포 후보의 지원 계약과 검증 상태는 [AIA 0.1.0 릴리스 기준](docs/RELEASE-0.1.0.md)에서 확인할 수 있다.
현재 제품 성숙도와 남은 제품화 항목은 [제품 상태](docs/PRODUCT-STATUS.md)에서 확인할 수 있다.

새 Windows 환경에서 설치하려면 [설치 가이드](INSTALL.md)를 먼저 읽는다.

사용자 지원 범위와 상태 해석은 [제품 지원 범위](docs/PRODUCT-SUPPORT.md),
보안 문제 보고 절차는 [SECURITY.md](SECURITY.md), 기여 규칙은
[CONTRIBUTING.md](CONTRIBUTING.md)를 참조한다.

시스템 전체 구성은 [AIA 시스템 구성도](docs/SYSTEM-OVERVIEW.md)에서 확인할 수 있다.

## 개발 환경

```powershell
uv sync
uv run pytest
```

평가 산출물은 `evaluation/mvp-1.0/<evaluation-id>/` 아래에 보존한다. 평가 기준, 허용된 주장, 제한사항, 위협 모델은 `docs/validation/`과 `docs/`에 함께 고정한다.

## 로컬 보안 콘솔 (EPIC-019)

선택적으로 로컬 콘솔을 실행할 수 있다.

```powershell
uv run aia-web
```

기본 주소는 [http://127.0.0.1:8787](http://127.0.0.1:8787)이다. 화면에서 Workspace, Codex task, Policy Profile, ENFORCE/AUDIT 모드를 입력하면 AIA Core의 보호 실행 흐름을 시작하고, Live Run과 Result Bundle을 확인할 수 있다. 기본 Control Root는 `%USERPROFILE%\.aia\control`이며 `AIA_CONTROL_ROOT` 환경 변수로 바꿀 수 있다.

콘솔은 로컬 단일 사용자 P1 도구다. 외부 bind/로그인/원격 접근/Database를 제공하지 않으며, Core의 보안 판정과 Result Bundle을 화면에 표시하는 역할만 한다. 화면에는 raw command와 evidence payload 값이 노출되지 않는다. 자세한 범위와 HTTP 계약은 [EPIC-019 문서](docs/epics/EPIC-019-LOCAL-SECURITY-CONSOLE.md)를 참조한다.

외부 Network에 노출하지 마십시오.

## 라이선스

이 프로젝트는 Apache License 2.0으로 배포됩니다. 자세한 내용은
[LICENSE](LICENSE)를 확인하십시오. 제품 이름과 로고의 사용 권한은 Apache
라이선스의 코드 사용 권한과 별도로 취급합니다.

## 실제 Codex 보호 실행

처음 설치한 뒤에는 환경 점검부터 실행합니다.

```powershell
uv run aia doctor
```

처음 설치하는 사용자는 다음 한 명령으로 AIA Hook을 추가할 수 있습니다.

```powershell
uv run aia setup
```

그다음 Codex에서 `/hooks`를 열어 AIA Hook을 직접 검토·신뢰하고, 다시
`uv run aia doctor`를 실행합니다. `aia protect`는 PreToolUse Hook이 설치되지
않은 상태에서는 Protected Run을 만들지 않고 즉시 다음 조치를 안내합니다.

사용자 정책을 직접 작성했다면 보호 실행 전에 Strict Validation을 실행합니다.

```powershell
uv run aia policy validate C:\workspace\policies\protected-policy.json
```

처음 정책을 만드는 사용자는 검증된 기본 프로필을 복사해서 시작할 수 있습니다.

```powershell
uv run aia policy profiles
uv run aia policy init C:\workspace\policies\my-policy.json --profile CONSERVATIVE_SECURITY
uv run aia policy validate C:\workspace\policies\my-policy.json
```

`policy init`은 기존 파일을 덮어쓰지 않으며, 다시 생성하려면 명시적으로
`--force`를 사용해야 합니다.

`aia setup`이 기존 Codex Hook 설정을 덮어쓰지 않고 AIA의 PreToolUse와
PostToolUse 항목을 추가합니다. PreToolUse는 실행 전 정책 관문이고, PostToolUse는
실제 실행 여부를 확인하기 위한 선택적 관찰 경로입니다. `aia doctor`가
`READY`를 보여주면 Codex에서 `/hooks`를 열어 AIA Hook을 검토하고 신뢰한 뒤
보호 실행을 시작합니다. 이미 Hook만 설치해야 하는 경우에는 다음 명령을
사용할 수도 있습니다.

```powershell
uv run aia hook install
```

```powershell
uv run aia protect C:\workspace\my-project
```

위 명령은 먼저 AIA Protected Run을 만들고 Workspace, 정책, Lease, Checkpoint, 센서를 준비한 뒤 Codex 대화형 세션을 엽니다. Codex 화면에서 여러 작업을 입력하고 Codex를 종료하면 AIA가 Evidence, Recovery, Integrity, Audit 결과를 확정합니다. 실행 화면의 `ACTIVE_VERIFIED`는 실제 Hook Evidence가 AIA Session과 연결됐다는 뜻이고, `ACTIVE_UNVERIFIED`는 아직 Hook 이벤트가 확인되지 않았다는 뜻입니다.

한 번의 작업만 자동으로 실행하려면 다음처럼 초기 작업을 전달할 수 있습니다.

```powershell
uv run aia protect C:\workspace\my-project --task "작업 내용을 입력"
```

종료된 실행을 다시 확인할 때는 로컬 Control Root의 기록을 조회합니다.

```powershell
uv run aia runs
uv run aia status <SESSION_ID>
uv run aia status <SESSION_ID> --json
uv run aia stop <SESSION_ID>
```

실행 중인 Session은 Control Root에 안전한 상태 스냅샷을 보존하므로, 보호 실행을
시작한 터미널과 다른 터미널에서도 `status`와 `stop`을 사용할 수 있다.

`COMPLETED_VERIFIED`는 실제 Hook Event와 검증된 Result Bundle이 확인된 실행이고,
`COMPLETED_DEGRADED`는 실행은 끝났지만 보호 경계가 완전히 검증되지 않은 실행입니다.
후자는 성공한 보호 실행으로 해석하지 말고 제한사항을 확인해야 합니다.
`aia stop`은 정책 위반 집행과 분리된 사용자 취소이며, 결과에는 `USER_ABORT`로 기록됩니다.

Hook을 Codex에서 검토·신뢰한 뒤 보호 실행을 시작한다. 실제 사전 차단 증명은 [docs/ACTUAL-CODEX-PROOF.md](docs/ACTUAL-CODEX-PROOF.md)를 참고한다.

현재 제품이 보장하는 보호 경계는 Windows 11, Codex CLI, AIA Protected Run,
그리고 지원되는 `PreToolUse` matcher입니다. `PostToolUse`는 실행 결과 확인을
위한 선택적 증거 경로이며 사후에 이미 발생한 부작용을 되돌리지 않습니다. Hook이
끊기거나 지원되지 않는 도구를 사용한 실행은 완전한 보호 실행으로 표시하지 않습니다. Actual Codex 전체 도구와
OS 전체 Writer를 보호한다고 주장하지 않으며, 제한사항은 [docs/LIMITATIONS.md](docs/LIMITATIONS.md)에 고정되어 있습니다.

제품 CLI 전체 경계를 disposable Workspace에서 다시 확인하려면 다음 opt-in smoke를
실행한다. 이 명령은 실제 Codex 실행을 시작하므로 일반 회귀 테스트에는 포함하지 않는다.

```powershell
uv run python scripts/product_e2e_smoke.py
uv run python scripts/product_e2e_smoke.py --scenario block-canary
```

`apply_patch` 경로까지 실제로 확인하려면 다음을 실행합니다.

```powershell
uv run python scripts/product_e2e_smoke.py --scenario block-apply-patch
```

`normal`은 실제 `aia protect` 경로의 정상 완료와 결과 Bundle을 확인합니다.
`block-canary`와 `block-apply-patch`는 실제 Codex `PreToolUse`에서 정책 위반 관문이
`CONTAIN / PRETOOL_BLOCK`으로 결정되고 Canary 부작용이 없는지 각각 확인합니다.
제품 서비스는
Hook deny만으로 실행 성공을 주장하지 않으므로, 이 smoke의 결과에는
`CANARY_NO_SIDE_EFFECT`와 `confirmed_block_count`가 따로 표시됩니다.

결정론적 전후 성능·보안 평가 결과는
[fixture 평가 대시보드](evaluation/product-before-after/fixture-20260910-001/report.html)에서
확인할 수 있다. 이 결과는 12개 시나리오의 AIA OFF/AIA ON 반복 실행을 포함하며,
Actual Codex 결과와 섞지 않고 별도 평가로 표시한다.
