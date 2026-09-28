# Integrated run history listing benchmark

Run from the repository root (no extra dependencies):

```powershell
.venv\Scripts\python.exe scripts\bench_run_history_listing.py
```

The benchmark creates temporary control roots at three documented sizes:
100, 500, and 1,000 persisted runtime states. Each size also has half as many
valid Result Bundles. Half of those bundles overlap runtime-state sessions,
leaving runtime-only and bundle-only sessions in the same listing. It measures
seven `list_runs()` calls per size by default and reports p50 and p95 latency.
`--runs` changes the measured calls and must be at least 3.

Every measured listing checks the distinct returned count, newest-first order,
and expected classification and launch mode for overlapping and source-only
sessions. Output contains only aggregate counts and timings; fixture IDs and
runtime-state or Result Bundle contents are never printed. These timings are a
local baseline, not a performance threshold.
