# Sunrise Drawing Editor 1.0.0 — 공식 소스 기준본

- 승인일: 2026-11-18 (KST)
- 기준: R24 (ff7cea02a78c30e02c19ad7a4808fd72854696f3)
- 공식 운영 브랜치: main
- 버전 보존 참조: V1_0_0_SOURCE (branch, not a release tag)
- 제품 버전: 1.0.0 (기존 APP_VERSION 유지)
- 상태: 공식 소스 승인; 실제 Windows EXE 배포 및 자동업데이트는 미승인.

## 변경 이력
Stage14 이후 사용자 피드백 기반: 온맵 PNG OCG/흰 여백 개선, GitHub 공지 및 업데이트 개별 버튼, 라이트/다크 테마 팝업, R17~23 패키징 분석 및 비교, R24 LEAN 단독 빌드 확정, 렌더링 단계별 0/33/67/100% 표시, 12MP 초과 흰 배경 PNG 여백 제거 단일 래스터링. 코어 기능 및 원본 보호 유지. 국토지리정보원 마크 제거는 이용 조건 및 원본 구조 미확인으로 미구현.

## 실측 및 검증 경계
사용자 제출 R23 Windows 비교 보고서: 기준 104818016 bytes, LEAN 72857768 bytes (69.48 MiB, 30.49% 절감), PYZ 72844904 bytes. PYZ 추가 절감 12864 bytes에 불과해 LEAN 선정. R24 자체 용량 미측정. R24 기존/신규 합성 PNG 6건 바이트 동일, 신규 4/4 시험 통과, 합성 벡터 PDF 4800x3600 5회 중앙 0.516532→0.364649초(29.4% 감소), 실제 사용자 Windows 실측 아님. R24 신규 Windows EXE, 실제 도면 전체 기능, DWG 변환기, 대용량 DXF, DPI/테마, 저사양 GPU/RDP, 업데이트 및 신뢰 서명 검증은 NOT RUN. 기존 서명 보고서는 자체서명 테스트용이며 Windows 신뢰 정책 미통과.

## 빌드 및 운영
Windows x64 Python 3.11+에서 BUILD_ONEFILE.cmd 하나로 LEAN 빌드, 서명 전후 smoke 및 실제 서명 EXE 합성 도면 QA를 수행. 실패 시 기존 dist 보호. 결과 dist/Sunrise Drawing Editor.exe, dist/SIGNATURE_STATUS.json, dist/SHA256.txt, build/staging/FUNCTIONAL_QA.json, build/staging/PLAN.json. 기존 파일의 신뢰 여부를 재검증하고 전체 실기 QA 후에만 공개 EXE 등록. latest.json의 official_release/update_endpoint_configured/automatic_update_available는 검증된 EXE 없이 true로 변경 금지. 배포 전 THIRD_PARTY_NOTICE.md의 라이선스 조건 확인. GitHub Actions 사용하지 않음.

## 자료 및 유지관리
README, notice.txt, latest.json, SOURCE_ARCHIVE_BLOBS.json을 공식 기준에 맞춰 관리. SOURCE_SHA256_MANIFEST.json은 이전 단계 역사 자료로 보존. 이후 피드백은 최소 영향 핫픽스 및 검증 후 새 버전(예: 1.0.1)으로 관리. R24 및 이전 브랜치/자료 보존.

## 1.0.0 빌드 메타데이터 보완 R01
File Manager의 제품별 `dist/release-metadata` 산출 계약과 동일하게 최종 서명·스모크/기능 검증 후 `latest.json`, `notice.txt`를 생성한다. 실제 EXE 파일명, SHA-256, 바이트, 버전 및 예정 GitHub Release URL, 서명 신뢰 상태를 기록한다. 공지는 저장소 원본을 UTF-8로 사용한다. 운영 피드/Control 변경 없이 후보 파일을 출력하며 전체 QA, 신뢰 서명 및 실제 Release 등록 전까지 배포 플래그는 false. 메타데이터 준비 오류 시 이전 EXE 유지, 일반 파일 교체 오류 시 sidecar 복구 후 실패. 전원 장애/동시 빌드 중단의 트랜잭션 복구 보장은 아님. 신규 합성 단위시험 5/5 PASS; 실제 Windows 빌드 NOT RUN. 제품 버전 1.0.0 유지(아직 EXE 미배포), 최초 승인 커밋 V1_0_0_SOURCE는 보존.
