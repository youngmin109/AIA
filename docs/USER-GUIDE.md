# AIA 사용자 가이드

AIA는 Codex를 대신하는 프로그램이 아니다. AIA가 먼저 보호 실행을 시작하고,
그 안에서 Codex를 자식 프로세스로 실행한다. 사용자는 Codex 화면이 열린 뒤
평소처럼 작업을 입력한다.

## 처음 한 번만 준비

저장소 폴더에서 PowerShell을 연다.

```powershell
cd C:\workspace\01_projects\aia-mvp
uv sync
uv run aia self-test
uv run aia setup
```

AIA의 현재 보호 범위와 지원하지 않는 경계를 확인하려면 다음을 실행한다.

```powershell
uv run aia capabilities
```

이 명령은 실제 Workspace나 Codex를 실행하지 않는 읽기 전용 제품 계약 조회다.

`self-test`가 `결과: PASS`이면 AIA Core 자체가 정상이다. 이 명령은 Codex나
사용자 Workspace를 실행하지 않는다.

`aia setup`은 Hook 파일을 설치한 뒤 현재 Codex가 보고한 PreToolUse Trust 상태도
함께 표시한다. `TRUSTED` 또는 `MANAGED`가 아니면 Codex에서 `/hooks`를 열어
AIA Hook의 명령과 Matcher를 확인하고 직접 신뢰해야 한다. `MODIFIED`,
`UNTRUSTED`, `NOT_VISIBLE`은 보호 실행이 준비된 상태가 아니다.

그 다음 Codex 화면에서 `/hooks`를 입력한다. AIA의 `PreToolUse` Hook 명령과
Matcher를 직접 확인하고 신뢰한다. AIA가 대신 신뢰하지 않는 이유는 사용자가
확인하지 않은 실행 경계를 자동으로 켜지 않기 위해서다.

신뢰를 마친 뒤 PowerShell에서 다음을 실행한다.

```powershell
uv run aia hook verify
uv run aia doctor
```

`aia doctor`의 마지막 결과가 `READY`여야 실제 보호 실행을 시작할 수 있다.
`MODIFIED`, `UNTRUSTED`, `NOT_READY`가 나오면 Codex `/hooks`에서 AIA Hook을
다시 확인하고 `uv run aia hook verify`를 다시 실행한다.

웹 콘솔의 `실행 전 준비 상태`도 같은 `readiness_code`와 다음 조치를 표시한다.
예를 들어 `CODEX_HOOK_TRUST_REQUIRED`이면 콘솔에서 실행 버튼을 누르기 전에
Codex `/hooks`에서 AIA PreToolUse Hook을 검토·신뢰해야 한다.

자동화나 상태 확인 화면에서는 `uv run aia doctor --json`의
`readiness_code`와 `next_step`을 사용한다. 예를 들어
`CODEX_HOOK_TRUST_REQUIRED`는 Codex `/hooks`에서 검토·신뢰한 뒤
`aia hook verify`를 실행해야 한다는 뜻이다. `READY`가 아닌 상태는 보호 실행을
시작할 수 있는 상태로 해석하지 않는다.

`aia hook status`에서 `CURRENT_BUT_UNTRUSTED`가 나오면 과거 검증 지문은 남아
있지만 현재 Codex가 Hook을 신뢰하지 않는 상태다. Codex `/hooks`에서 다시 검토·신뢰한
뒤 `uv run aia hook verify`를 실행한다.

## 정책을 먼저 확인하는 방법

웹 콘솔을 열면 `정책 미리보기`에서 파일 경로 또는 명령을 넣어 정책 결과를
확인할 수 있다.

```powershell
uv run aia console --open
```

브라우저에서 다음처럼 입력한다.

```text
행위 종류: READ
확인할 대상: .env
```

기본 `보호 우선 개발형` 정책에서는 다음 결과가 나온다.

```text
차단 대상
정책 효과: DENY
보안 자산: SECRET
```

이 미리보기는 Codex를 시작하지 않고 파일도 읽지 않는다.

## 보호 실행 시작

처음에는 실제 프로젝트 대신 복사본이나 테스트 폴더를 사용한다.

```powershell
uv run aia protect C:\workspace\my-project
```

AIA는 다음 순서로 준비한다.

```text
Workspace 확인
→ 정책 고정
→ Lease 준비
→ Checkpoint 생성
→ File / Hook / Process Sensor 준비
→ Codex 실행
```

터미널에 `Phase: READY`가 표시되면 준비가 끝났고 Codex를 시작하는 단계다. 잠시
후 Codex 화면이 열리면 작업을 입력한다. 30초 이상 계속되면 같은 실행의 Session
ID로 `uv run aia status <SESSION_ID>`를 실행해 상태를 확인하고, 필요하면
`Ctrl+C`로 사용자 중지를 요청한다.

