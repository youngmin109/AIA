# AIA 제품 정의

AIA는 Codex와 같은 에이전트 런타임에서 발생하는 실행 증거를 수집하고, 정규화·귀속·정책 판단·집행·복구·무결성 검증·감사를 연결하는 제품형 보증 계층이다. MVP는 에이전트가 수행한 위험한 작업을 설명 가능한 증거와 명시된 보안 불변식에 따라 통제할 수 있는 제품 기반을 만든다.

## 문제 정의

에이전트 실행은 도구 호출, 프로세스, 파일 변경, 정책 판단이 여러 경계에 걸쳐 발생한다. 실행 사실과 책임 주체를 일관되게 연결하지 못하면 잘못된 종료, 증거 손실, 복구 실패, 감사 불가능성이 생긴다. AIA는 실행 증거를 보존하고 판단의 근거와 결과를 추적 가능한 형태로 만든다.

## MVP 목표

- 제품형 MVP를 위한 독립 Python Repository와 명시적 개발 규칙을 제공한다.
- Runtime Evidence에서 Audit까지의 상위 흐름을 구현 가능한 계약으로 정리한다.
- 보안 불변식을 제품의 기준으로 고정하고, 이후 EPIC에서 각 기능을 근거와 테스트를 갖춰 추가한다.

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

- 독립 Repository bootstrap
- Python 3.13, uv, pytest, src layout 기반 개발 환경
- Runtime Evidence → Normalization → Attribution → Security Asset Policy → Enforcement → Recovery → Integrity Verification → Audit의 상위 제품 흐름 정의
- P0 결과와 Ground Truth를 참조 기준으로 문서화

## MVP Out of Scope

이번 EPIC에서는 Session Manager, Policy Engine, Watchdog, Hook, Attribution Engine, Process Monitoring, Enforcement, Checkpoint, Rollback, API, GUI, Claude 지원을 구현하지 않는다. 기존 P0 코드도 복사하지 않는다.
