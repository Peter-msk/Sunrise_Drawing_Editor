# Sunrise Drawing Editor v1.5.8 R18 — 그룹 내부 배포 검증 절차

상태: **미실행 체크리스트**. 공인 CA 인증서 확보는 내부 배포의 필수 조건이 아니다. 기존 Sunrise Group 자체 서명, 승인된 Windows 그룹 신뢰 정책, 실제 서명 및 EXE 해시 검증은 필수다. 아래 체크리스트는 기존 빌드/QA를 대체하지 않으며 체크 자체로 배포를 승인하지 않는다.

## 1. Windows CMD에서 빌드

1. SOURCE ZIP을 새 작업 폴더에 압축 해제한다. 이전 설치본, 사용자 설정, 원본 도면은 보존한다.
2. Windows x64 Python 3.11 이상과 Windows SDK SignTool, 그룹에서 승인한 기존 인증서(개인키 포함, My 저장소 또는 관리 PFX)를 확인한다. PySide6 Essentials 및 필요한 라이브러리는 기존 의존성 계약을 사용한다.
3. 독립적으로 확인한 **DER 공개 인증서 SHA-256**을 아래 예시에서 실제 64자리 값으로 대체한다. EXE/PFX 해시가 아니다. 그룹 IT의 신뢰 정책에 따라 검증하며 신뢰 저장소 자동 등록이나 경고 우회 금지.

```cmd
set "SUNRISE_GROUP_CERT_SHA256=관리자가_확인한_실제_64자리_지문"
RUN_V150_FINAL_QA.cmd
```

의존성은 현재 선택된 Python에 부족할 때만 설치를 시도한다. 설치를 금지하려면 실행 전 `set "BUILD_NO_INSTALL=1"`을 지정한다. PFX 사용 시 기존 `SUNRISE_SIGN_PFX_PATH`, `SUNRISE_SIGN_PFX_PASSWORD` 계약을 따르되 개인키/비밀번호를 소스·로그·공유 QA 자료에 넣지 않는다. `SUNRISE_SIGNTOOL_PATH`는 필요한 경우에만 설정한다. 그룹 지문 미지정 자체 서명은 내부 QA 전용이다.

## 2. 자동 QA 증거

- [ ] CMD 종료 코드 0, Qt 위젯 10/10 PASS (SKIP 불허)
- [ ] `dist\Sunrise Drawing Editor.exe` 실제 실행 및 버전 1.5.8 확인
- [ ] `dist\SHA256.txt`, `SIGNATURE_STATUS.json`, `SMOKE_STATUS.json`, `FUNCTIONAL_QA.json`, `V150_LOCAL_QA.json` 모두 같은 EXE 해시로 대조
- [ ] `V150_LOCAL_QA.json` 상태 `GROUP_INTERNAL_CANDIDATE_MANUAL_PENDING`, 그룹 인증서 지문 확인, `windows_qt_widget_status=PASS`
- [ ] `FUNCTIONAL_QA.json`의 `checks_passed`에 `png_alpha_crop_independent_pixel_exact` 포함 (네 가지 PNG 옵션 조합, 실제 EXE 실행으로 확인)
- [ ] 최종 QA가 SHA256.txt 및 배포 메타데이터·공지사항을 현재 후보와 대조했는지 확인 (불일치/누락 시 승인 차단)
- [ ] `dist\release-metadata\latest.json`의 공개 배포/자동 업데이트/endpoint 플래그 false 확인
- [ ] 실행파일 및 증거를 별도 폴더에 보존 (개인키/비밀번호 제외)

`GROUP_INTERNAL_CANDIDATE_MANUAL_PENDING`은 내부 배포 **후보**일 뿐 승인 아님. 실패 시 원인을 기록하고 기존 dist의 이전 실행파일을 새 제품으로 배포하지 않는다. 새 EXE 게시 전에 이전 최종 QA 보고서를 무효화하며, 일반적인 게시 실패 시 이전 파일/증거를 복원한다.

## 3. 실제 업무 및 화면 검증

| ID | 확인 사항 | 필수 증거 | 상태 |
|---|---|---|---|
| W01 | 실제 온맵 PDF 인식, 레이어 전체 OFF, 일반/조합 추출, 출처표시 및 이용조건 확인 | 실제 파일 해시, 허용된 출력 및 화면 | NOT_RUN |
| W02 | 실제 DXF 및 DWG, ODA/LibreCAD 지원 경로, 실패 안내 | 변환 도구 버전, 출력 해시, 원본 해시 | NOT_RUN |
| W03 | 100/125/150/175% DPI, 880px 창, 다크/라이트, 드래그 취소, NOTICE | 각 실제 캡처 | NOT_RUN |
| W04 | PNG 투명/흰 여백 제거 독립성, JPG/벡터 적용 범위, 분리 출력 정렬 | 파일별 크기·알파·비교 결과 | NOT_RUN |
| W05 | 한글·긴 경로, Junction, 경로 경쟁, 덮어쓰기 방지 | 테스트 폴더 및 로그 | NOT_RUN |
| W06 | 반복 일괄 출력, 강제 취소, 복구, 실제 PC 메모리 | 시간·RSS·완료 기록, 잔류 프로세스 확인 | NOT_RUN |
| W07 | 이전 승인 EXE에서 후보 EXE로 교체·롤백(격리된 테스트 경로) | 양쪽 해시, 실패 복구 증거 | NOT_RUN |
| W08 | 재배포 라이선스 및 고지, 설치된 정확한 버전, 그룹 사용 권한 | 담당자 검토 기록 | NOT_RUN |

W07은 공개 피드 활성화를 의미하지 않는다. 내부 업데이트 경로와 승인 방식은 그룹 운영 정책에 따라 별도로 확정해야 한다. 실제 운영 피드·Control 설정·기존 사용자 설치를 테스트에 사용하지 않는다.

## 4. 승인 기록

- EXE SHA-256 / 제품 버전 / Windows 버전 / Python 버전 / 인증서 공개 지문:
- 실기 검증 담당자 / 날짜 / 증거 경로:
- 미완료 항목 / 결함 / 라이선스 검토 담당자:
- 그룹 내부 배포 승인자 / 승인 여부: **PENDING**

`THIRD_PARTY_NOTICE.md`는 검토 목록이다. 특히 PyMuPDF/MuPDF AGPL 또는 상용 라이선스, Qt LGPL 또는 상용 라이선스 및 Onefile 배포 조건을 확인해야 한다. 그룹 내부 사용이라는 이유만으로 라이선스 준수 완료를 가정하지 않는다.
