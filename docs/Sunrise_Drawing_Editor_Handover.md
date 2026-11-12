# Sunrise Drawing Editor — 개발·운영 인수인계서

작성일: 2026-11-12  
기준: `Sunrise_Drawing_Editor_Release.zip` 공식 소스 기준본

## 1. 인수 결과

사용자가 Windows 실기검증 완료를 선언함에 따라 소스를 공식 운영 기준으로 승격한다. 이 채팅의 작업 환경에서는 Windows 원본 실기검증의 상세 로그를 재확인하지 못했으므로, **사용자 승인**과 **자동시험 기록**은 서로 구분한다. 별도 버전 번호를 관리하지 않는다.

## 2. 제품 목적·범위

- 다중 온맵 PDF 및 DXF를 열어 레이어 ON/OFF 상태 관리
- DWG는 별도 외부 변환기(ODA 또는 DWG 지원 LibreCAD)를 거쳐 처리; 모든 DWG를 기본 지원한다고 보장하지 않음
- 레이어 규칙을 저장해 다수의 온맵 도엽에 이름 기준 일괄 적용
- PDF/DXF 레이어 화면 표시, 확대·이동 시 부분 렌더링, PNG/JPG 다중 개별 추출
- 원본 기준 자동 해상도가 초기값; HD/FHD/QHD/4K, 사용자 지정 픽셀 크기, DPI 선택 제공
- 5,000만 픽셀 일괄 거부 제한 대신 대용량 출력은 타일/스트라이프 기록
- Sunrise 테마(라이트/다크), 고정 분할 레이아웃, 전용 아이콘
- 공지사항·자동업데이트·서버 연동 기능 없음

## 3. 소스 구조와 엔트리포인트

- `main.py`: 시작/자체 진단 진입점
- `drawing_editor/window.py`: PySide6 사용자 화면, 이벤트 및 작업자
- `drawing_editor/core.py`: PDF/DXF/DWG 렌더 엔진과 표시 상태
- `drawing_editor/tiles.py`: 고해상도 타일 이미지 출력
- `drawing_editor/state.py`: 선택 상태 및 규칙 저장
- `drawing_editor/batch.py`: 다중 추출 및 파일명 충돌·취소·오류 처리
- `drawing_editor/cad_catalog.py`, `cad_spatial.py`: 대용량 CAD 레이어 목록·부분 렌더링
- `drawing_editor/dwg_fallback.py`: 외부 DWG 변환 경로
- `BUILD_ONEFILE.cmd`, `build/`: CMD 전용 onefile 빌드, 인증서 서명, 사전 진단
- `tests/`: 파이썬 단위/회귀시험

## 4. Windows 빌드·실행

1. Windows 10/11 x64에서 기존 설치된 Python 3.11+ 및 Windows SDK SignTool을 준비한다.
2. 소스 루트의 `BUILD_ONEFILE.cmd` 실행. PowerShell 미사용, `.venv` 미생성. PyQt5/PyQt6/PySide2 패키징 제외.
3. 산출물: `dist\Sunrise Drawing Editor.exe`, `SHA256.txt`, `SIGNATURE_STATUS.json`.
4. 서명 실패·기동 실패 시 이전 게시 EXE를 유지하도록 설계됨. 실제 결과는 생성 로그로 확인한다.
5. 새 환경에서 DLL/Qt 플러그인 동봉, 서명 신뢰, Onefile 초기 실행시간을 점검한다.

## 5. 재현·검증 체크리스트

- `RUN_TESTS.cmd`로 자동시험 실행하고 결과 로그 보존
- 온맵 PDF에서 OCG 레이어 제어가 실제 출력 픽셀에 반영되는지 확인
- 100MB 이상 DXF에서 최초 로딩, 확대, 레이어 전환 시 RAM/시간 측정
- 비정형 페이지 회전(0°/90°/180°/270°) 및 타일 경계 누락 점검
- 다중 파일 규칙 적용에서 존재하지 않는 레이어, 잠금/중복 레이어 처리
- 원본 파일 SHA-256 불변 및 출력 명칭 충돌 없음 확인
- PNG 원본 자동 화질, JPG 손실 압축, 사용자 해상도/DPI 선택 확인
- Windows 100/125/150/175% 화면 배율의 고정 UI, 라이트/다크 UI 확인
- Onefile 빌드, Authenticode 주체/체인, 공인/내부 자체서명 구분 검증

## 6. 위험 및 유지보수 경계

- PyMuPDF AGPLv3 또는 상용 계약, PySide6/Qt 라이선스 등 외부 재배포 조건 확인 필요.
- 대용량 DXF 처리 한계는 파일 용량보다 객체 수·해치·폰트·블록/XREF에 영향 받음.
- 원본 영상/도면 편집(내용 저장) 기능 아님: 프로그램의 레이어 표시 선택과 이미지 출력만 변경.
- Sunrise Group 자체서명은 공인 발급 인증서와 동일하지 않음.
- 원본을 훼손하는 코드 변경 및 미검증 Windows PASS 주장 금지.

## 7. 운영 인수 기준

GitHub의 `main`을 공개 소스 기준본으로, Google Drive의 제품 폴더에 저장된 최신 ZIP과 이 문서, 작업지시서, 개발계획서를 운영 근거로 사용한다. 문제 발생 시 해당 ZIP과 테스트 자료를 기준으로 변경을 최소화한다.
