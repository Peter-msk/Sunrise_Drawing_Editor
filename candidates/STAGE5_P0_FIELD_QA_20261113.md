# Sunrise Drawing Editor — Stage5 P0 process + catalog execution evidence

Date (KST): 2026-11-13

## Changes written to this branch
- Integrated registration-generation ownership helper in drawing_editor/ui_interaction.py and applied it to both catalog success and catalog error callbacks in drawing_editor/window.py.
- Added tests/test_catalog_generation_semantics.py: 7 regression cases, including six pure behavior tests and a source contract checking both callbacks.
- Fixed tests/test_cad_worker_process.py: ezdxf 1.4.4 uses modelspace().add_blockref() to create DXF INSERT entities, not add_insert().
- Updated tests/test_p0_catalog_batch_gate.py source assertions to reflect the shared generation predicate.
- Updated RUN_P0_QA.cmd to include new catalog race tests; written targeted test count now 30.

## Actually executed in Linux
- Source under test: prior HiDPI ZIP + matching catalog helper + locally reconstructed isolated worker, NOT the exact bytes of the current GitHub branch.
- Full suite 228/228 PASS (previous 217 + six catalog predicate + five isolated child-process tests).
- Real original 421,316,933-byte DXF (290 layers, 2 default ON), isolated process preview 2.0456s at 800x600 pixels.
- Child RSS after preview ~189.2 MiB. This is a post-render reading, not a peak measurement.
- After terminating the DXF worker, synthetic OnMap PDF preview 0.0083s.
- Active DXF worker cancellation request returned in ~0.0002s; worker returned RenderCancelled, child exited, zero tracked worker sessions; original DXF and synthetic PDF source hashes unchanged.
- Synthetic OnMap 2-OCG PDF: 120 visibility changes and 30 restoration checks preserved output PNG hash.

## Important distinctions
- The latest GitHub branch itself, its exact child worker bytes, and the Windows Qt GUI have NOT been executed in this verification.
- No real source OnMap PDF was available. Do not extrapolate performance from the tiny synthetic PDF.
- The user-supplied DXF was read in a Linux sandbox; no original file modifications.
- Do not claim 228/228 is the GitHub work-branch pass or a Windows Onefile pass.

## Next gate
1. On Windows CMD, run RUN_P0_QA.cmd with real DXF/PDF paths (targeted 30 regression tests + real-file handoff).
2. Force a native CAD render to be in progress, select OnMap, verify user-visible preview, cancel, exit, child PID cleanup.
3. Verify OCG ON/OFF and original PDF output pixel identity after switching repeatedly.
4. Validate DPI 100/125/150/175% and light/dark text/icon bounds in real PySide6 GUI.
5. Only after current-branch tests PASS, run BUILD_ONEFILE.cmd and SignTool QA; official main/Drive remain untouched.

Development progress (weighted) = 50/100. This is NOT a release approval; RELEASE HOLD.
