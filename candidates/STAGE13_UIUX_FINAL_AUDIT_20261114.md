# Stage 13 — Sunrise Drawing Editor UI 레이아웃/UX 최종 감사 후보 (2026-11-14)

## 1. 기준 및 금지
- 부모 기준: Stage12 `ab3ed569338fb0382da7b04fa2a4bfcb18055b64`; 별도 후보 브랜치만 수정.
- 렌더 엔진(PyMuPDF·ezdxf), DisplayList, 원본 PDF/DXF/DWG, OCG, PNG/JPG, 배치 자식 프로세스, Windows 빌드 서명, 자동 업데이터 변경 **없음**.
- GitHub Actions는 재생성/실행하지 않음. 공식 main/Release 변경 없음.

## 2. 사용자 캡처 기반 UI 결함 및 코드 개선
| 범위 | 기존 위험 | 이번 조치 |
| --- | --- | --- |
| 03 미리보기 | 너비 760px 및 고DPI에서 페이지·확대·화면맞춤 총 7개 컨트롤이 한 줄에 고정되어 겹침/클리핑 위험 | Qt `QBoxLayout`의 두 하위 그룹으로 통합, 900px 미만에서는 두 행으로 분할 |
| 03 키보드/마우스 | Ctrl+S를 추출 중 누르면 취소 실행 가능 | 추출 중 Ctrl+S는 무시하고 버튼으로만 취소하도록 명확화; Ctrl+휠 확대와 휠 스크롤 유지 |
| 01/02/03/04 | 키보드 초점 시 상단 툴바의 포커스 경계가 충분히 드러나지 않음 | 툴바 버튼 `:focus`의 분명한 테두리 |
| 04 이미지 추출 | 하단 고정 CTA 접근성 및 소형 창에서 누락 가능 | 기존 고정 하단과 접근성 유지, 고DPI·좁은 창의 자동 기하 검증 |
| 라이트/다크 | 테마별 SVG·테두리·글꼴·돋보기 배치를 시각적으로 비교하지 못함 | 신규 Qt 위젯 캡처·기하 검증 스크립트 및 명확한 미검증 구분 |

## 3. 검증 도구 및 수락 조건
- `tests/test_stage13_ui_final.py`: 소스 계약, 반응형 그룹, Ctrl+S 취소 금지, 라이트/다크 QSS, 공통 CTA 검증. **실제 Python 실행 결과는 별도**.
- `RUN_STAGE13_UI_QA.cmd`: Git/ZIP 소스 동일성 → 변경영역 회귀 → 4개 QT_SCALE_FACTOR 배율 각각 새 Python 프로세스로 760/900/1120/1510px × 라이트/다크 화면 렌더링 → 소스 재검증.
- `quality/qa_stage13_ui_final.py`: 스크린샷 32장과 스케일별 JSON 4개; 검색 아이콘 중앙 정렬, 탐색/확대 컨트롤 겹침, 하단 추출 컨트롤 가시성, 테마 상태, 7개 미리보기 컨트롤 접근 확인.
- 각 QA JSON의 `pass`는 **Qt 위젯의 자동 기하 계약 통과**만 의미. 실제 물리 모니터 DPI 100/125/150/175% 및 사용자의 화면과 한글 오버플로우는 **Windows 화면 캡처를 사람이 확인하는 별도 승인**이 필요.

## 4. 타 GitHub 저장소 검토 적용 범위
- UI: `shadcn-ui/ui`, `ant-design/ant-design`, `mui/material-ui`의 일관된 위젯 상태·초점 의미만 적용.
- 레이아웃: `twbs/bootstrap` 및 `tailwindlabs/tailwindcss`의 브레이크포인트 원칙을 기존 Qt 네이티브 `panel_layout`에 맞게 사용.
- SVG 정렬: `FortAwesome/Font-Awesome` 사례의 일관된 아이콘 슬롯을 유지.
- JS/React/CSS/Node, 애니메이션, 인증/DB는 앱 기술과 무관해 **추가하지 않음**.

## 5. 검수 현황 — 오해 금지
- 수정 대상 파일과 이전 사용자 Windows 실기 캡처를 분석한 정적 감사: 진행.
- 신규 Stage13 Qt 위젯 자동 테스트: **NOT RUN** (현재 개발 도구에는 Windows PySide6 미설치).
- Windows 15개 온맵 실물 원본 추출·레이어 OCG·응답 없음 최종 확인: **NOT RUN**.
- 실제 Windows DPI와 Signed Onefile, 사용자 체감 FPS, 402MiB DXF: **NOT RUN**.
- 공식 release: **HOLD**. GitHub Source 브랜치/Drive 보관은 사용자가 지시한 소스 인계이며 공식 EXE 출시가 아님.

## 6. 사용자 실행
1. GitHub `STAGE13_SOURCE` 브랜치 ZIP을 `C:\\Sunrise_Drawing_Editor`에 단일 폴더로 압축 해제.
2. CMD: `RUN_STAGE13_UI_QA.cmd`. `quality\P0_runtime\UI_STAGE13`에서 32장 PNG/4개 JSON 검토.
3. `BUILD_ONEFILE.cmd`로 Windows Onefile 검수용 EXE 빌드. 기존 인증서와 SignTool 필요.
4. 사용자 제공 15장 온맵 일괄 추출 중 테마 전환/도면 선택/취소, 대형 DXF 확대, 라이트/다크 최종 화면 체크.
5. 필드 QA 통과 전에는 사용자에게 '모든 기능 최종 검증 PASS' 또는 공식 배포 완료로 안내하지 않음.

## 7. Google Drive 자료 정리 범위
- 지정 폴더: `★업무코딩/2. 일반업무/5. Sunrise Drawing Editor` (Google Drive folder ID `15je9J8dhp848Z9wKPAXm2sn5Y7TRbGRc`).
- **해당 폴더에 직접 속한 옛 Drawing Editor 문서만** 사용자의 요청에 따라 신규 기록 업로드·확인 이후 삭제 대상으로 분류.
- 다른 Sunrise 제품, 공통 개발표준, 공유자료, 원본 OnMap PDF/DXF/DWG, GitHub 소스/과거 커밋은 삭제하지 않음.
