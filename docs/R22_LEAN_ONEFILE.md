# R22 실측 기반 LEAN 후보

기준 R21 744ac052bd28551183f6f17b5db93d7188ed28f5. 사용자 제출 Windows SIZE_COMPARISON 두 파일의 기준 104819064 bytes, SAFE 절감 1773864 bytes (1.6923%), COMPACT 절감 9970272 bytes (9.5119%), COMPACT 94848792 bytes. 동일 기준의 보고서 결과이며 EXE 원본 재검증은 아님. COMPACT에 남은 QtQuick/QML/가상키보드 5549651 bytes, QtPdf/qpdf 2853381 bytes, pandas 외부 항목 4719572 bytes. 합계 13122604 bytes (12.51 MiB). 모두 제거된다고 가정한 산술 잔여량 81726188 bytes (77.94 MiB); 실제 빌드 크기는 아니다. PYZ 내부 감소는 별도 실측. 보고서의 기준 서명은 자체서명 테스트용이므로 정식 배포 승인 불가.

## 단일 명령
```cmd
BUILD_ONEFILE.cmd
```
R21 기본 빌드/SAFE/COMPACT/설치된 UPX·Nuitka를 유지하고 LEAN 후보를 추가한다. 별도 CMD 없음. LEAN은 COMPACT 규칙을 상속하고 Analysis excludes에 pandas, QtQuick/QtQuickWidgets/QtQuickControls2/QtQml/QtPdf/QtPdfWidgets/QtVirtualKeyboard를 추가한다. PySide6 소유의 지정 Qt DLL 및 qpdf, qtvirtualkeyboardplugin만 native import/delay-import/export-forwarder 보존 검사 후 제거한다. Windows PyInstaller 의존성 pefile 사용. 파싱 오류 시 LEAN 빌드 실패; 기준 및 다른 후보 유지. 정적 import는 동적 로딩 전체를 증명하지 않으므로 실제 QA 전 배포 금지. Pillow AVIF, lxml, NumPy, MuPDF, QtGui/Widgets/SVG, TLS 및 엔진 코드 보존. COMPACT의 소프트웨어 OpenGL 및 6개 이미지 플러그인 제외 정책은 그대로 상속하므로 해당 호환성 QA 필요.

## 결과 및 확인
dist는 기존 기준 EXE, dist_lightweight/r18-* 내 profile=lean인 SIZE_COMPARISON.json 및 SIGNATURE_STATUS.json이 신규 결과. 비교 결과 quality/onefile_selection/r22-*/BUILD_REPORT.json. policy.graph_excludes, policy.dependency_blocked_qt, pandas_archive_entries를 기록한다. graph excludes의 실제 효과는 후보 아카이브 및 모듈 그래프로 확인. 제외 대상이 실제로 남으면 절감 성과에서 제외하며 PYZ 내부 감사 미수행. 모든 후보는 기존 서명 전후 smoke 및 R20 QA 게이트 적용, 자동 승격 없음. 새 EXE의 Windows 실제 도면/외부래스터/저사양·RDP 등 13개 게이트 및 서명 검증 미수행. GitHub latest.json/notice.txt 및 제품 기능 소스 변경 없음.

## 확인된 검증
신규 LEAN 정책 단위시험 5/5 Linux PASS(합성 TOC, 모의 PE import), 신규 Python 파일 compileall PASS. 실제 PE 파서, Windows 빌드, 서명, 기능 QA, 크기 실측은 NOT RUN. 기존 PASS 엔진 시험은 변경 범위 밖.
