# Sunrise Drawing Editor — 개발·검증 기록

## 구현 변경

- Windows `PyInstaller --onefile --windowed` **빌드 스크립트** 및 패키징 후 `--self-test` 추가
- Sunrise Group(주체 `CN=Sunrise Group`) 인증서 검색 → 없으면 로컬 자체서명 인증서 생성 → Authenticode SHA-256 서명 → 게시자/해시 확인
- 실제 비공개 PFX를 제공하면 환경변수로 사용; 서명키/암호는 소스와 ZIP에 포함하지 않음
- 공지사항·자동업데이트 기능 없음, 배포 EXE에 제품 버전 표기 없음
- 파일 목록 빠른 등록, GUI가 전체 CAD 객체를 보존하지 않는 **메타데이터 전용 DrawingState** 신규 적용
- 무거운 도면 메타데이터 작업은 **전용 1-worker 스레드 풀**에서 순차 처리. 완료 전 레이어 적용/추출 차단
- CAD 레이어 조합 PDF 중간 렌더 LRU 캐시(최대 3개/96MiB, 항목당 64MiB 이하)
- DWG: ODA가 없는 경우 별도 설치 LibreCAD의 `dwg2dxf` CLI를 선택적 사용; 파일 기반 임시 결과 생성 후 삭제
- 기존 온맵 PDF OCG/미리보기 확대/대용량 PNG·JPG 타일/일괄 레이어 규칙·선택 추출 유지

## 확인된 항목

| 구분 | 상태 | 증거 |
|---|---|---|
| Python 문법/compileall | PASS | 모든 소스 import-independent compile |
| 전체 엔진 회귀 테스트 | **51/51 PASS** | `python -m unittest discover -s tests -q` |
| 대용량 6438×9308 px 타일 출력 | PASS | 기존 회귀시험 유지 |
| CAD 레이어 조합 캐시 재사용 | PASS | 동일 조합 복귀 시 PDF backend 재실행 횟수 유지 |
| GUI 경량 메타데이터 상태모델 | PASS | 40개 경로 등록·규칙 적용·잠금 상태 단위시험 |
| LibreCAD CLI 결합·원본 비파괴 | PASS | 합성 외부 실행파일로 DXF 변환 계약 확인 |
| ZIP 구조·CRC·SHA | PASS | 완료 후 별도 해시 매니페스트 생성 |

## 미실행 항목 — 절대 PASS로 승격하지 않음

| 구분 | 상태 | 이유 |
|---|---|---|
| Windows 네이티브 onefile EXE | NOT RUN | 작성 환경 Linux, PyInstaller는 Windows EXE 교차빌드 불가 |
| PySide6 실제 GUI / 테마 / 확대 | NOT RUN | GUI 런타임 미설치 |
| Windows `BUILD_ONEFILE.cmd`의 SignTool 서명 및 검증 | NOT RUN | Windows 인증서 저장소/SignTool 코드서명 미실행 |
| 100/300/500MB 실물 DWG·DXF | NOT RUN | 실물 대용량 도면 미제공 |
| LibreCAD DWGSUPPORT 실제 Windows 빌드 | NOT RUN | Windows LibreCAD 외부 실행파일 미제공 |
| 공식 재배포 라이선스 검토 | PENDING | PyMuPDF AGPL/상용, PySide6 LGPL/상용 규정 확인 필요 |

## Windows 배포 전 확인

1. Windows에서 `BUILD_ONEFILE.cmd` 실행하여 **onefile EXE 생성·기동 성공** 확인.
2. CMD의 `signtool verify /pa /v "dist\Sunrise Drawing Editor.exe"`로 확인하는 서명 주체 `CN=Sunrise Group` 확인. 자체서명인 경우 신뢰된 공인 게시자 서명으로 표시하지 말 것.
3. `dist\SHA256.txt`와 배포 EXE 해시 대조.
4. 실제 100/300/500MB DXF/DWG에서 열기 시간·렌더링 FPS·최대 메모리·취소 및 특수객체 누락 검증.
5. 외부 배포 전 AGPL/상용 라이선스·LGPL 의무 충족.

