# Sunrise Drawing Editor — UI 마감·파일/레이어 UX 심화

## 참고한 GitHub 공개 저장소

- [com55/pyside6-mcp](https://github.com/com55/pyside6-mcp) — Qt 위젯 트리, `objectName`, 접근성, 상태/위치 검사 개념
- [neatobandit0/qt-pilot](https://github.com/neatobandit0/qt-pilot) — 객체 이름 기반 동작, 실제 GUI 스크린샷과 Qt 내부 조사 개념
- [redf0x1/ui-ux-pro-mcp](https://github.com/redf0x1/ui-ux-pro-mcp) — 검색 범위 명시, 피드백 및 조작 접근성의 UX 원칙

프로젝트의 문서화된 구현 방식만 참고하여 자체 PySide6 코드를 수정했습니다. 위 저장소의 소스 파일을 복제하거나 상용 실행파일에 포함하지 않았습니다. MCP 서버를 실행했다는 뜻이 아니며 신규 필수 의존성을 추가하지 않았습니다.

## 반영한 변경

1. 모든 핵심 조작 버튼에 구별 가능한 `objectName`을 부여했습니다. 스타일 선택자 `#subAction` 등 역할에 종속된 이름은 `uxRole` 속성으로 옮겨 외형을 유지하면서 MCP식 위젯 검색에서 모호성을 줄였습니다.
2. 파일 목록에서 여러 도면을 선택해 **선택 도면 제거**를 누르거나 파일 목록에 포커스가 있을 때 Delete를 누르면 목록에서만 제거합니다. 2개 이상이면 한 번 더 확인합니다. 원본 도면 파일은 삭제하지 않습니다. 추출 진행 중에는 목록 제거를 막아 작업대상 혼란을 방지합니다.
3. 기존의 **전체 레이어 켜기/끄기**는 검색과 무관한 전체 동작으로 유지했습니다. 검색어가 있을 때만 **검색 결과 켜기/끄기**를 표시해 검색에 일치하는 잠기지 않은 레이어만 갱신합니다. 원래 레이어 순서와 검색 제외 레이어 상태는 유지합니다. 변경 후 미리보기는 한 번만 갱신합니다.
4. 중복 파일 추가는 조용히 무시하던 방식에서 `추가 N개 · 중복 건너뜀 N개 · 추가 실패 N개`로 처리 결과를 안내하도록 바꿨습니다.
5. 작은 논리 화면(760×480)부터 넓은 화면(1440×850)까지 CMD 기반 UI QA 시나리오를 분리했습니다. QA JSON에는 위젯별 이름/유형/위치/크기/표시/사용 가능 여부/접근성명과 중복 식별자 검사가 추가됩니다.

## 안전·정확성

- `core.py`, `cad_selective.py`, `cad_render_fast.py`, `cad_spatial.py`, `tiles.py`, `batch.py`, `state.py`, `BUILD_ONEFILE.cmd` 바이트 동일.
- 기존 회귀시험을 포함한 169개 `unittest` PASS.
- PySide6 미설치 Linux 환경이므로 실제 Windows Qt 화면, 클릭, 캡처, DPI, SignTool, EXE 빌드는 검증하지 못함. 모두 **NOT RUN**.
- 원본 해상도 자동 기본값, 출력 형식/경로, CAD 원본 읽기 전용 정책, ThreePass 최종 검증 근거는 변경하지 않음.

## Windows에서 GUI 확인

PySide6가 설치된 Windows CMD에서 `RUN_UI_QA.cmd`를 실행합니다. `quality/ui_qa_artifacts`에 JSON과 PNG를 기록합니다. 이 스크립트에서 `QT_SCALE_FACTOR`로 배율을 흉내 내더라도 Windows 실제 디스플레이 100/125/150/175% 배율 검증을 대신하지 않습니다. 캡처와 위젯 위치를 확인하고 사용자가 승인해야 정식 배포 가능합니다.
