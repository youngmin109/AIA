# AIA 제품 정의

AIA는 Codex와 같은 에이전트 런타임에서 발생하는 실행 증거를 수집하고, 정규화·귀속·정책 판단·집행·복구·무결성 검증·감사를 연결하는 제품형 보증 계층이다. MVP는 에이전트가 수행한 위험한 작업을 설명 가능한 증거와 명시된 보안 불변식에 따라 통제할 수 있는 제품 기반을 만든다.

## 문제 정의

에이전트 실행은 도구 호출, 프로세스, 파일 변경, 정책 판단이 여러 경계에 걸쳐 발생한다. 실행 사실과 책임 주체를 일관되게 연결하지 못하면 잘못된 종료, 증거 손실, 복구 실패, 감사 불가능성이 생긴다. AIA는 실행 증거를 보존하고 판단의 근거와 결과를 추적 가능한 형태로 만든다.

## MVP 목표

- 제품형 MVP를 위한 독립 Python Repository와 명시적 개발 규칙을 제공한다.
- Protected Run에서 Audit/Result까지의 상위 흐름을 구현 가능한 계약으로 제공한다.
- 보안 불변식, Evidence lineage, Recovery/Integrity 분리, 결과 검증을 제품의 기준으로 고정한다.
- 결정론적 핵심 흐름과 Actual Codex 정상 보호 실행을 검증하고, 미검증 영역은 제한사항으로 공개한다.

Reference Agent = Codex

P0 PASS / Project Feasibility VALIDATED

## 핵심 Security Invariant

- `EXACT` → automatic containment authority 가능
- `PROCESS` / `TEMPORAL` / `UNKNOWN` → automatic termination 금지, evidence 보존 및 사용자 검토
- Policy Violation alone != Kill
- Checkpoint는 Containment prerequisite가 아니다.
- Rollback은 valid checkpoint가 있을 때만 수행한다.
- Rollback 이후 Integrity Verification은 필수다.

## MVP In Scope

- Python 3.13, uv, pytest, src layout 기반 독립 Repository
- Protected Run, Active Policy Freeze, Safe Checkpoint, Runtime Evidence, Normalization, Attribution, Policy Evaluation
- Enforcement Gate와 실제 Block/Termination 결과 축
- Recovery와 Integrity Verification의 독립 상태 축
- Session Finalization, Audit, Result Bundle, Evidence tamper 검증
- Actual Codex 정상 보호 실행 검증 및 평가 산출물 보존
- P0 결과와 Ground Truth를 참조 기준으로 문서화

## MVP Out of Scope

Actual Codex의 구조화된 READ ingress 차단, Actual Codex destructive PROCESS/tree termination, Network Security, Database state protection, OS 수준 writer attribution, ACL/ADS 메타데이터 복구, 전체 Workspace 원자적 트랜잭션, GB 규모 성능 SLA, API/GUI/Claude 지원은 이 MVP의 검증 범위에 포함하지 않는다. 기존 P0 코드는 복사하지 않는다.
