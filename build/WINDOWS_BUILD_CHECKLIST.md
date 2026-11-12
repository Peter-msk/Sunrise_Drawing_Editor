# Windows 배포 실기 체크리스트 — CMD 전용

**빌드 진입점은 `BUILD_ONEFILE.cmd` 하나입니다.** PowerShell은 사용하지 않으며 가상환경도 만들지 않습니다.

## 선행조건

- Windows 10/11 x64
- 이미 설치된 64비트 Python 3.11 이상 (`py -3` 또는 `python`으로 실행 가능). 실제 사용자 PC의 Python 3.12도 허용
- 네트워크는 최초 라이브러리 설치 시에만 필요. 이미 설치돼 있으면 재설치하지 않음
- **Windows SDK Signing Tools의 `signtool.exe`** 필수. 없으면 Windows SDK를 설치하거나 `SUNRISE_SIGNTOOL_PATH` 지정
- 최초 자체서명 자동 생성 시 Windows 기본 `certutil.exe`와 Python `cryptography` 사용
- EXE 배포 라이선스 검토: PyMuPDF(AGPL/상용), Qt/PySide6(LGPL 등의 조건)

## 빌드 명령

명령 프롬프트(`cmd.exe`)에서 소스 폴더로 이동하여 실행:

```cmd
BUILD_ONEFILE.cmd
```

실행하는 순서:

1. 현재 설치된 x64 Python 검증. 3.11을 강제하지 않고 3.12도 사용
2. 종속성 import 확인, 누락된 항목에 한해 현재 Python에 pip 설치
3. 소스 컴파일 검사. 기존 엔진 전체 시험은 재실행하지 않음
4. 임시 위치에 PyInstaller onefile EXE 생성
5. **실제 패키징 EXE** `--self-test` 실행, 시간 초과·비정상 종료 검사
6. `Sunrise Group` 코드서명 후 EXE 내장 PKCS#7 인증서·Windows 신뢰 상태 확인
7. 서명된 EXE를 재실행하여 서명 후 실행 가능 여부 검사
8. 최종 EXE의 SHA-256이 일치할 때만 `dist`로 원자적 게시

엔진 전체 시험이 특별히 필요한 경우에만 아래처럼 사용:

```cmd
set BUILD_RUN_TESTS=1
BUILD_ONEFILE.cmd
```

자동 설치를 허용하지 않을 경우:

```cmd
set BUILD_NO_INSTALL=1
BUILD_ONEFILE.cmd
```

## 배포 결과

- `dist\Sunrise Drawing Editor.exe` — **배포할 유일한 실행파일**
- `dist\SHA256.txt` — 해시 메타데이터
- `dist\SIGNATURE_STATUS.json` — 인증서/신뢰상태(키·비밀번호 미포함)

EXE가 아닌 로그/메타데이터는 프로그램 실행에 필요하지 않습니다. 빌드·서명 실패 시 기존 `dist` 정상 EXE는 유지하며 신규 EXE는 게시하지 않습니다.

## Sunrise Group 서명 정책

### 1) 기존 사용자 인증서 우선

Windows `CurrentUser\My` 저장소에서 유효한 `CN=Sunrise Group` 코드서명 인증서를 재사용합니다. 인증서가 없으면 빌드 도중 RSA 3072 / SHA-256 **로컬 테스트용 자체서명** 인증서를 생성하고 `certutil -user`로 현재 사용자 저장소에 가져옵니다. 개인 키는 소스 ZIP이나 `dist`에 포함되지 않습니다. 관리자 권한과 Windows 신뢰 루트 추가는 요구하지 않습니다.

### 2) 정식 PFX 인증서로 서명하려면

다음 값은 **CMD 세션에서만** 직접 설정합니다. 인증서·비밀번호를 ZIP 또는 빌드 로그에 추가하지 않습니다.

```cmd
set "SUNRISE_SIGN_PFX_PATH=D:\\secrets\\SunriseGroup.pfx"
set /p "SUNRISE_SIGN_PFX_PASSWORD=Enter PFX password: "
set "SUNRISE_TIMESTAMP_URL=http://timestamp.digicert.com"
BUILD_ONEFILE.cmd
```

`set /p` 입력은 화면에 노출되므로 보안이 필요한 환경에서는 별도의 자격증명 관리 방식을 사용하십시오. 인증서 주체와 코드서명 EKU가 확인되지 않으면 빌드가 중단됩니다.

### 3) 신뢰 경고의 의미

자체서명은 EXE에 서명이 붙어도 **신뢰받는 게시자라는 뜻이 아닙니다.** Windows SmartScreen 또는 인증서 검증에서 경고할 수 있습니다. `SIGNATURE_STATUS.json`에서 `SELF_SIGNED_UNTRUSTED_TEST_ONLY`로 기록합니다. 외부 배포용 신뢰 체인은 정식 인증서를 사용하십시오. 서명 도구 미설치·해시 불일치·서명 인증서 불일치는 배포 실패로 처리합니다.

## Windows 완료판정

아래는 Linux 소스 정적검사로 대체할 수 없습니다.

- [ ] 로컬 CMD에서 빌드 8단계 모두 정상 종료
- [ ] 실제 EXE 실행 및 종료 정상
- [ ] `SIGNATURE_STATUS.json` 주체와 신뢰상태 확인
- [ ] 실제 온맵 PDF의 OCG 레이어 토글·미리보기·이미지 출력
- [ ] 실제 100MB 이상 DXF·DWG의 최초 읽기, 확대, 레이어, 일괄 추출
- [ ] Windows 화면 배율 100/125/150/175%, 라이트/다크 테마 확인
- [ ] 배포 라이선스·정식 서명 필요 여부 결정

## 복수 Qt 바인딩 설치된 Windows PC

`PySide6`와 `PyQt5`/`PyQt6`를 동시에 설치한 Python 3.12 시스템에서도 빌드하도록, CMD 명령에서 `PyQt5`, `PyQt6`, `PySide2` 및 미사용 `matplotlib`을 `--exclude-module`로 차단합니다. 광범위 `--collect-submodules ezdxf.addons.drawing`은 더 이상 사용하지 않습니다. PyQt5 삭제나 가상환경 생성은 필요하지 않습니다. 빌드 과정에서 같은 오류가 재발한다면 해당 단계의 전체 PyInstaller 로그를 확인하세요.
