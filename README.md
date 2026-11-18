# Sunrise Drawing Editor | 도면 편집기

**Sunrise Group**의 Windows 도면 이미지 추출 및 레이어 관리 도구입니다. 환경영향평가, 설계·GIS 자료 작성에 필요한 온맵 PDF와 CAD 도면의 레이어를 제어하여 필요한 도면을 간편하게 추출합니다.

![Sunrise Drawing Editor](assets/app.svg)

## 주요 기능

- 온맵(OnMap) PDF 및 DXF 다중 열기, 레이어 표시/숨김, 검색, 미리보기
- 레이어 ON/OFF 규칙 저장 및 선택 도면 일괄 적용
- 선택 도면별 PNG/JPG 이미지 추출, 원본 자동 해상도 또는 사용자 지정 크기/DPI
- PNG 투명 배경 및 흰 여백 제거, 대용량 분할 출력, 진행률 및 취소
- 원본 도면 비파괴, 결과 파일 덮어쓰기 방지, 라이트/다크 테마
- DWG는 ODA File Converter 또는 DWGSUPPORT 지원 LibreCAD 별도 설치 필요

## 실행 및 배포

Windows 10/11 x64. 소스 실행은 Python 3.11 이상과 `INSTALL_AND_RUN.cmd`, 재실행은 `RUN.cmd`를 사용합니다. `BUILD_ONEFILE.cmd`는 Windows에서 PyInstaller로 단일 EXE를 빌드하며, 기존 Sunrise Group 서명·스모크 테스트·SHA-256 검증 절차를 유지합니다. PowerShell 및 가상환경을 요구하지 않습니다.

- [공식 Releases](https://github.com/Peter-msk/Sunrise_Drawing_Editor/releases): 실제 공개된 파일만 다운로드하십시오. 소스 ZIP은 EXE가 아닙니다.
- 주요 기술: Python, PySide6, PyMuPDF, ezdxf, Pillow.
- 사용법 및 상세 개발 검증 이력: [기존 기술 문서](docs/TECHNICAL_HISTORY.md).

## 공지사항 및 업데이트

공식 GitHub [notice.txt](https://github.com/Peter-msk/Sunrise_Drawing_Editor/blob/main/notice.txt) 및 [latest.json](https://github.com/Peter-msk/Sunrise_Drawing_Editor/blob/main/latest.json)을 사용합니다. 공지사항과 업데이트는 독립 버튼 및 라이트/다크 테마 팝업으로 확인합니다. 배포된 Windows Onefile EXE는 실행 시 신규 공지와 업데이트를 확인하고, 신규 EXE가 공식 등록된 경우 사용자 선택으로 공식 배포 페이지를 엽니다. 자동 교체 후보 코드도 포함되지만 Windows 실기 검증 및 신뢰 가능한 공식 서명 EXE 등록 전에는 비활성화합니다. 현재 배포용 새 EXE는 등록되지 않았습니다.

## 피드백

[GitHub Issues](https://github.com/Peter-msk/Sunrise_Drawing_Editor/issues)에 증상, 실행 버전, 재현 순서, 출력 조건을 알려 주세요. 업무 도면, 개인정보, 인증정보는 공개 이슈에 첨부하지 마십시오.

## 라이선스 및 출처

프로젝트 자체 라이선스는 별도 확정되지 않았으며 공개 열람이 자유로운 재배포 허가를 의미하지 않습니다. 외부 라이브러리 조건은 [THIRD_PARTY_NOTICE.md](THIRD_PARTY_NOTICE.md)를 참고하십시오. 특히 PyMuPDF AGPL/상용 라이선스 및 Qt LGPL 의무를 확인해야 하며, 온맵 등 원본 자료의 출처 및 이용조건을 준수해야 합니다.

Copyright © 2026 Sunrise Group. All rights reserved.
