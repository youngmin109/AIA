# AIA Protected Run 사용자 가이드

## 이 문서의 목적

이 문서는 AIA를 처음 실행하는 사용자가 보호 세션을 시작하고, Hook·File·Process Sensor의 결과를 확인하고, 시연용 결과와 실제 Codex 결과를 구분하도록 돕는다. AIA는 사용자가 이미 만든 Workspace만 보호한다. Workspace를 자동으로 만들지 않는다.

## 1. 먼저 확인할 것

Windows 11, Python 3.13, `uv`, Codex CLI가 준비된 저장소에서 PowerShell을 연다.

```powershell
cd C:\workspace\01_projects\aia-mvp
uv sync
uv run --isolated --project . python -m aia.cli doctor
```

Windows 애플리케이션 제어 정책이 `uv run aia` 실행 파일을 차단하면 콘솔 스크립트 대신 위의 `python -m aia.cli` 형식을 사용한다.

## 2. Hook을 준비하고 확인하기

처음 한 번 설정을 설치한다.

```powershell
uv run --isolated --project . python -m aia.cli setup
```

Codex에서 `/hooks`를 열어 AIA PreToolUse Hook을 검토하고 Trust한다. Trust는 사용자가 직접 확인하는 단계다. 그다음 실제 임시 Probe를 사용한 검증을 실행한다.

```powershell
uv run --isolated --project . python -m aia.cli hook verify
uv run --isolated --project . python -m aia.cli doctor
```

`VERIFIED`, `PROTECTION_PROVEN`, `SESSION_BOUND_HOOK_EVENT_OBSERVED`가 확인되고 `doctor`가 `READY`를 표시해야 실제 Protected Run을 검토할 수 있다.

## 3. 실제 Workspace에서 보호 세션 시작하기

먼저 사용자가 만든 프로젝트 폴더를 선택한다. 예를 들어 `C:\workspace\my-project`가 이미 존재해야 한다.

```powershell
uv run --isolated --project . python -m aia.cli protect C:\workspace\my-project
```

AIA는 정책, Workspace Lease, Checkpoint, Hook·File·Process Sensor를 준비한 뒤 Codex CLI를 실행한다. Codex 세션이 열린 다음 그 안에서 작업을 입력한다. 보호 세션을 시작하는 명령과 Codex에게 실제 작업을 전달하는 단계는 분리되어 있다.

사용자가 중지하면 AIA는 결과를 확정한다. 다음 명령으로 실행 기록을 볼 수 있다.

```powershell
uv run --isolated --project . python -m aia.cli runs
uv run --isolated --project . python -m aia.cli status <SESSION_ID> --json
```

## 4. 브라우저 콘솔에서 확인하기

```powershell
uv run --isolated --project . python -m aia.cli console --open
```

콘솔은 `127.0.0.1`에서만 열리는 로컬 화면이다. 새 보호 실행 화면에서는 이미 존재하는 Workspace를 입력하고 정책과 모드를 선택한다. Workbench 화면에서는 Codex 작업창과 센서 상태를 함께 볼 수 있다.

표시되는 센서 의미는 다음과 같다.

| 센서 | 관찰하는 사실 | 담당하지 않는 일 |
|---|---|---|
| Hook Sensor | Codex PreToolUse 요청과 Hook 상태 | 임의의 OS 프로세스 종료 |
| File Sensor | Workspace 파일 변화 | 파일 변화 자체의 자동 rollback |
| Process Sensor | AIA가 관리하는 프로세스 트리와 종료 | 모든 Windows 프로세스 감시 |

차단 사건에서 `BLOCKED / SUCCEEDED`를 보려면 AIA의 집행 성공과 실제 도구가 실행되지 않았다는 확인이 모두 있어야 한다. Hook deny만으로 side effect가 없다고 단정하지 않는다.

## 5. 시연용 더미 데이터

발표나 제품 설명을 위해 실제 프로젝트를 건드리지 않는 세 가지 결과를 만들 수 있다.

```powershell
uv run --isolated --project . python -m aia.cli demo `
  --scenario process-kill `
  --workspace C:\workspace\aia-demo-fixture `
  --control-root C:\workspace\aia-demo-control-fixture `
  --open
```

