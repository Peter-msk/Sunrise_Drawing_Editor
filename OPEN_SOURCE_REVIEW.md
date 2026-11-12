# 공개 GitHub 저장소 기술 검토 — Sunrise Drawing Editor

확인 기준: 2026-11-11. 도면을 **읽고 레이어 표시를 제어하여 JPG/PNG로 출력**하는 범위이며 CAD 객체 편집 전체 기능을 복제하지 않습니다.

| 저장소 | 형식/특징 | 라이선스 및 핵심 제약 | 이번 반영 |
|---|---|---|---|
| [mozman/ezdxf](https://github.com/mozman/ezdxf) | ASCII/바이너리 DXF, 레이어 및 모델스페이스, Drawing/PyMuPDF backend, `iterdxf` 대용량 ASCII 객체 스트리밍 | MIT. `iterdxf`는 모든 DWG/XREF/복잡한 블록에 대한 동일한 렌더링 기능이 아님 | 기존 엔진 유지, CAD 레이어 조합 렌더 캐시·백그라운드 메타데이터 적재 적용 |
| [pymupdf/PyMuPDF](https://github.com/pymupdf/PyMuPDF) | PDF/온맵 OCG 제어, 클립 렌더링, 이미지 타일 출력 | AGPLv3 또는 상용. 비공개 재배포 전 라이선스 검토 필요 | 기존 엔진 유지, PDF 스레드 간 객체 공유 방지 |
| [LibreCAD/LibreCAD](https://github.com/LibreCAD/LibreCAD) | DXF/DWG 2D CAD, CLI `dwg2dxf`, `dxf2png`, `dwg2png` | GPLv2. DWG CLI는 **DWGSUPPORT 옵션으로 빌드**된 경우에만 작동 | **별도 설치된 실행파일을 CLI로 호출하는 선택적 DWG 대체 경로** 추가. EXE에는 포함하지 않음 |
| [LibreCAD/libdxfrw](https://github.com/LibreCAD/libdxfrw) | DXF/DWG C++ 파서 | GPL-2.0-or-later, DWG 버전 및 객체 종류에 따른 구현 차이 | 내부 링크/번들 제외. LibreCAD를 통한 파일 변환 경로 활용 |
| [LibreDWG/libredwg](https://github.com/LibreDWG/libredwg) | DWG 파싱 및 변환 명령 | GPLv3+, 일부 최신·특수 DWG 객체 미지원 가능 | 미포함: 라이선스 및 DWG 지원 범위 검증 후 별도 평가 |
| [pyinstaller/pyinstaller](https://github.com/pyinstaller/pyinstaller) | Windows onefile EXE 패키징 | GPLv2 with bootloader exception (상세 라이선스 직접 확인) | Windows 빌드 스크립트 통합 |

## 기술적 판단

1. 단순 GUI 앱에 LibreCAD 전체 GUI·C++ 렌더러를 중복 임베딩하면 설치 크기와 법적·운영적 부담이 커집니다. **확인된 ezdxf/MuPDF 렌더링 경로 재사용**이 최우선입니다.
2. 수백 MB CAD의 가장 큰 위험은 원본 바이트보다 `readfile()` 후 수많은 엔티티·블록·해치의 전개가 메모리/CPU를 점유하는 것입니다. 이번에는 사용자가 파일 20~50개를 열더라도 UI가 파서 객체 수십 개를 보관하지 않도록 경계를 분리했습니다.
3. `iterdxf`는 메모리에 모든 엔티티를 올리지 않는 좋은 대안이지만, 제한된 객체/ASCII DXF 중심이며 INSERT·스타일 등이 완전히 보존되는 일반 렌더러 대체품이 아닙니다. 성급히 기본값으로 전환하면 도면 내용이 사라질 수 있습니다.
4. DWG는 ODA File Converter가 여전히 실무 호환성 경로입니다. 공개소스 대안은 별도 설치 LibreCAD CLI로 **선택적 fallback**을 추가했으며 실제 수백 MB DWG 지원은 검증 전입니다.
5. PyMuPDF의 AGPL 의무와 PySide6의 LGPL/상용 라이선스 조건을 충족하지 않은 상태에서 **독점 EXE의 정식 배포 허가가 확보된 것으로 간주하지 않습니다.**

## 확인이 남은 항목

- Windows PyInstaller onefile 실제 빌드·실행(현재 개발 환경: Linux) — NOT RUN
- `CN=Sunrise Group` 인증서 실제 생성/서명/체인 신뢰 — NOT RUN
- DWGSUPPORT가 활성화된 LibreCAD Windows 실물 DWG 변환 — NOT RUN
- 실제 대용량 DXF/DWG(100/300/500MB) 메모리·로드·렌더링 벤치마크 — NOT RUN
- 특수 글꼴, XREF, SHX, 치수·해치, 3D 엔티티 결과 동일성 — NOT RUN
