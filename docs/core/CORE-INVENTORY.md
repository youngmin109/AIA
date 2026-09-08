# AIA 제품 핵심 구조 조사 목록

## 조사 범위와 판단 기준

이 문서는 2026-09-08 현재 Reference Repository의 작업 트리를 읽기 전용으로 분석한 결과다.

Reference Repository:

C:\workspace\01_projects\ai agent moniter

분류는 파일이 현재 실행된다는 사실이 아니라, 새 제품에서 그 파일이 맡고 있는 책임과
재사용 위험을 기준으로 한다.

- **PRODUCT CORE**: 실행을 관찰하고, 판정하고, 통제하고, 복구하고, 보고하는 제품 책임.
- **EVALUATION**: 평가 계약, frozen oracle, 결과, 점수 계산. 제품 런타임에 포함하지 않는다.
- **TEST HARNESS**: simulator, fixture, 실제 Agent 실행 보조, 자동화 시험 환경.
- **LEGACY / ADVISORY**: 기존 POC 통합, Intent/Risk 휴리스틱, UI·CLI 등 참고용 표면.

P0 소스는 새 Repository로 복사하지 않는다. 아래의 재사용 표시는 코드 복사가 아니라,
책임·계약·실패 경계를 새 MVP에서 별도로 설계할 때 참고할지 여부를 뜻한다.

## PRODUCT CORE

