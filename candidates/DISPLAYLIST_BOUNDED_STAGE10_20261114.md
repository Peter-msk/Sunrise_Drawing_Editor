# Stage 10 — 대형 DXF의 제한적 DisplayList 반복 렌더링 통합 (2026-11-14)

## 범위와 기준
- 공식 main 및 Stage 9 기준 9dbb4203의 정상 빌드, OnMap 읽기, 레이어 ON/OFF, 이미지 추출 동작 유지
- 변경은 `drawing_editor/core.py`의 staged CAD clip 미리보기 최적화에 한정
- 기존 ThreePass painter, PDF OCG, 렌더 출력 포맷, 저장, GUI, 빌드 CMD는 무변경
- GitHub Actions 재개 금지; 본 브랜치에는 `.github/workflows` 없음

## 후보 적용 조건
- **DXF 원본 96MiB 초과**에도, 실제 렌더 대상은 현재 선택한 레이어들의 **임시 PDF**임
- 임시 PDF <= **1.5MiB**, 원본에서 선택한 엔티티 **1~256개**, 현 레이어 상태와 selective staging signature 동일
- 반복된 확대/이동의 **두 번째 clip 렌더 호출 이후** 한 개 DisplayList 유지
- 선택 개수가 많거나 임시 PDF가 큰 도면은 이전 ThreePass 경로 유지
- PDF 원본/비선택 CAD의 다른 기존 DisplayList 조건은 이전과 동일

## 메모리/정확성 경계
- 캐시는 현재 스레드/worker의 문서 소유, 동시 다수 DisplayList 금지
- 레이어 ON/OFF, 원본 도면 전환, 세션 종료 시 기존 코드가 cache 및 native 객체 무효화
- DisplayList 생성 실패/렌더 실패는 기존 page.get_pixmap() 기반 권위 경로로 복귀
- 원본 파일 및 영구 데이터는 변경하지 않음
- **주의:** 1.5MiB 파일/256 엔티티가 네이티브 렌더러 피크 메모리 상한을 보증하지 않음
- 긴급 회피: Windows CMD에서 `set SUNRISE_DISABLE_LARGE_CAD_DISPLAYLIST=1` 후 동일 EXE 실행

## 검증
- 기존 합성 원호(16,692개 경로, 25개 뷰 x 2배경)는 이전 별도 실험에서 direct 5.31554초, DisplayList 1.26031초(3회 중앙값); RGB/RGBA 픽셀 SHA 일치
- 정확한 Stage10 GitHub 브랜치 전체 Python 테스트: **NOT RUN**
- Windows 사용자의 실제 402MiB DXF, 특히 G0022322·C0285311 조합의 속도/피크 RSS/픽셀 동일성: **NOT RUN**
- Windows PySide6 화면, Onefile, SignTool 및 최종 사용자 수락검증: **NOT RUN**
- 본 ZIP은 **전체 소스가 들어있는 사용자 검수 후보**이며 공식 main, Release, Google Drive 기준본을 대체하지 않음

## 사용자 실행
1. GitHub의 `candidate/render-displaylist-bounded-20261114` 브랜치에서 Download ZIP
2. 압축 해제 후 기존 `BUILD_ONEFILE.cmd` 실행
3. 정상 OnMap/DXF 파일에서 반복 확대·레이어 ON/OFF/이미지 추출 확인
4. 문제가 있으면 시스템 변경 없이 해당 CMD 세션에서 `set SUNRISE_DISABLE_LARGE_CAD_DISPLAYLIST=1` 적용 후 재실행
5. 실측 증거 없이 성능 개선이 확정되었다고 보고하지 않음
