## Admin Sidebar Static Handling Fix

- [ ] Define a `SERVE_STATIC_VIA_DJANGO` flag in `rd1web/rd1web/settings.py` with a sensible default.
- [ ] Update `rd1web/rd1web/asgi.py` to use the new flag when deciding to wrap the app with `ASGIStaticFilesHandler`.
- [ ] Verify settings to ensure the new flag keeps static assets working on all worker ports.

## RMA Test Log Cleanup Plan

- [x] Inspect `/srv/rma-b31/*/test_results.log` layout to understand target files without altering mtimes.
- [x] Decide on safe editing approach that removes trailing `DCGM LC/AC test Finished` lines only when preceded by matching failures.
- [x] Execute the cleanup across all matching logs while preserving original mtimes.
- [x] Re-verify a sample of edited logs to confirm formatting and timestamps remain unchanged.

## Investigate DCGM Failure Count

- [ ] Reproduce the RMA statistics view/API output to confirm `dcgm_test` failure count is zero.
- [ ] Trace how `test_results` data is parsed and stored to ensure DCGM failures register correctly.
- [ ] Identify mismatches between log patterns, database records, and UI aggregation causing zero counts.
- [ ] Propose and validate a fix (code or data) so DCGM failures appear in statistics.

## RMA Scanner Refresh Logic

- [x] Review `scan_rma_directory` skip logic to understand current mtime-only behavior.
- [x] Design an updated change-detection strategy (e.g., file size/hash) that lets us re-parse logs when contents change but mtime stays the same.
- [x] Implement the new detection mechanism with minimal disruption and add logging/tests if needed.
- [x] Verify by re-running the scanner on sample directories to ensure updated stats.

## DCGM Finished Line Sweep

- [ ] Enumerate all `/srv/rma-b31/*/test_results.log` files whose most recent DCGM entry is `Failed`.
- [ ] Detect any lingering `DCGM LC/AC test Finished` lines in those logs, regardless of position.
- [ ] Remove the `Finished` lines while preserving mtimes and re-check affected logs.
- [ ] Reconfirm a few sample directories and rerun statistics to ensure counts reflect new failures.

## MI300 All Log Button Logic

- [ ] Locate the MI300 log-table or button component in the frontend and note the handler entrypoint.
- [ ] Trace the backend/API endpoint (or Redux/query hook) that feeds the button and summarize its logic.
- [ ] Verify any related Django/REST handlers or services that compute the "all log" data and describe how they work.

## Generate Requirements.txt

- [x] Review current requirements.txt and identify missing dependencies
- [x] Check installed packages in venv to find what's actually used
- [x] Add missing critical packages (daphne, fabric) to requirements.txt
- [x] Organize requirements.txt with comments for better maintainability
- [x] Verify all dependencies are included
