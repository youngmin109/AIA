# EPIC-018 Performance Boundary

The source benchmark is the prior immutable artifact:
`eval-20260909T144119Z/performance/benchmark.json`.

The following names apply in this revalidation:

| Source metric | Revalidation meaning |
|---|---|
| `pretool_decision_ms` | `Policy/Gate evaluator latency` from the deterministic evaluator harness |
| `detection_to_decision_ms` | `Policy/Gate evaluator latency` from the same fixture timing path; no sensor timestamp is included |
| `process_termination_ms` | Fixture-only benchmark field; it is not Actual Codex OS termination latency |
| Actual Codex OS termination duration | `NOT_MEASURED` |

The existing P95 values are retained as evaluator or lifecycle measurements. They do not establish end-to-end Agent latency, Hook ingress latency, process observation latency, Windows termination latency, throughput, concurrency, long-duration stability, or an SLA. The benchmark contract was not changed for presentation.
