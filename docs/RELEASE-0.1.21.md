# AIA 0.1.21 Release Readiness

0.1.21은 File Sensor가 관찰한 사실을 사용자가 결과 화면에서 확인할 수 있도록
보강한 유지보수 릴리스다. AIA는 검증된 Evidence Bundle의 메타데이터만 집계하며,
원문 payload와 민감한 값은 화면에 노출하지 않는다.

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
powershell -ExecutionPolicy Bypass -File .\scripts\release-gate.ps1
```

## 결과 화면에서 확인할 수 있는 것

- 파일 시스템 변경 이벤트 수
- PreToolUse Evidence 수
- PostToolUse Evidence 수
- 센서 상태 기록 수

이 수치는 “파일 변경이 관찰되었다”는 뜻이다. 어떤 프로세스가 정확한 Writer인지
자동으로 증명하거나, 관찰만으로 사전 차단이 이루어졌다고 해석하지 않는다.

## 회귀 결과

- 전체 pytest: **579 passed, 3 skipped, 2 warnings**
- 기존 Core·Actual Codex 증거·배포 검증 계약 유지
- 안전한 Evidence 메타데이터 집계 테스트 추가
