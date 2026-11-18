# R19 — UPX / Nuitka Onefile 비교 후보

기준 R18 (68e45673dc9ab5c9c1ab37df6cf3f8755deac3b5). 기존 약 100MB EXE 및 R17/R18 실측 JSON 미확보. 비교용 소스만 작성; Windows 용량 감소 실측 없음. 기존 일반 빌드와 SAFE/COMPACT 명령, 공식 dist, 제품 버전/공지/업데이트 파일, 엔진 로직 유지.

## UPX

공식 https://upx.github.io/ 경로에서 Windows용 UPX를 개별적으로 확보하고 해시와 출처를 확인한다. 사용자 PC의 신뢰하는 폴더를 명시한다.

```cmd
BUILD_COMPRESSION.cmd --backend upx --upx-dir "C:\Tools\UPX" --baseline "C:\Sunrise\Sunrise Drawing Editor.exe"
```

R18 SAFE 필터를 적용하고 NumPy 소유 numpy.libs 내 libopenblas / libscipy_openblas DLL만 대상으로 지정한다. 그 외 바이너리는 basename 기반 UPX 제외 목록으로 전달하고 이름 충돌 시 제외한다. 실제 UPX 적용 여부는 PyInstaller 로그 및 결과 바이너리에서 확인해야 하며, 호환성 보호 장치에 의해 PyInstaller가 압축을 건너뛸 수 있다. 후보가 없으면 빌드 중단. 압축된 BLAS도 CAD 필수 의존성이므로 수치·성능 시험 필수. 원본 DLL과 공식 EXE를 수정하지 않는다.

## Nuitka (실험용, 배포 금지)

기존 Windows Python 빌드 환경과 MSVC C++ Build Tools 필요. 필요한 패키지는 사용자가 직접 설치한다. 도구 버전은 보고서에 기록되며 호환 가능한 버전 사용 필요. 컴파일러의 부속 도구 다운로드 요청은 출처를 검토한 뒤 승인하거나 취소한다.

```cmd
py -3 -m pip install nuitka ordered-set zstandard
BUILD_COMPRESSION.cmd --backend nuitka --baseline "C:\Sunrise\Sunrise Drawing Editor.exe"
```

Onefile / PySide6 plugin / assets 포함 / Windows GUI 모드. PyInstaller와 다른 실행 계약을 격리하기 위해 별도 nuitka_entry.py가 외부 EXE 경로를 등록한다. CAD 및 일괄 추출 worker는 별도 bootstrap을 사용하고 상속된 Nuitka Onefile 환경변수를 제거한다. 소스 실행 및 PyInstaller 경로는 그대로 유지. Nuitka 후보의 자동 EXE 교체 UI와 helper 진입을 비활성화한다. 실제 worker 시작/종료/취소/파일 정리 및 메모리, GitHub 수신, 앱 리소스 경로 검증은 Windows에서 별도 수행. Nuitka CArchive가 아니므로 R17 PyInstaller 내부 감사 도구를 적용하지 않는다.

## 결과

기존 dist가 존재하면 baseline 자동 사용, 아니면 후보만 기록하고 감소 수치는 null. 두 백엔드 모두 기존 서명 도구 사용, 서명 전후 실제 EXE self-test, 원본 해시 재확인, 고유한 dist_compression/r19-* 후보 경로에만 게시한다. SIZE_COMPARISON.json에는 파일 바이트/sha256, 절감률, build_seconds, post_sign_smoke_seconds, 도구 버전, UPX의 경우 whitelist 및 CArchive가 기록된다. post_sign_smoke_seconds는 smoke 스크립트 전체 시간이며 사용자 GUI 초기 표시 시간이 아니다. Nuitka 컴파일 보고서는 build/compression_work/r19-*/NUITKA_REPORT.xml. 공식 GitHub 업데이트는 변경하지 않는다.

## 실행검증 결과와 남은 게이트

- 신규 6/6 단위시험 PASS (Linux Python 3.13.5), 신규 Python compileall/spec AST PASS. 시험 대상 6개 파일의 Git blob은 로컬 시험본과 동일함.
- 신규 worker 호출부 및 업데이트 조건 통합은 정적 앵커 확인; 실제 Windows/PySide6/UPX/Nuitka/PyInstaller 미설치로 native build, GUI, CAD/DWG/PNG/JPG 비교, worker 취소 및 릴리즈 자동 교체는 NOT RUN.
- 실측 없이 용량 목표를 달성했다고 판단하지 않는다. 기존 통과 항목을 전체 반복하지 않고 변경 영향이 있는 실행 계약을 우선 검증한다.
- 다음 R20 진입은 동일 환경에서 R18 SAFE/COMPACT와 R19 UPX/Nuitka 후보의 서명된 바이트 및 실행 실측, 전체 필수 기능, 백신/원격 데스크톱, worker 취소, 라이선스 및 신뢰된 인증서 검토를 근거로 한다. Nuitka 자체교체 지원은 별도 검증/승인 없이는 금지.

공식 참고: https://pyinstaller.org/en/stable/usage.html , https://nuitka.net/user-documentation/user-manual.html , https://nuitka.net/user-documentation/common-issue-solutions.html
