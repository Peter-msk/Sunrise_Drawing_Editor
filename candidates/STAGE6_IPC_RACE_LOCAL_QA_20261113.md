# Stage 6 — DXF→OnMap response IPC race fix / local integration QA

Date: 2026-11-13 (KST). Release state: **HOLD**.

## Scope and source identity
- The GitHub work branch has the P0 response IPC cancellation code change in `drawing_editor/cad_worker.py` and `tests/test_cad_ipc_close_race_stage6.py`.
- Local QA used a separate **reconstructed integration** of the earlier HiDPI source plus P0 worker/catalog/batch/GUI contracts. It is NOT byte-identical to the evolving GitHub work branch; the current branch also has file-signature ownership controls that may not be in the local package.
- Source archive in user conversation: `Sunrise_Drawing_Editor_Stage6_P0_Verified_Local_20261113_SOURCE.zip`; ZIP SHA-256 `220f8d127461e10d1795cafd3d5f2b4e25f486f29a9fbb63d8f7b63cf4d05f15` (231 files, CRC and 230-file manifest verified). **Not for release**.

## Defect and focused change
A user selecting the OnMap PDF while a large DXF child renderer is finishing may close the CAD worker's IPC directory between `response_path.is_file()` and `Path.read_text()` / `Path.read_bytes()`. This can produce `FileNotFoundError`, incorrectly shown as a DXF failure instead of a cancelled stale preview.

The child-process response reader now catches `OSError` / `ValueError`; it converts them to `RenderCancelled` **only when** the session has been closed or a cancellation event is set. Errors without cancellation remain errors. This preserves source-corruption detection.

A deterministic regression deliberately deletes the response immediately before read and verifies `RenderCancelled`, subprocess exit and cleaned private IPC directory.

## Execution evidence (reconstructed Linux, Python 3.13.5)
- Full suite in local integrated working tree: **234/234 PASS**, 24.794 seconds.
- ZIP independently extracted to a fresh directory: **234/234 PASS**, 25.036 seconds, `compileall` PASS.
- Real input DXF: 421,316,933 bytes, 290 layer catalog entries, 2 ON.
- Real DXF subprocess preview followed by **synthetic** 2-OCG OnMap PDF preview, 3 cycles: DXF 2.411 / 1.928 / 1.868 seconds; each child PID exited, DXF and synthetic PDF PNG SHA-256 stable, input file SHA-256 unchanged.
- Real DXF in-flight cancel: 0.000379 seconds for termination request; worker thread returned `RenderCancelled`, process exited, IPC removed, live sessions 0, next synthetic PDF preview 0.009369 seconds.
- Full Linux Qt GUI is **NOT RUN**: PySide6 unavailable. This is NOT the user's original OnMap PDF, NOT Windows Onefile, and NOT the exact GitHub branch code.

## QA gates / next stage
- Obtain a verifiable copy of the latest GitHub work-branch commit and run exact-branch regression tests; avoid replacing the branch with the reconstructed ZIP.
- Windows CMD: `RUN_P0_QA.cmd "D:\\Drawings\\3구간 최종 철탑.dxf" "D:\\Drawings\\실제온맵.pdf"`; then Windows GUI 10 switch/cancel/close cycles.
- Measure selection-to-preview latency, peak parent & child RSS, closed worker PID, OCG OFF→ON pixel parity, light/dark UI DPI 100/125/150/175%, Windows Onefile and SignTool signatures.
- Historical source/output baseline, official GitHub main and Google Drive release remain read-only.
- Latest work-branch progress currently recorded as **55/100**, a development/partial QA measure; release gate not satisfied.
