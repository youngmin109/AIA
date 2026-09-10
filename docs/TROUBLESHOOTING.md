# AIA 문제 해결

## `workspace must be an existing directory`

AIA는 입력한 Workspace를 자동으로 만들지 않는다. 사용자가 이미 존재하는
프로젝트 폴더를 선택해야 한다.

```powershell
New-Item -ItemType Directory -Force "C:\workspace\my-project"
uv run aia protect "C:\workspace\my-project"
```

실제 프로젝트를 보호하기 전에는 복사본이나 disposable Workspace로 확인한다.

## `CODEX_HOOK_TRUST_REQUIRED`

Hook 파일은 설치됐지만 Codex가 AIA `PreToolUse` Hook을 아직 Trust하지 않은
상태다. Codex 화면에서:

```text
/hooks
→ AIA PreToolUse Hook 선택
→ 명령과 Matcher 검토
→ Trust
```

그 후 다시 실행한다.

```powershell
uv run aia hook verify
```

AIA는 이 Trust를 자동으로 처리하지 않는다. `aia hook verify`가 이 상태에서
멈추는 대신 Probe를 시작하지 않고 즉시 안내하는 것이 정상 동작이다.

## `CODEX_PRETOOL_HOOK_NOT_VISIBLE`

Codex의 현재 Hook 목록에서 AIA PreToolUse Hook을 찾지 못한 상태다. 다음을
확인한다.

```powershell
uv run aia hook install
```

그 다음 Codex `/hooks`를 다시 열어 AIA Hook이 보이는지 확인하고 Trust한다.

## `aia hook verify`가 `NOT_VERIFIED`인 경우

`NOT_VERIFIED`는 AIA가 보호를 증명하지 못했다는 뜻이다. 특히 다음 결과는
성공으로 해석하지 않는다.

- Hook Event가 0건
- Probe 파일은 생성됐지만 Hook이 관찰되지 않음
- Codex 실행 정책이 `read-only` 또는 `approval=never`로 강등됨
- Result Bundle이 `VALID`가 아님

```powershell
uv run aia doctor
uv run aia hook status
```

두 명령의 `codex_hook_trust`, `hook_verification`, `activation_status`를 함께
확인한다.

## 실행 화면이 `READY`에서 오래 멈추는 경우

정상 준비에는 Workspace 검사, 정책 고정, Lease, Checkpoint, 센서 검사가
포함된다. 잠시 기다린 뒤 다른 PowerShell에서 상태를 확인한다.

```powershell
uv run aia runs
uv run aia status <SESSION_ID>
```

오류가 표시되면 실행 중인 명령을 `Ctrl+C`로 중지하고, 결과가 `FAILED` 또는
`ABORTED`로 정리됐는지 확인한다. 동일 Workspace에 남은 Lease가 있으면 이전
실행이 아직 끝나지 않았거나 종료 정리가 실패한 것일 수 있다.

## `aia` 명령을 찾지 못하는 경우

저장소에서 실행할 때는 다음처럼 `uv run`을 붙인다.

```powershell
cd "C:\workspace\01_projects\aia-mvp"
uv run aia self-test
```

릴리스 wheel을 사용자 명령으로 설치한 경우에는 새 PowerShell 창을 열거나
사용자 PATH를 갱신한 뒤 `aia --version`을 실행한다.

## `self-test`는 통과했지만 보호 실행이 시작되지 않는 경우

`self-test`는 AIA Core만 확인한다. 실제 Codex 보호를 증명하지 않으므로 다음
두 단계를 별도로 통과해야 한다.

```powershell
uv run aia hook verify
uv run aia doctor
```

`VERIFIED`와 `READY`가 확인된 뒤에만 `aia protect`를 실행한다.
