# EPIC-013 — Runtime Policy Evaluation

## 목적

이번 EPIC은 EPIC-011의 `NormalizedAction`을 EPIC-004에서 Session에 고정한
`ActivePolicySnapshot`에 결정론적으로 적용한다.

```text
NormalizedAction
        ↓
RuntimePolicyEvaluator
        ↓
기존 SecurityAssetPolicy / Policy Engine
        ↓
RuntimePolicyEvaluation
```

Policy는 관찰된 Canonical Action이 사용자가 정의한 보안 정책을 준수했는지만
판정한다. Agent 귀속은 Attribution의 책임이고, 실제 차단·거부·종료는 후속
Enforcement Gate의 책임이다.

## Runtime Policy Domain

새로운 Decision이나 Effect Enum을 만들지 않았다. 다음 EPIC-003 Domain을
그대로 사용한다.

- `Operation`
- `PolicyDecision`: `COMPLIANT`, `VIOLATION`, `INDETERMINATE`
- `PolicyEffect`: `ALLOW`, `AUDIT`, `DENY`
- `PolicySubject`
- `PolicyEvaluation`
- `ResolvedPolicy`
- `SecurityAssetPolicy`

Runtime 전용 객체는 Action 상관관계와 Active Policy Authority metadata를
보존하기 위한 immutable wrapper다.

## Active Policy Authority

`RuntimePolicyEvaluator`는 `ActivePolicySnapshot` 또는
`ProtectionPreparationContext`에서 얻은 snapshot만 받는다. 원본 한국어 JSON,
Profile source, 다른 `ResolvedPolicy`를 평가 시점에 다시 읽지 않는다.

각 결과에는 다음이 남는다.

- `policy_id`
- `policy_version`
- `policy_profile`
- `active_policy_fingerprint`
- `action_id`
- `aia_session_id`

Evaluator 생성 시 snapshot의 Session ID, policy ID, policy version, profile 및
fingerprint가 snapshot 내부의 동결 정책과 일치하는지 확인한다. Action의
Session ID가 다르면 다른 Session의 정책으로 평가하지 않고
`INDETERMINATE / POLICY_SESSION_MISMATCH`를 반환한다.

자산 유형은 현재 `NormalizedAction`에 포함된 기계적 사실이 아니다. Runtime
caller가 자산 유형을 지정하거나 기본값을 주입하지 않는다. Adapter가 Frozen
Policy의 각 Rule이 선언한 asset type으로 후보 Subject를 기계적으로 만들고
`operation + canonical path/raw command`를 Rule에 적용한다. 최종 결과의
`asset_type`은 우선순위가 결정된 matched Rule에서만 나온다. 매칭 Rule이
없으면 Policy의 `default_effect`를 사용하고 결과 asset type은 `None`으로
남긴다.

## Action → PolicySubject

File Action은 `canonical_path`를 그대로 Policy Subject의 `path`로 사용한다.
Raw Evidence path를 Policy 계층에서 다시 해석하거나 파일시스템을 resolve하지
않는다.

```text
NormalizedAction
  operation = DELETE
  canonical_path = ".env"
        ↓
Frozen Rule asset_type + operation=DELETE + path=".env"
```

Command와 Process의 `EXECUTE`는 `raw_command`가 있을 때만 다음 Subject가
된다.

```text
Frozen Rule asset_type + operation=EXECUTE + raw_command=raw_command
```

Action에 들어온 `normalized_command`만으로 판정하지 않는다. 기존 Policy
Engine의 target adapter가 각 Frozen Rule의 asset type을 사용해 권위 있는 raw
command를 `normalize_command`로 정규화하고 명령 패턴을 비교한다. Runtime public
API에는 caller가 `asset_type`을 override할 수 있는 경로가 없다.

## File Operation과 Evidence Sufficiency

`READ`, `CREATE`, `MODIFY`, `DELETE`는 canonical path가 있고 Workspace 경계
오류가 없을 때 평가한다. missing, outside, escape, different drive 등으로
정상 canonical path를 만들지 못한 경우에는 default effect를 적용하지 않고
`INDETERMINATE / POLICY_PATH_EVIDENCE_INSUFFICIENT`를 반환한다.

`NormalizationCompleteness.PARTIAL` 자체는 Policy를 자동으로
`INDETERMINATE`로 만들지 않는다. 현재 Policy에 필요한 path 또는 raw command가
있으면 평가할 수 있다. 부모 Process identity나 Hook 계보가 부족한 것은
Attribution의 한계이며 Policy Evidence 부족과 별개다.

## Command와 Process EXECUTE

Command Action은 raw command 전체를 lexical command pattern과 비교한다.
Command splitting, shell parsing, SQL parsing, Script 내부 효과 추론은 하지
않는다.

```text
DROP TABLE users
```

와 명시적으로 같은 command pattern이 있을 때만 해당 Rule이 매칭된다.

```text
python reset_db.py
```

가 내부에서 어떤 SQL을 수행했는지는 이 계층의 근거가 아니다. Process Target의
`EXECUTE`도 process executable만으로 command를 만들어내지 않는다. raw command가
없으면 `INDETERMINATE / COMMAND_EVIDENCE_INSUFFICIENT`다.

## MOVE / RENAME

`MOVE`와 `RENAME`은 source와 destination을 같은 Operation으로 각각 평가한다.
최종 결과는 `RuntimePathEvaluation` 두 개를 보존한다.

