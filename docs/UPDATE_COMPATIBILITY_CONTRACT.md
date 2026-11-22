# Sunrise Drawing Editor 업데이트 호환 계약 (복구·고정)

2026-11-23 기준. 프로그램 본래 목적인 원본 도면 선택 추출과 무관한 기능은 변경하지 않습니다.

## 확인한 이력

- `V1_0_0_UPDATE_FIX_R03`와 `V1_1_0_UPDATE_FIX_R03`, `V1_1_0` 브랜치는 두 Release asset 이름을 허용하도록 수정한 **호환성 복구 기준본**입니다.
- `v1.0.0` 및 `v1.1.0` **태그에 남아 있는 코드**는 과거의 `Sunrise%20Drawing%20Editor.exe` URL만 허용하고, 서명자 일치 조건도 포함합니다. 태그가 가리키는 소스가 사용자 PC에 설치된 바이너리와 동일하다고 단정할 수 없습니다.
- `main`의 v1.5.0 `release_feed.py`와 `onefile_update.py`는 R03 호환 계약(두 이름 허용, HTTPS + 정확한 SHA-256/크기, 새 EXE 버전·자체시험, 롤백)을 유지합니다. 구버전 설치 파일 자체는 원격 소스 변경으로 고칠 수 없습니다.

- v1.5.0 개발 도중 `build/approve_update.py`에 Windows 공인 CA 신뢰만 허용하는 추가 승인 조건이 생겼습니다. 이것이 v1.1.0 R03 자체 서명 승인 계약과 달라진 실제 지점이며, 현재 소스에서 R03 방식으로 복구했습니다. 자체 서명은 계속 `SELF_SIGNED_UNTRUSTED_TEST_ONLY`로 보고하며 공인 인증서인 것처럼 표시하지 않습니다.

## 고정 규칙

1. Release asset의 정식 이름은 `Sunrise.Drawing.Editor.exe`이며, 구형 `Sunrise%20Drawing%20Editor.exe`도 제한된 허용 목록에 유지합니다. 해당 URL을 다른 외부 도메인·임의 파일명으로 확장하지 않습니다.
2. `latest.json`에는 명시적인 버전·제품 ID·플랫폼·정확한 Release URL·다운로드 URL·SHA-256·바이트 크기가 필요합니다. 활성화 상태를 추정하지 않습니다.
3. 실제 업데이트는 Sunrise Control의 `product.sunrise_drawing_editor` `update`가 `allow`일 때만 가능합니다. `operation=allow`는 프로그램 실행을 계속 허용합니다.
4. 기존 EXE는 업데이트 승인을 받아도 다운로드·버전 검사·`--self-test`·해시 검증·교체 전후 검증을 통과해야 합니다. 실패하면 기존 EXE와 롤백 정보를 보존합니다.
5. R03 계약처럼 Sunrise Group Authenticode 서명자가 실제 EXE에 포함돼 있고 빌드 증거·해시·런타임·기능 QA가 모두 일치하면 자체 서명도 배포 후보 승인 검토가 가능합니다. 자체 서명의 Windows 신뢰 상태는 `SELF_SIGNED_UNTRUSTED_TEST_ONLY`로 보존하며 SmartScreen 경고 가능성을 명시합니다. 공인 인증서는 권장하지만 업데이트 다운로드 계약의 필수 조건으로 새로 강제하지 않습니다.
6. 기존 v1.0.0·v1.1.0 **태그 바이너리**가 구형 단일 URL/서명 규칙을 사용하는지 실제 PC에서 확인하고, 차이가 있으면 동일 해시의 호환 이름 asset 및 검증된 서명을 준비한 뒤 **별도 업데이트 교체 시험**을 진행합니다.

## 현행 긴급 차단 상태

- `Sunrise_Control/main/control.txt`: `product.sunrise_drawing_editor`의 `operation=allow`, `update=block`, `minimum_version` 공란.
- `Sunrise_Drawing_Editor/main/latest.json`: `update_endpoint_configured=false`, `official_release=false`, `automatic_update_available=false` 유지.
- 캐시 정책은 최대 21,600초(6시간)일 수 있습니다. 위 두 차단을 동시에 유지해 원격 정책 수신 지연 중에도 갑작스러운 강제 업데이트를 예방합니다.

## 복구 확인 절차

`python -m unittest discover -s build -p 'test_update_legacy_regression.py' -v`

실제 Windows 업데이트는 별도의 구버전→신버전 교체·재시작·롤백 검증이 통과하기 전까지 활성화하지 않습니다.