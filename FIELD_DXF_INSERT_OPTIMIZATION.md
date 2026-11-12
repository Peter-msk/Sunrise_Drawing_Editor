# Sunrise Drawing Editor — 실물 철탑 DXF 반복 INSERT 병목 최적화

- 분석 및 구현일: 2026-11-12 (한국시간)
- 대상 입력: 사용자가 대화에 첨부한 `3구간 최종 철탑.dxf`, 원본 421,316,933바이트(약 401.8MiB)
- 대상 프로그램: 직전 `Sunrise_Drawing_Editor_DXF_FastPath.zip` 기반 보완 사본
- 실행환경: Linux / Python 3.13 / ezdxf 1.4.4 / PyMuPDF 1.26.7 / Pillow 12.3.0
- 이 ZIP은 사용자의 원본 철탑 DXF를 포함하지 않는다.

## 1. 실측 병목

최초 기본 표시 상태는 레이어 290개 중 2개를 켜며 실제 표시 엔티티는 LWPOLYLINE 39개다. 그러나 사용자가 숨겨진 `C0285311` 레이어를 켜면 INSERT 9,533개가 추가된다. 원본 블록 `C0285311`의 개별 INSERT는 LINE 두 개를 포함해, ezdxf가 약 19,066개 선 그리기 명령으로 확장한다.

실측에서 임시 DXF 생성, ezdxf 파싱, CAD Frontend 기하 확장, PDF 내부 명령 생성의 작업이 각각 발생했다. 단순 선을 하나의 compound path로 합치면 교차점의 안티앨리어싱이 변해 픽셀 완전 일치 검증에 실패했으므로 채택하지 않았다.

## 2. 변경 내용

### A. 문자열 XDATA와 OBJECTS 메타데이터 처리 구분

`drawing_editor/cad_selective.py`에서 표준 DXF의 XDATA 코드 `1001`(앱 ID) 및 `1000`(인라인 문자열)로만 구성된 엔티티는 외부 객체 참조가 아니라는 점을 구분한다. APPID 정보는 기존 TABLES 섹션을 유지하므로 손실되지 않는다. 레이어 선별 시 원본 레코드를 바이트 그대로 복사하고, **임시 렌더링 DXF**에서만 불필요한 OBJECTS 섹션을 생략한다.

안전 정책: 1005 핸들 참조, 숫자/중첩/지원하지 않는 XDATA, 102 확장 사전, 340/347/348/360/390 등 외부 연계, 특수 엔티티, XREF 및 복합 블록은 기존 보수적 경로를 사용한다. 원본 파일의 메타데이터를 삭제하지 않는다.

### B. PDF 개별 선 그리기 명령의 고속 처리

신규 `drawing_editor/cad_render_fast.py`는 기존 ezdxf Frontend에서 생성된 선·색상·폭·레이어·그리기 순서를 그대로 받는다. 불투명한 일반 LINE에 대해서만 PyMuPDF의 원래 `Shape.finish()`가 만드는 문자열 조각을 스타일별로 한 번 검증하고, 연속된 개별 PDF 그리기 명령을 목록에 추가한 후 일괄 결합한다. 개별 선마다 독립 `q ... S ... Q` 연산을 유지하므로 한 번에 칠하는 compound path 방식과 다르다.

PyMuPDF의 내부 출력 형식이 바뀌거나 안전조건이 맞지 않거나 투명도가 있는 경우에는 **기존 stock PyMuPDF 백엔드**로 돌아간다. 임시 메모리 사용은 최대 16,384개의 문자열 조각 단위로 제한한다. 빌드 의존성을 추가하지 않는다.

## 3. 실제 원본의 개선 전후 결과

동일한 첨부 DXF 및 동일한 미리보기 조건으로 이전 FastPath와 이번 보완 코드를 각각 별도 Python 프로세스에서 실행한 단일 관측값이며, 고정 성능 보장은 아니다.

