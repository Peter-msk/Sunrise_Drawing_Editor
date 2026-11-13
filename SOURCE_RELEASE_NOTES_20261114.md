# Sunrise Drawing Editor — 소스 전용 정식 릴리스 (2026-11-14)

## 배포 유형
**공식 GitHub 소스 배포만 포함합니다. Windows EXE / 설치 프로그램은 포함하지 않습니다.**
제품의 별도 자동 업데이트·버전 번호 체계를 도입하지 않습니다.

## 검증된 변경 사항
- 64MiB 이상 DXF 미리보기 및 확대 렌더의 별도 프로세스 격리, 취소·워커 재생성·원본 변경 감지·IPC 종료 경합 보완
- DXF↔PDF 파일 선택 생명주기, 카탈로그 세대 식별, 대용량 PDF OCG 잠금·출력 로직 보완
- 라이트/다크 테마 대비, 14개 주요 SVG 아이콘의 광학 중심 정렬, HiDPI 레이아웃·QA 추가
- 소스 동일성 검사와 Windows/Linux 자동시험을 위한 GitHub Actions 릴리스 게이트 설치

## GitHub Actions 시험 결과
PR #1의 소스 트리와 CI 자동 병합 트리 SHA는 일치했습니다.
- Windows Python 3.12: 전체 **262개 시험 PASS** (3개 skip)
- Ubuntu Python 3.12: 전체 **262개 시험 PASS**
- Windows PyInstaller onefile **무서명 진단 빌드 PASS**, 패키지 --self-test PASS
- 무서명 진단 EXE SHA-256: DE4ED19A6A95951E8312A51AF0EE9150B37EDE554E6E9817859FED65FDA209EB
- CI Run: https://github.com/Peter-msk/Sunrise_Drawing_Editor/actions/runs/43520845417

## 아직 통과하지 못한 운영 배포 관문
- 사용자의 **실제 원본 온맵 PDF**와 421,316,933바이트 철탑 DXF를 사용한 Windows GUI 10회 전환·취소·OCG 시각검증
- Windows 100/125/150/175% 실제 모니터 DPI에서 라이트/다크 UI 수동 승인
- Sunrise Group **공인 또는 신뢰된 Windows Authenticode 코드서명**, 서명된 실행 파일 해시 및 설치·종료 검증
- PyMuPDF의 AGPLv3 또는 상용 라이선스에 따른 재배포 적합성 판단 (README 참조)

## 소스 사용 및 원본 보호
- 본 GitHub Release는 공식 main의 소스 ZIP과 SHA-256 목록을 제공합니다.
- **서명된 EXE, Windows 제품 출시 또는 완료된 현장 검증을 의미하지 않습니다.**
- 원본 DXF/DWG/PDF는 ZIP에 포함하지 않으며 테스트용 신뢰되지 않는 인증서를 공식 배포로 취급하지 않습니다.
- 저장소에 별도의 LICENSE가 없으므로 공개 조회 자체를 별도의 재사용 허가로 해석해서는 안 됩니다.
