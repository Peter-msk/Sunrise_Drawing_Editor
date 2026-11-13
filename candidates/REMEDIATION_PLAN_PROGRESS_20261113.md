# Sunrise Drawing Editor — P0/P1 통합 보완계획 및 진행률
작성일: 2026-11-13 (KST)

## 기준본
- 공식 main: 2238b4b19bcda690669324de4a68644412ab1e5a (188 test baseline).
- 후보 원본: Sunrise_Drawing_Editor_Render_Icon_HiDPI_20261113_SOURCE.zip (기존 기록: 217 tests).
- 적용 순서: 공식 main → P0 ExactCrop → FourthPass → Preview Recovery → HiDPI → DXF/PDF Theme patch → **본 P0 catalog/batch patch**.
- 본 브랜치는 누적 변경이 반영된 **개발 후보 통합 소스**이다. Python·Windows 런타임 및 정식 EXE 검증이 완료된 기준본은 아니다.
- 근거: 실제 사용자가 421MiB 대형 DXF 이후 온맵 PDF로 복귀할 때 미리보기 지연/미표시, 렌더 대기 중 종료 불능, 라이트·다크 대비/아이콘 정렬 문제 보고.

## 진행률 기준 (총 100점)
| 단계 | 배점 | 현재 인정 점수 | 완료 근거 / 미완료 |
|---|---:|---:|---|
| 1. 소스 이력·결함 경계 확정 | 10 | 10 | 누적 패치 문맥 및 호출 경로 정적 감사 |
| 2. P0 렌더 프로세스 격리·취소·종료 | 35 | 25 | 대형 DXF 하위 프로세스 유지·취소·원본 변경 감지, 실물 로컬 확인; Windows·정확한 브랜치 전체 실행 미완료 |
| 3. 카탈로그·파일/레이어 생명주기 | 20 | 13 | 파일 등록세대 차단, DXF 워커 소유권을 파일 경로·크기·mtime_ns에 종속, 비정상 종료 후 새 워커 복구 |
| 4. 라이트·다크 테마·아이콘 | 15 | 4 | SVG 40개 존재 및 토큰 대비 정적 점검, 새 7개 시험 작성; Windows 시각 QA NOT RUN |
| 5. 실물 기능/성능/출력 회귀 | 10 | 3 | 로컬 변경 경계 228/228 PASS, 실물 DXF 하위프로세스 취소·정리 PASS(로컬 재현), Windows NOT RUN |
| 6. Windows Onefile/서명/배포 판정 | 10 | 0 | NOT RUN |
| **총계** | **100** | **55** | **구현·실행 가능한 로컬 재현검증 기반의 개발 진행률이며 릴리즈 검증 완료율 아님** |

## 현재 통합 후보 적용과 QA

- 현재 통합 개발 브랜치: `work/p0-render-lifecycle-audit-20261113`.
- P0 등록세대 검사, 파일별 MuPDF gate, 격리 CAD worker, HiDPI와 45개 SVG 자산은 **이미 브랜치 소스에 반영**되었다. 예전 단계 패치를 다시 적용하면 중복·충돌 위험이 있으므로 금지한다.
- 관련 소스: `drawing_editor/cad_worker.py`, `window.py`, `batch.py`, `ui_interaction.py`, `main.py`.
- 실행: Windows CMD에서 해당 브랜치의 작업복사본으로 이동하여 `RUN_P0_QA.cmd` 실행. 원본 파일을 이용할 때 DXF와 PDF 경로를 인수로 주어 10회 엔진시험을 추가한다.
- 신규 대상 시험: 기존 30개 + 이번 소스 동일성/비정상 종료 시험 5개 = **35개 작성**. 정확한 GitHub 브랜치 전체 시험과 Windows GUI는 **NOT RUN**.
- 현재 수정된 소스 및 다른 도면 간 전환에서는 기존 프로세스를 백그라운드 정리하여 네이티브 캐시가 다른 400MiB DXF에 이월되지 않도록 한다.
- 현재 완료되지 않은 P0 검증: **실제 원본 온맵 PDF**, Windows PySide6 UI, DXF 렌더 중 실제 전환·강제 종료, Onefile/SignTool.
- 공식 `main`, Google Drive 기준본과 배포 EXE는 수정하지 않았다. **RELEASE HOLD**.


