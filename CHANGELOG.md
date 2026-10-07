# 변경 이력

이 파일은 공개 배포 버전의 사용자에게 보이는 변경 사항을 기록한다.

## [0.1.30] - 2026-10-07

### 개인용 정책과 여러 복구 지점

- 정책 네 가지와 사용자 지정을 한 줄로 표시한다. 복잡한 별도 상세보기는 제외하고 기존 설명·판정 미리보기를 유지한다. 기존 정책 파일은 변경하지 않는다.
- 사용자 지정 정책에서 대상 패턴, 행동별 허용·감사·금지, 우선순위와 기본 효과를 편집하고 엔진 검증 후 저장한다. 새 실행부터 적용된다.
- 최초 기준점을 유지하면서, app-server 작업 완료 후 조건을 충족한 자동 지점과 사용자 수동 지점을 추가한다. 변화가 없는 자동 지점은 중복 저장하지 않는다.
- 기록에서 지점을 선택하고 현재 변경을 미리 본 뒤, 실행 종료 후 복원·SHA-256 검증을 수행한다. 반복 복구 이력은 원래 결과 묶음을 수정하지 않고 별도로 남긴다.
- Windows 가디언을 독립 창으로 표시한다. 메인 앱을 최소화해도 남으며 실제 실행·센서·확인 요청 상태를 안내한다. 완전 종료하면 함께 닫힌다.
- 설정에서 가디언 크기를 작게·보통·크게로 조절한다. 열기·숨기기는 상태 안내 상자 안에 작은 버튼으로 모았다.
- 복구 지점은 저장 일관성 검증이며 코드 안전성 인증이 아니다. 세션당 최대 50개이며 외부 프로그램의 파일 쓰기는 완전히 차단하지 못한다.

## [0.1.29] - 2026-09-11

### 콘솔 중심 사용자 실행 흐름

- 로컬 콘솔에서 기존 Workspace를 선택해 보호 실행을 시작하고 Codex를 별도 Windows 터미널에서 열 수 있다.
- 실행 중 Hook·File·Process Sensor 상태와 raw payload 없는 안전한 이벤트 타임라인을 표시한다.
- 차단 사건의 정책 판정·AIA 결정·실제 실행 결과를 분리해 표시하고 Codex 세션을 유지한다.
- 콘솔에서 Strict Validation 기반 사용자 정책을 작성·검증·저장할 수 있다.
- 실행 기록에 Workspace·상태·보호 상태·차단 여부·날짜 필터를 제공한다.

## [0.1.28] - 2026-09-11

### Process Sensor 실패 보수성 보강

- 관리 대상 프로세스의 자식 트리 조회가 `AccessDenied` 또는 OS 오류로 실패하면
  이를 빈 트리나 정상 상태로 처리하지 않고 `OWNER_UNVERIFIABLE` 및 `FAILED`로 기록한다.
- 조회 실패 상황에서 Process Evidence를 생성하거나 Sensor가 `HEALTHY`라고 주장하지
  않는 결정론적 테스트를 추가했다.
- Windows 11, Python 3.13, Codex CLI 전용 제품 범위와 세 센서 계약은 유지한다.

## [0.1.27] - 2026-09-11

### 세 센서 검증과 결과 화면 보강

- 검증된 Protected Run은 `AGENT_HOOK`, `FILESYSTEM_WATCHER`, `PROCESS_RUNTIME` 세 센서가 모두 실행 중 `HEALTHY`이고 종료 후 `STOPPED`인 경우에만 `*_VERIFIED`로 표시한다.
- 센서가 누락되거나 실패하면 실행을 `*_DEGRADED`로 표시한다.
- Result와 Live Run 화면에서 센서별 상태와 Process Evidence 건수를 확인할 수 있다.

## [0.1.26] - 2026-09-11

### MVP 지원 범위 고정

- 현재 제품의 Codex PreToolUse 의미 해석 범위를 `Bash`와 `apply_patch`로 고정했다.
- MCP 서버 등록·호출과 MCP 도구 의미 해석을 제품 실행 경로에서 제거했다.
- MCP Hook 요청은 `UNSUPPORTED_TOOL_PATH`로 거부하며, 과거 MCP 실험 산출물은
  현재 지원 기능으로 재사용하지 않는다.
- Actual Codex 증명 스크립트와 지원 문서를 현재 제품 범위에 맞게 정리했다.

## [0.1.25] - 2026-09-11

### Actual Codex 제품 증명 안정화

- 현재 설치된 Hook·Codex·AIA 런타임 지문이 검증된 경우, 제품 증명 시나리오가
  매번 별도의 모델 기반 Hook Probe를 반복하지 않고 현재 설치 증명을 격리된
  실행 Control Root에서 재사용한다.
