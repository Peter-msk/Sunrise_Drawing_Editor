# Sunrise Drawing Editor — Google Drive ThreePass 기준본 대조 및 CAD 2차 최적화

- 기준일: 2026-11-12 (한국시간)
- **운영 기준본(비변경)**: Google Drive `Sunrise_Drawing_Editor_Final_20261112.zip`; SHA-256 `655f4d47b83aca64fcabdd89d5e1aea0939ff84930e0f80d9e4c5d49fd16892e`
- 개발 출발점: 직전 `Sunrise_Drawing_Editor_CAD_Performance_Improved.zip`; SHA-256 `db55a888ba03ccd9464570afbf0d0abb0041178e5f7f75a8ec2ef02e7b3fd136`
- 상태: **개발 후보 / 공식 Release 아님**. GitHub `main` 및 Drive 원본을 수정하지 않음.

## 1. Drive 자료 수신 및 대조

관련 Drive 자료:

- 최종 ZIP: https://drive.google.com/file/d/11LHEHhMl4ep1ziR3TpxDrch8SH3J6dET/view
- ThreePass 인수인계서: https://docs.google.com/document/d/1yO45TE6X4GsbLNl-Eu4p9_vZjIdDG6JYagDFl3j8f4k/edit
- 작업지시서: https://docs.google.com/document/d/1GHR6d8-hCN1D-leWPUoOtfTtgWuezab-hcZ-cYQcw2Y/edit
- 운영 계획: https://docs.google.com/document/d/19gNcYTfIgbF0kCj52il9QOyxADCRGPV2UqSPDCmn6bw/edit

Drive ThreePass ZIP은 117개 파일이다. 직전 개선 ZIP과 상대경로/파일해시를 대조한 결과, 동일 113개, 차이 3개 (`SOURCE_SHA256_MANIFEST.json`, `drawing_editor/core.py`, `drawing_editor/cad_selective.py`), 개선본의 누락 1개 (`quality/DEEP_THREE_PASS_UNITTESTS.log`), 개선본의 추가 7개였다. 누락된 기존 QA 로그를 **원본 바이트 그대로 복원**했다.

특히 Drive 문서가 확정하는 402MiB 실물 DXF(421,316,933바이트) ThreePass 결과 및 131/131 회귀시험은 기존에 완료된 *과거 증거*다. 이 ZIP에는 실물 DXF가 포함되어 있지 않다.

## 2. 이번 코드 변경

- `drawing_editor/core.py`: 선택적 레이어 적재 작업에서 전체 CAD recorder를 먼저 구성하는 불필요한 중복 생성 방지. 기본 full-DXF 경로는 변경하지 않음.
- `drawing_editor/cad_selective.py`: 같은 원본/동일 레이어의 INSERT 참조 블록명과 보수적 OBJECTS 의존성 판정 캐시. 원본 크기/mtime 변경 시 색인 사용을 거부.
- `drawing_editor/cad_selective.py`: DXF 핸들 **값** `102`를 OBJECTS 의존성 **그룹 코드** `102`로 오판하는 false-positive 수정. 엄격한 CRLF 코드/값 번갈아 스캔; 256KiB 초과 의심 엔티티는 원래 OBJECTS 보존.
- 직전 ZIP의 선택 엔티티 연속구간 묶음 기록(4MiB 한도), DisplayList 실패 시 정확 렌더러 폴백과 이전 모든 기능 유지.
- 신규 `tests/test_cad_next_optimization.py` 6개 시험: 반복 블록 캐시, OBJECTS 캐시, true code/handle value 구별, 계층 블록, 반복 이미지 동일성, 원본 변경 무효화.

## 3. 실제 검증

- 전체 자동시험 **145/145 PASS** (2026-11-12, Python/Linux 실행 경로). 파일 `quality/ROUND2_FULL_TESTS.log`.
- ZIP 재패키징 후 **CRC 검사 및 매니페스트** 검사 필수.
- 합성 DXF(233,370바이트; 900 반복 INSERT + 300 숨김 LINE) 각 환경 독립 프로세스 3회 중앙값 (`quality/DRIVE_BASELINE_COMPARE.json`):

| 구간 | Drive ThreePass | 이번 후보 | 판정 |
|---|---:|---:|---|
| 첫 선별 적재 | 4.28ms | 6.71ms | **느려짐**, 최적화 개선으로 주장하지 않음 |
| 반복 선별 적재 | 2.44ms | 0.60ms | 약 75% 단축 |
| 최초 미리보기 | 708.26ms | 615.61ms | 약 13% 단축, 합성 입력에 한정 |
| 확대 미리보기 | 20.17ms | 26.17ms | 이득 미입증, 측정 변동 있음 |

- **최초 및 확대 RGB 픽셀 SHA-256 일치**, 입력 원본 SHA-256 불변.
- 선별 임시 DXF의 **파일 SHA-256은 다름**: 보수적 group-code 판정 수정으로 불필요한 OBJECTS가 제거된 탓이며, 출력 이미지의 RGB 동일성을 별도 검증함.

## 4. 승인 및 미검증 경계

- Drive의 ThreePass Final은 공식 기준으로 계속 보존한다.
- 4차 DisplayList는 *실험 후보 상태를 유지*한다. 단일 도면 확대 렌더에서 유의미한 이득이 확인되지 않았으며, 402MiB 원본의 25회 확대/이동, 메모리 RSS 검증 전에는 공식 기능으로 승격하지 않는다.
- 실제 402MiB DXF 신규 재측정: **NOT RUN** (원본 바이트 없음).
- Windows 10/11 Onefile EXE 빌드/SignTool/100·125·150·175% DPI UI: **NOT RUN**.
- PyMuPDF·PySide6 재배포 라이선스: **PENDING**.
- 원본 직접 쓰기/덮어쓰기, 프로그램 버전/자동업데이트/공지 추가, 빌드 PowerShell·.venv 강제 없음.
- GitHub main 및 Google Drive 기존 파일 **미수정**. 정식 배포는 사용자 승인과 Windows 실기 PASS 이후 판단.
