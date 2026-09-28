# Result Bundle history scan benchmark

Run from the repository root (no extra dependencies):

```powershell
.venv\Scripts\python.exe scripts\bench_result_bundle_history.py
```

The script creates committed Result Bundles in a temporary directory, then
measures 20 scans with a new reader for each cold scan and 20 repeated scans
with one warm reader. “Cold” means the reader's parsed-data caches start empty;
the operating system file cache is not cleared. Every scan must return the
complete expected set and report `bundle_status=VALID` for every bundle.
Use `--bundles` and `--iterations` to change the sample size; at least 100
bundles are required.

## Recorded run

Run on 2026-09-29 with Python 3.13.5, 100 bundles, and 20 scans per mode:

```text
scan_validation=all 100 bundles returned with bundle_status=VALID
cold_ms_p50=211.441 cold_ms_p95=224.966
warm_ms_p50=196.348 warm_ms_p95=222.109
```

These timings are a local baseline, not a performance threshold. The warm
reader still verifies each committed bundle on every history scan.
