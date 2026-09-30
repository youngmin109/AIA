# Benchmarks

Micro-benchmarks written during the 2026-09-29 self-improvement loop. Run each one from the repository root, for example:

```powershell
.venv\Scripts\python.exe scripts\benchmarks\bench_run_history_listing.py
```

| Script | Measures |
|---|---|
| `bench_checkpoint_integrity.py` | Checkpoint creation and two-pass SHA-256 verification on 5,000 generated files |
| `bench_result_bundle_history.py` | Result Bundle history scans (verification on every scan) |
| `bench_run_history_listing.py` | `list_runs` with many runtime states and bundles |
| `bench_evidence_chain_presenters.py` | Evidence Chain presenter scaling |
| `bench_workbench_event_buffer.py` | Workbench event buffering and replay |
| `bench_process_sensor_fallback.py` | Process tree polling with real helper processes and snapshot disabled |

## Read the numbers as relative, not absolute

These scripts use generated data and, in places, fake process tables. They compare one code version with another on the same machine. They do not show what a user will see.

A performance claim needs a measurement in the real environment. On 2026-09-29 a process sensor change looked faster on a fake process tree but made the first protected launch take 6.4 s instead of 0.1 s on a real machine with 333 processes (fixed in `3ccec5d`). Measure a real process tree, real files, or a real run before claiming a speed-up.
