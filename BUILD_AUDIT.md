# Sunrise Drawing Editor — CMD 전용 Onefile 빌드 재감사

**소스 기준:** 사용자가 Windows에서 실패를 보고한 `Sunrise_Drawing_Editor_Validated.zip`의 실행검증 보완 기준본. 프로그램의 도면·레이어·출력 비즈니스 로직은 변경하지 않고 **빌드·서명·실행 스크립트에만 변경을 집중**함.

## 보고된 Windows 오류와 조치

| 보고된 문제 | 실제 원인 | 보완 |
|---|---|---|
| `[ERROR] No runtime installed that matches 3.11` | PowerShell이 `py -3.11`에 고정됨. 사용자 PC는 Python 3.12 | `py -3`로 현재 설치된 x64 Python 3.11+ 사용. 3.11 강제 제거 |
| Python `-c ... print(dependency` 구문 오류 | PowerShell의 Python 인자 전달 과정에서 이중인용부호가 깨짐 | `-c` 제거, `build/preflight.py`를 파일로 실행 |
| 불필요한 `.venv` | 빌드·실행 배치파일이 새 가상환경을 생성 | `.venv` 생성·참조 전부 제거, 현재 Python에 필요한 종속성만 설치 |
| 큰 PySide6 WebEngine/Pdf 설치 | `PySide6` 메타패키지가 Addons·WebEngine 등 사용하지 않는 모듈까지 설치 | `PySide6-Essentials`로 경량화, PyInstaller에서도 WebEngine/Pdf 모듈 제외 |
| 상대 리소스 경로 | `--specpath`를 이동하면 PyInstaller 데이터 경로 기준이 바뀔 수 있음 | `main.py`, assets, spec, dist, work 경로를 모두 절대경로화 |
| 서명 실패 후 EXE 혼동 | 기존 스크립트가 바로 dist에 빌드함 | 새 EXE를 `build/staging`에 생성; 서명·검증·기동 확인 후 `dist`에 원자적으로 게시 |
| 코드서명 구현이 PowerShell 의존 | `.ps1` 스크립트에서 인증서 검색·생성·서명 | Windows 내장 `certutil.exe`, Windows SDK `signtool.exe`, Python 빌드 헬퍼로 교체 |
| 서명된 EXE 실제 기동 보장 부족 | 서명 이전 1회만 EXE 자체 검사 | 서명 전·후 각각 실제 패키징된 EXE `--self-test` 실행 + 제한시간 검사 |
| 기존 PASS 기능 매 빌드 재검증 비용 | 빌드마다 전체 대용량 엔진 시험까지 수행할 수 있음 | 기본 빌드에 컴파일·패키징 기동 검사만 수행; `BUILD_RUN_TESTS=1`로 전체 시험 선택 |

## 8단계별 검사 현황

| 단계 | 구현 계약 | 현재 확인 |
|---|---|---|
| 1. Python | 설치된 Python 3.11+ / 64비트 / Windows 확인 | **소스·테스트 PASS**, Windows 현장 미실행 |
| 2. 의존성 | 존재하면 pip 재설치 없음. 없을 때만 현재 Python에 설치 | **소스·테스트 PASS**, Windows 현장 미실행 |
| 3. 사전검사 | Windows SDK SignTool 존재, source 컴파일, 선택적 전체 시험 | **소스·테스트 PASS**, Windows 현장 미실행 |
| 4. Onefile | PyInstaller `--onefile --windowed`, assets 절대경로 | **명령·경로 정적검사 PASS**, Windows 생성 미실행 |
| 5. 서명 전 기동 | 빌드된 EXE `--self-test` 직접 실행, 타임아웃 적용 | **스모크 검사 로직 PASS**, Windows EXE 미실행 |
| 6. Sunrise Group 서명 | 기존 인증서 사용 또는 로컬 테스트 인증서 생성 후 Authenticode 적용 | **인증서 생성·PE/PKCS#7 단위시험 PASS**, 실제 SignTool 미실행 |
| 7. 서명 후 기동 | 서명 후 동일 EXE 재실행, 해시로 확인 | **검사 로직 PASS**, Windows EXE 미실행 |
| 8. 배포 | 서명정보·서명 후 스모크 해시가 일치해야 dist에 원자적 게시 | **정상·실패 단위시험 PASS**, Windows 배포 미실행 |

### 주의할 신뢰 경계

