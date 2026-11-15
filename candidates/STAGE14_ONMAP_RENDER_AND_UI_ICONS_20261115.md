# Sunrise Drawing Editor — Stage 14 영상 기반 렌더링 응답성·전체 아이콘·체크박스 개선 (2026-11-15)

## 1. 실제 사용자 입력 근거
- 영상: `Sunrise_20261115_225248.mp4`, 길이 **104초**, **30fps**, **1544×930**.
- 사용자 이미지 4장: 라이트 모드 레이어 체크박스·도면 추가/삭제 버튼·아이콘의 미완성 인상과 정렬·검색 돋보기·04 이미지 추출 컨트롤.
- 영상에서 실제로 보이는 구간: 약 12초 다크 프로그램 창, 20초대 온맵 파일 등록, 28초경 빈 미리보기·32초경 지도 표시, 64초경 '레이어 규칙 일괄 적용 결과' 대화창(15개 일치/15개 변경), 76초경 렌더 완료 화면, 84초경 새 도면 미리보기 공백·88초경 지도 재표시.
- **주의:** 이는 영상 샘플에서 관찰한 화면 전환 시점이지 CPU 작업 완료시간/Windows API 응답없음 신호의 정밀 계측이 아님. 사용자가 보고한 멈춤·버벅임을 추가 검증해야 함.

## 2. 코드 수준 발견 원인
1. Stage13 `RenderTask`는 >=64MiB DXF만 별도 `--cad-worker`에 격리했으나 **온맵 레이어가 있는 PDF는 Qt와 같은 Python 프로세스의 MuPDF/QThread 경로**에서 렌더했음. 네이티브 PDF 래스터가 오래 걸리면 해당 프로세스의 UI 응답성 저하 위험.
2. 레이어 버튼은 클릭마다 렌더 취소 요청을 하지만 대기 시간 135ms였음. 연속 체크에서는 자원 소모가 큰 이전 PDF 작업이 개시될 가능성.
3. 별도 프로세스로 이동할 경우 JSON object key는 무조건 문자열이 되어 PDF OCG xref의 정수 키가 손실되는 문제가 있었음. 누락 없이 복원해야 함.
4. 레이어 체크박스는 Qt 기본 상태, 기존 SVG의 실제 도형 크기/변환 및 역할 인지가 일관되지 않아 라이트/다크에서 부조화.

## 3. Stage14 실제 코드 수정
- `drawing_editor/window.py`: OCG 레이어가 있는 PDF의 preview/detail 작업도 프로세스 격리. `_layer_changed`, 전체 켜기/끄기, 검색 레이어 켜기/끄기에서 **260ms 디바운스** 후 마지막 상태만 렌더하도록 변경. 첫 도면/페이지 표시에는 **110ms** 기존보다 빠른 스케줄. 현재 렌더 취소는 그대로 유지.
- `drawing_editor/cad_worker.py`: 기존 1개 네이티브 렌더 프로세스 재사용을 PDF에도 적용. 원본 OCG xref int를 JSON IPC 후 복원. 사용자가 다른 레이어로 전환하면 기존 native child 종료/교체, 이후 최종 상태 렌더. source 파일은 읽기 전용.
- `assets/icon_*.svg`: **20종 기능 아이콘 × 기본/라이트/다크 3종 = 60개**, 추출·중단 흰색 2개, 레이어 체크용 새 흰색 체크 1개 = **63개 재설계·추가**. 같은 24px viewBox, 1.9~2px 둥근 선·안전 여백, 라이트 #B8480B / 다크 #FFAD78 / 기본 #B8480B.
- 기능 구분: **도면 추가=폴더와 + / 현재 도면 목록 제거=문서와 − / 저장 규칙 삭제=휴지통 / 규칙 적용=확인 표시**. 확대·축소·화면맞춤·검색·눈 열기·눈 감기·내보내기·선택 등 개별 심벌 설계.
- `window._apply_theme`: `QTreeWidget::indicator` 및 `QCheckBox::indicator` **17px 둥근 체크박스** + 주황색 활성 배경 + 흰색 체크 SVG, 미선택 및 hover/disabled 구분. 양 테마 QSS 동시 적용.
- renderer `fitz`/ezdxf/PyMuPDF, 내보내기, PDF/DXF 원본, OCG 실제 저장, FileList·RuleStore·Windows 빌드 설정은 변경하지 않음.

## 4. 검증
- `tests/test_stage14_render_icons.py` — 정적 계약 5개 + 실제 합성 11 OCG PDF에 대한 child-process ON → OFF → ON PNG 픽셀/기하 비교 1개.
- `quality/benchmark_stage14_onmap.py` — 실제 사용자의 PDF 1~15개에서 native child 첫 표시·한 레이어 반전·원복의 수행시간·PNG SHA 측정 및 미변경 보장, 선택적으로 `--exe`로 Onefile cold start/self-test 시간 측정. **이 도구로 출력된 수치가 있어야 성능 PASS 판정 가능**.
- `RUN_STAGE14_QA.cmd` — Git/ZIP 소스 동일성 확인 → 수정코드 compile → 신규 OCG/아이콘 검증 → 기존 아이콘 DPI/대비 회귀 → 4 DPI×2 테마×4 창 너비 32 PNG 캡처 → 무결성 재확인.
- 실제 온맵 15개 파일 전환 시 UI 응답없음 해결, 사용자 Win10/11 onefile, 물리 DPI, 실제 성능 단축률: **NOT RUN / 최종 승인 대기**.
- 기존 Stage11/12 이미 PASS 처리된 무관 시험 재수행 금지. Graphical UI QA는 수정된 테마/아이콘에 한정.

## 5. 사용자가 실행할 명령
```cmd
cd /d C:\Sunrise_Drawing_Editor
RUN_STAGE14_QA.cmd
```
실제 온맵 15개가 있는 폴더도 점검하려면:
```cmd
set "STAGE14_PDF_DIR=D:\ActualOnMap"
RUN_STAGE14_QA.cmd
```
또는 Windows EXE 시작 시간 측정:
```cmd
python -m quality.benchmark_stage14_onmap --exe "dist\Sunrise Drawing Editor.exe"
```

## 6. 배포 및 롤백 경계
- Stage13 공식 `main` 및 RELEASE, Drive의 이전 검수본은 별도.
- 신규 검수 후보 브랜치 `STAGE14_SOURCE` 다운로드 ZIP. Windows CMD `BUILD_ONEFILE.cmd`는 기존 그대로.
- 현 소스 ZIP의 Git object 해시와 manifest를 대조할 수 있으나 **컴파일 통과나 Windows 실기까지 대체하지 않음**.
- GitHub Actions workflow 0개 유지; 사용자가 허락하기 전 자동 재활성화하지 않음.
