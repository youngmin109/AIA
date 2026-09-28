# AIA 0.1.23 Release Readiness

0.1.23은 보호 실행 중 사용자가 파일 시스템 관찰 상태를 확인할 수 있도록 보강한
유지보수 릴리스다.

실행 중 화면의 `파일 관찰` 수치는 AIA File Sensor가 Control Root의 append-only
Evidence 파일에 기록한 `FILESYSTEM_EVENT` 메타데이터 건수다. 원문 경로·명령·payload는
화면이나 상태 API에 반환하지 않는다. 이 수치는 파일 변경 관찰을 뜻하며, 정확한
Writer 판별이나 사전 차단 성공을 뜻하지 않는다.

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
powershell -ExecutionPolicy Bypass -File .\scripts\release-gate.ps1
```

현재 전체 테스트 결과는 `582 passed, 3 skipped, 2 warnings`다.

완료된 Result Bundle은 계속 검증된 Bundle에서만 읽으며, 실행 중 상태는 안전한
메타데이터 집계만 허용한다.
