# Sunrise Drawing Editor — 대용량 CAD 성능 개선 및 최종 소스 검증

- 점검일: 2026-11-12 (KST)
- 인수 소스: 사용자 직접 첨부 `Sunrise_Drawing_Editor-candidate-cad-displaylist-cache.zip`
- 기준 ZIP SHA-256: `8c549045cc4a80af5ba8496148130a102597756121dbbf11c9cec367565dadb6`
- 수행 범위: DXF 레이어별 선택 적재 I/O, 선택적 DisplayList 예외 복구, 회귀시험 및 합성 성능 비교
- 운영 기준: 기존 GitHub `main` / Google Drive `Release.zip`은 **변경하지 않음**. 이번 ZIP은 후속 검증 사본이며 Windows 공식 배포본으로 승격하지 않음.

## 1. 현재까지의 개발 단계 파악

첨부 기준본에는 기존 Release(자동시험 92개 기준) 이후 다음 작업이 포함되어 있다.

1. 사용자 실물 약 401.8MiB DXF의 ASCII DXF 레이어 카탈로그 및 선택적 엔티티 적재. 약 290개 레이어, 엔티티 레코드 약 220,350개, 초기 표시 레이어 2개라는 수치는 **기존 현장 보고서**의 기록이며 이번 작업에서 원본 실물 재검증한 값이 아니다.
2. 선택 시 불필요한 BLOCKS/OBJECTS의 보수적 생략과 반복 INSERT/원호 렌더링 가속.
3. 3차 개선에서 엔티티의 레이어별 오프셋 인덱스, 그리기 순서·BoundingBox 재활용, 활성 레이어 PDF 문서 1개 재사용.
4. 추가 `CAD_DISPLAYLIST_CANDIDATE.md`의 작은 staged PDF DisplayList 재사용 후보. 기존 문서상 이 부분은 실물 성능 미검증인 실험 기능.

## 2. 이번 변경한 소스

| 파일 | 내용 |
|---|---|
| `drawing_editor/cad_selective.py` | 엔티티 기록 중 원본에서 연속된 바이트 구간을 최대 4MiB 단위로 결합해 출력. 선택·순서·좌표·엔티티 group code 변경 없음. 원본 전체를 메모리에 복제하지 않음. |
| `drawing_editor/core.py` | 선택적 PDF DisplayList 렌더가 RuntimeError/ValueError/MemoryError로 실패하면 이전 정확한 `page.get_pixmap` 경로로 1회 폴백, 같은 상태에서 실패한 목록 다시 만들지 않음. |
| `tests/test_cad_io_batch.py` | 연속·비연속·큰 레코드·빈 선택, 실제 번들 DXF를 CRLF canonical 형태로 변환한 단계별 소스 정확 일치 및 미리보기 출력 일치, 선택적 렌더 실패 폴백 검사 추가. |
| `quality/benchmark_cad_io_batch.py` | 이전 개별 엔티티 쓰기와 신규 연속 구간 쓰기 전후 성능·해시 재현 스크립트. |
| `quality/CAD_IO_BATCH_BENCHMARK.json` | 이번 합성 측정 로그. |

프로그램 UI, Windows 빌드 CMD, 원본 자동 이미지 해상도, DPI, PNG/JPG 저장, 레이어 규칙, DWG 외부 변환, 제품 버전/공지/업데이트 미포함 정책은 수정하지 않았다.

## 3. 측정 결과: 엔티티 기록 구간만

합성 입력: group-code가 있는 120,000개 단순 DXF 레코드(5,640,000 bytes). 그중 연속 8개 선택·2개 비선택 패턴으로 **96,000개 선택**. 동일 파일/입력/5회 측정의 중앙값.

| 측정 대상 | 기존 개별 기록 | 개선 후 연속 기록 | 차이 |
|---|---:|---:|---:|
| 메모리 BytesIO 출력 | 0.007351초 | 0.006370초 | 약 13.3% 감소 |
| 임시 파일 출력 | 0.014169초 | 0.011455초 | 약 19.2% 감소 |
| 선택 결과 SHA-256 | 동일 | 동일 | 바이트 완전 일치 |

