# R23 PYZ 내부 용량 분석 및 수집 최적화

기준 R22 3c7ad9a13b772ea9fefa031fd3cdf043fc3c4da2. 사용자 제출 R21 SAFE/COMPACT JSON의 PYZ.pyz는 각각 17,676,033 bytes (16.86 MiB), 내부 모듈명/크기 목록은 원본에 없다. 실제 R22 LEAN EXE 및 PYZ 세부 목록 미확보. 기존 R21 COMPACT는 94,848,792 bytes이며 R22/R23 실측값 아님.

## 단일 실행
BUILD_ONEFILE.cmd를 인수 없이 실행. 기존 기준/SAFE/COMPACT/LEAN/선택 UPX·Nuitka 유지; 신규 PYZ 후보는 LEAN 정책 상속 후 8개 명시적인 선택 모듈/패키지의 Analysis 수집을 제한한다. IPython, pytest, tkinter, PIL.ImageTk, ezdxf.addons.drawing.pyqt/qtviewer/matplotlib, ezdxf.addons.xqt. 모듈이 실제로 기존 PYZ에 있는지 아직 미확인; 없으면 감소 효과 없음. QtWidgets/PyMuPDF 기반 앱의 대체 UI 및 개발용 모듈 대상으로 한 실험. Pillow AVIF, lxml, fontTools, numpy, ezdxf 핵심, TLS, QtWidgets 및 앱 코드는 유지. 별도 CMD 없음.

## 측정
기존 CArchiveReader.open_embedded_archive의 TOC를 읽고 모듈 압축 바이트/패키지별 합계/헤더 및 TOC 등 오버헤드/정렬된 목록/제거·추가 모듈을 기록. EXE/PYZ 코드 실행·추출 없음. 기존 PYZ 합계에 세부 항목을 다시 더하지 않는다. PyInstaller 6.x 내부 API 호환성 오류는 ERROR 기록; 신규 PYZ 후보는 자체 분석 실패 또는 제외 모듈 잔류, 기준 비교 실패 시 후보 게시 금지. 기존 기준 빌드 및 다른 후보는 분석 오류만으로 막지 않는다. 실제 모듈 크기 감소와 전체 EXE 감소를 구분. Analysis.pure 모듈명과 기존 graph/xref 자료를 사용하여 후속 검토. Nuitka에는 이 PYZ 포맷 미적용.

- dist_lightweight/r18-*/SIZE_COMPARISON.json: profile=pyz, baseline.pyz, candidate.pyz, pyz_comparison, policy.pure_module_names.
- quality/onefile_selection/r23-*/BUILD_REPORT.json: lean_to_pyz (동일 실행 LEAN 및 PYZ 각각 1개 존재 시 직접 비교), 전체 빌드 결과.
- dist는 기존 기준 EXE만 게시. 모든 기존 QA 및 신뢰 서명 조건 유지. 공식 새 EXE 배포 없음.

## 검증
Linux Python에서 신규 정책 5/5 PASS, 신규 파일 compileall PASS, 해당 두 파일 Git blob 동일. 합성 TOC 및 모의 reader 시험이며 실제 PyInstaller CArchiveReader/PYZ API 연동, Windows 빌드, 기능 QA, 전체 통합 회귀 및 용량 실측 NOT RUN. 변경된 통합 시험의 실제 실행은 별도 확인 필요. 기존 EXE나 공식 main, notice/latest 메타데이터 변경 없음. 70 MiB 목표는 아직 실측 근거 없는 목표이며 이 단계의 절감량 예측 불가.

참고: https://pyinstaller.org/en/stable/hooks.html 및 https://github.com/pyinstaller/pyinstaller/blob/develop/PyInstaller/utils/cliutils/archive_viewer.py
