# Sunrise Drawing Editor — 공개 UI/UX MCP 설계 기반 UI·레이아웃·UX 최적화 결과

**작업일:** 2026-11-12  
**소스 기준본:** `Sunrise_Drawing_Editor_Final_Integrated_Source_20261112.zip`  
**이번 산출물:** `Sunrise_Drawing_Editor_UIUX_Optimized_Source_20261112.zip`  
**릴리스 상태:** UI/UX 개선 후보 소스 / Windows GUI·서명 배포 게이트 대기

## 1. 공개 GitHub MCP 조사

- [UI/UX Pro MCP](https://github.com/redf0x1/ui-ux-pro-mcp): 디자인 시스템, 색상·타이포그래피, UX·접근성·아이콘 검색 기능을 공개 README로 확인. 이 설계 기준을 Qt 컴포넌트에 맞게 구현.
- [PySide6 MCP](https://github.com/com55/pyside6-mcp): Qt 위젯 트리·geometry·실화면 캡처·상호작용 자동화를 제공함을 확인. Windows에서 이용할 수 있는 독립적인 UI 실측 QA 도구를 코드에 추가.
- **MCP 서버를 직접 설치·호출한 것은 아니며, 어느 저장소의 외부 실행 코드도 프로그램에 탑재하지 않음.** 링크의 공개 기술 정보와 문서화된 기능을 근거로 개선을 설계함.

## 2. 적용한 핵심 UX 개선

1. `drawing_editor/ui_design.py`: 전용 라이트/다크 테마 토큰과 논리 화면 폭 760·900·1120·1340px 대응 패널 배치 규칙 추가. 패널은 드래그로 붕괴하지 않고 미리보기 너비를 보호.
2. `drawing_editor/window.py`: 작업 영역만 세로 스크롤되도록 개편하고 **이미지 추출 설정과 실행 버튼은 하단에 고정**. 소형 창에서 일부 설명과 보조 버튼 텍스트는 간결하게 전환.
3. 도면 목록에서 PDF/DXF/DWG 로컬 파일 드래그·드롭. 기존 `add_files` 및 대용량 CAD 백그라운드 카탈로그 경로를 재사용하며 원본은 읽기 전용.
4. 빈 미리보기 안내, 레이어 검색 결과 없음 안내(검색 자체는 ON/OFF 불변), 실제 선택 도면 수에 맞춘 추출 CTA와 로딩 상태 표기.
5. 아이콘 버튼·도면/레이어 목록·출력 설정에 접근성 이름, 키보드 탭 순서, 키보드 포커스 테두리. 검색 힌트/긴 상태는 자동 생략 및 툴팁으로 완전한 텍스트 보존.
6. 핵심 추출 버튼의 흰색 글자 대비를 약 3.03:1 → 약 5.29:1로 조정. `QWidget#drawingRoot` 하위 컴포넌트에 버튼 상태 QSS를 제한해 Qt 공통 대화상자 영향 최소화.
7. `quality/qa_gui_layout.py`와 `RUN_UI_QA.cmd`를 추가하여 Windows에서 창 위젯 좌표, 표시 상태, 캔버스 너비, 캡처 PNG 및 JSON을 저장하도록 준비.

## 3. 직접 실행한 검증 결과

| 항목 | 결과 |
|---|---|
| Python 자동 회귀시험 | **157/157 PASS** (직전 146개 + UI 신규 11개) |
| 전체 소스 compileall | PASS |
| 760~1920 논리 px별 미리보기 너비 계약 | PASS |
| 라이트·다크 테마 CTA/본문/보조글 색상 대비 | PASS (Python 계산) |
| 도면 드롭·빈 상태·선택 CTA·Tab 접근성 코드 계약 | PASS (정적·순수 함수 시험) |
| 기존 CAD/출력/Windows 빌드 관련 파일 바이트 불변 | PASS (기준 ZIP과 해시 비교) |
| Windows PySide6 실제 GUI 화면 캡처 | **NOT RUN** (현재 Linux, PySide6 미설치) |
| Windows Onefile EXE 생성 및 SignTool | **NOT RUN** |
| 402MiB 실물 DXF 로딩·화면 QA | **NOT RUN** |

**실행환경:** Linux-6.18.57-x86_64-with-glibc2.41 / Python 3.13.5.

## 4. 기준본 대비 기존 변경파일

- `FINAL_SOURCE_HANDOVER.md`
- `drawing_editor/window.py`
- `tests/test_ui_contract.py`

새 UI·QA 파일과 문서는 `6`개(매니페스트 추가 전 파일 비교). CAD 엔진·출력 모듈·CMD 빌드 스크립트의 SHA-256은 직전 최종 소스와 같습니다. 사용자 DXF 원본과 서명 키는 포함하지 않았습니다.

## 5. Windows 시각 QA 실행법

`RUN_UI_QA.cmd`를 Windows CMD에서 실행하면 Qt 1.0·1.25·1.5·1.75 배율 **시뮬레이션** 스크린샷/위젯 좌표를 `quality/ui_qa_artifacts`에 생성하도록 구성했습니다. 이 스크립트는 지금까지 실행하지 않았습니다. 사용자의 실제 Windows 디스플레이 설정을 100/125/150/175%로 변경해 확인하는 과정도 별도로 필요하며, 캡처 한 장만으로 버튼 잘림·레이어 선택·드롭·취소 UX가 모두 합격했다고 판단하지 않습니다.

**차기 게이트:** Windows Qt 스크린샷, 소형 창·실제 DPI, 다중 파일 선택→레이어 토글→이미지 출력, SignTool 포함 Onefile 빌드·기동 검증.

## 6. 무결성 및 보존정책

- 기존 최종 통합 소스 ZIP을 수정하지 않고 별도 개선 패키지 생성.
- Google Drive ThreePass 정식 기준본과 GitHub `main` 변경 없음.
- `SOURCE_SHA256_MANIFEST.json`은 소스별 해시를 재생성하며 자기 자신은 해시 대상에서 제외.
- UI 기능만 변경, 버전 노출·자동업데이트·외부 네트워크 의존성 추가 없음.
