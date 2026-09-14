# AIA MVP

AIA는 Codex와 같은 Agent의 보호 실행을 위한 독립적인 제품형 MVP Repository다. MVP는 실행 증거를 수집하고, 정규화·귀속·정책 평가·집행·복구·무결성 검증·감사를 연결한다.

현재 구현 상태와 지원 범위는 [제품 상태](docs/PRODUCT-STATUS.md)와 [제한사항](docs/LIMITATIONS.md)에 기록되어 있다. 실제 Codex 검증에서는 Bash와 `apply_patch`의 사전 차단을 확인했다. MCP는 현재 제품 범위에서 제외하며, 파괴적 PROCESS 시나리오는 별도 제한사항으로 남아 있다.

제품 정의와 개발 규칙은 [PROJECT.md](PROJECT.md), [ARCHITECTURE.md](ARCHITECTURE.md), [AGENTS.md](AGENTS.md)를 참조한다.

현재 설치에서 AIA가 보호한다고 주장하는 범위는 `uv run aia capabilities`로 확인할 수 있다.
현재 제품 성숙도와 남은 제품화 항목은 [제품 상태](docs/PRODUCT-STATUS.md)에서 확인할 수 있다.
공개 버전별 변경 사항은 [변경 이력](CHANGELOG.md)에서 확인할 수 있다.
릴리스 wheel·sdist와 SHA-256 manifest 생성 방법은 [배포 패키지 가이드](docs/DISTRIBUTION.md)를 참조한다.

새 Windows 환경에서 설치하려면 [설치 가이드](INSTALL.md)를 먼저 읽는다.
처음 실제 실행까지는 [빠른 시작](docs/QUICKSTART.md)을 따른다. 오류가 발생하면
[문제 해결](docs/TROUBLESHOOTING.md)을 확인한다.
처음 사용하는 사람은 [사용자 가이드](docs/USER-GUIDE.md)를 먼저 읽는다.

릴리스 ZIP을 사용하는 경우에는 압축을 푼 폴더에서 포함된 `install.ps1`을 실행하면
wheel이 사용자 도구로 설치된다. 소스 저장소에서 개발하거나 실행할 때는
`uv run aia` 경로를 사용한다.

사용자 지원 범위와 상태 해석은 [제품 지원 범위](docs/PRODUCT-SUPPORT.md),
보안 문제 보고 절차는 [SECURITY.md](SECURITY.md), 기여 규칙은
[CONTRIBUTING.md](CONTRIBUTING.md)를 참조한다.

시스템 전체 구성은 [AIA 시스템 구성도](docs/SYSTEM-OVERVIEW.md)에서 확인할 수 있다.

## 개발 환경

```powershell
uv sync
uv run pytest
```

저장소에 Push하거나 Pull Request를 만들면 Windows 실행 환경에서 같은 잠금 파일로
전체 pytest, Python compile, AIA Core self-test를 자동 실행한다. CI가 통과하지 않은
변경은 릴리스 후보로 취급하지 않는다.

처음 설치한 뒤 실제 프로젝트를 건드리지 않고 제품 흐름을 확인하려면 다음을
실행한다.

```powershell
uv run aia demo
```

실제 Codex 차단 증명은 Hook을 검토·신뢰하고 `uv run aia hook verify`를 완료한
뒤 `uv run aia demo --live`로 별도 실행한다. 이 명령은 disposable Workspace를
사용한다.

평가 실행 결과와 원본 Evidence는 개인 Workspace와 비밀정보가 포함될 수 있으므로 저장소에 넣지 않는다. 재현 가능한 성능 측정 스크립트와 데이터 형식은 [평가 도구 안내](scripts/product_evaluation/README.md)에서 확인할 수 있으며, 실행 결과는 로컬의 무시된 디렉터리에 저장한다.

## 로컬 보안 콘솔 (EPIC-019)

선택적으로 로컬 콘솔을 실행할 수 있다.

```powershell
uv run aia console --open
```