| 파일 또는 모듈 | 현재 역할 / 주요 입력 | 주요 출력 / 주요 의존성 | 새 MVP 분류 및 판단 |
|---|---|---|---|
| src/ai_assurance/mvp.py | Agent 실행 하나를 위한 전체 lifecycle을 조정한다. workspace, prompt, agent, mode, session, 정책, resume 정보를 입력받는다. | 원시 evidence 경로, action, policy/risk 결과, termination, recovery, integrity, security report를 포함한 result bundle을 출력한다. agents, session, watcher, runtime_observer, attribution, policy_v1, enforcement, run_state, security_report에 의존한다. | **참고**. 제품 orchestration의 경계는 재사용하지만 현재 P0의 결합된 실행 함수를 복사하지 않는다. |
| src/ai_assurance/agents.py | Codex/Claude executable을 발견하고, 모델·resume·workspace·prompt를 실행 명령으로 변환한다. ephemeral hook 설치와 stream parsing도 담당한다. | HookInstallation, process command, StreamRecord, agent 상태 정보를 출력한다. subprocess, Codex/Claude CLI, poc002 hook 설치에 의존한다. | **선별 참고**. Agent adapter 경계와 Codex 우선 연동 방식만 참고한다. Claude 지원은 이번 EPIC의 구현 대상이 아니다. |
| src/ai_assurance/session.py | 한 보호 실행의 in-memory lifecycle, 허용 상태 전이, 이벤트·risk·process·snapshot·rollback 결과를 묶는다. | SessionStatus, Session, StateTransition, SessionMetrics를 출력한다. events, process_manager, risk, rollback에 의존한다. | **선별 참고**. 세션과 상태 전이는 핵심 책임으로 채택하되 POC 상태값과 제품 상태 모델은 분리한다. |
| src/ai_assurance/run_state.py | 실행 경계의 durable run-state를 원자적으로 기록하고 중단·orphan 실행을 해석한다. session, owner process, agent process, phase, result 경로를 입력받는다. | run-state.json과 incomplete result를 출력한다. psutil, atomic_write_json에 의존한다. | **선별 참고**. Session Manager의 durable journal 책임으로 흡수한다. 현재 형식은 제품 계약으로 고정하지 않는다. |
| src/ai_assurance/events.py | Watchdog가 만든 파일 이벤트를 FileEvent로 정규화하고 thread-safe collector에 저장한다. session, event type, path, digest, size가 입력이다. | FileEvent, EventCollector, protected/ignored-reported event stream을 출력한다. Python threading/condition에 의존한다. | **선별 참고**. append-only evidence와 ignored stream의 구분은 재사용하고 저장 형식은 재정의한다. |
| src/ai_assurance/watcher.py | 보호 workspace의 create/modify/delete/move를 감시하고 경로 정책에 따라 이벤트를 수집한다. workspace, session, EventCollector가 입력이다. | FileEvent와 content digest/size, ignored event를 출력한다. watchdog, workspace_policy에 의존한다. | **참고**. Evidence Collector의 한 센서로 모델링한다. Watcher가 writer identity를 증명한다고 해석하지 않는다. |
| src/ai_assurance/hook_capture.py | Hook stdin payload를 decode하고 session/turn/agent metadata, PreTool 결과, 오류를 JSONL로 남긴다. PreToolUse는 정책을 평가해 machine response를 반환한다. | hook evidence record, PreTool deny/allow response, capture error를 출력한다. pretool_policy, policy_v1, stdin/env에 의존한다. | **선별 참고**. Hook은 raw evidence source이며 직접 Hook identifier를 가진 행위만 EXACT 후보가 된다. |
| src/ai_assurance/command_telemetry.py | ToolAction의 command와 structured tool input에서 파일·execute action을 추출하고 network 관련 입력도 선택적으로 관찰한다. Hook record의 tool input/output과 workspace가 입력이다. | NormalizedAction 목록과 command effect/source evidence를 출력한다. attribution, normalized_action, shell_effects에 의존한다. | **선별 참고**. command telemetry는 lexical evidence로만 사용하고 script/DB 내부 효과를 추론하지 않는다. Network telemetry는 Legacy / Optional Telemetry / Future Scope이며 MVP Security Authority가 아니다. |
| src/ai_assurance/runtime_observer.py | 등록된 root process identity의 descendants를 주기적으로 관찰하고 outbound socket telemetry도 선택적으로 기록한다. root PID/create time, session, interval이 입력이다. | RuntimeProcessEvidence, 선택적 RuntimeNetworkEvidence, JSONL evidence, 보수적 NormalizedAction을 출력한다. psutil, attribution, normalized_action에 의존한다. | **Process 관찰만 핵심 참고**. Runtime Evidence와 PID 재사용 방지 조건을 채택하되, PROCESS를 파일 writer EXACT로 승격하지 않는다. Network observation은 Legacy / Optional Telemetry / Future Scope로 분류하며 제품 보안 Claim이나 Enforcement Authority에 사용하지 않는다. |
| src/ai_assurance/attribution.py | Hook action, turn window, process lifetime, watchdog FileEvent를 결합해 행위 귀속 등급을 계산한다. | ToolAction, TurnWindow, ProcessTreeLifetime, AttributedAction과 EXACT/PROCESS/TEMPORAL/UNKNOWN을 출력한다. events, datetime, UUID에 의존한다. | **핵심 참고**. 보수적 귀속 계약의 근거로 사용한다. 구현 이식은 하지 않고 제품 계약을 먼저 확정한다. |
| src/ai_assurance/merge.py | Hook, process, temporal, snapshot evidence를 canonical path와 logical action으로 병합하고 transient evidence를 보존한다. | LogicalAction, ActionEvidence, MergeMetrics/Result를 출력한다. attribution, path normalization, snapshot evidence에 의존한다. | **선별 참고**. 원시 evidence 보존과 logical action 분리를 채택한다. 병합이 원시 기록을 삭제하지 않도록 한다. |
| src/ai_assurance/normalized_action.py | 여러 센서의 행동을 action type, target, count, turn, evidence, attribution으로 통일한다. | NormalizedAction과 attribution별 kill_authorized flag를 출력한다. attribution에 의존한다. | **핵심 참고**. Normalization과 권한 flag를 분리 설계한다. kill_authorized는 Policy/Enforcement 계약으로 재검증한다. |
| src/ai_assurance/policy_v1.py | 명시된 Security Asset Policy를 검증하고 Canonical Action의 path/command/operation/evidence stage를 평가한다. | COMPLIANT/VIOLATION/INDETERMINATE, matched rule, evidence limitation을 출력한다. P0 구현의 enforcement helper는 새 MVP에서 Gate와 분리한다. Python 표준 라이브러리만 사용한다. | **핵심 설계 참고**. 동일한 validated policy를 PreTool과 Runtime에 적용한다. Attribution 등급 때문에 Policy Decision을 낮추지 않는다. 코드 자체는 복사하지 않는다. |
| src/ai_assurance/enforcement.py | 정책 결과, EXACT attribution, owned process identity, session/sensor/lease 상태를 확인하는 fail-closed gate다. | Enforcement Decision과 gate check를 출력하고, 실제 kill·rollback 결과는 실행 경로가 반환한다. process_manager, integrity, rollback에 의존한다. | **핵심 설계 참고**. Gate는 실제 프로세스를 종료하지 않는 독립 권한 경계로 둔다. PreTool Adapter/Process Manager가 실제 BLOCKED/TERMINATED를 확인하며, Checkpoint 유무가 containment 승인 자체를 대신하지 않게 한다. |
| src/ai_assurance/process_manager.py | AIA가 spawn한 process를 session별로 registry에 보관하고 PID/create_time을 검증한 뒤 process tree를 종료한다. | ManagedProcess, KillResult, process status와 terminated/failed PID를 출력한다. subprocess, psutil에 의존한다. | **핵심 설계 참고**. 관리자가 소유한 process만 다룬다는 원칙을 채택한다. PID 단독 신뢰는 금지한다. |
| src/ai_assurance/snapshot.py | project root 아래 workspace를 검증하고 파일을 복사하면서 SHA-256 manifest를 고정한다. | SnapshotDescriptor, immutable snapshot path/manifest, copy metrics를 출력한다. pathlib, shutil, hashlib, workspace_policy에 의존한다. | **선별 참고**. Checkpoint Manager의 안전 경계와 trusted manifest 개념을 참고한다. |
| src/ai_assurance/rollback.py | 성공한 managed process kill 뒤 session snapshot으로 workspace를 복구하고 복구 후 manifest를 비교한다. | RollbackResult, restored/failed path, integrity_passed를 출력한다. snapshot, integrity, KillResult에 의존한다. | **핵심 설계 참고**. valid checkpoint 뒤에만 rollback하고, rollback 뒤 Integrity Verification을 필수로 둔다. |
| src/ai_assurance/integrity.py | workspace 파일의 SHA-256 manifest를 생성하고 expected/actual path·digest를 비교한다. | IntegrityResult와 NOT_CHECKED/VERIFIED/FAILED에 해당하는 비교 결과를 출력한다. pathlib, hashlib에 의존한다. | **핵심 설계 참고**. Recovery Coordinator와 분리된 독립 검증 책임으로 둔다. |
| src/ai_assurance/workspace_policy.py / workspace_lease.py | 보호·ignored-reported·ephemeral 경로를 나누고, canonical workspace에 동시 보호 실행이 하나만 있도록 한다. | 경로 분류, lease acquire/release, busy 상태를 출력한다. pathlib, file locking, process identity에 의존한다. | **선별 참고**. Session Manager와 Evidence Collector의 경계 조건으로 재설계한다. |
| src/ai_assurance/security_report.py | durable result에서 정책 판정과 실제 개입을 분리해 사용자용 JSON/Markdown 보고서를 만든다. | 최종 headline, decision, intervention, termination, observation, next steps, limitations를 출력한다. result mapping과 표준 라이브러리에 의존한다. | **참고**. Report Generator의 출력 계약을 참고하되 상태 모델은 EPIC-001 기준으로 다시 고정한다. |
| src/ai_assurance/durability.py / retention.py / sensor_health.py | 결과를 atomic write하고, 완료·incident evidence를 보존하며, Hook·runtime·watcher 센서 상태를 평가한다. | commit marker, retention plan, sensor health와 오류 budget을 출력한다. 파일 I/O, hashlib, psutil에 의존한다. | **후속 참고**. 제품 기반에는 필요하지만 이번 EPIC에서는 구현·이식하지 않는다. |

