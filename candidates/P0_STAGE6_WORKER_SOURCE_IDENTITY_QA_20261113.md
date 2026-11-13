# P0 Stage6 — CAD worker source-identity QA checkpoint (2026-11-13)

## Implemented in current work branch
- drawing_editor/cad_worker.py: reuse native child only for matching (resolved DXF path, source size, mtime_ns); different or overwritten DXF asynchronously reaps the old child and creates a new session.
- tests/test_worker_source_identity.py: five checks for same-file reuse, different-file PID turnover, in-place source rewrite, unexpected child exit recovery, original SHA preservation.
- RUN_P0_QA.cmd: five new worker tests added; targeted regression **35 written**, Windows exact-branch execution NOT RUN.

## Executed evidence (local Stage5 replica + Stage6 patch; NOT byte-identical work branch)
- Python 3.13.5 Linux, PyMuPDF 1.26.7, ezdxf 1.4.4, PySide6 unavailable.
- Targeted worker tests 5/5 PASS.
- Local full suite **233/233 PASS**, compileall PASS.
- Actual original 421,316,933-byte DXF, 290 layers, 2 ON: 640x480 preview 2.286s, child RSS after preview 188.1MiB, not peak.
- Switching to another DXF: 0.846s; old child PID ended and cleanup joined.
- Synthetic two-OCG OnMap PDF after workers terminated: 0.005s.
- Original DXF and synthetic PDF SHA256 unchanged.

## Unpassed gates
- **Latest integrated GitHub work branch itself** tests are NOT RUN; do not reuse local PASS as exact branch PASS.
- Real user OnMap PDF, Windows Qt file-selection/cancel/close and actual layer UI, 100-175% DPI, signed PyInstaller Onefile are NOT RUN.
- A second small-DXF target was explicitly rendered via the isolated worker test path to verify child ownership. The GUI routing threshold remains 64MiB; this does not measure GUI's small-DXF path.
- Release HOLD; official main, Drive final and signed EXE unchanged.

## Handoff
Use RUN_P0_QA.cmd from the work branch root on Windows with real DXF and original OnMap PDF. For full suite set RUN_ALL_TESTS=1. Only promote after field QA and signed EXE inspection.

Stage6 development progress (weighted) **55%**, not percentage of Windows runtime acceptance.
