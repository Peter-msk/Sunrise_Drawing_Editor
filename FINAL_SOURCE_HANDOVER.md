# Sunrise Drawing Editor — 최종 통합 개발 소스 인수인계

**기준일:** 2026-11-12 (KST)  
**제공 상태:** 최종 통합 **소스 패키지**. Windows EXE 빌드·서명·고DPI 실기검증 전 단계.  
**대상:** `Sunrise_Drawing_Editor_Final_Integrated_Source_20261112.zip`  
**공식 비교 원본:** Drive `Sunrise_Drawing_Editor_Final_20261112.zip` (ThreePass Final).

## 1. 적용한 개발 결과

- Drive ThreePass의 PDF/온맵·DXF·외부 DWG 변환, 레이어 상태/규칙, PNG/JPG 추출, 원본 자동 해상도, 사용자 지정 크기와 DPI, 고해상도 타일 추출, Windows CMD Onefile 빌드 구조를 유지한다.
- 반복 DXF 선별 적재에서 원본이 변경되지 않은 경우의 INSERT 블록 참조와 OBJECTS 안전성 판정을 재사용한다. DXF 그룹 코드 `102`와 핸들 값 `102`를 혼동하지 않도록 수정한다.
- 선택적 CAD 선별 적재에서는 불필요한 전체 recorder 구성 단계를 건너뛰어 기존 직접 렌더링 경로를 사용한다.
- 원본 96MiB 초과 DXF에 대해서는 **미승인 CAD DisplayList 실험 기능을 적용하지 않는다.** 기존 ThreePass의 원본 크기 가드를 복원했다. 작은 도면의 후보 경로 또한 실패 시 원래 렌더러로 복구한다.
- 사용자 승인 없이 UI 버전 번호·공지·자동 업데이트·서버 연동·새 외부 엔진을 추가하지 않았다. 고객 업무용 DXF, PFX, 개인키는 ZIP에 포함하지 않는다.

## 2. 직접 검증 상태

- 전체 Python 문법 검사: PASS.
- 전체 자동 회귀시험: **146/146 PASS** (Linux x64 / Python 3.13.5, 새 96MiB 경계 시험 1개 포함).
- Drive ThreePass 및 이번 패키지의 내장 DXF/PDF 샘플 비교: 각 파일 최초 미리보기, 레이어 토글·복원, 8개 확대 클립, FHD PNG/JPG 출력의 RGB/파일 SHA-256 **전 항목 동일**. 입력 해시 불변.
- 최종 ZIP 모든 파일 CRC 및 자체 매니페스트 SHA-256 검증: 패키징 완료 후 검사.
- 이전 작업의 402MiB 실측 및 131개 테스트는 **과거 ThreePass 근거**이며 이번 실물 재측정으로 취급하지 않는다.

## 3. 미검증 필수 Release Gate

- Windows 10/11 x64 PyInstaller **Onefile EXE 실제 생성: NOT RUN** (현재 Linux 환경; PySide6, PyInstaller 없음).
- Windows SignTool Authenticode 서명과 `--self-test`: NOT RUN.
- Windows 100/125/150/175% DPI 창 실기: NOT RUN.
- 원본 421,316,933바이트 DXF의 레이어 `C0285311`, `G0022322`, 다중 INSERT, 25회 확대·이동, 피크 RSS 및 RGB 해시: NOT RUN (실물 파일 없음).
- 외부 배포용 PyMuPDF·PySide6/Qt 및 DWG 변환기 라이선스: PENDING.

## 4. Windows 빌드와 QA 재현

1. Windows x64에 시스템 Python 3.11 이상, SignTool 준비. PowerShell과 가상환경은 사용하지 않는다.
2. 최종 ZIP 압축 해제 후 **CMD**를 열고, 압축 해제한 소스 폴더에서 다음을 실행한다.

```bat
set BUILD_RUN_TESTS=1
BUILD_ONEFILE.cmd
```

3. `dist\Sunrise Drawing Editor.exe`가 생성되고 빌드 전·후 자체시험, 서명, 게시 게이트에 통과한 경우에만 Windows 바이너리의 배포 심사를 진행한다.
4. 이 프로젝트의 서명은 기본적으로 `CN=Sunrise Group` 자체서명이며, 공인 서명 신뢰와 동일하지 않다.
5. 실행·성능·출력·DPI 검증 표준은 `docs/FINAL_WINDOWS_QA_CHECKLIST_20261112.md`를 따른다.

## 5. 기준본 및 승인 경계

- 공식 Drive ThreePass 파일과 GitHub `main`은 변경하지 않았다. 새 ZIP은 최종 **개발 소스 인계본**이며 Windows 실기 PASS 전 **배포 승인 릴리스가 아니다.**
- 이전 소스 문서는 과거 개발 시점 기록으로 보존한다. 현 시점 판정은 **이 문서 및 `quality/FINAL_ASSEMBLY_QA_20261112.json`**을 우선 적용한다.
- 소스 파일별 해시는 `SOURCE_SHA256_MANIFEST.json`에서 확인한다. 매니페스트 자신은 재귀 해시를 피하기 위해 대상에서 제외한다.


## 6. UI/UX 추가 고도화 인수(2026-11-12)

- 후속 UI 전용 변경내역은 `docs/UI_UX_MCP_REDESIGN_20261112.md`를 우선한다.
- 760px부터 동작하는 논리 픽셀 기준 단계형 패널 폭, 고DPI 작업영역 스크롤, 파일 목록 드래그·드롭, 검색 결과 없음 안내, 선택 파일 건수와 추출 버튼 연동, 접근성 이름·탭 이동 및 4.5:1 이상 대비 색상 설계를 추가했다.
- `drawing_editor/ui_design.py`에서 앱별 디자인 토큰과 화면 폭 정책을 관리한다. 프로그램에 MCP 서버를 내장하지 않는다.
- `quality/qa_gui_layout.py`, `RUN_UI_QA.cmd`는 추후 Windows 실화면 검증용이다. 현재 Qt 환경 미설치 상태에서 미실행이며 실제 GUI PASS를 뜻하지 않는다.
- 이전 **146/146**은 UI 변경 전 소스의 시점별 기록이며, 이번 변경 후 **157/157** 회귀시험 PASS이다. CAD/출력 엔진 파일은 변경하지 않았다.
- 이번 UI/UX 후보 소스 역시 Windows GUI 및 Onefile 실빌드 전 **배포 승인 릴리스가 아니다**.
