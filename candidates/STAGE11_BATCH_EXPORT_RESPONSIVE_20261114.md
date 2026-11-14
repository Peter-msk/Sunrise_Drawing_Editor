# Stage 11 — 15개 온맵 PDF 추출 성능·UI 응답성·라이트/다크 정렬

**기준 SHA**: `d83ad1d4bfe68ddadd29584f47187960933d64e5` (Stage 10 소스)
**최종 결과**: 공식 릴리스가 아닌 전체 개발 소스 검수 후보. 원본 작업파일 불변.

## 1. 사용자 화면·결함
- 실제 Windows 화면에서 (B090)온맵 15장 일괄 이미지 추출 진행 중 '응답 없음' 보고. 진행률 5/15 · 28% 캡처.
- 추출 중 다른 도면 선택 및 라이트/다크 테마 전환 지연.
- 휠 단독 확대가 아닌 Ctrl+휠 확대, 일반 휠은 상하 스크롤, Shift+휠은 좌우 스크롤 요구.
- 검색 아이콘의 하향 치우침, 상단 도면 추가/현재 도면 제거가 텍스트처럼 보이는 문제.
- 04 이미지 추출 컨트롤 글꼴 크기를 다른 일반 패널 컨트롤과 일치.

## 2. 변경 범위
| 파일 | 변경 |
| --- | --- |
| `drawing_editor/batch_worker.py` | 신설: GUI 외부 단일 batch process · 원자적 진행률 JSON · 취소 flag · 결과 IPC |
| `main.py` | Frozen onefile --batch-worker 디스패치; QApplication 이전 처리 |
| `drawing_editor/window.py` | 배치 subprocess 호출, 휠·검색·툴바·footer 공통 스타일 |
| `drawing_editor/trim.py` | 대형 RGBA 스트라이프 1회 렌더·정확한 bbox·디스크 스풀 |
| `drawing_editor/tiles.py` | 기존 스트리밍 PNG 인코더가 저장된 픽셀 스트라이프를 그대로 받도록 확장 |
| `drawing_editor/core.py` | 12MP 초과 + 투명 PNG + crop에만 디스크 공간 조건부 고속 경로 |
| `tests/test_batch_responsiveness_stage11.py` | 15파일·OCG·PNG 해시·취소·UI 동작 계약 |
| `README.md`, `QA_STATUS.md` | 계약·상태·검증항목 업데이트 |

## 3. 정확성 및 안전 조건
- PDF OCG 레이어 xref 정수 키는 JSON 직렬화 후 복원. DXF 레이어명은 문자열 그대로 유지.
- 선택한 레이어 상태를 각 ExportJob에 고정. GUI에서 다른 파일을 선택해도 추출 대상/상태 변경 없음.
- 15개 작업을 순차 처리하므로 동일 PDF 수십개 병렬 객체 적재 없음. 별도 process이므로 Qt event loop는 PDF 렌더에 참여하지 않음.
- 취소 신호는 child에 전달되며, 자식이 응답하지 않으면 제한 시간 뒤 강제 종료.
- 12MP 초과 + 투명 PNG의 crop에만 임시 스풀 사용. 예상 스풀 용량이 1GiB 초과거나 남은 공간이 예상치+128MiB 이하일 경우 기존 2패스 렌더 보존.
- 각 렌더 스트라이프의 원본 RGBA 바이트를 그대로 저장해 다시 압축함. 좌표 변환·리샘플링·원본 PDF 수정 없음. 결과 PNG 기존 헤더 및 인코더 재사용.
- 이외 JPG, 불투명 PNG, 작은 PNG 출력 경로 및 기존 파일 덮어쓰기 보호 유지.

## 4. Windows CMD 실기 수락
1. `BUILD_ONEFILE.cmd`로 기존과 동일하게 빌드. `BUILD_RUN_TESTS=1`은 전체 회귀를 재실행할 때만 사용.
2. 온맵 15개 PDF 선택 후 원본 자동·투명 배경·흰 여백 제거를 설정하고 일괄 추출.
3. 진행 중 왼쪽 도면 클릭·라이트/다크 연속 전환·레이어 검색 실행 — 작업 진행과 GUI 반응성 관측.
4. Ctrl+휠 확대, 휠 상하, Shift+휠 좌우, 미리보기에서 드래그 이동 확인.
5. 라이트와 다크 각각 검색 아이콘 수직 정렬, 상단 버튼 외곽선/hover, 하단 컨트롤 문자 12px 확인.
6. 출력 PNG/JPG 해상도, 바이트/시각 품질, OCG 레이어 ON/OFF, 이미지 추출 완료 개수, 원본 SHA 확인.
7. 출력 도중 취소, 실수 클릭 연타, 디스크 부족, 보안 소프트웨어 child 차단, 대형 도면 전환의 오류 피드백 확인.

## 5. 검증 증거 현황
- 연결된 GitHub 소스 수정 및 브랜치 diff: 확인 대상.
- Linux Python 합성 회귀 테스트: **NOT RUN** (원격 GitHub 전체 checkout 불가).
- 사용자 Windows 실제 15장 온맵 및 GUI 캡처: 수정 전 스크린샷만 확보, 수정 후 **NOT RUN**.
- 새 Windows onefile/서명/실물 메모리 측정/속도개선 수치: **NOT RUN**.
- GitHub Actions/workflows: 변경 없음, 실행 금지.

## 6. 배포
- 신규 검수 후보 ZIP은 GitHub의 해당 브랜치/커밋에서 Download ZIP.
- 공식 main/기존 release/Drive 기준본/사용자 원본 PDF·DXF·DWG 변경 금지.
