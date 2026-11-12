# Sunrise Drawing Editor — GitHub 공개소스 조사 및 실제 속도 개선 보고서

검증일: 2026-11-12. 프로그램에 버전 번호를 사용하지 않음.

## 1. 공개 저장소 검토 결과 (공개 GitHub 자료)

| 저장소 | 주소 | 확인 기술 | 이번 처리 | 라이선스 주의 |
| --- | --- | --- | --- | --- |
| PyMuPDF | https://github.com/pymupdf/PyMuPDF | 페이지 파싱 명령(DisplayList), 클립 Pixmap | **기존 의존성 API를 추가 활용** | AGPLv3 또는 상용 |
| ezdxf | https://github.com/mozman/ezdxf | CAD 벡터 파싱, recording/replay, 레이어 렌더링 | 기존 엔진 유지 | MIT |
| libvips | https://github.com/libvips/libvips | 온디맨드 이미지 처리, 스트리밍, 저메모리 | 비교 후보, **미번들** | LGPL-2.1-or-later |
| pyvips | https://github.com/libvips/pyvips | libvips Python 인터페이스 | 비교 후보, **미설치·미번들** | MIT (네이티브 libvips는 별도) |
| libpng | https://github.com/pnggroup/libpng | 무손실 PNG 인코딩 및 디코딩 | 현재 Python zlib 스트림 유지 | 별도 라이선스 확인 필요 |

공식 기술 근거: https://pymupdf.readthedocs.io/en/latest/displaylist.html 및 https://pymupdf.readthedocs.io/en/latest/coop_low.html.

**선택 기준:** 이미 채택된 PyMuPDF, ezdxf 및 Python 표준 zlib를 활용하는 편이 Windows CMD 전용 onefile 빌드, 기존 Qt 충돌 방지 설정, 대용량 타일 기능을 유지하는 데 유리함. libvips/pyvips의 네이티브 배포 의존성과 라이선스 의무는 실제 Windows 패키징·대용량 성능 증거를 확보하기 전까지 추가하지 않음.

## 2. 실제 적용 코드

1. `drawing_editor/tiles.py`: 페이지마다 만들어진 DisplayList를 대용량 타일 하나의 출력이 끝날 때까지 재사용하여 여러 세로 띠의 반복 PDF 파싱을 억제. 주석이 누락되지 않게 `annots=True`로 생성. DisplayList 생성에 실패하면 기존 `page.get_pixmap`으로 안전하게 복귀.
2. `drawing_editor/tiles.py`: 전체 가로폭이 한 개의 클립 안에 있는 경우 PNG RGB 버퍼를 Python 행별 루프 대신 연속 메모리 복사로 채움. PDF의 해상도·회전·픽셀 좌표 계산은 변경하지 않음.
3. `drawing_editor/tiles.py`: PNG 여러 행을 묶어 zlib에 전달, 압축 레벨을 4에서 2로 조정. 압축은 **무손실**이므로 화질·원본 픽셀에는 변화가 없으나 저장된 PNG 파일 크기는 증가할 수 있음. 원본 파일 보존 및 중단된 출력물 정리 정책 유지.
4. `drawing_editor/tiles.py`: JPG 임시 RAW 버퍼는 동일 mmap에서 즉시 읽으므로 JPEG 인코딩 전 중복 `mmap.flush()` 제거. 최종 JPEG 인코딩 품질 98 및 크로마 서브샘플링 없음 그대로 유지.
5. `drawing_editor/core.py`: 같은 스레드에서 동일 PDF 문서·페이지·OCG 레이어 조합을 확대·이동할 때 DisplayList 1개만 재사용. 레이어가 변경되면 즉시 무효화, 임시 PDF 문서에서는 비활성화, 96MiB 초과 소스에서는 영구 캐시 비활성화. 이 제한은 파일 열기 제한이 아닌 **선택적 메모리 최적화 예산**임.
6. `tests/test_github_optimization.py`: 레이어 토글 무효화, 주석 보존, PNG/JPG 화질, DisplayList 실패 시 폴백, 원본 무변경 검사 추가.

## 3. 실행 측정 결과 (합성 PDF, 실물 온맵 아님)

실행 코드: `python quality/benchmark_github_optimization.py`.
이전 타일 코드(`quality/baseline_tiles.py`) 및 현행 타일 코드를 동일 프로세스에서 순서를 교차해 **각각 3회** 실행. 파일 형식·입력·출력 크기를 고정함.

- 시험 환경: Linux, PyMuPDF 1.26.7; 합성 벡터 PDF(선 객체 3,800개, OCG 1개, PDF 주석 1개)
- 대용량 PNG: 3000×4250픽셀, 이전 0.298407초 → 개선 0.216103초 (**27.6% 단축**)
- PNG 크기: 이전 531,033바이트 → 개선 756,954바이트 (**압축량 감소로 크기 증가; 픽셀 일치**)
- JPG: 2500×3400픽셀, 이전 0.200192초 → 개선 0.178930초 (**10.6% 단축**)·파일 크기 동일
- 확대 영역 25곳 반복: 이전 0.466743초 → 개선 0.441249초 (**5.5% 단축**)
- 두 출력 형식의 최종 이미지 픽셀 비교: **PASS** / PDF SHA-256 원본 불변: **PASS**

**한계:** 단순 페이지·짧은 미리보기에는 DisplayList를 만드는 비용이 이득보다 클 수 있음. 실제 온맵 PDF의 OCG/래스터 구성과 대형 CAD의 해치·블록·외부참조 등에 따라 효과가 달라짐. 이 시험은 100~500MB 실물 DXF/DWG, Windows GUI 렌더링 FPS, onefile 빌드 속도에 대한 증거가 아님.

## 4. 제품 계약 유지

- 출력 기본값 `원본 자동` 유지. HD/FHD/QHD/4K, 사용자 지정 최대 픽셀 및 DPI 기능 유지.
- 실제 픽셀 크기와 비율·원본 레이어 조합 유지. PNG는 무손실, JPG는 기존 품질98 유지.
- PDF/온맵·DXF·DWG 외부 변환 처리, 레이어 규칙 일괄 적용 및 다중 이미지 추출 유지.
- Windows `BUILD_ONEFILE.cmd` 전용·PowerShell 없음·가상환경 생성 없음·PySide6 단독 패키징·Sunrise Group 서명 절차 유지. Onefile EXE 실제 Windows 실행/서명은 **NOT RUN**.
- libvips는 요구조건에 필요한 DLL·Onefile 배포·재배포 의무가 정리되기 전까지 추가하지 않음. 기존 PyMuPDF의 AGPL/상용 재배포 조건은 여전히 검토 필요.

## 5. 검증 범위

- `python -m unittest discover -s tests -q`: **92/92 PASS** (기존 86 + 신규 6)
- 위 스크립트 전후 시간 및 픽셀 동일성: `quality/GITHUB_OPTIMIZATION_BENCHMARK.json` 확인
- 원본 도면은 읽기 전용으로 취급. 일부 사용자 라이브러리의 실제 대용량 원본 접근 및 Windows EXE·GUI·서명은 **NOT RUN**.
- 외부 라이브러리 소스 파일을 직접 복사·번들하지 않았으며, 기존 의존성의 공개 API와 표준 라이브러리를 사용함.
