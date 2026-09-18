# EPIC-018 Performance Result

평가 ID: `eval-20260909T144119Z`. 각 크기별 1 warmup + 30 repetitions을 수행했고 P95는 nearest-rank 방식으로 계산했다. 측정값은 Windows 11 Pro, Python 3.13.5, NVMe SSD 환경의 단일 실행 결과이며 고정 SLA가 아니다.

| Workspace | Startup/readiness P95 | Checkpoint P95 | Recovery + Integrity P95 | Integrity P95 | Finalization bundle P95 |
|---:|---:|---:|---:|---:|---:|
| 10 files | 57.588 ms | 147.433 ms | 96.924 ms | 51.542 ms | 74.083 ms |
| 100 files | 241.563 ms | 510.858 ms | 570.158 ms | 311.915 ms | 120.903 ms |
| 1,000 files | 1,531.824 ms | 4,822.376 ms | 4,463.311 ms | 2,322.300 ms | 102.033 ms |

PreTool decision은 현재 harness의 결정론적 policy timing이고, Process termination은 해당 benchmark 경로에서 실제 termination을 수행하지 않아 `0 ms` fixture 값이다. Actual Codex startup 또는 Agent latency를 의미하지 않는다.

이번 결과로 10/100/1,000 파일에 대한 동작과 경향은 기록할 수 있지만, GB 단위 지원·처리량·동시 실행·장시간 안정성·제품 SLA는 주장하지 않는다. 원본은 `evaluation/mvp-1.0/eval-20260909T144119Z/performance/benchmark.json`이다.