- Hook 설정이나 Codex 실행 파일이 바뀌면 기존 증명을 재사용하지 않고 정상 검증을
  다시 수행한다.
- 실제 Codex Bash, `.env`, `apply_patch`, Windows 삭제 차단과 정상 읽기 경로를
  사용자 Trust 후 제품 CLI로 재검증했다.

## [0.1.24] - 2026-09-11

### 콘솔에서 Hook 연결 검증

- 로컬 콘솔의 보호 실행 준비 화면에서 실제 Session-bound Hook 검증을 요청할 수 있다.
- 검증은 기존 `aia hook verify` 경로를 사용하며 Codex Hook Trust를 자동으로 변경하지 않는다.
- 검증 결과에 따라 준비 상태를 다시 갱신한다.

## [0.1.23] - 2026-09-11

### 실행 중 파일 관찰 표시

- 실행 중 보호 상태 화면에 File Sensor가 기록한 파일 시스템 Evidence 건수를 표시한다.
- 미완료 실행에서도 원문 payload가 아닌 안전한 메타데이터 건수만 읽는다.
- 완료된 Result Bundle은 기존 검증된 Evidence 경계를 그대로 사용한다.

## [0.1.22] - 2026-09-11

### 현재 Workspace에서 바로 시작

- `aia start`와 `aia protect`의 Workspace 인자를 생략하면 현재 디렉터리를 사용한다.
- 실행 시작 시 실제로 보호되는 Workspace 경로를 터미널에 표시한다.
- 기존 정책·Hook·보호 경계 계약은 변경하지 않는다.

## [0.1.21] - 2026-09-11

### 파일 시스템 관찰 결과 표시

- 검증된 Evidence Bundle의 안전한 메타데이터에서 File Sensor 변경 이벤트 수를 집계한다.
- CLI와 로컬 콘솔 결과 화면에 파일 변경·PreTool·PostTool Evidence 수를 표시한다.
- 원문 경로·명령·payload·비밀값은 결과 화면에 추가 저장하거나 노출하지 않는다.

## [0.1.20] - 2026-09-11

### 첫 실행 준비 상태 표시

- `aia setup --json`이 Hook 설치와 실제 보호 실행 준비 상태를 구분한다.
- `READY`, `CODEX_HOOK_TRUST_REQUIRED`, `HOOK_VERIFICATION_REQUIRED` 등
  준비 상태 코드를 제공한다.
- 일반 출력에도 보호 실행을 시작할 수 있는지와 다음 조치를 표시한다.
- Codex Hook Trust는 계속 사용자 검토·승인 경계로 유지한다.

## [0.1.19] - 2026-09-11

### 실행 기록의 검증 상태 표시

- 검증된 Result Bundle이 없는 terminal 실행을 `UNVERIFIED`로 표시한다.
- CLI와 로컬 콘솔에서 live/unverified 실행을 제품 성공 기록과 구분한다.
- 보안 판정과 Security Invariant는 변경하지 않는다.

## [0.1.18] - 2026-09-11

### 안전한 제거 절차

- 릴리스와 저장소에 `uninstall.ps1`을 추가했다.
- 기본 동작은 AIA가 설치한 Codex Hook만 제거하고, `-RemoveTool`을 명시한 경우에만
  사용자 수준 uv 도구를 제거한다.
- Protected Run 결과와 AIA Control Root는 자동으로 삭제하지 않는다.

## [0.1.17] - 2026-09-11

### Hook 온보딩 안내

- `aia hook explain` 명령을 추가해 Codex `/hooks`에서 검토할 AIA Hook의 matcher,
  command, 지원 도구, Trust 상태와 다음 검증 단계를 한 번에 확인할 수 있게 했다.
- Hook Trust나 설정을 자동 변경하지 않는 읽기 전용 온보딩 경계를 추가했다.

## [0.1.16] - 2026-09-11

### 콘솔 탐색 경로 수정

- 실행 중 화면과 결과 화면의 `새 보호 실행` 링크가 대시보드가 아닌 `/new` 실행 폼으로 이동하도록 수정
- 대시보드 기본 진입 이후에도 실행 완료 후 다음 작업을 바로 시작할 수 있도록 회귀 테스트 추가

## [0.1.15] - 2026-09-11

### 콘솔 기본 진입 화면

- 로컬 콘솔의 기본 경로(`/`)를 제품 대시보드로 변경
- 기존 보호 실행 폼을 `/new` 경로로 분리해 실행 의도를 명확히 표시
- `/dashboard` 별칭은 호환성을 위해 유지

## [0.1.14] - 2026-09-11

### 로컬 콘솔 대시보드

