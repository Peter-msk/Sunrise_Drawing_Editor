# 외부 라이브러리·재배포 점검

| 구성 | 용도 | 확인할 라이선스 |
|---|---|---|
| PyMuPDF/MuPDF | PDF OCG/래스터화, CAD PDF 렌더 후처리 | AGPLv3 또는 상용 라이선스. 비공개 재배포 전 필수 판단 |
| ezdxf | DXF parsing/drawing, ODA integration | MIT |
| PySide6/Qt | Windows GUI | LGPLv3 또는 상용(컴포넌트별 확인) |
| Pillow | PNG/JPG 이미지 후처리 | HPND/Pillow |
| PyInstaller | onefile 배포 도구 | GPLv2 with bootloader exception(공식 LICENSE 참조) |
| LibreCAD | **선택적 외부** DWG CLI | GPLv2 — 실행파일 별도 설치, 본 EXE에 미포함 |
| ODA File Converter | **선택적 외부** DWG 변환 | 별도 배포/사용 약관에 따름, 본 EXE에 미포함 |

고지 자체가 모든 라이선스 준수를 완성하는 것은 아닙니다. 소프트웨어 배포 형태·소스 공개 범위·수정 여부·사용 용도에 따른 라이선스 확인이 필요합니다.


## 공개소스 성능 후보 검토 (미번들)

- libvips (LGPL-2.1-or-later): https://github.com/libvips/libvips — 저메모리·스트리밍 대용량 이미지 엔진. 이번 EXE에 포함하지 않음.
- pyvips (MIT Python 바인딩, native libvips 의존): https://github.com/libvips/pyvips — 이번 EXE에 포함하지 않음.
- libpng (별도 라이선스): https://github.com/pnggroup/libpng — 독립 바인딩/소스 추가하지 않음.
- PyMuPDF DisplayList는 이미 설치된 PyMuPDF 공개 API를 사용하는 방식으로 적용했으며, 기존 AGPLv3/상용 재배포 검토 필요성은 변하지 않음.
