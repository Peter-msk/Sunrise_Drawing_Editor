# R21 단일 빌드 진입점

R20의 여러 CMD 실행 방식을 제거하고 BUILD_ONEFILE.cmd 하나로 통합한다. 새 소스 ZIP에서도 외부 기준 EXE 없이 현재 소스로 기준 EXE를 먼저 생성하고, 같은 실행의 기준 SHA-256으로 후보를 비교한다.

## 실행
Windows x64 Python 3.11+ 및 SignTool 필요. 기존과 같이 더블클릭 또는 CMD에서 다음 명령만 실행:
```cmd
BUILD_ONEFILE.cmd
```

기존 Python 및 의존성 설치 여부 확인 → 서명 도구 사전 검사 → 컴파일/선택 테스트 → 기준 Onefile 빌드 → 서명 전후 실제 EXE self-test → R17 내부 용량 분석 → SAFE/COMPACT 순차 빌드 → UPX/Nuitka 가능 시 순차 빌드 → 각 후보 서명 및 실행검사/해시 비교 → R20 선정 규칙 → 기준 EXE의 기존 게시 게이트. 새 후보만 비교한다. 이전 dist의 EXE가 없어도 작동하도록 설계했다.

UPX는 C:\Tools\UPX\upx.exe 또는 기존 SUNRISE_UPX_DIR 환경변수 위치를 검사한다. Nuitka/ordered-set/zstandard 세 패키지가 있어야 시도하며 MSVC 등 나머지 요구 사항은 기존 R19 정책을 적용한다. 외부 압축기/컴파일러를 몰래 다운로드하거나 자동 설치하지 않는다. 선택 도구가 없으면 NOT RUN, 빌드 오류는 FAILED로 기록하고 다른 후보는 계속 실행한다. 선택 후보 실패가 정상 기준 EXE의 생성을 막지는 않는다. CMD 성공은 기준 EXE 게시 성공이며 전체 후보 완료 여부는 matrix_complete 확인.

## 결과
- dist/Sunrise Drawing Editor.exe: 기존 서명·스모크·해시 게이트를 통과한 기준 EXE. 기존 dist는 이 게이트 전까지 교체하지 않는다.
- dist_lightweight/r18-*: SAFE/COMPACT 후보
- dist_compression/r19-*: UPX/Nuitka 후보
- quality/onefile_selection/r21-*/BUILD_REPORT.json: 동일 실행 기준 아카이브, 실제 후보 크기/해시/절감률, 실패·미실행 상태, 선정 조건. 이 보고서는 기준 EXE 게시 이전에 작성하므로 publication 필드는 게시 대기 상태이며 최종 게시 결과는 CMD와 dist/SIGNATURE_STATUS.json 확인.

13개 기능 QA와 실제 신뢰 서명, 업데이트 교체 및 롤백은 기존 R20 정책 유지. 단일 실행으로 기능 QA가 자동 PASS 되는 것이 아니며 경량화 후보는 자동으로 기존 EXE를 교체하지 않는다. 실제 용량 최적 후보는 별도 검증 후 확정한다. 공식 main 및 GitHub Releases는 변경하지 않는다.

기존 AUDIT_ONEFILE.cmd, BUILD_LIGHTWEIGHT.cmd, BUILD_COMPRESSION.cmd는 현재 사용자용 진입점에서 제거; 기존 Python 내부 도구는 재사용. R17~R20 문서는 과거 체크포인트이며 현재 실행은 본 문서 우선.

## 검증
Linux Python 3.13.5에서 신규 orchestration 모의 시험 4/4 PASS 및 두 신규 Python 파일 컴파일 PASS. 실제 PyInstaller, Windows CMD, SignTool, UPX/Nuitka 빌드와 EXE 성능/크기 비교는 NOT RUN. 실측치 없음. 여러 동시 빌드는 지원하지 않으므로 한 번에 한 BUILD_ONEFILE.cmd만 실행한다.
