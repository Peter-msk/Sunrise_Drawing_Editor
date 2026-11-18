# R17 Onefile 용량 정밀 감사

- 기준: R16 `b840edea9e0bd737a29b16d25765d65eab1f1363`.
- 목적: 사용자 확인 약 100MB EXE를 실제 CArchive 압축 바이트 기준으로 분석. 수치 없는 모듈 삭제 금지.
- 기존 앱, 빌드 CMD, 의존성, 서명, 공지, 업데이트 본체는 변경하지 않음.
- 독립 빌드 도구인 PyInstaller 6.x CArchiveReader를 재사용. EXE는 실행하거나 수정/추출하지 않음. PYZ를 중복 계산하지 않고, 전체 크기와 항목 합계 차이는 별도 표기. SHA-256과 리더 버전을 기록.
- 용량 분류는 경로/이름 기반 휴리스틱. 제거 후보는 의존성 확인 및 실제 실행 검증 후에만 채택. 미분류 파일은 다른 그룹으로 합산. 중복 파일의 내용 동일성, PE import dependency graph, 실제 디스크/RAM 사용량은 이번 단계에서 확정하지 않음.
- 로컬 실행 (이미 빌드한 EXE를 복사하지 않아도 됨):

```cmd
AUDIT_ONEFILE.cmd
AUDIT_ONEFILE.cmd "C:\Sunrise\Sunrise Drawing Editor.exe" "quality\onefile_size\R16_BASELINE.json"
```

기본 입력은 `dist\Sunrise Drawing Editor.exe`, 기본 출력은 `quality\onefile_size\ONEFILE_SIZE.json`. 같은 보고서 덮어쓰기를 금지하며 재실행은 두 번째 인수에 새 JSON 경로 지정. Windows 기존 빌드용 Python과 PyInstaller 사용, 자동 설치 및 가상환경 생성 없음. CMD 종료 코드 0이면 JSON 생성 및 분석 성공. 결과 JSON만 공유하면 R18 후보의 실측 순위를 정할 수 있음. 사용자 로컬 경로나 EXE를 공개 저장소에 올릴 필요 없음.

## 검증

- 신규 unittest 5/5 PASS (합성 TOC·mock reader output; Python 3.13, Linux).
- 신규 Python 파일 compileall PASS.
- 실제 PyInstaller EXE reader 연동, Windows CMD 실행, 실제 100MB EXE 용량 감사 NOT RUN. PyInstaller와 Windows EXE가 검증 환경에 없었음.
- EXE 크기 감소 실측 없음. 기존 PASS 엔진 시험은 변경 범위가 아니므로 재실행하지 않음.

## R18 진입 조건

실제 JSON에서 Qt, MuPDF, NumPy/BLAS, 기타 항목별 압축 바이트와 상위 30개를 확인한 뒤, PyInstaller TOC 및 의존성 로그를 근거로 하나씩 후보를 제거하는 A/B 빌드 계획을 확정한다. Qt platform/필수 SVG, PDF OCG, DXF/DWG, PNG/JPG 출력, worker 프로세스, TLS, 업데이트 및 서명은 유지한다.
