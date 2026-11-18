# R20 — Onefile 통합 비교 및 배포 후보 선정

R19 e62141b17e358ac8cbca225e4f2e31a6fe1f0951 기준. 기존 약 100MB EXE 및 Windows 실측 자료는 미제공. R20은 비교와 선정 규칙을 통합하며 실제 최적 후보 승인이나 배포는 완료되지 않았다.

## 단일 CMD 진입점
기존 Windows Python x64, PyInstaller 6.x, SignTool 등 이전 빌드 환경을 사용한다. 기존 정상 EXE를 먼저 보존하고 기준 경로를 지정한다. 
```cmd
BUILD_ONEFILE.cmd evaluate --baseline "C:\Sunrise\Sunrise Drawing Editor.exe"
BUILD_ONEFILE.cmd evaluate --baseline "C:\Sunrise\Sunrise Drawing Editor.exe" --upx-dir "C:\Tools\UPX" --nuitka
BUILD_ONEFILE.cmd compare --baseline "C:\Sunrise\Sunrise Drawing Editor.exe"
```
evaluate 기본 SAFE/COMPACT 순차 빌드; 옵션으로 UPX/Nuitka 추가(도구 사전 설치 필요). 기존 R18/R19 도구를 재사용하고 실패 코드도 기록한다. compare는 기존 후보만 읽으므로 재빌드하지 않는다. baseline 생략 시 dist 내 기존 EXE를 찾는다. 기본 명령 BUILD_ONEFILE.cmd (인수 없음)는 종전 빌드 체계 그대로. 결과는 quality/onefile_selection/R20_*.json에 독립적으로 기록. 기존 dist 및 GitHub main 운영 메타데이터에 변경을 가하지 않는다.

## 선정 규칙
후보의 실제 파일 크기와 SHA-256 재계산, 기존 SIZE_COMPARISON 및 SIGNATURE_STATUS 기록 일치, 같은 기준 EXE 바이트와 해시, 최소 5% 절감(잠정 공학적 기준), Windows 신뢰 서명 기록 및 아래 검증 증거. Nuitka는 자동 업데이트 계약이 검증되지 않았으므로 실험 상태 유지. 복수 검토 가능 후보 중 최소 실제 크기 추천. KEEP_BASELINE 또는 REVIEW_REQUIRED 상태 기록. 추천은 배포 승인이 아니며, native WinVerifyTrust/SignTool 독립 재확인 및 담당자 승인 후에만 기본 빌드 변경 가능. 본 비교기가 JSON의 실제 QA 수행/서명 신뢰를 새로 입증하는 것은 아니다. 이전 빌드 후보도 수집하므로 비교 보고서는 동일 환경에서 새로 빌드한 후보와 구분하여 검토한다.

## QA
docs/QA_APPROVAL_TEMPLATE.json을 후보 폴더의 QA_APPROVAL.json으로 복사. 실제 테스트 후에만 PASS 기입; reviewer 및 기준/후보 SHA-256 채움. 모든 게이트와 실제 검증 로그/캡처는 담당자가 보존. 허위 PASS 금지. 최소 시험: PDF OCG/온맵, DXF/DWG, PNG/JPG/여백 제거, 대용량 DXF 성능, worker 취소·정리, 라이트/다크/DPI, 저사양 GPU 및 RDP, 외부 이미지, GitHub TLS/공지/업데이트, 교체/롤백, 초기 구동·RAM·백신, 라이선스 및 신뢰 서명. 원본 자료와 비교하고 같은 Python/의존성/환경 사용. 현재 자체서명 테스트 인증서는 최종 선정 제외.

## 실제 확인
- Linux Python 3.13.5: 신규 7/7 단위시험 PASS 및 compileall PASS. 합성 MZ 파일/JSON 및 mock subprocess로 분기와 비교 로직 검증. 실제 서명 또는 Windows 기능 검증 아님.
- 원본/후보 실측, Windows CMD, UPX/Nuitka 실행, GUI/엔진, 업데이트, 신뢰 체인 재검증은 NOT RUN.
- 기본 패키징 방식을 실측 없이 변경하지 않음. GitHub 신규 EXE 및 main 승격 없음.
