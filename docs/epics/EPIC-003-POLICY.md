# EPIC-003 정책 프로필과 결정론적 정책 판정

## 목적과 정책 철학

AIA는 무엇이 위험한지를 사용자 대신 결정하는 제품이 아니다. 사용자가 정의한
보안 경계를 Agent가 실제로 준수했는지를 결정론적으로 검증한다. 이번 EPIC의 정책
시스템은 사용자 정책을 읽고, 관찰된 행위와 등록된 Rule을 비교해 정책 결과를
산출한다.

사용자 정책은 보호할 자산·경로·명령, 읽기·생성·수정·삭제·이동·이름변경·실행
허용 여부, Rule 우선순위와 기본 효과를 정한다. 시스템 보안 불변식은 사용자
정책이 바꿀 수 없다.

- `Policy Violation alone != Kill`
- `EXACT` 외 자동 termination 금지
- PID 단독으로 Process Identity 확정 금지
- Agent Self-report를 Security Evidence로 사용 금지
- valid checkpoint 없이 Rollback 금지
- Rollback 후 Integrity Verification 필수
- 필수 Evidence 부족 시 `COMPLIANT` 금지

Enforcement, Attribution, Recovery, Integrity는 이번 EPIC에서 구현하거나 정책
판정 결과에 연결하지 않는다.

## 정책 프로필

Policy Profile은 사용자가 선택하는 정책 템플릿이고 Session Mode가 아니다.
`AUDIT`/`ENFORCE`는 보호 실행의 동작 모드이며, 예를 들어 `Session Mode = ENFORCE`
와 `Policy Profile = 기본 개발형`은 함께 사용할 수 있다.

| 내부 코드 | 한국어 표시명 | 기본 효과 | 역할 |
|---|---|---|---|
| `BASIC_DEVELOPMENT` | 기본 개발형 | `ALLOW` | 일반 개발 자유도를 유지하면서 주요 변경과 파괴 행위를 기록·금지 |
| `CONSERVATIVE_SECURITY` | 보수적 보안형 | `AUDIT` | 중요 자산 변경과 파괴 명령을 더 엄격하게 관리 |
| `FREE_DEVELOPMENT` | 자유 개발형 | `ALLOW` | 명시적 파괴 가능 행위도 기본 차단하지 않고 중요 행위를 감사 |
| `CUSTOM` | 직접 설정 | 사용자 지정 | 하나의 완전한 사용자 정책 문서를 그대로 사용 |

기본 프로필은 수정 가능한 템플릿이다. 제품 엔진에 하드코딩된 시스템 보안
정책이 아니다. `CUSTOM`은 선택한 built-in profile 위에 암묵적으로 Rule을
merge하지 않는다. UI에서 템플릿을 복사해 편집하는 경험은 후속 범위이며, 현재는
완전한 사용자 정책 JSON을 명시적으로 제공한다.

## 한국어 정책 파일과 내부 모델

사용자에게 노출되는 정책 파일은 UTF-8 한국어 JSON이다. 현재 파일은 다음 위치에
프로필별로 분리되어 있다.

- `policies/profiles/기본-개발형.ko.json`
- `policies/profiles/보수적-보안형.ko.json`
- `policies/profiles/자유-개발형.ko.json`
- `policies/profiles/직접-설정.example.ko.json`

Loader가 JSON의 한국어 표시명과 Vocabulary를 내부 영어 Enum으로 변환한다. Policy
Engine은 한국어 문자열을 직접 비교하지 않으며, 공식 Vocabulary 이외의 표현은
Validation Error로 거부한다. 예를 들어 `차단`, `위험`, `막기`는 자동으로 `DENY`로
추론하지 않는다.

Loader는 최상위 정책 Object, Rule Object, `행위효과` Object 각각의 허용 Key를
검사한다. 공식 Schema에 없는 Key는 값이 사용되지 않더라도 Validation Error로
거부한다. 따라서 `정책버젼`, `자산종류`, `우선도`, `행위효과오타` 같은 입력은
조용히 무시되지 않는다.

지원하는 자산 유형은 다음 7개다.

| 한국어 | 내부 코드 |
|---|---|
| 비밀정보 | `SECRET` |
| 데이터베이스 관련 자산 | `DATABASE_RELATED` |
| 핵심 코드 | `CRITICAL_CODE` |
| 의존성 파일 | `DEPENDENCY` |
| 인프라 설정 | `INFRASTRUCTURE` |
| 저장소 관련 자산 | `REPOSITORY` |
| 작업공간 | `WORKSPACE` |