## 추가 CAD 렌더링 재사용 검증

- 기존 41개 + 신규 5개 자동시험 = **46/46 PASS**
- `ezdxf` 디스플레이 명령을 한 번 기록한 뒤 레이어 필터로 재생. 레이어 교체 후 전체 CAD 파싱 재수행 억제
- 초기 숨김 레이어, INSERT 포함 도면, 캐시 초과 폴백, 확대 클립, 원본 파일 해시 보존 시험 PASS
- 합성 5,000/20,000 객체 전후 중앙값은 `CAD_RENDER_OPTIMIZATION.md` 참조
- 실제 Windows GUI 및 실물 100~500MB DXF/DWG는 여전히 NOT RUN

## CAD 내부 PDF OCG 재사용 최적화 — 신규 검증

- 기존 46개 + 신규 5개 = **51/51 PASS**.
- PDF OCG 레이어 재사용 및 레이어별 바운딩 범위 판정. 바운딩 변화 시 이전 정확 경로로 자동 복귀.
- 5,000개/20,000개 합성 CAD: 실제 Layer_0 OFF 변환 시간 전후 측정. 기존과 개선 후의 렌더링 출력 8/8 픽셀 해시 일치.
- 측정·회귀 검증 기록은 `CAD_NATIVE_LAYER_OPTIMIZATION.md` 및 `quality/CAD_OCG_*` 참조.
- 실제 100/300/500MB DWG·DXF 및 Windows EXE·GUI·서명은 여전히 **NOT RUN**.

## 최신 추가 검증 — ASCII DXF 경량 카탈로그·대용량 가시영역 렌더

- 기존 51개 회귀시험 + 신규 7개 = **58/58 PASS** (`quality/CAD_LARGE_OPT_TESTS.log`).
- ASCII DXF LAYER 테이블 단독 메타데이터 추출 4개 시험: 기존 full parser와 레이어명/표시상태 동일, 한글 레이어명, 잘못된 원본 폴백, 제한 구간 파싱 PASS.
- 대용량 CAD 가시영역 렌더링 3개 시험: 8,800개 이상의 단순 도형 인덱스, 복합 객체(INSERT/TEXT) 유지, 원본 SHA256 불변 및 확대 클립 픽셀 비교, 인덱스 실패 시 전체 렌더 폴백 PASS.
- 부하 시험 8,000·24,000 객체, 두 클립 영역 모두 원래 전체 렌더와 픽셀 동일: `quality/LARGE_CAD_BENCHMARK.json`.
- 경계 렌더 캐시가 존재할 때 공간 필터링을 건너뛰고 더 빠른 기존 MuPDF 클립을 사용하도록 가드 추가.
- 대용량 출력 타일 PNG/JPG, 41개 기존 시험, 51개 중간 시험의 정상 경로 유지.
- Windows GUI/EXE/서명 및 라이브러리 실물 100~500MB DXF/DWG는 **NOT RUN**.

## CMD 전용 Onefile 빌드 재감사

- `BUILD_ONEFILE.cmd` 외 PowerShell `.ps1` 파일 제거. Python 3.11 고정과 가상환경 요구 제거.
- `INSTALL_AND_RUN.cmd`, `RUN.cmd`, `RUN_TESTS.cmd`로 실행 도구를 통일.
- `PySide6-Essentials` 도입, 미사용 WebEngine/Pdf 배포 제외.
- SignTool/CertUtil 기반 Sunrise Group 서명 및 실패 차단 추가.
- 상세 근거는 `BUILD_AUDIT.md` / `build/WINDOWS_BUILD_CHECKLIST.md`.
- **Windows 실제 exe/서명: NOT RUN. Linux에서 진행한 스크립트·엔진 단위시험을 Windows 실제 실행 PASS로 표시하지 않음.**


## Current renderer and export-resolution upgrade (2026-11-12)