- `/dashboard`에 실행 가능 여부, Codex Hook Trust, 지원 범위, 최근 보호 실행을 한 화면에 표시
- 보호 실행 전에 필요한 다음 단계와 제품의 보호 경계를 콘솔에서 명시
- 기존 새 보호 실행·실행 기록 화면은 그대로 유지

## [0.1.13] - 2026-09-11

### 첫 실행 데모 경로

- `aia demo`로 실제 Workspace와 Codex를 건드리지 않는 안전한 제품 데모 추가
- `aia demo --live`로 disposable Workspace의 실제 Codex PreToolUse 증명을 선택적으로 실행
- Codex `Edit`·`Write` matcher 별칭을 canonical `apply_patch` 계약으로 명시
- 빠른 시작 문서에 첫 실행 흐름과 데모 절차 추가

## [0.1.12] - 2026-09-11

### Codex 지원 범위 정합성 보강

- 공식 입력 계약이 확인되지 않은 `Edit`·`Write`를 보호 지원 목록에서 제외
- 실제로 검증된 `Bash`, `apply_patch`, 등록된 파일 읽기 MCP만 지원 범위로 표시
- 목록 밖 도구는 기존과 같이 `UNSUPPORTED_TOOL_PATH`로 처리

## [0.1.11] - 2026-09-11

### Hook 상태 표시 정확성 보강

- `aia hook status`가 Codex가 보고한 실제 PreToolUse Trust 상태를 표시
- `TRUSTED`·`MANAGED` 상태를 `MANUAL_REVIEW_REQUIRED`로 잘못 표시하지 않음
- Trust 상태별 CLI 회귀 테스트 추가

## [0.1.10] - 2026-09-11

### 보호 실행 부트스트랩 경계 보강

- Hook 실시간 검증에 사용하는 내부 Probe 경로를 일반 Protected Run의 숨은
  우회 플래그와 분리
- 검증 명령이 발급한 일회성 Probe 권한이 없으면 검증 전용 경로도 실행하지 않음
- CLI와 로컬 콘솔이 실제 Codex Hook Trust 상태를 그대로 표시
- 0.1.9 이후의 보안 경로 변경을 새 릴리스와 배포 문서에 반영

## [0.1.9] - 2026-09-11

### 미지원 도구 우회 방지

- Codex PreToolUse/PostToolUse Hook matcher를 `*`로 설치해 로컬 Hook 경로의
  도구가 지원 목록 밖이라는 이유만으로 조용히 빠지지 않도록 함
- AIA가 의미를 해석하지 못하는 도구는 `UNSUPPORTED_TOOL_PATH`로 거부
- 해당 실행을 정상 보호 성공으로 표시하지 않고 degraded 결과와 제한사항으로 보존
- capabilities, 진단 번들, 로컬 콘솔에 Hook matcher와 의미 해석 지원 목록을 분리해 표시

## [0.1.8] - 2026-09-11

### 보호 세션 진입점

- `aia start <workspace>`를 추가해 AIA가 먼저 보호 실행을 준비하고 Codex 대화형
  세션을 연다는 사용자 흐름을 CLI 명령으로 고정
- 기존 `aia protect`와 동일한 보안 경로를 사용하며 기존 사용법과 호환
- 설치·빠른 시작 문서에 세션 우선 실행 흐름을 명시

## [0.1.7] - 2026-09-11

### 제품 범위 확인

- `aia capabilities --json`으로 현재 지원 범위와 보호 주장 경계를 조회
- 로컬 보안 콘솔의 새 보호 실행 화면에 동일한 지원 범위와 필수 사용자 단계를 표시
- 릴리스 검증에서 설치된 wheel의 capabilities 계약을 확인

## [0.1.6] - 2026-09-11

### 결과 해석 명확화

- 보호 실행 결과에 전체 행위·정책 판정·정책 효과·집행·실행 결과 집계를 표시
- `COMPLIANT / VIOLATION` 정책 판정과 `ALLOW / AUDIT / DENY` 정책 효과를 분리
- Result Bundle에 행위별 `operation_effect`를 보존해 결과 화면과 JSON의 의미를 일치
- Recovery와 Integrity 상태를 CLI와 로컬 콘솔에서 독립적으로 표시
- 릴리스 manifest·SHA-256·clean wheel 검증을 거치는 명시적 수동 롤백 경로 제공
- 12개 시나리오·780건의 결정론적 AIA OFF/AIA ON 제품 평가와 오프라인 성능 대시보드 제공

## [0.1.5] - 2026-09-11

### Workspace 재사용 안전성

- AIA가 비정상 종료된 이전 Protected Run의 Agent Root가 정리되지 않은 Workspace를
  새 Protected Run이 자동으로 재사용하지 않도록 차단