**중요:** 위 결과는 DXF 엔티티 바이트를 복사하는 **부분 단계** 측정이며, 도면 열기 전체·CAD 기하 변환·복잡한 원호 래스터화·이미지 파일 생성 시간이 19.2% 줄었다는 뜻이 아니다. 실제 402MiB DXF 및 Windows에서는 별도 측정해야 한다.

## 4. DisplayList 후보 성능 게이트

현재 환경에서 약 2,500개의 CIRCLE PATH를 포함한 합성 PDF(압축 PDF 약 138KB)의 10개 서로 다른 clip을 렌더링했다.

- 일반 `page.get_pixmap` 누적 약 **1.41초**.
- `DisplayList` 생성 약 **0.10초**, 이후 10개 clip 렌더 약 **1.76초**.
- 10개 PNG 결과 SHA-256가 일반 경로와 모두 같았음.

이 도면에서는 DisplayList 경로가 더 느렸다. 따라서 **DisplayList로 인한 보편적인 속도 향상을 주장하지 않으며**, 기존 후보를 실험 상태로 유지한다. 이번 수정에서는 예외 시 정확한 일반 경로로 회복하도록 안전성을 보강했다. 실물 원호 중심 DXF의 반복 clip 속도·RSS를 확인한 뒤 최적화 유지/제거를 결정해야 한다.

## 5. 실행 검증 구분

- ZIP CRC: 인수 원본 PASS.
- Python 소스 compileall: PASS.
- 전체 Python unittest: **139/139 PASS** (첨부 후보 135개에서 신규 4개 추가).
- 번들 DXF의 기존 엔티티 개별 쓰기와 신규 연속 쓰기 staged 바이트 비교: PASS.
- 동일 staged DXF의 Preview PNG 바이트 비교: PASS.
- 선택적 DisplayList 예외 후 정확 렌더 폴백: PASS.
- 실제 사용자의 약 401.8MiB DXF를 이번 실행환경에서 새로 측정: **NOT RUN** (ZIP에 원본 도면 없음).
- Windows PySide6 GUI 및 100·125·150·175% DPI: **NOT RUN** (PySide6 미설치).
- Windows Onefile EXE, SignTool Authenticode: **NOT RUN** (Windows 환경 아님).
- 상용 배포 라이선스 검토: **PENDING**.

## 6. Windows 재검증 권장 순서

1. 새 ZIP을 **별도 작업 폴더**에 풀고 기존 공식 설치·사용자 원본·인증서 저장소는 직접 덮어쓰지 않는다.
2. 시스템 Python에서 `RUN_TESTS.cmd` 실행. 이전에 PASS인 변경 무관 기능은 개발 반복마다 강제 재검증하지 않고, 공식 배포 때 필요한 Gate만 수행한다.
3. 실제 402MiB DXF에서 기본 표시, INSERT ON/OFF, 원호 다량 표시, 서로 다른 10개 확대 clip을 기존 후보와 이번 ZIP으로 비교한다. 두 소스의 이미지 픽셀 해시·RSS·시간·원본 해시·임시 파일 정리를 기록한다.
4. 실제 이득/회귀 유무 확인 후 `BUILD_ONEFILE.cmd` 실행 및 `signtool verify /pa /v` 확인. 자체서명은 공인 신뢰를 뜻하지 않는다.
5. 오류 발생 시 `drawing_editor/cad_selective.py`의 `_write_selected_entities` 한 곳만 우선 비교·되돌리고, DisplayList 캐시 변경은 실패 복구 로직과 분리하여 평가한다.

## 7. 인수 및 승격 판정

- **후속 성능 개선 검증 ZIP 작성: 완료**
- **합성 입력 성능 및 바이트 동일성 검증: 완료**
- **사용자 실물 402MiB DXF의 개선 효과 확인: 미완료**
- **Windows 공식 Release 교체: 보류**
- 기존 GitHub·Google Drive 파일을 수정하거나 외부 공개 업로드하지 않았다.