- Base archive: `Sunrise_Drawing_Editor_QtFix.zip`. Existing CMD-only onefile, PySide6-only packaging, and Sunrise Group SignTool workflow preserved.
- Default output remains original-auto; selectable HD/FHD/QHD/4K upper bounds, custom maximum W/H, and manually specified DPI were added.
- Repeat preview caching now reuses the same image **and** page dimensions, without regenerating intermediate CAD/PDF page context for identical inputs.
- For >12MP export, full-width clipped stripes are used whenever they fit the RGB render-memory budget; extremely wide outputs use the existing multi-column fallback.
- Source compileall: PASS.
- Unit tests: **86/86 PASS** (77 prior + 9 new). Test log `quality/RENDER_EXPORT_UNITTESTS.log`.
- Synthetic page benchmark: `quality/EXPORT_STRIPE_BENCHMARK.json`. Median 0.28223 sec old vs 0.19766 sec new, 35 vs 7 get_pixmap() calls. Differences compared against reference full page captured in benchmark.
- Windows Onefile generation / signed EXE / actual PySide6 GUI / 100MB+ real DXF or DWG: **NOT RUN** in this Linux runtime. A GUI dependency installation was attempted but unavailable. This is not a Windows release PASS.


## GitHub 공개소스 기반 스트리밍 출력 최적화 (2026-11-12)

- PyMuPDF DisplayList 재사용, PNG 일괄 zlib 압축, RGB 연속 메모리 복사, JPG scratch mmap flush 생략.
- 전체 자동시험: **92/92 PASS** (기존 86+신규 6).
- 전후 속도 및 픽셀 비교: `quality/GITHUB_OPTIMIZATION_BENCHMARK.json`. 원본 PDF SHA-256 변경 없음.
- 실제 Windows GUI·onefile SignTool·실물 100MB 이상 DWG/DXF는 **NOT RUN**.
- 추가 네이티브 DLL을 도입하지 않았고 빌드 스크립트는 CMD만 유지.

## 2026-11-12 사용자 실물 DXF INSERT 병목 재검증

- 첨부 `3구간 최종 철탑.dxf` 실제 엔진에서 INSERT 레이어 최초 ON 8.6257초 → 3.5378초 단일 실행 관측. 초기·ON·OFF 픽셀 해시 모두 이전 코드와 일치.
- PyMuPDF의 반복 선 PDF 콘텐츠 스트림을 기존 구현과 **바이트 단위 일치**하는 상태로 생성하는 회귀시험 추가.
- 임시 DXF만 변경, 원본 SHA-256 동일. 신규 Windows EXE, 코드서명 실제 실행은 NOT RUN.
- 상세 보고서: `FIELD_DXF_INSERT_OPTIMIZATION.md`.

## UI/UX 재감사 및 개선 검증본 (2026-11-12)

- 이전 실제 402MiB DXF 및 INSERT 최적화 기준본 위에 `drawing_editor/window.py` UI만 조정, 새로운 SVG 아이콘 14개 추가.
- 좌측 도면 선택 현황, 가운데 레이어 검색·가시성·저장 규칙, 우측 미리보기 페이지/확대·맞춤 조작, 하단 원본 자동/지정 해상도·출력 버튼을 재배치.
- 최소 창 970×510 논리 픽셀, 사용 가능 화면 크기에 맞춘 초기 창 크기, 좁은 창 패널 220/320 논리 픽셀.
- 기능/빌드 112개 회귀시험 + 신규 UI 정적 계약 12개 = **124 / 124 PASS**. 전체 재실행 기록: `quality/UI_CONTRACT_TESTS.log`.
- **Windows PySide6 실제 창/150~175% DPI, Onefile EXE/서명: NOT RUN (Linux에 Qt 미설치, 패키지 설치 불가).** 코드/아이콘/정적 계약 검사를 GUI 시각검증으로 혼동하지 않습니다.
- GitHub main, Google Drive 원격 공식 ZIP은 본 개선 요청만으로 갱신하지 않습니다.

## 심층 1·2·3차 DXF 최적화 회귀검증 — 2026-11-12

