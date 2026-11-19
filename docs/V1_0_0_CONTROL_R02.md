# v1.0.0 CONTROL R02

기준 main 63ed803effe3302b3300427d6d2a7c57a74d75ca. Sunrise Control 실제 control.txt schema v1, 등록 ID sunrise_drawing_editor. 참고: https://github.com/Peter-msk/Sunrise_Control/blob/main/control.txt 및 File Manager SunriseControlService.cs. v2 signed policy/lease 문서는 DESIGN / NOT IMPLEMENTED이며 이번 대상 아님.

- 시작 시 고정 HTTPS URL(redirect 거부, 최대 128KiB, 호출 대기 5초), global→product 우선순위, operation=allow/maintenance/block. 차단/점검 시 DrawingWindow 생성 전 기존 테마 팝업 후 종료.
- update=required이고 현재 버전이 minimum_version 미만이면 일반 진입 금지. 기존 latest.json이 제공하는 유효한 신규 EXE가 최소 버전을 만족할 때만 기존 updater 또는 공식 배포 페이지 선택. 닫기/취소/실패 시 진입 금지. operation 차단이 우선. blank minimum_version은 강제하지 않음.
- update=block은 자동/수동 업데이트 조회, 기존 EXE 다운로드 시작, 교체 helper의 최종 교체 전 정책 재검사에서 차단. 브라우저 열기 전에도 재검사. 공지는 독립. helper 및 CAD/배치 worker/self-test는 원래 진입 계약 유지; helper의 교체 자체는 정책 검사. 실행 중인 정상 도면 작업을 원격으로 종료하지 않으며 실행 정책은 다음 시작 시 확인. 실시간 원격 종료/보안 lease 아님. 수동 배포 페이지 열기 전 추가 정책 확인은 최대 5초의 UI 대기가 발생할 수 있음.
- 유효한 마지막 캐시(기본 21600초, File Manager와 동일 60~86400초 제한) 사용, 만료 시 마지막 정상 global fallback 사용, 최초 오프라인/손상 캐시 기본 allow/allow(현재 그룹의 기본 정책). 캐시는 LOCALAPPDATA/Sunrise Group/DrawingEditor/control-v1-cache.json. 로컬 캐시/클라이언트는 서명된 보안 경계가 아님. 업무 도면 및 경로를 서버에 전송하지 않음.
- 기존 GitHub 제품별 latest.json/notice.txt, release metadata 생성, Lean spec, 서명/해시, Onefile 및 CMD 유지. 중앙 control.txt 변경 없음.
- 실제 Linux 신규 순수 정책 시험 9/9 PASS 및 진입점 stand-in 시험 3/3 PASS. main.py, release_feed.py, control.py, 신규 시험 2개 Git blob 일치 확인, 해당 파일 compileall PASS. 실제 Qt 연결 및 Windows 패키지 미실행. Qt 회귀시험 보완, Windows GUI 시작 차단/필수 업데이트/실제 교체/전체 기능 QA NOT RUN. 실제 control 상태 변경 테스트는 운영 서버에 하지 않음. 공식 신규 EXE 및 자동 배포 비활성 유지.
