# Sunrise Drawing Editor

**도면 레이어 관리 및 이미지 추출 프로그램 · v1.0.0**

![Sunrise Drawing Editor](assets/app.svg)

Sunrise Drawing Editor는 환경영향평가, 설계 및 GIS 업무에 사용하는 온맵(OnMap) PDF와 CAD 도면에서 필요한 레이어를 선택하고 보고서에 활용할 이미지를 추출하는 Windows용 프로그램입니다.

## 개발 목적

복잡한 도면에서 필요한 정보만 표시하고 여러 도면을 동일한 조건으로 이미지화하는 반복 작업을 줄이는 것이 목적입니다. 원본 도면을 수정하지 않고 레이어 표시 상태와 출력 조건을 조정할 수 있습니다.

## 주요 기능

| 기능 | 설명 |
| --- | --- |
| 도면 관리 | 온맵 PDF, DXF 및 DWG 불러오기와 다중 도면 관리 |
| 레이어 제어 | 레이어 검색, 개별 표시/숨김, 전체 켜기/끄기 |
| 레이어 규칙 | 표시 조건 저장 및 선택 도면 일괄 적용 |
| 미리보기 | 확대·축소·이동, 확대 영역 고해상도 렌더링 및 단계별 진행률 |
| 이미지 추출 | 선택 도면의 PNG·JPG 개별 및 일괄 추출 |
| 출력 설정 | 원본 자동 해상도 또는 사용자 지정 이미지 크기 및 DPI |
| PNG 편집 | 투명 배경 및 흰 여백 제거 |
| 대용량 처리 | 분할 렌더링, 추출 진행률 및 작업 중단 |
| 작업 환경 | 라이트·다크 테마, 원본 도면 보존 및 출력 파일 덮어쓰기 방지 |

## 지원 환경 및 형식

- Windows 10/11 (64비트)
- 입력: PDF(온맵 등), DXF, DWG
- 출력: PNG, JPG
- DWG 사용 시 ODA File Converter 또는 DWG 지원 LibreCAD의 별도 설치가 필요합니다.

## 사용 방법

1. 프로그램을 실행하고 작업할 도면 파일을 추가합니다.
2. 도면 목록에서 원하는 도면을 선택합니다. Ctrl 또는 Shift를 이용해 여러 도면을 선택할 수 있습니다.
3. 레이어 목록에서 필요한 레이어를 켜거나 불필요한 레이어를 끕니다. 반복 사용하는 조건은 규칙으로 저장하고 선택 도면에 적용할 수 있습니다.
4. 미리보기에서 표시 상태와 도면 내용을 확인합니다.
5. 출력 형식(PNG 또는 JPG), 해상도 및 저장 위치를 설정합니다. PNG는 투명 배경과 흰 여백 제거 옵션을 사용할 수 있습니다.
6. **선택 도면 추출**을 눌러 이미지를 저장합니다.

## 실행 방법

[프로그램 다운로드(Releases)](https://github.com/Peter-msk/Sunrise_Drawing_Editor/releases)에서 공개된 Windows 실행파일을 확인할 수 있습니다. 현재 v1.0.0 실행파일은 배포 준비 중입니다.

소스로 실행하려면 [최신 소스 ZIP](https://github.com/Peter-msk/Sunrise_Drawing_Editor/archive/refs/heads/main.zip)을 내려받아 압축을 해제합니다. Python 3.11 이상이 설치된 Windows에서 처음에는 `INSTALL_AND_RUN.cmd`, 이후에는 `RUN.cmd`를 실행합니다.

## 활용 분야

환경영향평가 보고서 작성, 토지이용 및 사업계획 도면 정리, GIS·CAD 자료 이미지화, 설계 도면의 레이어별 추출 등에 활용할 수 있습니다.

## 문의 및 피드백

사용 중 발견한 오류나 개선 의견은 [GitHub Issues](https://github.com/Peter-msk/Sunrise_Drawing_Editor/issues)에 남겨 주세요. 증상과 재현 방법을 알려 주시면 도움이 됩니다. 업무 도면이나 개인정보는 공개 게시물에 첨부하지 마세요.

원본 도면의 출처 및 이용조건을 준수해 주세요. 외부 라이브러리 관련 사항은 [THIRD_PARTY_NOTICE.md](THIRD_PARTY_NOTICE.md)를 참고할 수 있습니다. 소스 공개가 자유로운 재배포 허가를 의미하지는 않습니다.

Copyright © 2026 Sunrise Group. All rights reserved.
