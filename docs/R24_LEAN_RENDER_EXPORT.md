# R24: LEAN 선정, 렌더링 단계 표시, 이미지 추출 단일 패스

R23 사용자 보고서(공통 기준 EXE 104818016 bytes, 후보 SAFE 103047392, COMPACT 94847744, LEAN 72857768, PYZ 72844904). LEAN 30.491178% 절감, PYZ 추가 절감 12864 bytes (LEAN의 0.01766%). 따라서 LEAN만 기본 빌드 프로필로 선정한다. 실제 서명/별도 SHA 기록은 일치하지만 EXE 원본 미제공, 독립 해시 재계산 불가. 자체서명 테스트 인증서와 SignTool verify 1로 정식 자동 업데이트 승인 금지. R24 빌드 크기는 신규 소스이므로 재측정 필요.

## 사용자 실행: BUILD_ONEFILE.cmd
기존 Python 의존성/서명 도구 확인 → LEAN spec 단독 빌드 → 서명 전후 smoke → 실제 서명된 EXE의 합성 도면 batch QA → 로컬 dist 게시. SAFE/COMPACT/PYZ/UPX/Nuitka 반복 빌드 없음. 기존 도구 보존. 실패 시 기존 dist EXE를 교체하지 않음(기존 publisher 계약 범위). build/staging/FUNCTIONAL_QA.json은 실제 EXE 해시와 수행 항목 기록. 정식 GitHub 배포 및 신뢰 서명/전체 실기 QA는 별도. LEAN에서 제외했던 소프트웨어 OpenGL 및 일부 Qt 이미지 코덱/가상 키보드 등은 저사양/RDP·외부 이미지·접근성 실기 위험이 남음. 

## 렌더링 진행률
미리보기/확대 영역 상태 라벨에 0% 대기, 33% 네이티브 작업 시작, 67% 렌더 결과 반환, 100% 캔버스 반영 완료. 완료 단계 비율이며 네이티브 API 내부 연산%, 시간 추정 아님. 기존 signal/seq 및 cancel 이벤트 사용. 이전 도면의 늦은 진행 신호 무시, 취소나 실패에 100% 미표시. 장기 실행 시 현재 단계와 대기시간 표시. GUI 실기 NOT RUN.

## 이미지 추출
12MP 초과 흰 배경 PNG+여백 제거: 기존 투명 PNG의 단일 래스터 패스/임시 디스크 spool을 RGB까지 일반화. 3바이트/픽셀 RGB와 4바이트/픽셀 RGBA 구분, 기존 1GiB spool 제한 및 여유 공간 기준 유지. 부족 시 기존 2-pass fallback. 픽셀, 색, DPI, 원본 파일 계약 유지. JPG·소형 PNG 기존 경로 유지. 강제 종료의 Windows 임시 파일 청소 등 실기 필요.

## 검증 증거
Linux Python에서 trim.py 및 tiles.py Git blob 일치 확인. 신규 tests/test_rgb_crop_r24.py 4/4 통과. 4개 합성 OCG PDF RGB 및 1개 RGBA 흰색 도형/얇은 선, 빈 캔버스 1개: 기존 두 패스와 PNG 바이트 동일, scan/encode 취소 및 scratch 정리. 신규 trim/tiles/verify_lean/test 컴파일 확인. 4800x3600 합성 선 8000개 벡터 PDF(5회, warmup 후, BytesIO 결과), 기존 중앙값 0.516532초, 신규 0.364649초, 29.4% 감소, PNG 파일 720826 bytes 동일. 실제 사용자 도면/Windows SSD/모든 JPG 작업을 대표하지 않음.
verify_lean.py가 실제 EXE worker를 호출해 4개 합성 온맵 유사 PDF PNG/JPG, DXF 레이어, 사전 취소, 원본 SHA를 검사하도록 연결. 해당 EXE 검사는 현 환경 Windows/Qt/PyInstaller 부재로 NOT RUN. 전체 엔진 회귀, GUI, RDP, 실물 DWG, 400MiB DXF, 외부 래스터, 실제 업데이트 교체/서명 신뢰 및 현장 속도 미검증. R24를 정식 release로 자동 등록하지 않는다.
