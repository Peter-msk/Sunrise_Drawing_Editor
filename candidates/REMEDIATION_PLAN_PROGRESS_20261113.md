# Sunrise Drawing Editor — P0/P1 통합 보완계획 및 진행률
작성일: 2026-11-13 (KST)

## 기준본
- 공식 main: 2238b4b19bcda690669324de4a68644412ab1e5a (188 test baseline).
- 후보 원본: Sunrise_Drawing_Editor_Render_Icon_HiDPI_20261113_SOURCE.zip (기존 기록: 217 tests).
- 적용 순서: 공식 main → P0 ExactCrop → FourthPass → Preview Recovery → HiDPI → DXF/PDF Theme patch → **본 P0 catalog/batch patch**.
- 본 브랜치는 *패치/QA 작업 브랜치*이다. 누적된 전체 실행 소스나 Windows EXE가 아니다.
- 근거: 실제 사용자가 421MiB 대형 DXF 이후 온맵 PDF로 복귀할 때 미리보기 지연/미표시, 렌더 대기 중 종료 불능, 라이트·다크 대비/아이콘 정렬 문제 보고.

## 진행률 기준 (총 100점)
| 단계 | 배점 | 현재 인정 점수 | 완료 근거 / 미완료 |
|---|---:|---:|---|
| 1. 소스 이력·결함 경계 확정 | 10 | 10 | 누적 패치 문맥 및 호출 경로 정적 감사 |
| 2. P0 렌더 프로세스 격리·취소·종료 | 35 | 22 | 비차단 종료 유지, 실패한 자식 워커 폐기·다음 요청 새 프로세스 복구 코드/시험 작성; 해당 워커 실행 NOT RUN |
| 3. 카탈로그·파일/레이어 생명주기 | 20 | 6 | 제거·재추가 세대 검사 및 PDF 카탈로그 취소, 일괄 export gate 코드 반영 |
| 4. 라이트·다크 테마·아이콘 | 15 | 4 | SVG 40개 존재 및 토큰 대비 정적 점검, 새 7개 시험 작성; Windows 시각 QA NOT RUN |
| 5. 실물 기능/성능/출력 회귀 | 10 | 2 | 실물 421MiB DXF + 합성 온맵 PDF 순차 엔진 3회 / 기존 217개 시험 PASS; 최신 워커·GUI NOT RUN |
| 6. Windows Onefile/서명/배포 판정 | 10 | 0 | NOT RUN |
| **총계** | **100** | **44** | **구현·정적 검토 진행률, 릴리즈 검증 완료율 아님** |

## 패치 1: catalog generation + batch MuPDF gate
- candidates/P0_CATALOG_LIFECYCLE_BATCH_GATE_20261113.patch
- 변경 예정: drawing_editor/window.py, drawing_editor/batch.py
- 새 registration seq와 경로를 동시에 확인해 제거 후 재추가에 이전 metadata가 덮어씌워지지 않도록 한다.
- 오래된 카탈로그는 cancel event를 통해 대기 중인 MuPDF gate 획득을 중단한다.
- batch_export 전체에서 gate를 잡는 대신 한 파일만 처리하는 동안 보유하여 PDF preview/catalog이 파일 사이에 접근할 기회를 제공한다.
- **제한:** 긴 단일 DXF native call을 강제 종료하지 못한다. 이를 해결하는 프로세스 격리 단계는 *미구현*이다.
- static/patch authored, 실제 Python/Qt/Windows 실행 **NOT RUN**.

## 패치 적용/검증 (Windows CMD)
1. 이전 HiDPI 소스를 독립 작업 폴더에 압축 해제, DXF/PDF Theme patch 적용.
2. 본 패치를 같은 작업 폴더에 두고:
   git apply --check P0_CATALOG_LIFECYCLE_BATCH_GATE_20261113.patch
   git apply P0_CATALOG_LIFECYCLE_BATCH_GATE_20261113.patch
3. 본 브랜치의 후보 테스트 파일을 작업 폴더의 tests/test_p0_catalog_batch_gate.py로 복사.
4. python -m unittest discover -s tests -p "test_p0_catalog_batch_gate.py" -v
5. 관련 기존 테스트 + 전체 python -m unittest discover -s tests -v; 이후 Windows RUN_PREVIEW_QA.cmd로 실기.
6. 시나리오: DXF 추가→PDF 선택→DXF 제거→동일 경로 재추가→이전 카탈로그 결과 유입 여부 / PNG 출력 3건을 진행하면서 PDF 미리보기 / 421MiB DXF→온맵 10회 왕복 / 메모리 RSS 및 UI 이벤트 지연.
7. 원본 PDF/DXF SHA 불변, 레이어 표시 픽셀 동일성, canceled task의 재실행·종료 안전성 확인.
8. 결과 없이는 PASS, 배포 완료, 정식 버그 수정 확정이라고 표시하지 않는다.

## 다음 실제 구현 P0 (별도 범위)
- native CAD rendering을 별도 프로세스에 격리; PyMuPDF를 동일 프로세스 다중 스레드에서 병렬 사용하지 않음.
- 프로세스 요청 ID/작업 단위 소유권/레이어 스냅샷/취소·timeout/무응답 종료/다시 시도.
- 기존 ThreePass INSERT·ARC 정확한 페인트 명령, P0 PNG 출력/원본 비파괴 유지.
- 421MiB 실물 DXF와 온맵 PDF의 전환/취소/종료/메모리/픽셀 증거를 확인한 뒤 채택 여부 판단.

## 배포
- GitHub main, Drive 기준본, 배포 EXE 변경 금지.
- 새 코드 조각은 직접 실행해 PASS한 것이 아니라 기존 소스를 분석하여 작성한 **격리 후보**임을 유지.


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
