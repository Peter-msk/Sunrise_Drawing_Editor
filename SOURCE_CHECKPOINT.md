# Sunrise Drawing Editor — 소스 체크포인트

- 제품명: Sunrise Drawing Editor
- 버전 레이블: 사용하지 않음
- 기준 소스: `Sunrise_Drawing_Editor_일괄처리.zip`
- 이번 변경: onefile Windows 빌드·그룹 서명 단계, 대용량 도면 비동기 메타데이터 적재 및 CAD 렌더 조합 캐시, 공개 LibreCAD CLI 선택적 DWG 변환기
- 앱 업데이트·공지사항: 없음
- Windows 바이너리 생성 및 서명은 **Windows 빌드 머신에서 실행 필요**
- Python 단위시험: 41/41 PASS
- Runtime: Windows NOT RUN
- 무결성: `MANIFEST_SHA256.txt` 참조

## 최신 개선 소스 체크포인트

- 변경: CAD 그리기 명령 캐시 및 원래 그리기 순서 보존, 캐시 메모리 안전상한/기존 경로 자동 폴백, 레이어 상태 원복 버그 회귀 검증
- 기준: 기존 onefile·그룹서명·일괄처리 배포 소스 (기존 기능 유지)
- 자동시험: 46/46 PASS
- Windows Onefile 서명 및 실물 도면 Runtime: NOT RUN

## 최신 변경: CAD OCG 네이티브 레이어 전환

- 부모 기준: 기존 `Sunrise_Drawing_Editor_렌더링_개선.zip`.
- 변경 모듈: `drawing_editor/core.py`(OCG 레이어 캐시·도면 범위 검사), `tests/test_cad_ocg.py`(추가 회귀); 기존 레이어 캐시 검사 기준을 변경 경로의 의미에 맞춰 강화.
- 외부 종속성 추가 없음. 레이어 변경이 도면 바운딩을 바꾸는 경우에는 직접 CAD 렌더링으로 폴백.
- 자동시험 51/51 PASS; 동일 도면의 기존 엔진 대비 8/8 픽셀 이미지 동일.
- Windows Onefile/서명/대용량 실물 CAD Runtime: NOT RUN.
- 버전 번호 미사용; 공지·업데이트 기능 추가 없음.

## 최신 변경: 대용량 CAD 경량 목록 및 선택적 공간 렌더링

- 부모 기준: 이전 `Sunrise_Drawing_Editor_최적화.zip` (51회 회귀검증 기준본).
- 변경 모듈: `drawing_editor/core.py` (대용량 클립·캐시 가드), `drawing_editor/cad_spatial.py` (안전 그리드), `drawing_editor/cad_catalog.py` (ASCII DXF 레이어 목록), `drawing_editor/window.py` (목록 로딩·작업자 역할 분리), 신규 회귀시험 2개 파일.
- 추가 타사 라이브러리 없음. 원본·레이어 및 자동 출력 계약, onefile 빌드 및 그룹서명 스크립트는 유지.
- 엔진 자동시험 **58/58 PASS**, 합성 확대 클립 출력 4/4 픽셀 일치. 성능 측정: `quality/LARGE_CAD_BENCHMARK.json`.
- Windows 실기/실물 100MB 이상 CAD: NOT RUN. 버전·공지사항·업데이트 기능 추가 없음.


## Current delivery checkpoint — GitHub performance optimization

- Branch source baseline: `Sunrise_Drawing_Editor_Optimized.zip`. Historical QA files are retained as records.
- Modified: `drawing_editor/core.py`, `drawing_editor/tiles.py`; new `tests/test_github_optimization.py`, benchmark and its isolated legacy writer in `quality`.
- Source-based GitHub comparison / benchmarks / constraints: `GITHUB_PERFORMANCE_AUDIT.md`.
- Latest engine tests: 92/92 PASS. Windows onefile build, UI and Authenticode: NOT RUN.