## EVALUATION

| 파일 또는 모듈 | 현재 역할 / 주요 입력 | 주요 출력 / 주요 의존성 | 새 MVP 분류 및 판단 |
|---|---|---|---|
| evaluation/freeze-candidates/1.0.3/ | evaluation-contract, policy schema, testset schema, reference oracle, validator, freeze status를 함께 보관한다. frozen JSON/YAML과 policy 후보가 입력이다. | 계약 검증 결과, validation result, freeze manifest를 출력한다. Python 표준 라이브러리와 JSON schema 형태에 의존한다. | **평가 전용**. Ground Truth로 참고하지만 제품 package와 정책 런타임에 포함하지 않는다. |
| data/testset-001.yaml, data/testset-002.yaml, data/testset-003.yaml 및 schema/oracle/hash | 행동 fixture와 expected outcome의 frozen 기준선이다. | 점수 계산용 입력과 SHA-256 attestation을 제공한다. 평가 runner에 의존한다. | **보존·참고**. 새 MVP가 결과를 바꾸거나 자동 복사하지 않는다. Ground Truth는 변경하지 않는다. |
| scripts/run_testset*.py, evaluate_testset003.py, score_testset003_public_surface.py, candidate_validator_1_0_3.py | testset을 로드하고 public API, PreTool, Risk/Guard, contract를 실행·점수화한다. | score JSON/Markdown, mismatch와 validation status를 출력한다. ai_assurance public API와 frozen data에 의존한다. | **평가 전용**. 제품의 판단 엔진과 분리한다. |
| scripts/benchmark_v06.py, benchmark_v07.py | snapshot/rollback, watcher/runtime 등의 성능과 회귀 지표를 측정한다. | timing JSON/Markdown을 출력한다. 제품 모듈, disposable workspace에 의존한다. | **참고 전용**. SLA나 제품 권한을 결정하지 않는다. |
| evaluation/actual-agent-e2e/1.0.3/ | First Attempt E2E, P0 Live Policy, destructive probe의 fixture·run metadata·raw evidence·report를 보관한다. 실제 Codex 실행과 disposable workspace가 입력이다. | evidence bundle, E2E result, P0 report를 출력한다. Codex, runner, product hooks/sensors에 의존한다. | **평가 증거 전용**. 결과를 새 MVP의 실행 데이터나 코드로 복사하지 않는다. |
| docs/AIA-MVP-REQUIREMENTS-v1.0.md, docs/V0.6-*.md, docs/V0.7-*.md, docs/poc002/*RESULT.md | P0/P1 구현의 요구사항, 평가 해석, 제한, POC 단계 결과를 설명한다. | 사람이 검토할 수 있는 계약·결과·제한을 출력한다. 소스·평가 산출물을 참조한다. | **공식 참고 자료**. 주장 범위와 Security Invariant를 재검토할 때 사용한다. |
| tests/test_testset002_*.py, tests/test_testset003_*.py, tests/test_canonical_outcomes.py | frozen contract, oracle independence, public surface, canonical outcome을 검증한다. fixture와 public API가 입력이다. | pytest assertion과 score/contract regression 결과를 출력한다. pytest와 제품 public API에 의존한다. | **평가 테스트 전용**. 신규 MVP의 bootstrap test와 섞지 않는다. |

## TEST HARNESS

| 파일 또는 모듈 | 현재 역할 / 주요 입력 | 주요 출력 / 주요 의존성 | 새 MVP 분류 및 판단 |
|---|---|---|---|
| simulator/fake_codex_mvp.py, normal_agent.py, destructive_agent.py, short_lived_process.py, long_running_process.py, child_process_spawner.py | 정상·위험·자식 process와 파일 변경을 결정적으로 재현한다. fixture workspace와 command가 입력이다. | process tree, file mutation, 종료·복구 시험 자극을 출력한다. subprocess와 disposable filesystem에 의존한다. | **시험 전용**. 제품 runtime에 포함하지 않고, 향후 별도 harness에서 필요한 경우 새로 만든다. |
| simulator/step02_*.py, step03_validation.py, step016_validation.py, attack_scenario_a_batch.py | Intent/Risk, attribution, EXACT enforcement/recovery, attack scenario의 반복 실행을 조정한다. | validation result, timing, evidence path, batch statistics를 출력한다. simulator와 product modules에 의존한다. | **시험 전용**. 제품 책임 정의의 근거로만 참고한다. |
| src/ai_assurance/poc002.py | 실제 Codex를 disposable smoke workspace에서 실행하고 Hook, JSONL, ProcessTree, Watchdog, snapshot/manifest를 수집한다. | SmokeResult, codex/hook/watchdog/runtime JSONL, timeline을 출력한다. subprocess, hook_capture, runtime observer에 의존한다. | **하네스**. 실제 Evidence Collector 요구사항을 이해하는 데 참고하고 제품 API로 이식하지 않는다. |
| src/ai_assurance/attack_lab/ | prompt injection/MCP 등 안전한 decoy, collector, scenario runner, outcome evaluator를 제공한다. disposable lab root와 decoy assets가 입력이다. | lab evidence, PREVENTED/DETECTED_AND_RECOVERED/DETECTED_ONLY/MISSED 결과를 출력한다. subprocess, filesystem containment, product sensors에 의존한다. | **평가·하네스 전용**. 실사용 Agent 보안 기능과 분리한다. |
| tests/test_*.py 전체 | 모듈 단위, lifecycle, integration, web, process, snapshot, rollback 회귀를 실행한다. pytest fixtures와 tmp paths가 입력이다. | assertion, regression status, skipped environment constraints를 출력한다. pytest와 전체 소스에 의존한다. | **시험 전용**. 새 MVP에서는 계약이 확정된 뒤 필요한 테스트만 독립적으로 작성한다. |
| evaluation/*/workspaces, .assurance/* 및 .test-* 산출물 | 실제·결정적 실행을 위한 disposable workspace와 raw result를 보관한다. | fixture mutation, raw log, result bundle을 출력한다. runner와 local Agent에 의존한다. | **보존된 증거/하네스**. 제품 소스나 runtime state로 사용하지 않는다. |

## LEGACY / ADVISORY

| 파일 또는 모듈 | 현재 역할 / 주요 입력 | 주요 출력 / 주요 의존성 | 새 MVP 분류 및 판단 |
|---|---|---|---|
| src/ai_assurance/intent.py | raw prompt와 명시 constraint에서 task type, scope, explicit/forbidden operation, destructive/external 허용을 휴리스틱하게 추출한다. | Intent와 IntentConstraints를 출력한다. 정규식, 문자열 heuristic에 의존한다. | **Advisory**. 사용자 의도 설명과 경고에 참고할 수 있지만 Security Enforcement Authority를 주지 않는다. |
| src/ai_assurance/risk_decision.py | Intent와 NormalizedAction을 결합해 action-only scope, secret, network, delete, shell effect를 평가한다. | ALLOW/FLAG/KILL, rule ids, reasons, DecisionEvidence를 출력한다. intent, normalized_action, shell_effects, policy_patterns에 의존한다. | **Advisory**. v1 Policy가 COMPLIANT일 때 이 결과만으로 BLOCKED/TERMINATED를 만들지 않는다. |
| src/ai_assurance/risk.py | Watcher FileEvent를 단순 rule로 처리해 risk event를 만든다. | RiskEvent와 risk level을 출력한다. events, policy patterns에 의존한다. | **Legacy advisory**. 제품 권한을 갖지 않으며, v1 Policy와 별도 결과로 표시한다. |
| src/ai_assurance/sequence_risk.py | 같은 session의 action history에서 secret read 뒤 network, 누적 삭제 등 sequence를 검토한다. | SequenceSummary와 누적 risk signal을 출력한다. normalized action history에 의존한다. | **Advisory 후보**. sequence context는 보고에 유용하지만 단독 종료 권한은 없다. |
| src/ai_assurance/shell_effects.py / policy_patterns.py | shell command를 READ/VERIFY/MUTATION 등 lexical effect로 분류하고 민감 경로 pattern을 제공한다. | ShellEffect와 pattern match를 출력한다. 문자열 parsing/fnmatch에 의존한다. | **참고**. command pattern은 lexical evidence일 뿐 script/DB 의미론을 증명하지 않는다. |
| src/ai_assurance/pretool_policy.py | Hook 단계에서 prompt/constraints와 tool input을 평가해 PreToolLevel과 allow/flag/deny 응답을 만든다. | PreToolDecision, Hook response, block reason을 출력한다. shell_effects, path parsing에 의존한다. | **호환·참고**. v1 Security Asset Policy를 단일 권위로 정리할 때 경계를 다시 설계한다. |
| src/ai_assurance/orchestrator.py | POC-001의 snapshot → watcher → process → risk → kill → rollback lifecycle을 동기적으로 연결한다. | Session과 POC report를 출력한다. session, snapshot, watcher, process_manager, risk, rollback에 의존한다. | **Legacy POC**. 제품 Session Manager의 설계 근거로만 참고하고 복사하지 않는다. |
| src/ai_assurance/webapp.py, web/, cli.py, launcher.py | local API, GUI, CLI, launcher로 실행·세션·보고서를 사용자에게 노출한다. | HTTP/HTML/CLI response와 UI 상태를 출력한다. FastAPI, uvicorn, frontend assets에 의존한다. | **Reference surface**. 이번 EPIC과 제품 core 계약 확정 뒤 후속으로 검토한다. |
| AI-Assurance-Launcher.bat, README 실행 절차 | Windows에서 기존 P0 GUI와 CLI를 시작하는 편의 표면이다. | 사용자 실행 명령을 출력한다. local Python/uv 환경에 의존한다. | **제외/참고**. 신규 MVP의 실행 표면으로 이식하지 않는다. |

## 조사 결론

P0는 기능이 부족해서가 아니라 서로 다른 목적의 코드가 한 package와 한 Repository에
함께 있어 책임 경계가 흐려진다. 새 MVP는 다음 순서를 제품 권위의 기준으로 삼아야 한다.

Runtime/Hook/Workspace Evidence → canonical Normalization → conservative Attribution
→ validated v1 Security Asset Policy → Enforcement Gate → Process/Recovery
→ Integrity Verification → Audit/Report

Intent/Risk는 이 흐름의 보조 설명과 사용자 검토 신호로 둘 수 있지만, v1 Security
Asset Policy의 판정이나 Enforcement Gate의 권한을 대체하지 않는다.