| 항목 | 이전 FastPath | 개선 후 |
|---|---:|---:|
| 기본 상태 최초 미리보기 | 2.0340초 | 1.7581초 |
| `C0285311` 최초 ON 및 미리보기 | **8.6257초** | **3.5378초** |
| 레이어 ON 상태의 프로세스 RSS | 276.14MiB | 220.12MiB |
| 임시 적재 DXF 크기 | 8,987,348바이트 | 3,153,681바이트 |
| 임시 적재 엔티티 수 | 9,572개 | 9,572개 |
| ON → OFF 후 기본 미리보기 복원 | 0.000105초 | 0.000093초 |

주요 병목인 INSERT 최초 ON 시간이 약 59.0% 단축됐고, 임시 DXF는 약 64.9% 축소됐다. 다른 반복 실측에서는 개선본 3.83초도 관측돼 운영 환경에 따른 편차가 있다. Python PDF 명령 재생만을 별도 측정하면 기존 약 4.1초에서 이번 약 1.2~1.5초 수준으로 감소했으며, **PDF 내용 스트림은 바이트 동일**했다.

### 실제 원본 정확성 비교

| 상태 | 출력 크기 | RGB 픽셀 SHA-256 | 결과 |
|---|---:|---|---|
| 기본 2개 레이어 | 938×700 | `48a12fbcfb4e8e99c2aedb405c399a471c024ba23bb26400c51e1c4aaaf0dfbf` | 기존과 일치 |
| `C0285311` ON | 843×700 | `9658d3fe016eca13e7d892e238e31fbbb5ef6f84c53a7be46e812fb10bb92b8d` | 기존과 일치 |
| `C0285311` OFF 복원 | 938×700 | `48a12fbcfb4e8e99c2aedb405c399a471c024ba23bb26400c51e1c4aaaf0dfbf` | 기존과 일치 |

추가 ON 상태에서 FHD 원본 비율 유지 PNG/JPG 저장을 실행했으며, 두 결과 모두 **1301×1080픽셀**이었다. 원본 DXF의 SHA-256은 테스트 전후 모두 `34ccb4cffee9d022ac489ab5a8a0f1e5f1eb46560d85bc66b2bbfd1bcd25eb49`였다.

## 4. 보존 사항 및 미검증 범위

- 기본 원본 자동 해상도와 HD/FHD/QHD/4K/사용자 지정/DPI, PNG/JPG, 다중 도면 및 온맵 PDF, DWG 외부 변환을 유지한다.
- CMD 전용 `BUILD_ONEFILE.cmd`, 현재 시스템 Python, 가상환경 없음, PowerShell 없음, PySide6 단일 바인딩 및 Sunrise Group 서명 절차를 변경하지 않는다.
- 제품 이름에 버전 표시·공지·업데이트 기능을 추가하지 않았다.
- 이 Linux 환경에서 검증한 것은 실물 DXF 엔진이며, **새 코드의 Windows Onefile EXE 생성·GUI·Authenticode 서명은 실행하지 않았다.** 사용자 이전 Windows 검증을 이번 수정본의 자동 PASS로 간주하지 않는다.
- 무제한 레이어 ON, 모든 XREF/IMAGE/해치, 모든 PyMuPDF 버전에서의 동일 속도는 보장하지 않는다. 고속 선 생성 경로가 사용 환경과 맞지 않으면 기존 경로로 자동 복귀한다.
- 이전에 승격된 GitHub `main` 및 Google Drive 공식 ZIP은 이 개선 검증본 생성으로 자동 변경하지 않는다.

## 5. 재현 방법 (Windows CMD, 가상환경 생성 없음)

```bat
py -3 -m unittest discover -s tests -q
py -3 quality\real_insert_probe.py "D:\drawings\3구간 최종 철탑.dxf" comparison.json C0285311
BUILD_ONEFILE.cmd
```

세부 단위시험: `tests/test_cad_selective.py`, `tests/test_cad_fast_render.py`. 이전과 새 이미지의 픽셀·개별 PDF 그리기 스트림을 비교하며, 원본을 읽기 전용으로 사용한다.
