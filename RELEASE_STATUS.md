# Sunrise Drawing Editor — 공식 배포 상태

- 승격일: 2026-11-12 (한국시간)
- 상태: **사용자 실기검증 완료 선언에 따라 공식 소스 기준본으로 승격**
- 제품명: Sunrise Drawing Editor (프로그램 내 버전 번호 없음)
- 공식 기준 소스: 이 저장소의 `main` 브랜치와 동시 배포한 `Sunrise_Drawing_Editor_Release.zip`
- 실기검증 증거: 사용자 직접 완료 선언. **이 저장소에는 Windows 실기 로그나 서명 검증 결과를 첨부하지 않았음**
- 이 작업 환경에서 확인한 사항: 기존 패키지 ZIP 무결성, 파일명·보안 문자열 감사, 소스 및 문서 구성
- 실행 및 배포 방식: Windows x64, `BUILD_ONEFILE.cmd`, CMD만 사용, 가상환경 미생성, PySide6, PyInstaller onefile
- 공지·업데이트 기능: 미포함
- 그룹 서명: `CN=Sunrise Group`; 자체서명은 외부 PC의 신뢰 보증이 아니므로 인증서 경로별 구분 필요
- DWG: 별도 ODA 변환기 또는 지원되는 LibreCAD 실행파일 의존

## 공개 저장소의 범위

소스, 빌드 CMD 및 Python 헬퍼, 문서, 소규모 합성 테스트 자료만 포함합니다. 개발 단계의 원시 QA 로그와 내부 실행 경로를 포함하는 자동 측정 결과, 인증서/비밀키, 대용량 실무 도면은 공개하지 않습니다.

## 라이선스

본 프로젝트 자체의 라이선스는 소유자가 별도 명시하기 전까지 지정되지 않았습니다. 외부 라이브러리 사용 및 재배포 조건은 `THIRD_PARTY_NOTICE.md`에 정리돼 있습니다. 특히 PyMuPDF AGPLv3/상용 라이선스와 Qt LGPL 의무를 정식 바이너리 배포 전 확인해야 합니다.

## 실제 대형 DXF 보완 검증본 (공식 main 미반영)

사용자가 첨부한 401.8MiB 실물 DXF의 선택적 레이어 적재와 참조 블록 폐포를 구현했습니다. 기존 92개 + 신규 8개 = 100개 자동시험 통과, 실물 엔진 첫 미리보기 약 2.87초, 원본 SHA-256 불변. Windows Onefile/서명 재검증 및 GitHub·Drive 공식본 교체는 이번 작업 범위에서 수행하지 않았습니다. 버전 번호를 부여하지 않습니다.


## 최신 로컬 DXF 최적화 검증본 (공식 원격 저장소 미반영)

402MiB 사용자 실물 DXF에서 독립 검증한 추가 최적화를 적용한 작업 사본입니다. `FIELD_DXF_SECOND_PASS.md` 및 `quality/FINAL_UNIT_TESTS.txt`에 엔진 검증 증거가 있습니다. Windows 새 EXE 및 재서명 실기시험을 이번 실행 환경에서 수행하지 않았으므로 **공식 GitHub main과 Drive 공식 ZIP은 자동 변경하지 않았습니다**.

## 최신 로컬 반복 INSERT 렌더링 최적화 검증본 (공식 원격 저장소 미반영)

사용자 제공 421,316,933바이트 DXF의 반복 INSERT 최초 ON 비용을 줄였습니다. 직전 FastPath 대비 8.63초 → 3.54초(독립 단일 실행), 픽셀·PDF 명령 스트림 일치. 인라인 문자열 XDATA 안전처리 및 PyMuPDF 명령 리스트 재생 최적화가 포함되며, 별도의 공식 버전 번호는 부여하지 않습니다. 새 Windows EXE 실기는 이번 환경에서 수행하지 않았으며, 기존 GitHub/Drive 공식 기준본을 변경하지 않았습니다. `FIELD_DXF_INSERT_OPTIMIZATION.md` 참고.


## UI/UX 개선 검증본

- 기준: 공식본 위에 402MiB 실물 DXF INSERT 처리 최적화까지 반영한 별도 ZIP.
- 이번 변경: UI/UX 위치, 아이콘, 상태, 레이어 검색/필터, 창 DPI 배치만 개선. 도면 파서/렌더러/추출 코어는 미변경.
- 검증: `UI_UX_FINAL_AUDIT.md` 참조.
- **GitHub main·Google Drive의 기존 공식 ZIP은 이번 요청에서 수정하지 않음.**
- Windows GUI/EXE 실기검증은 별도(현재 Linux에 PySide6 미설치).

## 차기 소스 검증본 — 402MB DXF 3차 병목 개선

본 압축본은 이전 공식 공개 소스에 대한 **후속 개선 검증본**이다. 사용자가 제공한 철탑 DXF로 1·2·3차 심층 최적화와 총 131개 자동시험을 수행했다. 원본 파일 및 이미지는 포함하지 않는다. GitHub `main`/Google Drive 공식본은 이번 대화에서 아직 수정하지 않았으며, Windows Onefile/GUI/서명 실기 검증도 새 소스에 대해서는 **NOT RUN**이다. 자세한 근거: `THREE_PASS_DEEP_VALIDATION.md`.