행위는 `READ`, `CREATE`, `MODIFY`, `DELETE`, `MOVE`, `RENAME`, `EXECUTE`이고,
정책 효과는 다음 세 가지다.

- `ALLOW` / 허용
- `AUDIT` / 기록
- `DENY` / 금지

`AUDIT != VIOLATION`이다. `AUDIT`는 `COMPLIANT`이면서 감사 기록을 남긴다.
`DENY`는 `VIOLATION`을 만들지만 `DENY != KILL`이며 실제 Enforcement 조치를
수행하지 않는다.

내부 Domain Model은 `PolicyProfile`, `SecurityAssetType`, `Operation`,
`PolicyEffect`, `PolicyDecision`, `PolicyRule`, `SecurityAssetPolicy`,
`PolicySubject`, `PolicyEvaluation`, `ResolvedPolicy`로 구성된다. Rule은 ID,
priority, asset type, path/command pattern, operation별 effect를 가진다. 모델은
가능한 범위에서 불변으로 유지하며, 중복 Rule ID와 잘못된 값은 거부한다.

하나의 Rule은 정확히 하나의 target만 가진다. File Rule은 `path_patterns`와 파일
Operation을 사용하고, Command Rule은 `command_patterns`와 `EXECUTE`만 사용한다.
두 target이 동시에 있거나 어느 target도 없으면 거부한다. 사용자가 일부 Operation만
정의하는 것은 허용한다.

## 프로필별 기본 정책

### 기본 개발형

기본 효과는 `ALLOW`다.

- `.env`: 읽기 허용, 생성·수정·이동·이름변경 기록, 삭제 금지
- `pyproject.toml`, `uv.lock`, `requirements*.txt`, `package.json`, lock 파일:
  읽기 허용, 생성·수정·이동·이름변경 기록, 삭제 금지
- `Dockerfile`, `docker-compose*.yml/yaml`, `*.tf`: 읽기 허용, 생성·수정·이동·
  이름변경 기록, 삭제 금지
- `DROP DATABASE`, `DROP TABLE`, `TRUNCATE`: 실행 금지
- `alembic downgrade`: 실행 기록
- `git reset --hard`, `git clean -fd`: 실행 기록
- `git clean -fdx`: 실행 금지

핵심 코드 경로는 자동 추론하지 않는다. 대량 삭제·수정 패턴도 구현하지 않는다.

### 보수적 보안형

기본 효과는 `AUDIT`다.

- `.env`: 읽기 기록, 생성·수정·삭제·이동·이름변경 금지
- 의존성 파일과 인프라 설정: 읽기 허용, 생성·수정·이동·이름변경 기록, 삭제 금지
- `DROP DATABASE`, `DROP TABLE`, `TRUNCATE`, `alembic downgrade`: 실행 금지
- `git reset --hard`, `git clean -fd`, `git clean -fdx`: 실행 금지

사용자가 핵심 코드 경로를 지정한 경우에만 해당 경로 Rule을 사용할 수 있다.

### 자유 개발형

기본 효과는 `ALLOW`이며 기본 `DENY` Rule을 두지 않는다.

- `.env`: 읽기·생성 허용, 수정·삭제·이동·이름변경 기록
- 의존성 파일과 인프라 설정: 읽기·생성·수정·이동·이름변경 허용, 삭제 기록
- 데이터베이스 관련 명령과 저장소 관련 명령: 실행 기록

자유 개발형도 AIA 시스템 보안 불변식은 변경하지 않는다.

### 직접 설정

직접 설정은 사용자가 기본 효과, 자산 유형, Path Pattern, Command Pattern,
Operation, Effect, Priority를 모두 선택하는 완전한 정책 문서다. 예제에서는
`DROP TABLE`과 `.env` 삭제를 허용하고, `git reset --hard`를 금지하는 등 built-in
profile과 다른 조합을 표현한다. 특정 Asset Type을 Rule에서 생략하는 것도
유효하다. 생략된 행위는 사용자가 지정한 `기본효과`를 따른다.

## Profile Resolution

`ProfileResolver`는 선택한 프로필을 다음과 같이 하나의 `ResolvedPolicy`로 바꾼다.