`--open`을 붙이면 해당 Demo Session의 Workbench 화면이 바로 열린다. 직접 열려면 다음처럼 Control Root를 지정해 콘솔을 연다.

```powershell
$env:AIA_CONTROL_ROOT = 'C:\workspace\aia-demo-control-fixture'
uv run --isolated --project . python -m aia.cli console --open
```

시나리오를 바꾸려면 `process-kill`, `hook-block`, `file-rollback` 중 하나를 지정한다.

- `process-kill`: 관리 대상 Process Tree 관찰과 `TERMINATED` 결과를 표시한다. unrelated 프로세스 영향은 `False`로 기록된다.
- `hook-block`: PreToolUse 단계의 `BLOCKED` 결과를 표시한다. Process 종료를 주장하지 않는다.
- `file-rollback`: File Sensor 관찰 뒤 `RESTORED`와 `VERIFIED`가 분리되어 표시된다.

이 결과의 `run_classification`은 `ENGINEERING_FIXTURE`다. 따라서 발표할 때는 “제품 화면과 Result Bundle 흐름을 재현한 결정론적 시연 데이터”라고 설명하고, Actual Codex 실행 증명이라고 말하지 않는다.

## 6. Actual Codex 차단 검증

Hook Trust를 완료한 뒤 별도 disposable Workspace에서 실제 Hook 경로를 검증한다.

```powershell
uv run --isolated --project . python -m aia.cli hook verify
uv run --isolated --project . python -m aia.cli demo --live --scenario block-canary
```

Actual Codex 결과에 구조화된 READ 또는 파괴적 PROCESS 경로가 남지 않으면 PASS로 바꾸지 않고 제한사항으로 기록한다.

## 7. 정량 평가 실행

결정론적 Fixture 비교는 기본 30회다.

```powershell
uv sync --group evaluation
uv run --isolated --project . python scripts/product_evaluation/run_fixture_evaluation.py `
  --output-root evaluation/product-before-after/fixture-local `
  --evaluation-id fixture-local `
  --repetitions 30
uv run --isolated --project . --group evaluation python scripts/product_evaluation/build_report.py `
  --input evaluation/product-before-after/fixture-local/raw-runs.jsonl `
  --output evaluation/product-before-after/fixture-local/report.html
```

`report.html`은 외부 인터넷 없이 열 수 있다. 성능 표에는 전체 작업, 보호 준비, Checkpoint, PreTool 판단, Recovery, Integrity, 결과 확정의 최소값·중앙값·P95·최대값이 표시된다. 센서 표에는 Hook·File·Process 센서 성공률과 각 `N`이 표시된다.

AIA OFF에서 센서를 실행하지 않는 항목은 `0%`가 아니라 “미측정”이다. Fixture 센서 수치는 합성 Evidence 경로를 기준으로 하며 Actual Codex 센서 성공률과 분리한다.

## 8. 결과를 읽는 순서

1. `Bundle: VALID` 또는 결과 화면의 `Evidence Bundle VALID`를 확인한다.
2. `run_classification`이 `ENGINEERING_FIXTURE`인지 `PRODUCT_PROTECTED_RUN`인지 확인한다.
3. Hook·File·Process Sensor의 건강 상태와 Evidence 수를 확인한다.
4. 정책 판정과 실제 집행 결과를 분리해 읽는다.
5. Process 종료 결과의 unrelated 영향 여부를 확인한다.
6. Recovery와 Integrity를 각각 확인한다.
7. `limitations`를 읽고, 확인되지 않은 경로를 성공으로 해석하지 않는다.

## 9. 문제 해결

`doctor`가 `NOT_READY`이면 다음 순서로 확인한다.

```powershell
uv run --isolated --project . python -m aia.cli hook explain
uv run --isolated --project . python -m aia.cli setup
```

그다음 Codex `/hooks`에서 AIA Hook을 검토·Trust하고 `hook verify`를 다시 실행한다. `aia.exe`가 애플리케이션 제어 정책으로 차단되면 `uv run --isolated --project . python -m aia.cli` 형식을 계속 사용한다.

지원 범위 밖 Agent나 도구를 AIA가 자동으로 보호한다고 가정하지 않는다. 문제가 재현되면 raw evidence나 Workspace 내용을 공개 저장소에 올리지 말고, 비밀정보가 제외된 지원 번들을 사용한다.
