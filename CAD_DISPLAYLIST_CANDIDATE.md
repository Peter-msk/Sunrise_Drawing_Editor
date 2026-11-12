# CAD PDF repeated viewport display-list candidate

Status: **experimental / not runtime-validated**. Previous official main is unchanged.

## Specific source bottleneck
The ThreePass core barred DisplayList reuse when the original DXF exceeded 96 MiB, even if the selected-layer PDF was small. Thus a 402 MiB mostly-hidden DXF repeatedly decoded the current PDF's path commands for every new pan/zoom clip.

## Proposed, narrowly scoped improvement
- Allow one DisplayList for the **current staged PDF** only if the staged PDF is at most 2 MiB and the selected entity count is at most 512.
- Build only on the second distinct preview clip for the same drawing state; avoid one-off list construction.
- Retain ownership in the existing worker and invalidate immediately on layer/document changes.
- Disable retries after a DisplayList allocation/renderer exception for the same state.
- Leave all JPEG/PNG export paths, source coordinates, shapes, DPI settings, and Qt/CMD build scripts unchanged.

## Evidence and validation boundary
Static source patch guards: PASS. **Python syntax/engine tests: NOT RUN** because the attached-file execution environment was unavailable in this task. Real 402 MiB DXF before/after time, pixel equivalence, Windows GUI and Onefile signing: **NOT RUN**. No performance claim is made. Do not promote this branch to main until tests and DXF field checks pass.

## Required local verification
1. RUN_TESTS.cmd
2. python quality/validate_three_pass.py "D:\\Drawings\\3구간 최종 철탑.dxf" --output QA_report.json --artifacts QA_images
3. Check basic preview / arc-heavy layer / INSERT ON and OFF / repeated clips.
4. Compare RGB pixel SHA-256 and RSS peak versus unchanged ThreePass source.
5. BUILD_ONEFILE.cmd (uses CMD only; no venv or PowerShell).