Codex 화면이 열리면 그 안에서 작업을 입력한다.

```text
README.md를 읽고 현재 프로젝트를 세 문장으로 요약해줘
```

세션을 끝내려면 Codex를 정상적으로 종료한다. 그러면 AIA가 Evidence, 정책
판정, Recovery, Integrity, Audit 결과를 확정한다.

한 번의 요청만 실행하려면 다음처럼 사용할 수 있다.

```powershell
uv run aia protect C:\workspace\my-project --task "README.md를 읽고 한 문장으로 요약해줘"
```

## 차단 동작을 확인하는 방법

실제 Codex를 사용하는 차단 검증은 disposable Workspace를 자동으로 만들고
끝난 뒤 정리한다.

```powershell
uv run aia proof
```

`.env` 비밀정보 읽기 차단과 secret marker 비유출을 확인하려면 다음을 실행한다.

```powershell
uv run aia proof --scenario block-env
```

Windows 기본 정책의 `Remove-Item` 파일 삭제 차단은 다음으로 확인한다.

```powershell
uv run aia proof --scenario block-windows-delete
```

이 명령들은 실제 Codex 실행을 사용한다. `permissionDecision=deny`만으로
성공시키지 않고, Codex가 도구를 실행하지 않았고 부작용이 없었는지까지 확인한다.
기본 출력은 사람이 읽는 한국어 요약이며, 전체 JSON 보고서가 필요하면
`uv run aia proof --json`을 사용한다.

## 결과 확인

실행이 끝난 뒤 PowerShell에서 실행 목록을 확인한다.

```powershell
uv run aia runs
uv run aia status <SESSION_ID>
uv run aia console --open
```

결과를 해석할 때는 다음을 함께 본다.

```text
Bundle: VALID
Hook Event: 확인됨
Policy: VIOLATION 또는 COMPLIANT
Enforcement: BLOCKED / NONE / TERMINATED
Execution Result: SUCCEEDED 또는 FAILED
Recovery: RESTORED
Integrity: VERIFIED
```

`COMPLETED`만으로 보호가 검증된 것은 아니다. `COMPLETED_VERIFIED`는 실제
Session-bound Hook Event와 센서 상태, 검증된 Result Bundle이 함께 확인된
경우에만 사용한다. `COMPLETED_DEGRADED`는 실행은 끝났지만 보호 경계에
제한이 있었음을 뜻한다.
실행 중 Hook Broker가 사라져 보호 경계가 끊기면 `FAILED_DEGRADED`가 기록될 수
있습니다. 이 경우 AIA는 관리 Agent 트리 중지를 시도하지만, 종료 성공 여부는
결과의 `protection_failure_termination_result`에서 별도로 확인해야 합니다.
Live Run 화면의 `LAUNCHING`은 보호 준비가 끝난 뒤 Codex 프로세스와 Process Sensor를
등록하는 중이라는 뜻이다. 이 단계에서는 Session 상태가 아직 `READY`일 수 있으며,
Codex가 등록되고 실행 상태가 확인되면 `RUNNING`으로 전환된다.

AIA가 비정상 종료되어 이전 실행이 `ORPHANED_DEGRADED`로 남으면 같은 Workspace로
새 보호 실행을 바로 시작할 수 없다. 기록된 Agent Root가 실제로 사라진 뒤 다음
명령으로 정리 확인을 남긴다.

```powershell
uv run aia reconcile <SESSION_ID>
```

정리 확인 전에는 이전 Codex와 새 Codex가 같은 Workspace를 동시에 변경하지 않도록
새 실행이 거부된다. AIA는 살아 있는 이전 Agent를 자동으로 종료하지 않는다.

## 현재 보호 범위

현재 제품은 Windows 11, Codex CLI, AIA Protected Run, Codex 로컬 Hook 경로의
`PreToolUse`를 대상으로 한다. Hook matcher는 `*`지만 AIA가 의미를 해석하는
도구는 명시된 목록으로 제한하며, 목록 밖 도구는 `UNSUPPORTED_TOOL_PATH`로
거부한다. 모든 Codex 도구, 모든 MCP, 사용자가 직접 실행한 OS 작업, Hook을
우회한 경로까지 보호한다고 주장하지 않는다.
자세한 범위와 제한은 [PRODUCT-SUPPORT.md](PRODUCT-SUPPORT.md)와
[LIMITATIONS.md](LIMITATIONS.md)를 확인한다.
