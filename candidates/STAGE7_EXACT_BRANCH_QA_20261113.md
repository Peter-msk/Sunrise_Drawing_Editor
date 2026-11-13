# Sunrise Drawing Editor — Stage 7 정확한 GitHub 소스 기준 QA 게이트

**작성:** 2026-11-13 KST  
**개발 브랜치:** `work/p0-render-lifecycle-audit-20261113`  
**판정:** SOURCE/TEST GATE AUTHORED, **TEST EXECUTION NOT RUN**  
**배포:** RELEASE HOLD. GitHub `main`, Drive 기준본, 서명 EXE 변경 금지.

## 목적
이전 Stage 6의 234/234 PASS 결과는 별도 로컬 재구성 소스에서 발생했다. 최신 GitHub 개발 브랜치는 추가 워커 원본 식별/IPC/카탈로그 코드가 포함되어 있으므로 해당 숫자를 **정확한 브랜치의 통과 기록으로 대체할 수 없다**.

이번 Stage 7은 Windows CMD 검증이 실제로 어떤 커밋과 어떤 소스 바이트를 검사했는지 명확히 남기는 오류 방지 게이트이다.

## 이번 변경
- `quality/qa_exact_branch.py`: 공식 GitHub origin, 체크아웃 브랜치, HEAD SHA, 예상 커밋(선택), 수정된 추적 파일, 추적되지 않은 실행 코드 및 테스트, 소스 SHA-256 집계, Git tree SHA를 검사한다. 결과는 `quality/P0_runtime/SOURCE_IDENTITY.json`에 기록한다.
- `tests/test_exact_branch_qa.py`: 새 9개 시험(정상 커밋 지문, 수정된 파일, 미추적 코드, 원격 저장소 위장, 브랜치 불일치, 커밋 불일치, QA 파일 변조, QA 미추적 Python, 생성된 보고서 허용).
- `RUN_P0_QA.cmd`: 모든 시험 **전과 후**에 동일한 소스 신원 게이트를 실행하고, 이전에 누락된 Stage 6 DXF IPC 파일 전환 경합 시험도 필수로 실행한다.
- 신규 게이트는 **기존 실행 경로/렌더링 결과/PNG 저장 알고리즘을 변경하지 않는다.**

## 실행 예정인 대상 시험: 45개
1. 소스 식별과 무결성 9개
2. DXF 격리 워커 9개
3. IPC 응답-종료 경합 1개
4. 카탈로그 및 MuPDF 배치 잠금 7개
5. 카탈로그 세대·삭제·재등록 7개
6. 워커 소스 수정·재시작 5개
7. HiDPI·테마·SVG 7개

`RUN_ALL_TESTS=1`을 명시했을 때만 기존 전체 회귀시험을 추가 실행한다. 과거 PASS 항목의 자동 중복검사를 기본적으로 수행하지 않는다.

## Windows CMD 실행 절차
1. 배포 폴더나 공식 main을 덮어쓰지 말고 별도 작업 폴더를 만든다.

```bat
git clone --branch work/p0-render-lifecycle-audit-20261113 --single-branch https://github.com/Peter-msk/Sunrise_Drawing_Editor.git Sunrise_Drawing_Editor_P0_QA
cd /d Sunrise_Drawing_Editor_P0_QA
RUN_P0_QA.cmd
```

2. **421,316,933바이트 원본 DXF 및 실제 온맵 PDF**를 사용한 10회 반복 시험:

```bat
RUN_P0_QA.cmd "D:\Drawings\3구간 최종 철탑.dxf" "D:\Drawings\실제온맵.pdf"
```

3. 대상 코드가 변경되어 영향 범위 전체 시험이 필요한 경우:

```bat
set "RUN_ALL_TESTS=1"
RUN_P0_QA.cmd "D:\Drawings\3구간 최종 철탑.dxf" "D:\Drawings\실제온맵.pdf"
```

4. 특정 원격 커밋을 사전에 확인했다면 `EXPECTED_SOURCE_SHA` 환경변수를 그 SHA로 지정해 HEAD 불일치를 즉시 FAIL 처리할 수 있다. 설정하지 않으면 보고서의 SHA를 공식 GitHub 개발 브랜치 최신 커밋과 수동으로 대조한다.

**주의:** Git 기록이 없는 Stage 6 로컬 ZIP은 `qa_exact_branch.py`에서 FAIL 처리된다. 이 정책은 원본이 잘못됐기 때문이 아니라 GitHub 동일 소스 증명을 할 수 없기 때문이다.

## Windows GUI 실기에서 필수 확인
- 421MiB 철탑 DXF 렌더 진행 중 실제 온맵 PDF 선택 → 새 미리보기 표시, 오래된 DXF 결과 미적용, 워커 PID 소멸
- 실제 온맵 OCG ON/OFF 후 원상 복원 PNG 픽셀 동일성
- 파일 제거·동일 경로 재등록·파일 내용 갱신 중 카탈로그 응답 처리
- 확대/스크롤 및 취소 후 하위 프로세스/IPC 폴더·메모리 누수
- Windows 100/125/150/175% 라이트·다크 글자 대비, 버튼·아이콘 광학 중심과 기준선
- Windows Onefile 실행, 정상/비정상 종료 및 SignTool 서명

## 이번 세션 검증 한계
- GitHub에서 실제 소스 파일·테스트 파일·CMD 러너 존재, 총 45개 `test_*` 메서드, 8단계 실행 순서, 필요 판정 조건을 **정적 확인**했다.
- 현 실행환경 Python/컨테이너 도구가 오류를 반환했다. 따라서 새 9개 시험, 현재 정확한 GitHub 브랜치 전체시험, Windows 실기 결과를 **PASS로 기록하지 않는다**.
- 이전 Stage 6 로컬 통합본의 234/234 PASS 기록은 유효한 **이전 범위의 별도 결과**로 유지된다.
- **진행률 55/100 유지:** 코드 QA 게이트는 마련했지만 Windows·동일 소스 실행 관문이 미완료이므로 새 완료율을 부여하지 않았다.

## 수정 범위와 보존
- 신규: `quality/qa_exact_branch.py`, `tests/test_exact_branch_qa.py`, 본 문서
- 보완: `RUN_P0_QA.cmd`, 보완계획
- 변경 없음: `drawing_editor/core.py`의 ThreePass/PNG P0, 공식 main, Drive, EXE