## Stage 2 implementation checkpoint — 2026-11-13

- Work branch now contains ACTUAL cumulative source files (not only detached patches): `drawing_editor/core.py`, `window.py`, `cad_selective.py`, `trim.py`, `batch.py`, `icons.py`, `ui_interaction.py` and `main.py`.
- New module: `drawing_editor/cad_worker.py`; 64MiB+ DXF preview/detail runs in a persistent child process instead of holding the main application's MuPDF gate.
- Switching to OnMap/small drawing releases even an idle CAD worker. A cancelled render kills its child process, avoiding a native worker blocking subsequent PDF previews.
- 45 HiDPI SVG assets and 12 uncorrupted historical test/quality files have been included. A malformed historical HiDPI test patch was excluded deliberately.
- 7 new worker integration/regression tests: `tests/test_cad_worker_process.py`. Headless real-DXF/OnMap script: `quality/qa_dxf_onmap_handoff.py`.
- Work was verified via source patch context/hunk counts and GitHub branch file fetch. **Python execution, 421MiB field DXF, Windows runtime, DPI, signed Onefile: NOT RUN**.
- QA reference: `candidates/P0_PROCESS_ISOLATION_QA_20261113.md`.
- No official main/Drive deployment. Previously generated hash manifest is historical and not an attestation for this branch.


## Stage 3 checkpoint — 2026-11-13, ~40% implementation progress

- Real follow-on change: `drawing_editor/cad_worker.py` now supports a nonblocking `background=True` reaper; GUI OnMap selection calls `shutdown_all_workers(background=True)` and no longer waits synchronously for a 0.8+0.8 second process termination sequence. Reaper thread is **non-daemon** so cleanup can finish without leaving an orphan on normal interpreter exit.
- Active CAD response polling detects `self.closed` and yields `RenderCancelled`, instead of lingering behind a native subprocess after the GUI switched drawings.
- `tests/test_cad_worker_process.py`: 8 written tests (includes async worker reaping contract).
- `tests/test_p0_catalog_batch_gate.py`: 7 written tests now in discoverable `tests/` rather than only in `candidates/`.
- `tests/test_hidpi_theme_icons_regression.py`: 7 independently authored tests to replace the corrupted historical HiDPI test patch; checks 20 light/dark icon pairs, theme text contrast and raster reuse. It does not claim real Qt visual verification.
- `RUN_P0_QA.cmd`: targeted test runner for these 22 tests, plus optional 10-cycle field DXF→OnMap test; full historical suite only with `RUN_ALL_TESTS=1`.
- `quality/qa_dxf_onmap_handoff.py`: write a failure JSON report even when real QA aborts; RSS clearly identified as **parent process only**, not child peak RSS.
- Pure JavaScript inspection of theme values found light panel/foreground contrast 10.99:1, light muted/panel 5.00:1, dark foreground/panel 12.91:1 and dark muted/panel 7.89:1; rendered Windows colors/contrast not tested.
- **Execution status**: container and Python runtime unavailable in this session; new 22 tests, Windows GUI, 421MiB DXF, real OnMap PDF and Onefile/SignTool are all NOT RUN. Do not use progress percentage as QA PASS.
- Official main, Drive baseline, signed EXE untouched; work only on isolated GitHub branch.


## Stage 4 checkpoint — 2026-11-13; 44% development progress