기본 주소는 [http://127.0.0.1:8787](http://127.0.0.1:8787)이다. `--open`을 지정하면 기본 브라우저에서 이 로컬 주소를 연다. 화면에서 Workspace, Codex 작업 요청, Policy Profile, ENFORCE/AUDIT 모드를 입력하면 AIA Core의 보호 실행 흐름을 시작하고, Live Run과 Result Bundle을 확인할 수 있다. 기본 Control Root는 `%USERPROFILE%\.aia\control`이며 `AIA_CONTROL_ROOT` 환경 변수로 바꿀 수 있다. 기존의 `uv run aia-web` 명령도 계속 사용할 수 있다.

기본 화면(`/`)은 실행 전 준비 상태, Codex Hook Trust, 현재 지원 범위, 최근
Protected Run을 보여주는 대시보드다. 대시보드는 실행을 자동으로 시작하지 않으며,
`새 보호 실행`(`/new`) 화면에서 사용자가 명시적으로 시작한다.

콘솔은 로컬 단일 사용자 도구다. 외부 bind/로그인/원격 접근/Database를 제공하지 않으며, Core의 보안 판정과 Result Bundle을 화면에 표시하는 역할만 한다. 화면에는 raw command와 evidence payload 값이 노출되지 않는다.

새 보호 실행 화면의 `정책 미리보기`에서는 실제 실행 전에 파일 경로 또는 명령을
넣어 선택한 정책의 판정·Effect·보안 자산·적용 Rule을 확인할 수 있다. 미리보기는
Codex를 시작하지 않고 실행 대상에도 접근하지 않는다.

외부 Network에 노출하지 마십시오.

콘솔에서 `새 보호 실행`을 시작하면 AIA가 사용자가 이미 만든 Workspace를 확인한
뒤 보호 준비를 수행하고, `별도 Windows 터미널에서 Codex 열기`를 선택한 경우
Codex를 별도 창의 자식 프로세스로 실행한다. 실행 화면에는 Hook·File·Process
Sensor 상태와 민감정보를 숨긴 안전한 이벤트 요약이 1초마다 갱신된다. 위험 행위가
차단되면 Codex 세션은 종료하지 않고 사건 카드에 `VIOLATION → CONTAIN →
BLOCKED / SUCCEEDED`를 실제 확인된 경우에만 표시한다.

`새 보호 실행` 화면의 `정책 만들기`에서 현재 한국어 Strict Schema에 맞는 File Rule
또는 Command Rule을 작성하고 검증할 수 있다. Validation을 통과한 정책만
`%USERPROFILE%\.aia\policies`에 저장되며, 저장된 파일은 `CUSTOM` 프로필로 다음
실행에 선택한다. AIA는 Workspace를 자동 생성하지 않는다.

## 라이선스

이 프로젝트는 Apache License 2.0으로 배포됩니다. 자세한 내용은
[LICENSE](LICENSE)를 확인하십시오. 제품 이름과 로고의 사용 권한은 Apache
라이선스의 코드 사용 권한과 별도로 취급합니다.

## 실제 Codex 보호 실행

처음 설치한 뒤에는 환경 점검부터 실행합니다.

```powershell
uv run aia doctor
```

Hook 설치·Trust·검증의 차이가 헷갈리면 다음 읽기 전용 안내를 먼저 실행합니다.

```powershell
uv run aia hook explain
```

이 명령은 Codex 설정이나 Trust 상태를 변경하지 않고, Codex `/hooks`에서 검토할
matcher와 command, 현재 Trust 상태, `aia hook verify`까지의 순서를 보여줍니다.

처음 실행하면 `hook_verification`이 `FAIL`일 수 있습니다. 아직 실제 Codex
실행에서 AIA Hook이 동작했다는 증명이 없다는 뜻입니다. 아래 설정과 실제 검증을
완료한 뒤에만 보호 실행을 시작할 수 있습니다.

AIA 설치와 Core 자체가 정상인지 먼저 확인하려면 다음 명령을 실행합니다. 이
점검은 임시 Workspace와 Control Root를 사용한 뒤 삭제하며 Codex를 실행하지
않습니다. 따라서 `PASS`여도 실제 Codex Hook 연결이 증명된 것은 아닙니다.

```powershell
uv run aia self-test
```

문제 보고가 필요하면 전체 경로·Workspace 내용·raw evidence·명령 출력이 빠진
진단 번들을 만들 수 있습니다.

```powershell
uv run aia support-bundle --output .\aia-support-bundle.json
```

이 파일은 AIA 버전, Python·Windows·Codex 상태, Hook Trust 상태와 최근 실행의
보호 상태 요약만 포함합니다.

처음 설치하는 사용자는 다음 한 명령으로 AIA Hook을 추가할 수 있습니다.

```powershell
uv run aia setup
```

그다음 Codex에서 `/hooks`를 열어 AIA Hook을 직접 검토·신뢰합니다. `aia protect`는 PreToolUse Hook이 설치되지
않은 상태에서는 Protected Run을 만들지 않고 즉시 다음 조치를 안내합니다.
설치 여부와 실제 보호 실행에서 Hook Event가 관찰됐는지는 다음 명령으로 구분해
확인할 수 있습니다.

```powershell
uv run aia hook status
```

`PreToolUse 설치: YES`는 설정 파일이 있다는 뜻이고, `Hook 관찰 상태:
OBSERVED_IN_PAST`일 때만 과거 실행에서 AIA Session에 연결된 Hook이 확인됐다는
뜻입니다. 현재 설정과 검증 기록이 모두 유효한 상태는 `CURRENTLY_VERIFIED`이며,
설치만 되어 있고 Event가 없으면 보호 성공으로 해석하지 않습니다.

처음 실행할 때 AIA는 `PROTECTED_DEVELOPMENT` 프로필을 기본 사용합니다. 이 프로필은
`.env` 같은 비밀정보 읽기와 대표적인 파괴 명령을 기본 차단하고, 일반 소스 변경은
기록합니다. 개발 흐름을 더 넓게 허용하려면 보호 실행에서 다른 프로필을 명시적으로
선택할 수 있습니다.

사용자 정책을 직접 작성했다면 보호 실행 전에 Strict Validation을 실행합니다.

```powershell
uv run aia policy validate C:\workspace\policies\protected-policy.json
```

실제 Agent를 시작하기 전에 정책 결과를 미리 확인할 수도 있습니다. 이 명령은
파일이나 명령을 실행하지 않고, 검증된 정책 객체에 대상만 대입해 최종 판정과
매칭 Rule을 보여줍니다.

```powershell
uv run aia policy evaluate --operation READ --path .env
uv run aia policy evaluate --operation EXECUTE --command "python build.py"
uv run aia policy evaluate --policy C:\workspace\policies\my-policy.json --operation DELETE --path protected\main.py
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
`READY`를 보여주면 사전 조건이 준비된 것입니다. Codex에서 `/hooks`를 열어 AIA Hook을 검토하고 신뢰한 뒤
보호 실행을 시작합니다. 이미 Hook만 설치해야 하는 경우에는 다음 명령을
사용할 수도 있습니다.

```powershell
uv run aia hook install
```

실제 사용 전에 현재 Codex가 AIA Hook을 실행할 수 있는지 확인하려면 다음을
실행합니다. 임시 Workspace에서 무해한 Probe를 한 번 실행하고, 결과 Bundle은
Control Root에 보존하며 임시 Workspace는 삭제합니다.

```powershell
uv run aia hook verify
```

`VERIFIED`와 Session-bound Hook Event가 확인될 때만 일반 보호 실행을 검증된
상태로 해석합니다. `NOT_VERIFIED`이면 Codex `/hooks`에서 AIA Hook을 검토·신뢰한
뒤 다시 실행합니다.

`aia hook verify`는 먼저 Codex의 현재 PreToolUse Trust 상태를 확인합니다. 상태가
`MODIFIED`, `UNTRUSTED` 또는 `NOT_VISIBLE`이면 실제 Probe를 시작하지 않고 즉시
원인과 다음 단계를 출력합니다. Codex `/hooks`에서 AIA PreToolUse Hook을 직접
검토·신뢰한 뒤 다시 실행합니다. 이 점검은 Hook을 자동으로 신뢰하지 않으며,
신뢰된 경우에도 실제 Session-bound Hook Event가 확인될 때만 `VERIFIED`가 됩니다.

`VERIFIED`가 된 뒤 `uv run aia doctor`를 다시 실행하면 `READY`가 되어야 합니다.
검증 파일은 현재 Hook 설정과 Codex 실행 파일에 묶여 있으므로, 둘 중 하나가
바뀌면 다시 `aia hook verify`를 실행해야 합니다.

```powershell
uv run aia protect C:\workspace\my-project
```

위 명령은 먼저 AIA Protected Run을 만들고 Workspace, 정책, Lease, Checkpoint, 센서를 준비한 뒤 Codex 대화형 세션을 엽니다. Codex 화면에서 여러 작업을 입력하고 Codex를 종료하면 AIA가 Evidence, Recovery, Integrity, Audit 결과를 확정합니다. 실행 화면의 `ACTIVE_VERIFIED`는 실제 Hook Evidence가 AIA Session과 연결됐다는 뜻이고, `ACTIVE_UNVERIFIED`는 아직 Hook 이벤트가 확인되지 않았다는 뜻입니다.

처음 사용하는 사람은 제품 흐름이 드러나는 `start` 명령으로 같은 대화형 보호
세션을 열 수 있습니다. AIA가 먼저 보호 실행을 준비하고 Codex 화면을 연 뒤,
사용자는 그 세션 안에서 작업을 입력합니다.

```powershell
aia start C:\workspace\my-project
```

저장소에서 `uv run`으로 실행할 때는 `uv run aia start C:\workspace\my-project`를
사용합니다. 기존 `protect` 명령도 같은 보안 경로로 계속 지원됩니다.

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

AIA가 강제 종료되어 이전 실행이 끝나지 않은 상태로 남으면 `aia status`와 로컬
콘솔에 `ORPHANED_DEGRADED`가 표시됩니다. AIA 조정 프로세스와 기록된 Agent Root의
PID·생성 시각을 확인한 뒤 Agent Root가 실제로 사라진 경우에만 다음 명령으로
이전 실행의 정리 확인을 남깁니다.

```powershell
uv run aia reconcile <SESSION_ID>
```

이 명령은 Evidence를 삭제하지 않고, 고아 실행을 성공한 보호 실행으로 바꾸지
않습니다. Agent Root가 살아 있거나 신원을 확인할 수 없으면 정리를 거부합니다.
같은 Workspace로 새 보호 실행을 시작하는 것도 정리 확인 전에는 거부됩니다. 이
확인은 이전 Codex와 새 Codex가 같은 Workspace를 동시에 변경하지 않도록 합니다.
실행 중 Hook Broker가 사라져 관리 트리 중지를 시도한 경우에는
`FAILED_DEGRADED`로 기록될 수 있습니다. 이 상태는 보호 경계가 끊겼고
보호 성공으로 해석할 수 없다는 뜻입니다. 관리 트리 종료 결과는 사용자 중지나
정책 집행 결과와 별도의 `protection_failure_termination_result`에서 확인합니다.
`aia stop`은 정책 위반 집행과 분리된 사용자 취소이며, 결과에는 `USER_ABORT`로 기록됩니다.
완료된 Result Bundle에서는 `user_abort_termination_result.status`와
`verified_tree_gone`으로 실제 관리 트리 종료 여부를 확인할 수 있습니다. 이 값은
정책 위반 집행용 `process_termination_result`와 별도입니다.

AIA를 업데이트한 뒤 matcher가 바뀌어 `aia doctor`가 `NOT_READY`를 보여주면
`uv run aia hook install`을 다시 실행하고 Codex `/hooks`에서 변경된 Hook을
다시 검토·신뢰합니다. 검증된 Hook Event가 하나도 없는 실행은
`COMPLETED_DEGRADED`로 기록되며 보호 성공으로 표시하지 않습니다.

Hook을 Codex에서 검토·신뢰한 뒤 보호 실행을 시작한다. 실제 사전 차단 증명 절차는
[빠른 시작](docs/QUICKSTART.md)과 [제품 지원 범위](docs/PRODUCT-SUPPORT.md)를 참고한다.

현재 제품이 보장하는 보호 경계는 Windows 11, Codex CLI, AIA Protected Run,
그리고 지원되는 `PreToolUse` matcher입니다. 현재 실제로 검증된 matcher에는
`Bash`, `apply_patch`가 포함됩니다. MCP를 포함한 목록 밖 도구는
`UNSUPPORTED_TOOL_PATH`로 거부합니다. `PostToolUse`는 실행 결과 확인을
위한 선택적 증거 경로이며 사후에 이미 발생한 부작용을 되돌리지 않습니다. Hook이
끊기거나 지원되지 않는 도구를 사용한 실행은 완전한 보호 실행으로 표시하지 않습니다. Actual Codex 전체 도구와
OS 전체 Writer를 보호한다고 주장하지 않으며, 제한사항은 [docs/LIMITATIONS.md](docs/LIMITATIONS.md)에 고정되어 있습니다.

제품 CLI 전체 경계를 disposable Workspace에서 다시 확인하려면 다음 opt-in smoke를
실행한다. 이 명령은 실제 Codex 실행을 시작하므로 일반 회귀 테스트에는 포함하지 않는다.

```powershell
uv run aia proof
```

기본값은 실제 `Bash PreToolUse → deny → Canary 미생성`을 확인하는 차단 증명이다.
이 명령은 시작 전에 현재 Hook Trust와 Session-bound Hook 연결을 다시 검증한다.
검증에 실패하면 Codex를 실행하지 않고 원인과 artifact 경로를 남긴다. 기존 스크립트
경로도 호환성을 위해 유지한다.

터미널에는 PASS/FAIL, 실제 도구 차단 여부, Canary 부작용, Evidence Bundle 상태를
읽기 쉬운 요약으로 출력한다. 자동화나 상세 분석에 필요한 전체 JSON은 다음처럼
명시적으로 요청한다.

```powershell
uv run aia proof --json
```

```powershell
uv run python scripts/product_e2e_smoke.py
uv run python scripts/product_e2e_smoke.py --scenario block-canary
```

`apply_patch` 경로까지 실제로 확인하려면 다음을 실행합니다.

```powershell
uv run python scripts/product_e2e_smoke.py --scenario block-apply-patch
```

`.env` 비밀정보 읽기 차단까지 실제로 확인하려면 다음을 실행합니다.

```powershell
uv run aia proof --scenario block-env
```

이 시나리오는 disposable Workspace의 `.env` 읽기 시도를 실제 Codex가 실행하기
전에 차단하고, Codex 출력·Evidence·Result에 secret marker가 남지 않았는지도
함께 확인합니다.

`normal`은 실제 `aia protect` 경로의 정상 완료와 결과 Bundle을 확인합니다.
`block-canary`와 `block-apply-patch`는 실제 Codex `PreToolUse`에서 정책 위반 관문이
`CONTAIN / PRETOOL_BLOCK`으로 결정되고 Canary 부작용이 없는지 확인합니다.
`block-env`는 `.env`가 `SECRET` 자산으로 판정되고 실제 차단과 secret marker 비유출이
확인되는지 별도로 검사합니다.
제품 서비스는 Hook deny만으로 실행 성공을 주장하지 않으므로, Canary 시나리오는
`block_confirmation=CANARY_NO_SIDE_EFFECT`, `confirmed_block_count` 1 이상,
`canary_executed=false`가 함께 확인될 때만 제품 경로의 사전 차단 성공으로
해석합니다. `block-env`는 `block_confirmation=SECRET_NOT_LEAKED`와
`secret_leaked=false`를 확인합니다. Gate만 생성되고 실제 Codex 차단 확인이 없으면
proof는 실패합니다.
Hook 신뢰가 적용되지 않은 환경에서는
`COMPLETED_DEGRADED`가 기록되며 파일이 생성되지 않았다는 사실만으로 성공
처리하지 않습니다.

결정론적 전후 성능·보안 평가는 `scripts/product_evaluation/run_fixture_evaluation.py`로
생성한다. 결과는 기본적으로 저장소 밖 또는 `.gitignore` 대상 디렉터리에 보존하며,
Actual Codex 결과와 섞지 않는다.

## 현재 구현과 지원 범위

현재 실제로 구현된 기능은 다음과 같다.

- Windows 11과 Codex CLI를 위한 Protected Run
- Codex PreToolUse Hook Sensor
- Workspace 파일 변경을 관찰하는 File Sensor
- AIA가 시작한 Codex 프로세스 트리를 관찰하는 Process Sensor
- 한국어 정책 프로필과 Strict Validation
- 정책 판정, PreTool 차단, Evidence Bundle, Checkpoint·Recovery·Integrity 결과
- 로컬 콘솔과 실행 결과 확인

현재 지원하지 않거나 설계·평가 범위로만 남아 있는 기능은 다음과 같다.

- MCP, Claude 및 외부 Agent
- 네트워크 보안
- OS 전체 프로세스·Writer 보호
- AIA Protected Run 밖의 실행 보호
- 서명된 자동 업데이트와 원격 관리
