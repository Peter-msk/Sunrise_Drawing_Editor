# Stage 8 — UI/UX audit, local regression and Google Drive handover

Date: 2026-11-14 KST. **RELEASE HOLD / candidate only.**

## Actual GitHub changes
- Work branch: `work/p0-render-lifecycle-audit-20261113` (never merged into official main).
- Code/visual changes: `drawing_editor/window.py` generic light/dark QSS fallback reordered before semantic header/hint labels, explicit disabled text style maintained; 14 light/dark SVG assets optically centered without altering 24×24 viewBox or stroke colors.
- New `tests/test_ui_optical_alignment_stage8.py`: four static/optical checks, CairoSVG optional.
- New `quality/qa_windows_ui_capture_stage8.py`: save Windows Qt Light/Dark screenshots for 100/125/150/175% scaling. **NOT RUN on Windows.**
- Code-bearing GitHub commit before this report: `29d2bc50b36e5808af5e7da270fdc4f544c3c025`.

## Verification scope
- The locally mounted `Sunrise_Drawing_Editor_Stage6_P0_Verified_Local_20261113_SOURCE.zip` was independently extracted and amended with Stage8 QSS + 14 SVG + 4 regressions and a Windows QA capture script.
- Local Linux Python 3.13.5 full unittest: **238/238 PASS** (39.421s); new optical static regression: **4/4 PASS**; package ZIP CRC + per-file SHA-256: **PASS**.
- This locally tested source is **NOT byte-identical to the current GitHub branch** (notably core/worker/window/main differ). The above PASS does NOT certify full integrated branch.
- Exact branch test, Windows PySide6 screenshots, user's actual OnMap PDF, 421MiB DXF Windows GUI switch, Onefile signing/installer: **NOT RUN**.
- Product release approval: **HOLD**, official main and prior EXE unchanged.

## Candidate ZIP
- File: `Sunrise_Drawing_Editor_STAGE8_20261114_LOCAL_UIQA_CANDIDATE_SOURCE.zip`
- Size 442,308 bytes, 222 source files + SHA manifest/handover materials.
- SHA-256: `34f8b9c07617e41caf1b1a11f167a1763f263c0a2fab399761b25e0bf3134f65`
- **NOT production release; do not overwrite the authoritative GitHub branch with this ZIP.**
- Original user DXF and OnMap PDF are not packaged.

## Verified Google Drive handover
Folder: https://drive.google.com/drive/folders/15je9J8dhp848Z9wKPAXm2sn5Y7TRbGRc

1. ZIP: https://drive.google.com/file/d/1PEITfEsf0y8oa2l1MG0VprebRyGk9mD7/view
2. Handover: https://drive.google.com/file/d/1IdO_k3gKe2sb-qsSyLv7Db57q2V3qKEU/view
3. Work instructions: https://drive.google.com/file/d/1IRhUb091rLYmG9kIJCpkWfDIWeDxBm-m/view
4. Development plan: https://drive.google.com/file/d/18jYxO5GQUI5-O1IkHJ93bzX4rtBg5Sss/view
5. QA JSON: https://drive.google.com/file/d/1kUqjUvHs-_YRV16IrkgZcRQ5NlOneF-L/view

Upload and Drive folder read-back: 5/5 verified.

## Next mandatory gates
1. On Windows clone exact GitHub work branch and run `quality/qa_exact_branch.py` then `RUN_P0_QA.cmd`.
2. Test 421MiB real DXF -> original OnMap PDF 10× and OCG OFF/ON 30×; verify no stale preview, child PID, input hash changes or memory leak.
3. Windows 100/125/150/175% Light/Dark screenshot comparison; adjust and retest any visible clipping/contrast failures.
4. Full exact-branch regression and Windows Onefile/SignTool build and smoke with approved sign key; explicit release approval only afterward.
