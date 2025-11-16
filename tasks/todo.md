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

## RMA GPU All Log Test Item

- [x] Mirror this RMA GPU All Log plan into `tasks/todo.md` with a checkbox TODO list to track implementation steps.
- [ ] Add an `All Log` test choice to `RmaForm.tests` and the `rma_pxe.html` Tests UI, with JS to show it only for MI300X/MI325X/MI355X images and to make it mutually exclusive with other tests/fw_update.
- [ ] Add a new `rma_collect_mi3xx_alllog_from_form` endpoint in `rma_logs.py` plus URL in `pxe/urls.py` that uses `collect_mi3xx_alllog_task` with base SN, RMA number, and BMC IP from the form, creating `{base_sn}_{rma_number}` under `RMA_BASE_DIR` if needed.
- [ ] Refactor MI3XX ALL LOG modal/JS into shared code and wire the RMA GPU page to call the new endpoint, display progress, and redirect to the `{base_sn}_{rma_number}` RMA logs directory on success.
- [ ] Manually test the All Log flow for MI300X/MI325X/MI355X images, verifying logs are stored correctly, redirect works, and no PXE DB entries are written when All Log is selected.