- Container Python runtime became available. Existing `Sunrise_Drawing_Editor_Render_Icon_HiDPI_20261113_SOURCE.zip`: **217/217 unittest PASS** (21.342 seconds). Not a GitHub work-branch PASS.
- Real user-supplied 421,316,933-byte DXF: quick 290-layer catalog, 2 default ON, ~0.006s. One 640x480 DXF preview 1.705s with peak RSS ~580MiB in that process.
- Real DXF and existing small **synthetic** OnMap 2-OCG PDF sequential preview 3 cycles (DXF 1.1254 / 1.0456 / 0.9702s; OnMap 0.0172 / 0.0201 / 0.0207s). Per-input raster hashes and source hashes unchanged.
- Synthetic OnMap OCG OFF→ON 12 cycles baseline; source image restored identically, ~0.0009s per pair.
- Work-branch P0 change: failed isolated subprocess now always closes and clears its thread-local CAD session. Recovery regression added: missing DXF failure -> valid DXF preview, worker tests now **9 written, NOT RUN**. Total new targeted tests **23 written**, not runtime verified.
- Field evidence: `candidates/FIELD_DXF_SEQUENTIAL_ENGINE_QA_20261113.md`, local detailed JSON file available separately. Current work branch itself not available as a local runnable ZIP; do not equate the sequential baseline pass with child-process or Windows GUI pass.
- Windows PySide6 GUI / actual OnMap original PDF / child-process run / Onefile signed build: **NOT RUN**.


## Stage 5 checkpoint — 2026-11-13; progress 50%

- Local HiDPI baseline + same pure generation fence + behavior-equivalent isolated CAD worker: 228/228 PASS (217 baseline + 6 catalog tests + 5 subprocess tests). Not byte-identical to the exact GitHub branch; Windows GUI NOT RUN.
- Real 421,316,933-byte user DXF, 290 layers, 2 ON: initial isolated preview 2.0456s, child RSS 189.2MiB post render. After closing worker, synthetic OnMap PDF preview 0.0083s.
- Active worker cancellation: cancel signal return 0.0002s, worker thread raised RenderCancelled, child terminated, tracked live sessions zero, source SHA-256 unchanged.
- Synthetic OnMap PDF 120 OCG visibility changes, restored PNG hash 30/30 cycles.
- Fixed ezdxf 1.4.4 regression fixture from missing add_insert method to supported add_blockref method.
- Integrated catalog_result_is_current into drawing_editor/ui_interaction.py and window.py success/error paths; added tests/test_catalog_generation_semantics.py (7 tests: 6 pure, 1 static GUI contract).
- Repaired stale text assertions in tests/test_p0_catalog_batch_gate.py; RUN_P0_QA.cmd includes four targeted test groups and optional real DXF/PDF step.
- Current branch: 30 targeted tests WRITTEN, NOT RUN as the exact integrated GitHub source. Local 228 PASS is not branch-wide PASS.
- Official main, Drive, signed EXE unchanged. RELEASE HOLD.


## Stage 6 checkpoint — 2026-11-13; progress 55%

- Local base is a **Stage5 runnable replica**, not the exact cumulative GitHub branch. Current local Stage6 source changes `cad_worker.py` to bind a reusable native child to (resolved path, file size, mtime_ns). Any other DXF or edited same-path DXF starts in a fresh process and the previous worker is asynchronously reaped.
- New runtime tests `tests/test_worker_source_identity.py` (5); authored in the GitHub branch. Behavior-equivalent local tests 5/5 PASS.
- Local full regression 233/233 PASS (228 Stage5 baseline + 5 new). Python compileall PASS. **Does not certify exact GitHub branch**.
- Actual 421,316,933-byte original DXF and two additional fixtures: first isolated 640x480 preview 2.286s; child RSS after render 188.1MiB; switching to other DXF disposed old PID; synthetic OnMap PDF preview after worker cleanup 0.005s; original DXF and synthetic PDF SHA256 unchanged.
- `RUN_P0_QA.cmd` updated to include new worker identity tests, 35 authored targeted cases total; Windows tests NOT RUN.
- WARNING: local source-identity patch is against local Stage5 worker replica and should not be applied directly to the GitHub branch. The current GitHub branch code is authoritative; its worker and test changes were committed separately.
- Next gates: exact branch full test; real user OnMap PDF; Windows UI file-switch cancellation, DPI 100/125/150/175; Onefile/SignTool QA.