- 세 built-in profile은 해당 한국어 JSON을 로드한다.
- `CUSTOM`은 명시적인 사용자 JSON 또는 mapping이 필요하다.
- `CUSTOM`에 정책이 없으면 실패하며 built-in profile로 fallback하지 않는다.
- 반환 결과에는 `profile`, `policy_id`, `policy_version`, `source`, `policy`가
  포함되어 어떤 문서가 사용됐는지 추적할 수 있다.
- 실제 Session Active Policy Freeze는 후속 Lifecycle EPIC의 책임이다.

## Path Rule

MVP 공식 환경은 Windows 11이며 Policy Engine은 workspace-relative canonical path를
받는다고 가정한다. 이 계층은 filesystem resolve, symlink, junction을 검증하지
않는다. 그 책임은 후속 Workspace/Normalization 계층에 있다.

비교 전에 경로의 `\\`를 `/`로 바꾸고, 연속 separator와 `.` segment를 정리하고,
case-insensitive 비교를 수행한다. 따라서 `SRC\\AUTH\\LOGIN.PY`와
`src/auth/login.py`는 같은 입력으로 처리된다. Rule에 등록되지 않은 다른 경로는
해당 Rule과 match하지 않으며 기본 효과를 사용한다.

Target이 일치해도 현재 Operation의 Effect가 Rule에 없으면 그 Rule은 현재 Action의
매칭 Rule에서 제외한다. 다른 적용 Rule이 없으면 `default_effect`를 사용한다.

파일 행위에 path evidence가 없으면 정책 효과를 추측하지 않고
`INDETERMINATE`를 반환한다.

## Command Rule

데이터베이스와 저장소 명령도 다른 자산과 같은 사용자 정책 Rule이다. Command
Evaluation은 다음 네 사실만 사용한다.

`Raw Command → case normalization → 연속 공백 정리 → 앞뒤 공백 제거 → lexical pattern match`

원본 명령은 `PolicyEvaluation.raw_command`에 보존한다. 등록된 `DROP TABLE` 문자열이
관찰됐다는 사실은 표현할 수 있지만, 그 명령이 실제로 Table을 삭제했는지나 DB
상태가 어떻게 됐는지는 주장하지 않는다. `python reset_db.py`를 보고 DB 삭제나
초기화를 추론하지 않는다. EXECUTE에 raw command evidence가 없으면
`INDETERMINATE`다.

프로필 JSON은 Resolver가 한 번 검증·변환해 immutable `ResolvedPolicy`를 만든 뒤
평가에 사용한다. Evaluation 단계에서 원본 JSON을 다시 읽지 않는다. Session Active
Policy Freeze와 외부 Trusted Storage는 후속 EPIC의 책임이다.

## Priority와 Conflict

여러 Rule이 match하면 숫자가 가장 큰 priority를 사용한다. 같은 최고 priority의
Rule들이 같은 effect이면 그 effect를 사용하고 모든 `matched_rule_ids`를 보존한다.
같은 최고 priority에서 effect가 충돌하면 임의로 `DENY wins` 또는 `ALLOW wins`를
선택하지 않고 다음 결과를 반환한다.

- `policy_decision = INDETERMINATE`
- `reason = POLICY_CONFLICT`
- 충돌한 최고 priority Rule ID 보존

## Policy와 Attribution의 차이

Policy Engine은 “관찰된 행위가 현재 정책을 위반했는가?”만 판단한다. Attribution은
별도 책임으로 “그 행위를 Agent에게 어느 수준까지 귀속할 수 있는가?”를 판단한다.
따라서 Attribution 정보가 없거나 낮다는 이유로 충분히 관찰된 정책 위반을
`COMPLIANT`로 낮추지 않는다. 이번 EPIC의 Policy Engine에는 Attribution이나
Enforcement 입력이 없다.

필수 Evidence가 부족한 경우에만 `INDETERMINATE`가 가능하다. 이 EPIC은
`INDETERMINATE`를 사용자 검토 대상으로 남기며, 실제 차단·종료·복구를 수행하지
않는다.

## 범위 밖 책임

Codex 실행, Agent Adapter, Hook, Runtime Evidence Collector, 전체 Canonical Action
Pipeline, Attribution, Enforcement Gate, Process Kill, Checkpoint, Recovery,
Integrity, API, GUI, Claude, Network Security, Intent/Risk, AI 기반 정책 생성·자산
분류, 대량 삭제·수정 Rule, Profile 자동 추천은 구현하지 않는다.
