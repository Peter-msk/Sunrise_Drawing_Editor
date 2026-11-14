# Sunrise Drawing Editor — 추천 GitHub 저장소 20종 적용·제외 감사 및 Qt UX 보완

- 기준일: 2026-11-14 KST
- 평가 기준: 사용자 제공 **「개발 구성별 추천 GitHub 저장소 목록.md」** (UI 5 / UX 5 / 레이아웃 5 / 기능 5)
- 검토 제품: Sunrise Drawing Editor, Windows/PySide6-Essentials desktop, PDF/DXF/DWG, local-first, read-only input files
- 공식 소스 기준: GitHub main \`08da8c66e358ffea6c28a02436be0a9ee6d25077\` (Actions workflow 제거 반영 이후)
- 변경 브랜치: \`review/github-recommendations-native-ux-20261114\` (공식 main과 기존 Source Release는 변경하지 않음)
- 판단 기준: 호환성 / 소유권 / 사용자 가치 / 기존 기능 보호 / 배포·라이선스 / 신규 의존성 최소화

## 1. 저장소별 적용 결정

| 분류 | 추천 GitHub 저장소 | 결과 | 이 프로그램의 적용 범위·이유 |
|---|---|---|---|
| UI | shadcn-ui/ui | 원칙 적용 | 명확한 접근성 이름과 개별 상태 표현, React/Tailwind 코드는 불필요 |
| UI | ant-design/ant-design | 원칙 적용 | 업무 동작을 설명하는 버튼·입력 상태, React 컴포넌트 직접 도입 불가 |
| UI | mui/material-ui | 원칙 적용 | 접근성·포커스·테마 토큰, Qt의 기존 위젯 재사용 |
| UI | FortAwesome/Font-Awesome | 기존 자산 유지 | 이미 light/dark SVG가 존재. 새로운 아이콘 라이선스·재배포 의무 도입 불필요 |
| UI | saadeghi/daisyui | 원칙 적용 | 버튼의 의미 있는 role을 기존 uxRole 및 Qt 스타일시트로 보존 |
| UX | animate-css/animate.css | 직접 도입 제외 | HTML/CSS 애니메이션 불필요. 기존 비차단 진행률 상태 표현을 Qt 접근성에 연결 |
| UX | nolimits4web/swiper | 제외 | CAD 편집기는 슬라이더 콘텐츠가 아니라 확대·드래그 캔버스를 사용 |
| UX | alvarotrigo/fullPage.js | 제외 | 고정형 세 패널 데스크톱 화면을 스크롤 스냅 방식으로 바꾸지 않음 |
| UX | motiondivision/motion | 제외 | React 기반 전환 라이브러리. 대형 DXF 렌더/프레임과 충돌 가능성·이득 불명 |
| UX | SortableJS/Sortable | 원칙 참고 | 파일 목록 Qt 네이티브 드롭과 Ctrl/Shift 다중선택 보존. 미요청 재정렬을 추가하지 않음 |
| 레이아웃 | twbs/bootstrap | 원칙 적용 | 논리 픽셀 단위의 기존 panel_layout 브레이크포인트 유지 |
| 레이아웃 | tailwindlabs/tailwindcss | 제외 | 기존 QSS 및 ui_design.THEMES가 단일 기준원, 새 웹 CSS 런타임 불필요 |
| 레이아웃 | necolas/normalize.css | 제외 | 브라우저 초기화 용도는 PySide6 Widgets 제품과 맞지 않음 |
| 레이아웃 | Semantic-Org/Semantic-UI | 원칙 참고 | 위젯 이름·동작 의미 분명히. jQuery/웹 클래스 도입 불필요 |
| 레이아웃 | jgthms/bulma | 제외 | Qt 레이아웃 엔진에 CSS Flexbox를 중복 도입하지 않음 |
| 기능 | public-apis/public-apis | 제외 | 현 제품은 로컬 도면 렌더·추출, 외부 데이터 API 요구 없음 |
| 기능 | supabase/supabase | 제외 | 로그인·DB·원격 파일 동기화 미요청, 원본 보호/개인정보 부담 증가 |
| 기능 | strapi/strapi | 제외 | CMS·관리자 대시보드 현재 범위 외 |
| 기능 | nocodb/nocodb | 제외 | 도면 레이어 스냅샷 저장에 웹 협업 스프레드시트 백엔드 불필요 |
| 기능 | pocketbase/pocketbase | 제외 | 로컬 EXE에 별도 백엔드·사용자 인증 불필요 |

> 사용자 제공 추천 목록의 Star 수는 당시 근사치이며, 본 개선의 채택·제외 기준으로 활용하지 않았음. 외부 저장소 소스 코드를 복사하거나 재배포하지 않았음.

## 2. 실제 반영 — Qt 네이티브 최소 변경

- \`drawing_editor/window.py\`
  1. 반응형 760~900px 화면에서 축약되는 '전체'/'끄기'/'적용' 등 8개 동작에 불변 접근성 이름과 설명을 지정함. 버튼 UI 문구·기능 동작·단축키는 변경하지 않음.
  2. 6px 높이의 텍스트 없는 기존 이미지 추출 진행 바에 \`setAccessibleName\` / \`setAccessibleDescription\` 추가. 데이터 처리 및 결과 값 산출에는 손대지 않음.
  3. \`ElidedLabel.setText\`에서 길이 축약으로 보이는 도면명과 관계없이 **전체 파일명**을 \`accessibleName\`으로 유지함. 기존 툴팁·시각적 축약 방식 유지.
- \`tests/test_recommended_native_ux_20261114.py\`: 5개 새로운 headless 회귀시험. 전체 파일명, 8개 동작 명칭, 화면 축약과 접근성 분리, 진행률 이름, web/backend 의존성 미추가를 검사.
- 신규 runtime 의존성: **0개**. \`requirements.txt\`, CAD 렌더 엔진, OCG, 레이어 규칙, PNG/JPG 출력, 원본 파일을 수정하지 않음.
- GitHub Actions/CI 워크플로: **추가·실행·재활성화 없음**.

## 3. QA 증거 및 한계

| 검증 대상 | 결과 | 유의 |
|---|---|---|
| 신규 Qt UX 정적 회귀 | **5/5 PASS** | 로컬 Stage8 기반 소스에 동일 UX 변경 반영 |
| 로컬 통합 회귀 | **243/243 PASS** | Python 3.13.5, Linux; Stage8 로컬 재구성본 기반, 정확한 GitHub 브랜치 전체와 byte-identical 아님 |
| 컴파일 | **PASS** | \`python -m compileall -q drawing_editor tests\` |
| 실제 GitHub 수정 소스 정확한 브랜치 전체 자동시험 | **NOT RUN** | 현재 환경은 GitHub clone 불가, Actions 사용자 지시로 중지 |
| Windows PySide6 스크린리더/DPI/실기 | **NOT RUN** | 사용자 PC 수동 검증 필요 |
| 실물 원본 DXF/온맵 PDF 렌더 영향 | **NOT RUN** | 이번 변경은 렌더 함수와 파일 I/O에 변경 없음 |
| 정식 EXE·코드 서명 | **NOT RUN** | 별도 Windows QA/신뢰 서명 필요 |

## 4. 최종 판단과 다음 승인 절차

- 권장 저장소의 UI/UX/반응형 **설계 원칙만 채택**, 기존 PySide6 데스크톱 계약과 독립 제품 경계를 보존한다.
- 설치 비용·라이선스가 있는 JS/Web/서버 패키지를 도입하지 않는다.
- 다음 Windows 단계: 이 브랜치 소스로 실행→760/900/1120/1340 논리 픽셀에서 버튼 이름/탭 순서/스크린리더·키보드 확인; 실제 DXF 도면명 완전 전달; 이미지 추출 진행률 확인; 라이트/다크 DPI 100/125/150/175% QA.
- 미검증 런타임은 PASS로 표기하지 않고 별도 보완 후 GitHub PR 검토. **자동 Actions 금지**, main과 이미 발행된 공식 릴리스 유지.