- `python -m unittest discover -s tests -q`: **131/131 PASS**.
- `quality/BASELINE_REAL_VALIDATION.json` vs `quality/OPTIMIZED_REAL_RELEASE_VALIDATION.json`: 실물 DXF 기본/INSERT/추가 폴리라인/복원/줌 RGB 픽셀 해시 모두 일치, FHD PNG/JPG·25MP 타일 PNG 결과 파일 SHA-256 일치, 원본 해시 무변경.
- 큰 원호 레이어 PDF 콘텐츠 해시 동일, 경로 명령 출력 최적화 검증. 실제 402MB에서 Windows GUI/Onefile/서명 **NOT RUN**.
- 성능/메모리 측정과 한계: `THREE_PASS_DEEP_VALIDATION.md`.


## PNG transparent RGBA stage / UI render refinement (2026-11-12)
- Existing UI/UX Stage 2+3 baseline preserved. New changes to GUI, zoom policy, PNG export, and standalone QA.
- Pure Python engine/test suite: 180/180 PASS (Python 3.13.5, Linux).
- Small RGBA PNG and >12 MP tiled RGBA both produce true transparent page regions; painted white source geometry stays opaque.
- Original opaque PNG/JPEG file-by-file SHA-256 identical to prior ZIP sample.
- Windows PySide6 GUI 100–175% DPI, Windows onefile/signature, source OnMap PDFs provided only as screenshots: NOT RUN.
- The test does NOT mean the actual user OnMap map's white painted page content has been removed. Only transparent page background is affected.


## 온맵 PNG 외곽 흰 여백 제거 (2026-11-12 개발 후보)

- **PNG** 기본 UI 선택: `투명 배경` + `흰 여백 제거`(각각 개별 선택 가능). JPG는 기존 불투명 전체 용지 출력 정책 유지.
- 기존 `원본 자동`은 래스터 원본 밀도/벡터 300 DPI 유지; 여백 제거는 표시 내용의 **외곽 용지 영역만 제외**하며 원본 PDF/DXF 좌표나 내용은 수정하지 않음.
- GUI 선택 여부와 별개로 Python API `OutputOptions()`는 `crop_margins=False`로 유지하여 기존 출력 호환성 보장.
- 12MP 이하: 같은 원본 렌더링 픽셀에서 정확한 외곽 흰색 여백만 제거. 12MP 초과: 저메모리 미리보기로 영역을 정한 뒤 원래 전체 타일 픽셀을 스트리밍하여 필요한 픽셀만 PNG로 기록. 변형/리샘플링 없음.
- 화면 내용이 불명확하거나 빈 도면이면 용지 전체 출력으로 안전하게 폴백. 흰색 지도 내부 객체, 도면 색상과 선폭을 임의 제거하지 않음.
- 제공된 **실제 온맵 추출 PNG 8개**를 직접 검사: 모두 1416×2048/RGBA(alpha=255), 보이는 도면 범위 (113,195)-(1300,1673), 외곽 크롭 결과 1187×1478, 원본 범위 픽셀 동일.
- **해당 도엽의 원본 온맵 PDF는 Library/Drive에서 확인되지 않아 PDF 실물의 OCG 렌더링 결과를 직접 검증했다고 주장하지 않음.** 원본 PNG를 임시 PDF에 배치한 대체 입력 시험과 프로그램 기존 PDF·DXF 테스트는 완료.
- 자동 회귀 188/188 PASS; 기존 불투명 PNG/JPG SHA-256 동일; 실제 Windows PySide6·EXE·고DPI QA NOT RUN.

## 2026-11-14 Stage 10 — 제한적 대형 DXF DisplayList 반복 렌더링 후보

- 부모: Stage 9 GitHub 후보 `9dbb4203c0525dc2e84c778e4fa22c6c9b607fcf` (별도 후보 브랜치만 변경).
- 기능 변경: DXF 선택 적재로 생성한 작은 PDF(<=1.5MiB, 선택 엔티티 1~256개)에 한하여 두 번째 clipped preview부터 하나의 PyMuPDF DisplayList를 재사용하도록 기본 활성화.
- 원본 도면, 레이어 편집 규칙, 이미지 출력, 빌드 CMD, CAD 백엔드와 사용자 GUI는 변경하지 않음. 레이어/소스 전환 때 기존 리스트 폐기, 오류 시 ThreePass 원경로 복귀 유지.
- 긴급 롤백: Windows CMD 실행 전에 `set SUNRISE_DISABLE_LARGE_CAD_DISPLAYLIST=1`.
- 기존 2026-11-13 합성 측정 5.31554→1.26031초(50회 뷰 렌더, 출력 픽셀 동일)는 **과거 합성 근거**이고 본 소스 Windows 실측이 아님.
- 새 후보의 원격 브랜치 정확한 전체 unittest, 402MiB 실물 peak RSS/속도, Windows onefile/GUI/서명: **NOT RUN**. 공식 릴리스 **HOLD**, Actions/workflows **미사용/없음**.

