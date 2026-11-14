# Stage 9 — 추천 GitHub 목록 후속 UX·오류 피드백 감사

- 작성일: 2026-11-14 KST
- 제품: Sunrise Drawing Editor (Windows PySide6, PDF/DXF/DWG 로컬 비파괴 도면 편집기)
- 적용 입력: 사용자 제공 「개발 구성별 추천 GitHub 저장소 목록.md」의 UI / UX / 레이아웃 / 기능 총 20개
- 상위 검토: [GITHUB_RECOMMENDATIONS_NATIVE_QT_REVIEW_20261114.md](GITHUB_RECOMMENDATIONS_NATIVE_QT_REVIEW_20261114.md)
- 대상 브랜치: \`review/github-recommendations-native-ux-20261114\`
- 공식 \`main\` / 기존 \`source-20261114\` Release / Google Drive 기준 ZIP: **수정하지 않음**
- GitHub Actions: **재활성화·실행하지 않음**, 브랜치에 workflow 파일 0개

## 1. 추가 확인 결함 및 원인

### A. '잠긴 레이어만 검색' 시 동작 불가능 버튼 노출
- 기존 \`_filter_layers\`는 검색 결과 \`matches > 0\`이면 '검색 결과 켜기/끄기' 영역을 표시함.
- 실제 동작 가능 조건은 \`_sync_actions\`가 계산하는 \`matching_editable_layers\`의 **잠기지 않은 검색 일치 레이어 존재 여부**임.
- 검색 결과가 모두 잠겼다면 버튼은 비활성화되고, 왜 사용하지 못하는지 안내는 나타나지 않았음.
- 수정: 순수 헬퍼 \`layer_search_feedback(query, matched, editable)\`로 빈 검색 / 결과 없음 / 잠긴 결과만 있음 / 수정 가능한 결과 존재 상태를 구분하고, \`_sync_actions\` 이후 실제 활성 상태에 따라 동작 영역을 숨기거나 명확한 잠금 메시지를 표시함.
- 검색은 여전히 **화면 표시만 제어**하고 파일 또는 레이어 ON/OFF 상태를 바꾸지 않음.

### B. 파일 분석 중/성공/실패 안내가 시각적 텍스트/툴팁에만 의존
- PDF/DXF/DWG 추가 후 메타데이터 분석 중, 완료, 실패를 기존 목록 텍스트로 표시했으나 파일 목록 항목의 Qt AccessibleDescriptionRole이 없었음.
- 수정: \`QListWidgetItem.setData(Qt.ItemDataRole.AccessibleDescriptionRole,...)\`로 작업 중·레이어 분석 완료·실패 원인을 전달함.
- 읽기 실패 시 기존 오류 툴팁과 상태 표시를 유지. 파일 목록 제거와 입력 원본은 변경 없음.

## 2. 실제 소스 변경
- \`drawing_editor/ui_interaction.py\`: 검색 피드백 순수 함수 1개
- \`drawing_editor/window.py\`: 레이어 검색 가능 동작과 메시지 동기화, 파일 목록 3단계 접근성 설명
- \`tests/test_locked_layer_search_stage9.py\`: 순수 및 실제 AST 추출 GUI 메서드를 fake widget으로 실행하는 8개 신규 회귀시험
- 렌더 코어(\`core.py\`), CAD 워커(\`cad_worker.py\`), 일괄 출력(\`batch.py\`), 원본 도면·빌드 설정·requirements: 변경하지 않음
- 외부 GitHub 추천 프로젝트 소스 복사나 추가 패키지 설치 없음

## 3. 실행 결과 및 엄격한 검증 범위

| 대상 | 결과 | 비고 |
|---|---|---|
| Stage 9 신규 검색/접근성 회귀 | **8/8 PASS** | 로컬 미러 변경 동일, Python 3.13.5 Linux |
| Stage 8+추천 UX+Stage 9 로컬 통합회귀 | **251/251 PASS** | 약 32.7초, \`unittest discover -s tests -q\` |
| 로컬 Python 컴파일 | **PASS** | \`python -m compileall -q drawing_editor tests\` |
| GitHub 브랜치 정적 확인 | **PASS** | 브랜치 변경 경로에 렌더 코어 없음; 워크플로 파일 0개 |
| GitHub 정확한 브랜치 전체 실행 | **NOT RUN** | 컨테이너에서 \`git clone\` DNS 실패. Actions는 사용자 지시로 꺼둠 |
| Windows PySide6 실제 UI/스크린리더 | **NOT RUN** | 현재 검증 환경 PySide6 미설치 |
| 원본 온맵 PDF 및 421MB DXF 실기·DPI | **NOT RUN** | 이번 범위는 UX 제어·상태 안내 로직 |
| Windows 서명 EXE 배포 | **NOT RUN / HOLD** | 기존 source release 유지 |

**주의:** 251/251 PASS는 사용자가 이전에 제공한 Stage 8 로컬 검증 ZIP에 추천 UX 및 Stage 9 변경을 반영한 테스트 결과임. 최신 GitHub 브랜치 전체가 byte-identical한 로컬 clone에서 PASS한 결과라고 주장하지 않음. GitHub 공식 소스가 기존에 통과한 262개 테스트와도 시험 모수가 달라 단순 숫자 비교 불가.

## 4. 후속 Windows QA 게이트

1. 위 브랜치의 실제 SHA 기준으로 수동 clone하여 전체 유닛테스트 실행 (**Actions 자동실행 금지**).
2. 잠금만 검색 / 일반 검색 / 검색 결과 없음 / 검색어 삭제 / 다중 레이어 선택에서 버튼 노출과 안내문 확인.
3. 파일 분석 중·정상·실패 항목을 Windows 스크린리더로 확인.
4. 760/900/1120/1340 논리 픽셀과 100/125/150/175% DPI에서 클리핑·탭 순서·라이트·다크 대비 확인.
5. 사용자 실물 DXF→원본 온맵 OCG 전환과 서명 EXE 검증 후에만 정식 제품 릴리스 후보로 판단.

## 5. 변경 불변 조건
- 원본 DXF/DWG/PDF 절대 덮어쓰기 금지.
- GitHub Actions 자동 실행 재개 금지.
- 명시 승인 없이 공식 \`main\`, 기존 GitHub Release, Drive 기준본 또는 Windows 정식 EXE 교체 금지.
