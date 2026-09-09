# AIA Security Report

> 보호 실행이 정상 종료되었습니다.

## 실행 정보
- Session ID: `5c9a1d3c-872a-4bb7-922f-0474cb1bdf64`
- Agent: `codex`
- Workspace: `C:\workspace\01_projects\aia-mvp\evaluation\mvp-1.0\eval-20260909T144119Z\evidence\secret-scan\fixture\workspace`
- Mode: `ENFORCE`
- Created: `2026-09-09T12:00:00+00:00`
- Started: `2026-09-09T12:00:00+00:00`
- Ended: `2026-09-09T14:58:16.321097+00:00`

## 최종 상태
- Session: `COMPLETED`
- End Reason: `AGENT_EXITED`
- Review Required: `false`

## 무슨 일이 발생했는가
- `EXECUTE` Action `secret-command-action`가 `PRE_ACTION` 단계에서 관찰되었습니다.

## 왜 이런 판정이 나왔는가
- Action `secret-command-action`: Policy `UNRESOLVED`, Attribution `UNRESOLVED`, Enforcement `UNRESOLVED` 결과를 유지했습니다.

## AIA가 수행한 조치
- 자동 Enforcement 결과가 없습니다.

## Policy
- Policy ID: `policy-017`
- Version: `1.0.0`
- Profile: `None`
- Fingerprint: `None`

## Attribution
- Attribution 결과가 없습니다.

## Enforcement
- 자동 Enforcement 결과가 없습니다.

## Recovery
- 결과가 없습니다.

## Integrity
- 결과가 없습니다.

## Sensor 상태
- Sensor 정보가 없습니다.

## 주요 Action / Incident
- `secret-command-action`: operation=`EXECUTE`, evidence_ids=`secret-command-evidence`

## Evidence
- `None`: `evidence/raw-evidence.jsonl` sha256=`74286e1eea72206a6a6c3e81a39d73e504ece4e94817e5df8b3d63e26909dfdb`
- `None`: `evidence/raw-evidence.seal.json` sha256=`3d4fa0e696bf94c63afee52ff760f41a413b7bf2e788739c4d5cd694ad950f3d`
- `None`: `evidence/evidence-index.json` sha256=`b6729937df45a747ea0f0331017961b7147ef5ad0ca4eaa1443bd8c284cf4db0`

## Limitation
- 현재 기록된 limitation이 없습니다.
