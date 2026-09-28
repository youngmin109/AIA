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

## Cache-miss byte reuse comparison

Run on 2026-09-29 with Python 3.13.5, 100 bundles, and 20 scans per mode.
Before and after scans used the same benchmark script and verified that every
scan returned all 100 bundles with `bundle_status=VALID`.

| Measurement | Before | After |
| --- | ---: | ---: |
| Cold p50 | 232.534 ms | 215.040 ms |
| Cold p95 | 254.903 ms | 230.949 ms |
| Warm p50 | 218.895 ms | 218.866 ms |
| Warm p95 | 233.947 ms | 225.695 ms |

The cache-miss path now parses the same bytes used to compute the content
digest. Timings are local observations, not performance thresholds.

## Larger standalone history scan

Run on 2026-09-29 with 1,000 bundles and 5 scans per mode:

```powershell
.venv\Scripts\python.exe scripts\bench_result_bundle_history.py --bundles 1000 --iterations 5
```

```text
bundles=1000 iterations_per_mode=5
scan_validation=all 1000 bundles returned with bundle_status=VALID
cold_ms_p50=2243.479 cold_ms_p95=2394.213
warm_ms_p50=2267.338 warm_ms_p95=2284.422
```

Every cold and warm scan returned the complete expected set and all bundles
verified as `VALID`. Timings are local observations, not performance thresholds.

## Verified raw-evidence byte reuse

Compared the N-039 implementation (which verified raw evidence and then read it
again for metadata) with the raw-evidence callback implementation on 2026-09-29,
using 1,000 bundles and 5 scans per mode. Every scan in both runs returned all
1,000 bundles with `bundle_status=VALID`.

| Measurement | Before | After |
| --- | ---: | ---: |
| Cold p50 | 2125.010 ms | 1994.756 ms |
| Cold p95 | 2248.791 ms | 2122.178 ms |
| Warm p50 | 2137.213 ms | 1955.846 ms |
| Warm p95 | 2169.611 ms | 2007.362 ms |

The verifier still hashes each artifact on every scan. The history reader parses
metadata from the same `raw-evidence.jsonl` bytes after verification, which
removes its second read. Timings are local observations, not performance
thresholds.
