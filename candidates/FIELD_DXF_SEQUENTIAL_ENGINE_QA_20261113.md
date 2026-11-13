# P0 421MiB DXF -> synthetic OnMap sequential-engine verification
**Date:** 2026-11-13 (KST). **Status:** PASS, *sequential engine only*.

## Inputs and environment
- Real user-provided DXF: 421,316,933 bytes; 290 source layers; two default ON. Original drawing file was read-only.
- PDF: existing small **synthetic OnMap fixture with 2 OCGs**, **not** the original user OnMap PDF.
- Python 3.13.5 / Linux; PyMuPDF 1.26.7; ezdxf 1.4.4.
- Render source: `Sunrise_Drawing_Editor_Render_Icon_HiDPI_20261113_SOURCE.zip`, **not** the latest work branch.
- Prior baseline suite executed **217 / 217 PASS**.
- Quick DXF layer catalog: ~0.006s, no full-parser fallback.
- A single cold DXF preview: 1.705s with peak process RSS ~580MiB (separate process/run measurement; peak, not retained RSS).
- Three DXF -> synthetic OnMap sequential render cycles at 640x480:
  - #1 DXF 1.1254s / OnMap 0.0172s
  - #2 DXF 1.0456s / OnMap 0.0201s
  - #3 DXF 0.9702s / OnMap 0.0207s
- The three DXF PNG SHA-256 values were identical, the three OnMap PNG SHA-256 values were identical, and source SHA-256 before/after were equal.
- Synthetic OnMap OCG layer OFF -> ON repeated 12 times. Original display was restored with identical raster hash after each cycle. Average per OFF/ON pair ~0.0009s in baseline.
- The local detailed JSON is `Sunrise_Drawing_Editor_Field_DXF_Sequential_QA_20261113.json` (local sandbox artifact; not attached to public repo to avoid publishing source hashes).

## Interpretation
- The **sequential CAD/PDF engine path** can produce repeatable images from the large DXF and synthetic OCG PDF.
- This does **not** reproduce or certify the earlier Windows PySide6 race (QThreadPool, file-switch, cancellation or concurrency).
- The current `drawing_editor/cad_worker.py` isolated-process implementation and new regression tests were **NOT RUN** in this measurement. No Windows PySide6 installed in the sandbox.
- No signed Windows EXE, actual OnMap source PDF, or 100/125/150/175% UI screenshots were run.

## Follow-on P0 change
- On child renderer error, `render_isolated()` now closes the potentially tainted child process and clears the thread-local session so a later preview starts with fresh state.
- `tests/test_cad_worker_process.py` has a newly authored missing-DXF -> valid-DXF recovery test (9 total worker tests). Latest branch runtime execution remains **NOT RUN**.

**Do not promote the GitHub work branch or main until isolated worker, real OnMap, GUI cancel, Windows Onefile and signer QA pass.**