- 기록된 Agent Root가 사라진 것을 확인하고 `aia reconcile`한 뒤에만 Workspace 재사용 허용
- 고아 실행 상태와 새 실행 거부 사유를 CLI·로컬 콘솔에서 확인

## [0.1.4] - 2026-09-11

### 안정성 보강

- AIA 조정 프로세스의 PID와 생성 시각을 Protected Run 상태에 보존
- AIA 비정상 종료 뒤 이전 실행을 `ORPHANED_DEGRADED`로 명시
- 기록된 Agent Root의 PID와 생성 시각이 실제로 사라진 경우에만 `aia reconcile` 허용
- 고아 실행 정리 확인과 상태를 CLI·로컬 콘솔에서 확인

## [0.1.3] - 2026-09-11

### 운영 보강

- `aia support-bundle` 명령으로 비밀정보를 제외한 설치·Hook·최근 실행 진단 파일 생성
- 진단 번들에 전체 경로, Workspace 내용, raw evidence, tool input, 명령 출력 미포함

## [0.1.2] - 2026-09-11

### 사용성 보강

- 보호 실행 종료 시 `COMPLETED_VERIFIED`, `COMPLETED_DEGRADED`,
  `FAILED_DEGRADED`를 사람이 읽을 수 있는 결과 요약으로 표시
- Hook Event 수, Incident 수, Result Bundle 상태, Result 경로와 다음 조치를 CLI에 표시
- 보호 상태를 보안 성공으로 해석할 수 없는 경우 명시적으로 경고

## [0.1.1] - 2026-09-11

### 보강

- 보호 실행 준비 후 Codex 등록 중인 `LAUNCHING` 상태를 CLI와 로컬 콘솔에 표시
- 다른 터미널에서도 `LAUNCHING` 상태와 보호 상태를 일관되게 조회
- `LAUNCHING` 중 사용자 중지 시 검증된 Process Identity가 있는 관리 Root만 종료
- Hook Broker 손실 시 `PROTECTION_FAILURE`와 `FAILED_DEGRADED` 결과를 분리 기록
- 전체 회귀 540건과 깨끗한 wheel 설치·릴리스 번들 검증을 추가 확인

### 지원 범위

- 지원 범위와 보안 주장은 0.1.0과 동일하게 Windows 11, Codex CLI,
  지원되는 PreToolUse matcher로 제한한다.

## [0.1.0] - 2026-09-11

### 추가

- Windows 11에서 Codex CLI를 AIA Protected Run의 자식 프로세스로 실행
- `PROTECTED_DEVELOPMENT` 기본 정책과 한국어 정책 프로필
- PreToolUse 기반 정책 판정과 지원 matcher의 사전 차단
- Workspace Lease, Safe Checkpoint, File/Hook/Process Evidence
- Recovery와 SHA-256 Integrity Verification을 분리한 Result Bundle
- CLI, 로컬 보안 콘솔, `doctor`, `self-test`, `hook verify`, `proof` 명령
- wheel·source distribution·ZIP 릴리스 번들과 SHA-256 manifest
- 릴리스 설치 전 wheel SHA-256 검증과 변조 패키지 거부
- AIA 버전 업데이트 때 이전 Python 경로의 AIA Hook을 중복 없이 안전하게 교체
- Hook 지문이 남아 있어도 현재 Codex Trust가 해제되면 `aia hook status`가 READY로 표시하지 않음
- 실행 중 Hook Broker 손실 시 관리 트리 중지 시도와 `PROTECTION_FAILURE` 결과를 별도 기록
- 결정론적 제품 전후 평가와 오프라인 HTML 대시보드

### 검증된 범위

- Windows 11, Python 3.13, Codex CLI 0.154.0 환경
- Bash, `apply_patch`, Edit/Write 계열과 등록된 파일 읽기 MCP matcher
- 실제 PreToolUse deny, 부작용 없음, Evidence Bundle 검증
- 사용자 중지 시 managed process tree 종료와 unrelated process 보존

### 제한사항

- 모든 Codex 도구·MCP·외부 Agent·수동 실행을 보호한다고 주장하지 않는다.
- Hook Trust는 사용자가 Codex `/hooks`에서 직접 검토·신뢰해야 한다.
- 정책 위반에 따른 Actual Codex destructive Process 자동 집행은 정상 제품 경로의
  완료된 보장으로 주장하지 않는다.
- Network Security, Database state, ACL/ADS, 대규모 Workspace SLA는 지원 범위 밖이다.

자세한 지원 계약과 현재 재검증 결과는
[docs/releases/RELEASE-0.1.0.md](docs/releases/RELEASE-0.1.0.md)와
[docs/validation/CURRENT-REVALIDATION.md](docs/validation/CURRENT-REVALIDATION.md)를
참조한다.
