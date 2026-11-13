# Sunrise Drawing Editor — P0 Child Renderer Candidate QA (2026-11-13)

## Status
- SOURCE CANDIDATE / **NOT RELEASE APPROVED**.
- Branch: `work/p0-render-lifecycle-audit-20261113`.
- Official `main` and Google Drive final baseline remain unchanged.
- Code path: `drawing_editor/cad_worker.py` + `window.py` + `main.py`, plus P0 catalog-gate changes.
- The source tree now includes cumulative P0/4th pass/recovery/HiDPI/switch code and 45 SVG assets.
- Python execution, Windows PySide6/Onefile and 421MiB input runtime are **NOT RUN** due tool execution environment unavailable.
- Historic `SOURCE_SHA256_MANIFEST.json` is NOT a hash manifest for this work branch. Generate a new file hash manifest only after a successful Windows run and approved candidate selection.

## Why subprocess isolation?
`QThreadPool(max=1)` plus native MuPDF can leave a preview busy even after `Event.set()` because a blocking C call cannot cooperatively poll the event. A 421MiB DXF child process can be terminated without killing the Qt GUI process. PyMuPDF PDFs are not shared across processes.

## Process contract
- `.dxf` and `size >= 64MiB` => isolated preview/detail; other PDFs and small CAD keep current paths.
- Same preview worker thread owns the reusable child and private temporary IPC directory.
- Only primitive JSON arguments + PNG bytes / page dimensions cross the process boundary.
- Each child request writes `request-NNNNNNNNN.json`; completion writes image first and atomically replaces `response-NNNNNNNNN.json`.
- No file overwrite of source data; requested PNG stays under a private temporary directory.
- Worker has a 180-second per-render timeout, 120-second idle exit and max 96MiB PNG response limit.
- Cancellation terminates the child, then returns `RenderCancelled`; the next request can spawn a new process.
- Switching to a PDF or small file releases even an idle child to reclaim the decoded CAD model.
- GUI close / approved emergency exit cleans child processes first.
- PyInstaller Onefile child uses `sys.executable --cad-worker`; unfrozen Python uses `-m drawing_editor.cad_worker`.
- These are intended contracts; **runtime behavior is not yet verified**.

## Stage 3 changes and test sequence
- File selection now calls `shutdown_all_workers(background=True)` so Qt does not synchronously wait for the native DXF subprocess to finish.
- A non-daemon reaper performs bounded wait/kill and temporary-file cleanup.
- `tests/test_cad_worker_process.py` now has 8 tests, including async-reaper cleanup contract.
- Integrated catalog/batch-gate tests: `tests/test_p0_catalog_batch_gate.py` (7 tests).
- Independent HiDPI/theme tests: `tests/test_hidpi_theme_icons_regression.py` (7 tests).
- Run `RUN_P0_QA.cmd` (no arguments = targeted tests only), or:
  `RUN_P0_QA.cmd "D:\\Drawings\\3구간 최종 철탑.dxf" "D:\\Drawings\\온맵원본.pdf"`
  to include the 10-cycle engine-only real-DXF→OnMap check.
- `RUN_ALL_TESTS=1` enables the legacy full suite deliberately, never automatically.
- All 22 new tests are **WRITTEN / NOT RUN** in this environment. The Windows GUI still needs manual DPIs and close/cancel action testing.
- The QA tool reports parent RSS only, and persists FAIL JSON on exceptions.

## Windows CMD QA steps
1. In an isolated work copy at the candidate branch, ensure runtime deps are installed and `RUN.cmd` launches.
2. `python -m unittest tests.test_cad_worker_process -v`
3. `python -m unittest discover -s tests -v` (run when the changed engine and application are present, before packaging)
4. `python quality\qa_dxf_onmap_handoff.py "D:\Drawings\3구간 최종 철탑.dxf" "D:\Drawings\B090온맵원본.pdf" --repeats 10 --report "D:\QA\DXF_ONMAP_HANDOFF.json"`
5. Test GUI DXF→OnMap 10 times with ~421,316,933 byte real DXF; use OnMap OCG toggles, large INSERT and 16,692 circle/arc scenario, clip zoom, cancelled preview and exit while busy.
6. Verify the OnMap preview never shows a stale DXF image, DXF worker process PID is gone after OnMap selection, and original DXF/PDF hashes are unchanged.
7. Measure median and P95 selection-to-preview, peak process/child RSS, worker startup cost, second-render cached cost and full-handoff time.
8. Test light/dark + Windows DPI 100/125/150/175% separately. Screenshot and compare icon/text alignment.
9. Test `BUILD_ONEFILE.cmd` with approved Windows SDK / SignTool. Signed Onefile worker dispatch, both `--self-test` and `--cad-worker` require real Windows verification.

## Known gaps / gates
- Real native render kill inside the child and verified child process cleanup: NOT RUN.
- Old `tests/test_hidpi_tile_icons_20261113.py` patch is malformed (declares 98 new lines but only 96 provided); deliberately excluded from the candidate. Recreate independently, never fabricate lost lines.
- A single large CAD *batch export* still uses GUI process MuPDF with per-file gate release. Full export process isolation is a separate P1 task.
- DXF small-file and DWG native conversion are not isolated; keep existing worker semantics until separate evidence.
- No automatic GitHub actions initiated, and no official main / signed release promoted.

## Gate to approve source
- New child-worker tests PASS, full relevant regression PASS.
- Real input DXF/OnMap report PASS and no stale/orphan process, hash mismatch or display corruption.
- Windows GUI close/cancel test PASS.
- Windows onefile build and signature gate PASS.
- Reviewer explicitly approves baseline update.
