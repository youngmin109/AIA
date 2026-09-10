# AIA 제품 지원 범위

현재 AIA는 모든 운영체제와 모든 Agent를 감시하는 범용 보안 제품이 아니다.
제품의 첫 지원 계약은 다음과 같이 고정한다.

```text
운영체제: Windows 11
Agent: Codex CLI
실행 방식: AIA Protected Run 안에서 시작한 Codex
정책 관문: Codex PreToolUse command Hook
지원 matcher: Bash, apply_patch, Edit, Write,
`mcp__filesystem__read_file`, `mcp__fs__read`
실행 확인: 선택적 Codex PostToolUse evidence
Control Root: Workspace 밖의 사용자별 AIA control directory
```

## 시작하기

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -SkipDoctor
uv run aia hook install
uv run aia policy validate C:\workspace\policies\protected-policy.json
```

설치 직후 Codex를 실행하지 않고 AIA Core만 점검하려면 다음을 사용한다.

```powershell
uv run aia self-test
```

이 점검은 임시 Workspace에서 정책 프로필, Active Policy Freeze, Workspace Lease,
Safe Checkpoint, Raw Evidence Seal을 확인하고 임시 산출물을 삭제한다. `PASS`는
Core 정상 상태를 뜻하며, 실제 Codex Hook 연결 증명은 포함하지 않는다.

처음 `aia doctor`에서 `hook_verification`이 실패하는 것은 정상이다. Codex에서
Hook을 검토·신뢰한 뒤 `uv run aia hook verify`를 실행해 실제 연결을 확인해야
`aia protect`를 시작할 수 있다.

정책을 새로 만들 때는 기본 프로필을 복사한 뒤 수정합니다.

```powershell
uv run aia policy profiles
uv run aia policy init C:\workspace\policies\my-policy.json --profile CONSERVATIVE_SECURITY
uv run aia policy validate C:\workspace\policies\my-policy.json
```

`aia hook install`은 정책 관문인 PreToolUse와 실행 확인용 PostToolUse Hook을
함께 설치한다. 기존 PreToolUse만 설치된 설정도 보호 실행은 계속 사용할 수 있지만,
PostToolUse가 없으면 실제 도구 실행 여부를 확인하는 증거가 줄어든다.

설치 상태와 실제 실행 활성화 상태는 별도로 확인한다.

```powershell
uv run aia hook status
```

`PreToolUse 설치: YES`는 Hook 설정이 존재한다는 뜻이다. `CURRENTLY_VERIFIED`는
현재 Hook 설정과 Codex 실행 파일에 연결된 실제 Session-bound Hook Event 검증이
유효하다는 뜻이다. `OBSERVED_IN_PAST`는 과거 실행에서만 관찰된 상태이므로
`aia hook verify`를 다시 실행해야 한다. 설치만 되어 있거나 `NOT_OBSERVED`이면
해당 실행을 보호 성공으로 해석하지 않는다.

`aia hook status`의 `현재 검증 증명: CURRENT`는 현재 Hook 설정, Codex 실행 파일,
Codex 설정 파일, AIA Hook 런타임 코드 지문이 모두 일치하는 실제 Probe 검증이
남아 있다는 뜻이다.
`MISSING_OR_STALE`이면
`uv run aia hook verify`를 다시 실행해야 한다.

검증 명령은 먼저 Codex PreToolUse Trust를 확인한다. `MODIFIED`, `UNTRUSTED` 또는
`NOT_VISIBLE`이면 임시 Probe를 실행하지 않고 즉시 종료하며, AIA Hook을 자동으로
신뢰하지 않는다. Codex `/hooks`에서 Hook을 직접 검토·신뢰한 뒤 다시 검증해야 한다.

같은 명령의 `Codex 실제 Trust`는 Codex가 현재 읽은 AIA Hook의 신뢰 상태다.
`TRUSTED`가 아닌 `MODIFIED` 또는 `UNTRUSTED`가 보이면 Hook 파일이 설치되어
있어도 Codex가 실행하지 않는다. AIA는 이 상태를 자동으로 신뢰 처리하지 않으며,
Codex `/hooks`에서 내용을 검토한 뒤 사용자가 직접 Trust해야 한다.

처음 사용하거나 Hook 설정을 변경한 뒤에는 다음 명령으로 실제 Codex 연결을
확인한다.

```powershell
uv run aia hook verify
```

이 명령은 임시 Workspace에서 무해한 Probe를 실행하고, Session-bound Hook Event와
유효한 Result Bundle을 확인한다. Probe Workspace는 검증 뒤 삭제되며, 검증 결과
Bundle은 Control Root에 남는다. `NOT_VERIFIED`이면 사용자는 Codex `/hooks`에서
AIA Hook을 검토·신뢰한 뒤 다시 검증해야 한다. `CODEX_EXECUTION_POLICY_DOWNGRADED`가
나오면 현재 Codex 실행 환경이 AIA가 요청한 sandbox 또는 approval 설정을 적용하지
않은 상태이므로, 보호 실행을 시작하지 않고 실행 환경을 먼저 고쳐야 한다.
Probe 파일이 생성됐지만 Hook Event가 0건이면 Probe가 실행된 것일 뿐 AIA 보호가
증명된 것이 아니다. 이 경우 AIA는 `PROTECTION_NOT_PROVEN`으로 표시하고 보호 실행을
성공으로 인정하지 않는다.

비대화형 Protected Run은 현재 Codex CLI가 제공하는 `--approve-for-me` 경로를 통해
`workspace-write`와 `on-request` 실행 정책을 요청한다. Result Bundle의 실제 실행
정책이 이 요청과 다르면 AIA는 실행을 성공한 보호 실행으로 포장하지 않고
`COMPLETED_DEGRADED`로 기록한다.

AIA를 제거하거나 Hook 설정을 되돌릴 때는 다음 명령을 사용한다. AIA가 추가한
Handler만 제거하고 다른 사용자 Hook은 보존한다.

```powershell
uv run aia hook uninstall
```

Codex의 `/hooks` 화면에서 AIA Hook을 직접 검토하고 신뢰한 다음 보호 실행을
시작한다.

```powershell
uv run aia protect C:\workspace\my-project
```

실행 중 사용자가 중지해야 하면 별도 터미널이나 웹 콘솔에서 중지 요청을 보낼 수 있다.

```powershell
uv run aia stop <SESSION_ID>
```

이 동작은 정책 위반 집행과 구분되는 `USER_ABORT`다. AIA는 등록된 Agent Root와
검증된 자식 프로세스만 대상으로 종료를 시도하고, 종료를 확인하지 못하면 성공으로
표시하지 않는다. Result Bundle에는 정책 집행용 `process_termination_result`와
분리된 `user_abort_termination_result`가 저장되며, 여기의 `status=SUCCEEDED`와
`verified_tree_gone=true`가 함께 있어야 실제 종료 성공으로 해석한다.

`aia status`는 보호 실행을 시작한 터미널과 다른 터미널에서 실행해도 Control Root의
실행 상태 스냅샷을 읽을 수 있다. 완료된 실행은 검증된 Result Bundle이 최종 권위이며,
실행 중인 세션은 비밀값이나 raw command를 포함하지 않는 상태 정보만 외부 조회에
제공한다.

명령을 한 번만 전달하려면 다음처럼 실행한다.

```powershell
uv run aia protect C:\workspace\my-project --task "테스트를 실행하고 변경 결과를 설명해줘"
```

첫 실행은 실제 Workspace 대신 복사본 또는 disposable Workspace에서 수행한다.

## 보호 상태 해석

| 상태 | 의미 |
|---|---|
| `PREPARING` | 정책, Lease, Checkpoint, Sensor를 준비하는 중 |
| `READY_UNVERIFIED` | 준비는 끝났지만 검증된 Hook Event가 아직 없음 |
| `ACTIVE_UNVERIFIED` | Codex는 실행 중이나 Hook 계보가 아직 확인되지 않음 |
| `ACTIVE_VERIFIED` | AIA Session에 연결된 실제 Hook Event를 확인함 |
| `DEGRADED` | 보호 경계 또는 Hook 처리에 오류가 발생함 |
| `COMPLETED_VERIFIED` | 실행과 결과 Bundle이 종료됐고 보호 경계 오류가 없음 |
| `COMPLETED_DEGRADED` | 실행은 끝났지만 보호 경계 오류가 있어 제한적으로 해석해야 함 |
| `ABORTED_VERIFIED` | 사용자가 중지했고 실행된 Agent의 Hook·센서 경계가 검증됨 |
| `ABORTED_DEGRADED` | 중지됐지만 보호 경계 검증이 충분하지 않음 |
| `ABORTED_BEFORE_LAUNCH` | Agent를 실행하기 전에 사용자가 취소함 |

`ACTIVE_UNVERIFIED`와 `DEGRADED`는 완전한 보호 성공으로 해석하지 않는다.
지원되지 않는 도구 경로, Hook 비활성화, 외부 Agent, 사용자의 수동 실행은 AIA가
`PROTECTED` 또는 `BLOCKED`로 주장하는 범위에 포함되지 않는다.

## AIA가 현재 증명하는 것

- 보호 실행 시작 전에 Workspace, 정책, Lease, Checkpoint를 준비한다.
- Protected Launcher는 바깥 Codex의 일시적 Session ID·권한 Profile을 자식 실행에
  전달하지 않고, 제품이 요청한 Sandbox·Approval 설정과 실제 Codex 시작 메타데이터를
  비교할 수 있게 한다.
- Active Policy를 하나의 Protected Run에 고정한다.
- 지원되는 Codex PreToolUse 입력을 AIA Hook Evidence로 보존한다.
- 명시적으로 등록된 파일 읽기 MCP 이름은 `READ`로 정규화하며, 실제 MCP 서버
  시작·호출부터 PreToolUse 차단까지의 경로를 `mcp-read` Canary로 검증했다.
- 정책 위반에 대해 Codex `permissionDecision=deny`를 반환한다.
- 실제 도구 실행 중단과 부작용 부재가 확인된 경우에만 `BLOCKED / SUCCEEDED`를 기록한다.
- 보호 실행 화면은 실행 중에도 검증된 Hook Action의 요약과 Incident를 갱신하며,
  원문 command나 민감한 payload를 화면으로 내보내지 않는다.
- 검증된 PreTool deny 이후에도 동일 Tool의 `PostToolUse`가 확인되면, 원래
  `PRE_ACTION` 차단 결과와 별도의 `POST_ACTION` Gate를 생성한다. 이때만
  Process Manager에 보상적 종료를 요청하며, 실제 종료 결과가 확인된 경우에만
  `TERMINATED / SUCCEEDED`를 기록한다.
- Session, Evidence, Result Bundle을 별도로 저장하고 Bundle 무결성을 검증한다.
- Recovery `RESTORED`와 Integrity `VERIFIED`를 독립적으로 표시한다.
- 독립 Windows Process Manager smoke에서 등록된 프로세스 트리만 종료하고
  unrelated process를 `LIVE_MATCH`로 보존한다.
- 실제 Codex 사용자 중지 경로에서 등록된 Agent Root → Child → Grandchild만
  종료하고 unrelated 프로세스를 보존하며, `user_abort_termination_result`의
  `SUCCEEDED + verified_tree_gone=true`를 Result Bundle에 기록한다. 이 동작은
  정책 위반 자동 집행과 별도인 사용자 세션 제어다.

## 현재 주장하지 않는 것

- 모든 Codex 도구와 MCP 경로의 보편적 차단
- 이름이 등록되지 않은 MCP 도구를 파일 읽기·쓰기라고 추측하는 것
- Hook 장애가 발생해도 모든 경로가 OS 수준에서 fail-closed라는 보장
- `PROCESS` Evidence만으로 정확한 파일 Writer를 증명하는 것
- 모든 OS 프로세스의 종료 또는 사용자의 수동 작업 통제
- Process Sensor 관찰만으로 자동 종료하는 것. Process termination은 검증된
  Gate와 AIA가 등록한 Agent Root가 함께 확인된 경우에만 시도한다.
- Network와 Database 상태 보안
- 정책 위반에 따른 Actual Codex destructive Process Tree 자동 집행이 성공했다는
  주장. 사용자 중지에 따른 실제 트리 종료 증명과 정책 위반 자동 집행은 서로 다른
  계약이다.
- 등록되지 않은 MCP 도구와 지원 범위 밖 MCP 서버의 보편적 보호
- 대규모 Workspace에 대한 성능 SLA
- 실행 환경이 제품이 요청한 Sandbox보다 약한 경우의 완전한 보호 보장. 이 경우
  Result Bundle은 `COMPLETED_DEGRADED`로 남으며 실행을 검증된 보호 성공으로
  해석하지 않는다.

자세한 제한사항과 평가 결과는 [LIMITATIONS.md](LIMITATIONS.md),
[CLAIM-MATRIX.md](validation/CLAIM-MATRIX.md),
[ACTUAL-CODEX-PROOF.md](ACTUAL-CODEX-PROOF.md)를 함께 확인한다.
