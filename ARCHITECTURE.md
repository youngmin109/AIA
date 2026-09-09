# AIA 상위 아키텍처

AIA MVP의 보호 실행 상위 흐름은 다음과 같다.

```text
Protected Run
        → Active Policy Freeze
        → Safe Checkpoint
        → Sensor Readiness
        → Protected Agent Launch
        → Raw Runtime Evidence
        → Normalization
        → Canonical Action
        ├→ Policy Evaluation
        └→ Attribution
        ↓
Enforcement Gate
        → Enforcement Execution
        → Recovery
        → Integrity Verification
        → Session Finalization
        → Audit / Result
```

Policy Evaluation은 관찰된 행위가 정책을 위반했는지 판단하고, Attribution은 그 행위를 Agent에 어느 수준까지 귀속할 수 있는지 독립적으로 판단한다. `PROCESS`, `TEMPORAL`, `UNKNOWN`은 충분한 증거가 없는 자동 종료 권한을 만들지 않는다. `Policy Violation`만으로 Kill을 수행하지 않는다.

Recovery와 Integrity는 별도 상태 축이다. `RESTORED`는 복원 작업 자체의 완료이고, `VERIFIED`는 복원 후 expected path/existence/SHA-256 검증 성공이다. 검증된 복구 성공은 `RESTORED + VERIFIED`일 때만 사용한다.

Enforcement Gate는 `CONTINUE / CONTAIN / REFUSE`를 결정한다. Gate 승인만으로 `BLOCKED` 또는 `TERMINATED`를 기록하지 않으며, 실제 PreTool deny 또는 managed process termination이 확인되어야 한다. Enforcement Execution Result는 `NOT_ATTEMPTED / SUCCEEDED / FAILED` 독립 축이다.

상세 모듈 구조와 배치 방식은 각 EPIC의 계약과 테스트에 따라 확정한다. 이 문서는 제품 흐름과 검증된 책임 경계만 정의한다.
