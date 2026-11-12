# Sunrise Drawing Editor — UI/UX + 확대 렌더링 + PNG 투명 출력 보완

## 작업 범위

- 기준: `Sunrise_Drawing_Editor_QtMCP_UIUX_Stage2_Stage3_Improved_20261112.zip` (UI/UX 2·3단계 소스)
- 사용자 화면 피드백: 라이트·다크 레이어 시인성, 도면 파일 영역 폭, 휠 확대의 중단 체감, 연속 ON/OFF 응답성, 주요 조작 버튼 아이콘 크기, PNG에서 흰색 배경 표시
- 원본 PDF/DXF/DWG는 수정하지 않음. `BUILD_ONEFILE.cmd`, CAD 선택 적재와 공간 인덱스 구조는 변경하지 않음

## 구현

1. 라이트/다크 테이블 텍스트와 선택 상태를 팔레트 변수 `fg`, `bg`, `highlight`로 지정.
2. 파일/레이어 패널의 논리 폭 구간별 재배치. 넓은 화면은 파일 292px·레이어 330px.
3. 휠/터치패드의 소수 배율 확대, 화면 맞춤 배율 기준 상한, 확대 중 기존 프레임을 우선 표시하고 230ms 이후 고해상도 클립 렌더링. 오래된 클립 결과는 버림.
4. 온맵 레이어 연속 변경 요청은 135ms 동안 모아 최신 상태만 화면에 표시.
5. 주요 버튼 아이콘 크기 및 최소 폭 통일.
6. PNG `투명 배경` 체크박스 GUI 기본 ON. JPG 선택 시 비활성화. API `OutputOptions` 기본은 불투명 유지.
7. 표준 PNG는 PyMuPDF `alpha=True`로 RGBA 저장, 12MP 초과 분할 PNG는 색상 타입 6(RGBA)으로 행 스트리밍. RGBA 4채널을 고려한 타일 RAM 계산.
8. **PDF가 직접 그린 흰색 도형/사각형은 보존**. 빈 PDF 페이지 배경만 투명 처리하며 의도치 않은 도형 제거를 하지 않음.

## 직접 실행 검증

- 전체 테스트: `python -m unittest discover -s tests -p "test_*.py" -q` 결과 **180/180 PASS**.
- 신규: `tests/test_png_transparency.py`에 기본 RGB 호환, 소형 RGBA, 12MP 초과 타일 RGBA, 투명 빈 영역, 실제 흰색 객체 보존, JPEG 투명도 입력 거절, 캐시 색상 설정 분리 검증.
- 신규: `tests/test_ui_render_feedback.py`에 반응형 패널, Zoom 증가율, 테마 명암 대비, 버튼·렌더링 지연 검증.
- 추가 실기: 저장 샘플 `SAMPLE_3_LAYERS.dxf`를 FHD 투명 PNG로 실제 추출. RGBA 및 alpha 최솟값 0 / 최댓값 255 확인.
- 원본 도면 불변, 분할 PNG 메모리 예산 유지, 기존 JPG 및 RGB PNG 경로 시험 통과.

## 미검증 및 조건

- 실제 제공받은 것은 화면 이미지이며 사용자의 원본 온맵 PDF/추출 PNG가 이번 런타임에 없어 해당 도엽의 흰 영역이 원래 PDF의 그려진 흰색 콘텐츠인지 판정할 수 없음.
- Windows PySide6 GUI 화면 캡처 및 고DPI(100%/125%/150%/175%)는 **NOT RUN** (현재 환경에 PySide6 없음).
- 402MiB 실제 DXF의 새 버전 ON/OFF 및 확대 성능 재측정은 **NOT RUN**.
- `Windows Onefile` EXE 빌드·SignTool 서명·실행은 **NOT RUN**.
- 프로그램 시작 시 원본 자동 해상도는 기존과 동일. 출력 옵션 `투명 배경`이 켜져 있더라도 PDF가 내부적으로 흰색 배경 이미지를 그렸다면 해당 영역은 흰색으로 남음.