```text
SOURCE      → PolicyEvaluation
DESTINATION → PolicyEvaluation
```

결합 규칙은 다음과 같다.

1. 하나라도 `VIOLATION`이면 최종 `VIOLATION`
2. 위반은 없고 하나라도 `INDETERMINATE`이면 최종 `INDETERMINATE`
3. 둘 다 `COMPLIANT`이면 최종 `COMPLIANT`

양쪽의 matched rule ID를 모두 보존하고, 어느 경로가 감사 대상인지도 각 path
result와 최종 `audit_record`에 반영한다.

## Policy Decision과 Attribution 독립성

Runtime Policy Evaluator는 Attribution module을 import하거나 호출하지 않으며
`AttributionResult`를 입력으로 요구하지 않는다. 같은 Action에 대해
`EXACT`, `PROCESS`, `TEMPORAL`, `UNKNOWN` 결과가 별도로 존재해도 동일한
Policy Input이면 Policy Decision은 바뀌지 않는다.

```text
DELETE .env
Policy Effect = DENY

Attribution = UNKNOWN
Policy Decision = VIOLATION
```

`UNKNOWN`을 이유로 `COMPLIANT`로 낮추거나 `PROCESS`를 이유로
`INDETERMINATE`로 낮추지 않는다. 두 결과를 결합해 `REFUSE`, `BLOCKED`,
`TERMINATED`를 만드는 일은 EPIC-014 Enforcement Gate의 책임이다.

## ALLOW / AUDIT / DENY

- `ALLOW` → `COMPLIANT`, `audit_record = false`
- `AUDIT` → `COMPLIANT`, `audit_record = true`
- `DENY` → `VIOLATION`

`Policy Violation != BLOCKED`이고 `Policy Violation != TERMINATED`다. 이번
EPIC에는 Enforcement Decision이나 실제 Action 필드가 없다.

기존 Policy Engine의 높은 Priority 우선, 같은 Priority의 동일 Effect 병합,
같은 Priority의 Effect 충돌 시 `POLICY_CONFLICT` 규칙을 그대로 호출한다.
DENY-wins로 변경하지 않았다.

## Stage와 Sensor Health

`PRE_ACTION`과 `POST_ACTION`은 Runtime 결과에 보존된다. 현재 Policy Domain에
Stage별 Rule이 없으므로 Stage가 Effect를 바꾸지 않는다.

`PRE_ACTION VIOLATION`은 `BLOCKED`가 아니며 `POST_ACTION VIOLATION`은
`TERMINATED`가 아니다. Sensor Health Evidence도 이 evaluator의 입력이 아니며
Sensor 상태 때문에 Policy Effect를 낮추거나 높이지 않는다.

## 결과와 Batch

`RuntimePolicyEvaluation`은 다음을 보존한다.

- Action/Session 식별자
- Operation과 Stage
- Active Policy metadata와 fingerprint
- Policy Decision과 Effect
- 자산 유형, matched rule IDs, audit flag
- 원본 raw command와 Policy Engine이 만든 normalized command
- 단일 underlying `PolicyEvaluation`
- MOVE/RENAME의 per-path evaluations
- 제한 사유와 안정적인 reason code

`RuntimePolicyBatchResult`는 입력 Action 순서를 유지하고 각 결과를 독립적으로
보존한다. `COMPLIANT`, `VIOLATION`, `INDETERMINATE`, audit count와 평가 시각을
함께 제공한다. 한 Action의 구조적 평가 실패가 다른 Action 결과를 삭제하지
않는다. 예기치 않은 내부 오류는 사용자에게 traceback을 노출하지 않고
`INDETERMINATE / POLICY_EVALUATION_ERROR`로 보존한다.

## Raw → Normalize → Policy Integration

이번 EPIC의 실제 연결은 다음 callable pipeline까지다.

```text
Raw Evidence
→ Normalizer
→ NormalizedAction
→ RuntimePolicyEvaluator
→ RuntimePolicyEvaluation
```

Attribution은 같은 `action_id`를 기준으로 별도 호출할 수 있지만 Runtime Policy
결과가 Attribution 값을 소비하지 않는다. Background watcher orchestration,
Enforcement Gate, Process Manager, Recovery, Rollback, Integrity는 연결하지
않았다.

## 현재 Claim과 제한

이번 구현으로 다음을 주장할 수 있다.

> AIA는 Session 시작 시 동결된 사용자 정의 Security Asset Policy를
> Canonical Runtime Action에 결정론적으로 적용해 Attribution과 독립적으로
> COMPLIANT / VIOLATION / INDETERMINATE를 판정한다.

아직 다음을 주장하지 않는다.

- Policy Violation을 실제로 차단함
- Agent를 종료함
- Script 내부 DB 변경을 이해함
- Process executable에서 실제 command를 추론함
- Normalized Action만으로 semantic asset type을 자동 분류함
- Sensor failure를 Policy Decision으로 해결함

기존 P0의 정책 Domain, Priority/Conflict 의미, 명령 lexical matching,
Attribution과 Enforcement 사이의 책임 분리를 참고했다. 제품 Runtime은
Active Policy Snapshot과 Canonical Action을 권위로 사용하며, P0의 live
enforcement gap을 이번 EPIC에서 우회 구현하지 않는다.

새 Dependency는 추가하지 않았다.
