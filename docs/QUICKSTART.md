# AIA 빠른 시작

AIA는 Codex를 대신하는 프로그램이 아니다. AIA가 먼저 보호 실행을 만들고,
그 안에서 Codex를 자식 프로세스로 시작한다. 사용자는 Codex 화면이 열린 뒤
평소처럼 작업을 입력한다.

## 1. AIA Core 확인

저장소 폴더에서 실행한다.

```powershell
uv run aia self-test
```

`PASS`가 나오면 AIA의 정책·Workspace Lease·Checkpoint·Evidence 핵심 기능이
정상이다. 이 명령은 Codex를 실행하지 않는다.

## 2. Hook 설치

```powershell
uv run aia setup
```

그 다음 Codex에서 `/hooks`를 입력하고 AIA `PreToolUse` Hook의 명령과 Matcher를
검토한다. 내용을 확인한 뒤 직접 Trust한다. AIA가 대신 Trust하지 않는 이유는
사용자가 승인하지 않은 실행 경계를 AIA가 임의로 활성화하면 안 되기 때문이다.

## 3. 실제 Hook 연결 확인

```powershell
uv run aia hook verify
```

이 명령은 임시 Workspace에서 무해한 Probe를 한 번 실행한다. 성공하면
`VERIFIED`가 표시된다. `MODIFIED`, `UNTRUSTED`, `NOT_VISIBLE`이면 Probe를
실행하지 않고 Codex `/hooks`에서 검토·Trust해야 할 내용을 알려준다.

설치된 제품 경로에서 실제 Bash 사전 차단을 한 번 확인하려면 다음을 실행한다.

```powershell
uv run aia proof
```

이 명령은 disposable Workspace에서 실제 Codex를 실행하고, Canary 미생성과
`Bundle VALID`까지 확인한다. Hook Trust가 확인되지 않으면 Codex 도구를 실행하지
않고 실패 원인과 artifact 경로만 남긴다. 실제 Codex 실행을 소비하므로 일반 회귀
테스트마다 반복하지 않는다.

## 4. 보호 실행 시작

먼저 실제 프로젝트 대신 복사본이나 테스트 프로젝트를 사용한다.

```powershell
uv run aia protect "C:\workspace\my-project"
```

이 명령은 다음 순서로 동작한다.

```text
Workspace 확인
→ 정책 고정
→ Workspace Lease 준비
→ Safe Checkpoint 생성
→ File / Hook / Process Sensor 준비
→ Codex 자식 프로세스 시작
→ Codex 화면에서 작업 입력
→ Evidence와 결과 Bundle 저장
```

화면에 `Protected Codex session is active.`가 표시되면 그때 Codex 세션 안에서
작업을 입력한다. 한 번의 요청만 자동으로 전달하려면 다음처럼 `--task`를 붙인다.

```powershell
uv run aia protect "C:\workspace\my-project" --task "README.md를 읽고 한 문장으로 요약해줘"
```

웹 콘솔(`uv run aia console`)에서도 작업 시작 방식을 선택할 수 있다. 기본값인
`대화형 보호 세션`을 선택하면 AIA가 먼저 보호된 Codex 세션을 열고, 열린 Codex
화면에서 사용자가 작업을 입력한다. `한 번의 작업 실행`을 선택하면 작업 요청을
미리 입력해 보호 준비가 끝난 뒤 한 번 전달한다.

## 5. 결과 확인

`AIA Protected Run: ...` 뒤에 표시된 Session ID를 사용한다.

```powershell
uv run aia runs
uv run aia status <SESSION_ID>
uv run aia console
```

보호 실행은 `COMPLETED`만으로 충분하지 않다. `Bundle VALID`, Hook Event, 센서
상태를 함께 확인해야 한다. 차단은 AIA가 `deny` 응답을 만들었다는 사실과 Codex가
실제로 실행하지 않았다는 확인을 모두 갖춘 경우에만 `BLOCKED / SUCCEEDED`로
기록한다.

## 지원 범위

현재 첫 제품 범위는 Windows 11, Codex CLI, AIA Protected Run, 그리고 AIA가
연결한 PreToolUse matcher다. 지원 범위 밖의 도구나 Hook을 우회한 실행은 AIA가
`PROTECTED` 또는 `BLOCKED`라고 주장하지 않는다. 전체 제한사항은
[LIMITATIONS.md](LIMITATIONS.md)에서 확인한다.
