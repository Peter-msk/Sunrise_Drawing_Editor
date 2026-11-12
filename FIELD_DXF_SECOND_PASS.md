# Sunrise Drawing Editor — 대형 DXF 2차 실물 최적화 및 검증

검증 기준: 2026-11-12, Linux Python 엔진. 프로그램 이름/배포 파일에 버전 번호를 붙이지 않음.

## 1. 실물 원본과 병목

- 대상: 사용자 제공 `3구간 최종 철탑.dxf` (원본 **421,316,933 bytes**, 약 401.8 MiB).
- DXF 레이어 290개, 초기 표시 2개, 레이어 선택 인덱스에 포함된 ENTITIES 레코드 220,350개, 초기 실제 선택 레코드 39개.
- 첫 개선본은 대용량 ASCII DXF에서 선택된 레이어의 엔티티와 참조 블록만 임시 파일로 추출했으나, 매번 `ezdxf.readfile()`에 넘기는 임시 DXF에는 **약 5.83 MB의 OBJECTS 섹션**도 남았다.
- 이 구간은 기본 두 레이어가 단순 LWPOLYLINE뿐인 도면의 **미리보기 렌더링에 불필요한 개별 객체 관리용 데이터**였다.

## 2. 이번 구현

1. **정규식/반복 검색 줄이기:** `drawing_editor/cad_selective.py`의 canonical CRLF DXF 엔티티 스캐너에서 그룹0 타입을 작은 고정 범위로 읽고, 그룹8 이름은 정확한 태그를 `mmap.find()`로 찾아 중간 정규식 매치 객체 생성을 없앴다. 비정상·비정규 헤더는 기존 `SelectiveDXFUnsupported` 폴백을 유지한다.
2. **안전한 OBJECTS 생략:** 원본 DXF는 절대 수정하지 않고, 임시 staged DXF에 한해서 OBJECTS 섹션을 제외한다. 조건은 (a) 선택된 모델 엔티티가 LINE/LWPOLYLINE/CIRCLE/ARC/POINT/SOLID/TRACE/3DFACE 등의 자체 완결 도형 또는 단순 INSERT (b) 참조 블록을 재귀적으로 확인해 직접적인 독립 도형만 존재 (c) 추가 객체 참조 태그(102, 340, 347, 348, 360, 390, 1001 등)가 없음 (d) 레코드 수 보호 조건 충족 (e) 표준 OBJECTS 섹션 경계가 완전함.
3. **보수적 보존:** 문자/MTEXT, 해치, 폴리라인+VERTEX, 특수/중첩/XREF 블록, 확장 데이터(XDATA), 객체 연결 참조나 분석하지 못한 구조는 기존과 동일하게 전체 OBJECTS 메타데이터를 유지한다. 대용량 소스 자체의 접근 한도를 추가하지 않았다.
4. **빌드 계약 불변:** PySide6 GUI, PNG/JPG 타일 및 일괄 출력, 원본 자동 화질+HD/FHD/QHD/4K/사용자 지정/DPI, 저장된 온맵 규칙, DWG 선택적 외부 변환, Sunrise Group 서명, CMD 전용 `BUILD_ONEFILE.cmd`, 무가상환경/무PowerShell 방침 유지.

## 3. 측정 및 정확도

| 항목 | 이전 공식 개선본 | 금번 개선본 | 해석 |
|---|---:|---:|---|
| 초기 가시 레이어 임시 DXF | 7,247,455 B | **1,413,788 B** | 약 80.5% 축소 |
| 초기 전체 미리보기 | **3.3995 s** | **1.7374 s** | 독립 실행 각각 1회 측정, 약 48.9% 차이 |
| 이전 검증 기록에서 초기 미리보기 | 2.8695 s | 1.4672 s | 서로 다른 단일 실행 측정, 동일 환경 내 관측 |
| 초기 미리보기 완료 후 RSS | 251.69 MiB | 192.15 MiB | 약 59.5 MiB 감소 (각 1회 관측) |
| INSERT 9,533개 레이어 첫 ON | 7.5244 s | 8.5927 s | 개선 입증 안 됨. XDATA 참조 347개 때문에 OBJECTS 보존, 작업 부하와 실행 편차 존재 |
| 같은 상태 재표시 | 실질적으로 즉시 | 실질적으로 즉시 | 기존 PNG/PDF 캐시 유지 |
| 원본 DXF 변경 | 없음 | 없음 | SHA-256 동일 |

