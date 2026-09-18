# AIA MVP 위협 모델

## 보호 대상과 경계

주요 보호 대상은 AIA가 시작한 Coding Agent의 보호 실행과 사용자가 지정한 Workspace다. Agent는 Workspace와 도구에 넓은 권한을 가질 수 있다고 가정한다. AIA는 보호 실행 세션, Active Policy, Checkpoint, Runtime Evidence, Enforcement 결과, Recovery 결과와 Audit/Result Bundle의 연결을 보존한다.

## 다루는 위협

- Agent가 실수로 보호 Workspace의 파일을 삭제·변경하는 행위
- 위험한 명령 또는 프로세스가 실행된 뒤 발생하는 부작용
- 정책 위반 뒤 managed process를 잘못 종료하는 행위
- 다른 프로세스나 PID 재사용 대상을 잘못 종료하는 행위
- 유효하지 않은 Checkpoint에서 복원을 시도하는 행위
- 복원 후 파일 내용이나 경로가 기준점과 다른데 성공으로 보고하는 행위
- 증거·결과·감사 산출물이 사후 수정되었는데 검증하는 행위

## 완화 범위

Process/Session identity와 `create_time` 확인, `EXACT` 기반 자동 종료 제한, PreTool Gate 계약, append-only Raw Evidence, immutable Checkpoint manifest, SHA-256 Integrity, staged/verified Result Bundle과 tamper 검증이 이 범위에 포함된다.

## 판단하지 않는 위협

AIA는 이번 MVP에서 악의적 의도나 정확한 파일 Writer를 추론하지 않는다. Network Security, Database state, ACL/ADS 메타데이터, OS 수준 writer attribution, 외부 프로세스의 모든 race/TOCTOU, 전체 Workspace 원자적 트랜잭션, GUI·MCP·Cloud 환경은 이 위협 모델의 보호 주장에 포함하지 않는다.

## 안전 원칙

`EXACT`만 automatic containment authority의 후보가 될 수 있다. `PROCESS`, `TEMPORAL`, `UNKNOWN`은 자동 termination 권한을 만들지 않으며, 불충분한 증거는 보존하고 사용자 검토로 남긴다. Containment와 실제 Action은 분리하고, Recovery와 Integrity도 분리한다.
