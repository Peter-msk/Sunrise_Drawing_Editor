# DXF → OnMap PDF 전환 및 UI 테마 P0 후보 패치 — 2026-11-13

- **적용 대상:** `Sunrise_Drawing_Editor_Render_Icon_HiDPI_20261113_SOURCE.zip` (직전 217 테스트 후보)만 지원.
- **기준본:** 해당 후보의 `drawing_editor/core.py` 및 `drawing_editor/window.py` 내용은 공식 GitHub main + P0 + FourthPass + Preview Recovery + HiDPI 패치를 순서대로 재구성하여 일치시킨 뒤 수정.
- **핵심:** 선택 전환 즉시 이전 DXF 렌더 취소, 128개 CAD primitive마다 협력 취소 검사, 실패한 thread document open 시 오래된 CAD 캐시 참조 방지. ThreePass 페인트 명령은 변경하지 않음.
- **테마:** 툴바 QToolButton 텍스트 색 명시, Qt palette의 Text/WindowText/ButtonText 및 Disabled 역할 일관화, 콤보 팝업·그룹 제목 보완, 아이콘 표시 슬롯 18×18.
- **검증:** 소스 패치 생성과 내용 확인만 실시. 이 실행 환경의 Python/container 도구가 ClientError를 반환해 새 자동시험, 실물 421MiB DXF, 실제 온맵 PDF, Windows UI 실기는 **NOT RUN**. 테스트 통과 수를 늘려 쓰지 않는다.
- **제한:** PyMuPDF의 네이티브 최종 PDF 생성 호출 내부나 사용자가 선택한 초대형 CAD의 전체 폴백은 여전히 즉시 중단 불가능할 수 있다. 프로세스 분리/워커 watchdog은 차후 실물 검증 후 결정.

## Windows CMD 적용
1. 위 원본 ZIP을 **별도 폴더**에 풀고 git 저장소가 없으면 해당 폴더에서 `git init` 을 수행한다.
2. 이 패치를 다운로드하여 프로젝트 루트에서 `git apply --check DXF_PDF_Theme_Contrast_20261113.patch` 실행.
3. 통과 시 `git apply DXF_PDF_Theme_Contrast_20261113.patch` 실행.
4. `python -m unittest discover -s tests` 및 `RUN_PREVIEW_QA.cmd "D:\Drawings\온맵원본.pdf"` 등 기존 QA를 수행.
5. DXF 선택→렌더 시작→PDF 선택→미리보기 출력, 10회 반복. 디스크·메모리·자원 반환, 테마 100/125/150/175% 시각 테스트도 확인. 모든 검증 전에는 배포 금지.

## 꼭 확인할 항목
- 큰 DXF를 연 직후 온맵 PDF로 바꿔도 미리보기가 표시되는지
- DXF INSERT·원호 9,533/16,692 경로에서 픽셀 결과가 이전 버전과 일치하는지
- 라이트·다크 전환 시 toolbar/combobox/checkbox/label 글자 대비
- 아이콘의 픽셀 중심과 텍스트 수직 기준선
- 중단·창 닫기·파일 제거 이후 원본 불변
