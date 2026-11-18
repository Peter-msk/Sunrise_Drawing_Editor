# R18 — Onefile 정밀 경량화 후보

기준: R17 (6343ae38b3bcdb9e2ee56b3978bf7f76ed353cd7). 사용자 확인 약 100MB EXE와 R17 실제 분석 JSON은 미확보. 실측 절감량 없음. 새로운 Windows 경량화 빌드 경로만 추가하며 기존 앱 소스, BUILD_ONEFILE.cmd, requirements, 공지/업데이트, 서명 프로토콜은 유지한다.

## 실행 (기존 Windows 빌드 환경)

```cmd
BUILD_LIGHTWEIGHT.cmd --profile safe --baseline "C:\Sunrise\Sunrise Drawing Editor.exe"
BUILD_LIGHTWEIGHT.cmd --profile compact --baseline "C:\Sunrise\Sunrise Drawing Editor.exe"
```

baseline을 생략하면 기존 dist의 EXE를 자동 선택하고, 없으면 후보만 측정한다. 기존 빌드 Python/PyInstaller 6.x/SignTool 사용; 자동 설치 없음. safe는 한국어와 영어 외의 명시적으로 식별된 Qt .qm 번역만 제외. compact는 이에 더해 Qt 소유의 qgif, qicns, qtga, qtiff, qwbmp, qwebp 플러그인 및 opengl32sw.dll만 제외하는 실험 후보. 기타 언어 UI 및 외부 래스터 참조, 저사양 GPU/RDP 호환성 영향 가능. qwindows, SVG/JPEG/ICO, Qt 기본 DLL, MuPDF, NumPy, Pillow, TLS, Python 및 알 수 없는 항목은 이 필터로 제거하지 않는다. Analysis 이후 필터링이므로 다른 DLL의 전이 의존성을 자동 제거하지 않는다. UPX 비활성 유지.

## 검증 및 출력

빌드 → 서명 전 self-test → 기존 Sunrise Group 서명 → 서명 후 self-test → R17 아카이브 감사 → 삭제 목록 실제 부재 확인 → baseline SHA-256 재확인 → 기존 검증된 publish helper를 별도 후보 경로에 실행.

각 실행은 고유한 build/lightwork/r18-* 및 dist_lightweight/r18-*를 사용. 후보 EXE, SHA256.txt, SIGNATURE_STATUS.json, SIZE_COMPARISON.json 생성. 기존 dist와 공식 GitHub 업데이트 파일은 변경하지 않는다. JSON에는 원본 및 후보의 실제 압축 크기, SHA-256, 라이브러리별 비중, 제거 항목, 감소 바이트/비율이 기록된다. 제거 SOURCE 바이트와 실제 압축 절감량을 구분한다. 음수 절감량 또는 0도 그대로 기록한다. 최초 비교는 동일 Python 및 의존성 버전에서 수행 권장.

## 검증 범위

- 신규 정책 단위시험 6/6 PASS, Python compileall 및 spec AST PASS (Linux).
- 실행파일 및 실제 TOC 미확보: 실제 PyInstaller/Windows CMD/서명/후보 EXE 실행/용량 측정은 NOT RUN.
- 다음 Windows 후보 실기: 기존 EXE와 같은 입력에서 PDF OCG, DXF/DWG, 배치 PNG/JPG 픽셀, 400MB급 DXF, SVG 아이콘/두 테마, 원격 데스크톱/저사양 GPU, 외부 래스터 참조, 공지/업데이트 TLS, worker 실행 비교. startup/RAM 측정 및 Qt 번역/플러그인 영향 확인. 전체 정식 배포 승인 별도.

공식 참고: https://pyinstaller.org/en/stable/spec-files.html 및 https://doc.qt.io/qt-6/windows-deployment.html