## Stage 11 — Windows 온맵 15장 일괄 추출 시 응답성·정렬 결함 보완 후보 (2026-11-14)

- 사용자 실제 Windows 스크린샷: 일괄 추출 약 28%, 대량 PDF 15장 선택, UI '응답 없음' 보고. 라이트/다크·하단 04 글자·상단 버튼·검색 아이콘 불균형 재현 보고 포함.
- 소스 확인 병목: 12MP 초과 + crop PNG의 정확한 두 번 래스터; GUI 프로세스 내 MuPDF 잠금으로 export와 preview 경합.
- 수정: 별도 `--batch-worker` 원파일 subprocess; JSON snapshot OCG 정수 키 복원; 1회 렌더+디스크 스풀로 PNG 투명 크롭; Ctrl+휠/휠/Shift+휠; 상단/검색/하단 양 테마 동기화.
- 가드: 1GiB 미만 스풀, 128MiB 디스크 여유 예약; 부족하면 원래 2회 패스; 원본은 읽기 전용, 결과 임시 원자적 무덮어쓰기.
- 회귀 파일: `tests/test_batch_responsiveness_stage11.py` (15개 합성 PDF, OCG, PNG 스트라이프 바이트 동등, 취소/경로 및 UI 정적 계약).
- Windows 사용자의 **15장 실물 OnMap**, PySide6 양 테마 100~175%DPI GUI, Onefile EXE, 신규 병목/응답성 실기 = **NOT RUN**. 소스 정적 감사만으로 실제 문제 해결 PASS를 주장하지 않음.
- GitHub Actions 실행/생성/활성화 금지. `main` 및 공식 배포 변경 없음.

## Stage 12 — 렌더링 엔진 사실확인, 소스 검증 기준 및 대형 PNG 안전 감사

- 코드 확인: `drawing_editor/core.py`의 `import ezdxf, fitz` 및 `FastPyMuPdfBackend`, `requirements.txt`의 `PyMuPDF>=1.24,<2`, `ezdxf>=1.3,<2` 확인. **엔진 전면 교체 흔적 없음**. 기존 자체 고속 백엔드·선택적 DXF·DisplayList가 기존 엔진 위에서 작동.
- P1 수정: `quality/qa_exact_branch.py`의 구형 P0 브랜치 고정을 `STAGE12_SOURCE`로 교체, `RUN_P0_QA.cmd`에서 Git/ZIP 다른 검증 경로, 새 `quality/qa_source_archive.py`로 GitHub ZIP 전체 파일 무결성 확인. 오래된 SHA256 매니페스트는 HISTORICAL 표시.
- P2 수정: 대형 RGBA one-pass trim 전 디스크 여유를 스풀 + 최종 PNG + 256MiB로 보수적 예약.
- QA 대상: `tests/test_stage12_source_archive.py`, 기존 `tests/test_exact_branch_qa.py`, Stage11 OCG/15개 합성 일괄 추출 및 Qt 라이트/다크. `RUN_STAGE12_QA.cmd` 로컬 수동 절차.
- **정적 소스 분석과 실제 QA를 혼동하지 않음:** 이 감사 중 전체 Windows 실행·15개 실물 OnMap·대형 DXF 402MiB 확대·메모리 피크·실기 화질·공인서명은 **NOT RUN**.
- 과거 CI 262 PASS는 현행 Stage12 검증결과가 아님. User 요청 GitHub Actions 중단 상태 유지. 공식 main/Release/Drive 기준본 미변경.
