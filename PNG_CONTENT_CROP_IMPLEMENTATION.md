# PNG 도면영역 추출 — 구현/QA 요약

- 원인: 사용자가 보낸 PNG 8개는 RGBA지만 실제 알파값이 전부 255, 용지 여백이 데이터 안에 포함되어 있음.
- 적용: `drawing_editor/trim.py`의 불투명·투명 이미지 ink bbox를 사용, 외곽 흰 용지 영역만 선택적 크롭.
- 작은 PNG: 동일 PyMuPDF 원본 렌더 bitmap에서 PIL로 픽셀 정확 크롭. 큰 PNG: 저해상도 외곽 사전 검출 후 원본과 같은 타일 렌더 픽셀에서 crop 열/행만 스트리밍 부호화.
- 출력 크기 변경은 요청된 PNG에서만 발생. 원본 지도의 축척·투명도·색상·기하·원본 파일은 그대로. `OutputOptions().crop_margins` 디폴트 False로 API 호환.
- GIF/JPG, 자동번역, 레이어 구성, DWG 변환 경로는 변경하지 않음.
- 검증: tests/test_png_content_crop.py (8 신규), 종전 180개 포함 188개 PASS.
- 대용량 타일 crop는 전체 페이지 스트라이프를 렌더링 후 필요한 부분만 PNG에 기록하므로 지도 픽셀 바이트 동일성과 메모리 예산을 우선하며, 빨라진다고 주장하지 않음.
- 실제 온맵 원본 PDF 및 Windows GUI/DPI 실기시험은 원본/환경 부재로 NOT RUN.