**중요:** 1회 또는 두 독립 실행의 숫자만으로 모든 PC에서 같은 비율의 개선을 보장하지 않는다. INSERT 많은 레이어는 오히려 더 오래 걸릴 수 있으며 이번 수정의 대상은 주로 **초기 표시 상태가 단순 벡터일 때의 첫 읽기**이다.

### 픽셀 동일성

이전 ZIP과 신규 소스를 별도 프로세스로 실행해 **동일한 실제 원본 DXF**에서 미리보기 세 상태를 검증했다.

| 상태 | 픽셀 크기 | RGB 픽셀 SHA-256 | 비교 |
|---|---|---|---|
| 초기 두 레이어 표시 | 938×700 | `48a12fbcfb4e8e99c2aedb405c399a471c024ba23bb26400c51e1c4aaaf0dfbf` | 동일 |
| 추가 `C0285311` 레이어 ON | 843×700 | `9658d3fe016eca13e7d892e238e31fbbb5ef6f84c53a7be46e812fb10bb92b8d` | 동일 |
| 추가 레이어 OFF 복원 | 938×700 | `48a12fbcfb4e8e99c2aedb405c399a471c024ba23bb26400c51e1c4aaaf0dfbf` | 동일 |

실물 기본 표시 상태에서 FHD 정책 PNG/JPG 출력 성공, 두 형식 모두 **1447×1080 픽셀**. 원본 DXF SHA-256은 작업 전후 `34ccb4cffee9d022ac489ab5a8a0f1e5f1eb46560d85bc66b2bbfd1bcd25eb49` 동일.

## 4. 안전 회귀 및 근거 파일

- 전체 Python 회귀시험 **105/105 PASS** (기존 100개와 신규 5개). `quality/FINAL_UNIT_TESTS.txt`.
- 신규 검사: 순수 원시 도형의 임시 OBJECTS 제외와 원본/출력 픽셀 동일, 단순 블록 INSERT 허용, 중첩 블록·텍스트·XDATA의 OBJECTS 보존, 장문 레이어명 정확성.
- 성능·해시: `quality/FIELD_DXF_BENCHMARK.json`, `quality/FIELD_DXF_BENCHMARK_OBJECTS_FAST.json`, `quality/REAL_DXF_LEGACY_PIXELS.json`, `quality/REAL_DXF_OPTIMIZED_PIXELS.json`.
- 재현 명령 (CMD, 가상환경 없음):
  ```bat
  py -3 quality\benchmark_field_dxf.py "D:\drawings\your.dxf" --layer C0285311 --report field_result.json
  py -3 -m unittest discover -s tests -q
  BUILD_ONEFILE.cmd
  ```

## 5. 미완료 및 배포 경계

- 이 시험은 **Linux 엔진 실물 DXF 검증**이며 Windows EXE Onefile 재빌드 및 서명, GUI DPI/UX 성능은 이번 턴에서 실행하지 않았다.
- INSERT 9,533개 첫 ON의 기하 해석·블록 확장 렌더링 비용은 본 작업으로 해결되지 않았다. 이 단계의 과감한 생략·선별은 출력 불일치 위험이 있어 보류했다.
- 원본 DXF 파일 및 파생 민감 도면 이미지는 프로그램 ZIP에 포함하지 않는다.
- 기존 GitHub 공식 main/Google Drive 공식 ZIP은 사용자 요청 없이 수정하지 않았다. 이 ZIP은 로컬 개선 검증본이다.