자체서명 `CN=Sunrise Group`은 **로컬/사내 테스트용 서명**이며 Windows가 신뢰하는 공인 게시자 보증이 아닙니다. 현재 사용자 인증서 저장소에만 가져오며 신뢰 루트에 자동 추가하지 않습니다. 최종 배포를 외부에 수행한다면 적절한 공인/조직 인증서와 타임스탬프를 준비해야 합니다.

### 필수 외부 도구

`signtool.exe`는 Windows SDK Signing Tools에서 제공되며 Python 패키지 설치만으로 만들어지지 않습니다. **없으면 빌드 3단계에서 명확한 오류로 중단**하고 서명하지 않은 EXE를 배포하지 않습니다. `SUNRISE_SIGNTOOL_PATH`로 기존 도구 경로를 지정할 수 있습니다.

### 라이선스

PyMuPDF(AGPL/상용) 및 PySide6-Essentials(Qt/PySide6 LGPL 등)의 재배포 의무는 별도 확인해야 합니다. 기술적인 서명이나 EXE 생성을 라이선스 승인으로 오해하면 안 됩니다.

## 실제 검증에서 확인한 내용

- 기존 엔진 자동시험 **61개 PASS** (소스 기반 직접 재실행)
- 새 빌드 파이프라인 단위시험 **13개 PASS**: 무가상환경/무PowerShell 경로, Python 선택, PKCS#12 생성, 코드서명 EKU, PE 내장 PKCS#7 추출, 미서명 배포 차단, 해시 불일치 시 기존 EXE 유지, 정상 배포 원자성 등
- 전체 자동시험 **74개 PASS** (본 문서 작성 후 전체 회귀 재실행 결과는 `quality/CMD_BUILD_UNITTESTS.log` 참조)
- Python 컴파일 검사 및 ZIP CRC·SHA256 매니페스트 검사 수행
- **Windows CMD 실제 실행 / Windows Onefile 생성 / SignTool 실제 코드서명 / Windows GUI 동작은 NOT RUN**: 현재 실행환경이 Linux이고, Windows SDK 및 CMD가 없음

## 최종 사용자 절차

1. 새 ZIP을 빈 폴더에 압축 해제하고 `BUILD_ONEFILE.cmd` 실행
2. 없으면 **Windows SDK Signing Tools** 설치 (SignTool은 자동으로 설치하지 않음)
3. 완료 후 `dist\Sunrise Drawing Editor.exe`를 실행해 실물 PDF/DXF/DWG 검증
4. `dist\SIGNATURE_STATUS.json`에서 서명 주체와 신뢰 상태 확인

필요한 경우 `set BUILD_NO_INSTALL=1`로 pip 설치를 금지하거나, `set BUILD_RUN_TESTS=1`로 전체 엔진 시험을 재실행할 수 있습니다. 공지사항·업데이트·버전 관리 기능은 없습니다.

## 추가 수정 — PyQt5 / PySide6 혼합 바인딩 충돌

- **사용자 Windows 빌드 로그:** `hook-PyQt5.py` 실행 시 기존 `hook-PySide6.py`와 충돌해 PyInstaller 빌드 중단.
- **원인:** `--collect-submodules ezdxf.addons.drawing`은 실제 앱에서 쓰지 않는 `matplotlib`, Qt 전용 viewer/backend 및 기타 선택적 모듈도 수집할 수 있습니다. 이 작업은 시스템 Python 3.12에 PyQt5가 설치돼 있으면 복수 Qt hook으로 이어질 수 있습니다.
- **개선:** 광범위 `--collect-submodules` 제거. 사용 중인 `ezdxf.addons.drawing.pymupdf`, `ezdxf.addons.drawing.recorder`만 명시적으로 포함. `--exclude-module PyQt5`, `PyQt6`, `PySide2`, `matplotlib` 추가. `QT_API=pyside6` 고정. `--clean`으로 이전 PyInstaller 분석 캐시 제거.
- **기존 방침 유지:** CMD 전용, 시스템 Python 3.12 사용, 가상환경 없음, PowerShell 없음, 서명 후 게시, 버전 없음.
- **검증 상태:** Qt 바인딩 선택 정책 정적시험 및 기존 엔진 회귀시험 수행. Windows PyInstaller Onefile 실제 실행과 Sunrise Group 서명은 이 Linux 환경에서 수행하지 못했으므로 **NOT RUN**.
- **중요:** 사용자가 PyQt5를 전역 Python 환경에서 삭제할 필요가 없습니다. 설치된 상태를 유지하더라도 해당 모듈은 EXE 수집 대상에서 제외됩니다.
