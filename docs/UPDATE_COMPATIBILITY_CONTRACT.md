# Sunrise Drawing Editor 업데이트 호환 계약 (복구·고정)

2026-11-23 기준. 프로그램 본래 목적인 원본 도면 선택 추출과 무관한 기능은 변경하지 않습니다.

## 확인한 이력

- `V1_0_0_UPDATE_FIX_R03`와 `V1_1_0_UPDATE_FIX_R03`, `V1_1_0` 브랜치는 두 Release asset 이름을 허용하도록 수정한 **호환성 복구 기준본**입니다.
- `v1.0.0` 및 `v1.1.0` **태그에 남아 있는 코드**는 과거의 `Sunrise%20Drawing%20Editor.exe` URL만 허용하고, 서명자 일치 조건도 포함합니다. 태그가 가리키는 소스가 사용자 PC에 설치된 바이너리와 동일하다고 단정할 수 없습니다.
- `main`의 v1.5.0 `release_feed.py`와 `onefile_update.py`는 R03 호환 계약(두 이름 허용, HTTPS + 정확한 SHA-256/크기, 새 EXE 버전·자체시험, 롤백)을 유지합니다. 구버전 설치 파일 자체는 원격 소스 변경으로 고칠 수 없습니다.

- v1.5.0 개발 도중 `build/approve_update.py`에 Windows 공인 CA 신뢰만 허용하는 추가 승인 조건이 생겼습니다. 이것이 v1.1.0 R03 자체 서명 승인 계약과 달라진 실제 지점이며, 당시 main 소스에서 R03 방식으로 복구했습니다. 자체 서명은 계속 `SELF_SIGNED_UNTRUSTED_TEST_ONLY`로 보고하며 공인 인증서인 것처럼 표시하지 않습니다.

## 고정 규칙

1. Release asset의 정식 이름은 `Sunrise.Drawing.Editor.exe`이며, 구형 `Sunrise%20Drawing%20Editor.exe`도 제한된 허용 목록에 유지합니다. 해당 URL을 다른 외부 도메인·임의 파일명으로 확장하지 않습니다.
2. `latest.json`에는 명시적인 버전·제품 ID·플랫폼·정확한 Release URL·다운로드 URL·SHA-256·바이트 크기가 필요합니다. 활성화 상태를 추정하지 않습니다.
3. 실제 업데이트는 Sunrise Control의 `product.sunrise_drawing_editor` `update`가 `allow`일 때만 가능합니다. `operation=allow`는 프로그램 실행을 계속 허용합니다.
4. 기존 EXE는 업데이트 승인을 받아도 다운로드·버전 검사·`--self-test`·해시 검증·교체 전후 검증을 통과해야 합니다. 실패하면 기존 EXE와 롤백 정보를 보존합니다.
5. R03 계약처럼 Sunrise Group Authenticode 서명자가 실제 EXE에 포함돼 있고 빌드 증거·해시·런타임·기능 QA가 모두 일치하면 자체 서명도 배포 후보 승인 검토가 가능합니다. 자체 서명의 Windows 신뢰 상태는 실제 검증 결과에 따라 보존하며 SmartScreen 경고 가능성을 명시합니다. R15부터 그룹 내부 후보에는 공인 CA를 요구하지 않되 독립적으로 확인된 그룹 인증서 지문 및 그룹 관리 PC의 Windows 신뢰 정책을 검증합니다. 내부 후보는 공개 자동 업데이트 승인으로 전환하지 않습니다.
6. 기존 v1.0.0·v1.1.0 **태그 바이너리**가 구형 단일 URL/서명 규칙을 사용하는지 실제 PC에서 확인하고, 차이가 있으면 동일 해시의 호환 이름 asset 및 검증된 서명을 준비한 뒤 **별도 업데이트 교체 시험**을 진행합니다.

## 2026-11-23 당시 긴급 차단 기록 (역사적 상태)

- `Sunrise_Control/main/control.txt`: `product.sunrise_drawing_editor`의 `operation=allow`, `update=block`, `minimum_version` 공란으로 기록됨.
- `Sunrise_Drawing_Editor/main/latest.json`: `update_endpoint_configured=false`, `official_release=false`, `automatic_update_available=false`로 기록됨.
- 캐시 정책은 최대 21,600초(6시간)일 수 있습니다. 당시 두 차단을 동시에 유지하여 원격 정책 수신 지연 중에도 갑작스러운 강제 업데이트를 예방하고자 했습니다.

## 2026-11-27 v1.6.0 통합 후보 및 현재 운영 피드 확인

- 실제 main 조회 결과 v1.5.0의 세 업데이트 플래그는 true였습니다. R19에서 운영 피드를 수정하지 않습니다. Control의 현행 서버 상태는 별도 조회·검증 필요합니다.
- 후보 브랜치의 `latest.json`은 v1.6.0이며 세 플래그가 false, SHA/크기 null입니다. 승인 전 main의 운영 피드와 교체하지 않습니다.
- 기존 main의 `test_update_legacy_regression.py` 및 이 문서를 후보 소스에 포함합니다. 기존 운영 피드 파싱, 자산 이름, 해시/크기 계약, 차단·롤백 경계는 유지합니다. 과거 v1.5.0 승인기의 자체 서명 허용 테스트와 R15의 신규 공개 승인 제한은 서로 다른 정책으로 구분합니다. 현재 후보의 신규 공개 승인기는 R15의 그룹 내부 후보 차단 계약을 유지합니다. 이는 기존 EXE의 런타임 업데이트 로직을 변경하는 것이 아닙니다.
- 공인 CA는 그룹 내부 배포 필수 조건이 아닙니다. 그룹 자체 서명 실제 검증, 사용자 PC의 신뢰 정책, 이전 버전→후보 업데이트 교체 시험, 라이선스 및 실물 도면 검증은 아직 대기 중입니다.

## 복구 확인 절차

`python -m unittest discover -s build -p 'test_update_legacy_regression.py' -v`

실제 Windows 업데이트는 별도의 구버전→신버전 교체·재시작·롤백 검증이 통과하기 전까지 활성화하지 않습니다.
