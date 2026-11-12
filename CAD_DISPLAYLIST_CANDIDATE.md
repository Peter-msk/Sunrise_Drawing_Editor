# CAD PDF repeated viewport display-list candidate

Status: **experimental / not runtime-validated**. Previous official main is unchanged.

## Specific source bottleneck
The ThreePass core barred DisplayList reuse when the original DXF exceeded 96 MiB, even if the selected-layer PDF was small. Thus a 402 MiB mostly-hidden DXF repeatedly decoded the current PDF's path commands for every new pan/zoom clip.

## Proposed, narrowly scoped improvement
- Allow one DisplayList for the **current staged PDF** only if the staged PDF is at most 2 MiB and the selected entity count is at most 512.
- Build only on the second distinct preview clip for the same drawing state; avoid one-off list construction.
- Retain ownership in the existing worker and invalidate immediately on layer/document changes.
- Disable retries after a DisplayList allocation/renderer exception for the same state.
- Leave all JPEG/PNG export paths, source coordinates, shapes, DPI settings, and Qt/CMD build scripts unchanged.

## Evidence and validation boundary
Static source patch guards: PASS. **Python syntax/engine tests: NOT RUN** because the attached-file execution environment was unavailable in this task. Real 402 MiB DXF before/after time, pixel equivalence, Windows GUI and Onefile signing: **NOT RUN**. No performance claim is made. Do not promote this branch to main until tests and DXF field checks pass.

## Required local verification
1. RUN_TESTS.cmd
2. python quality/validate_three_pass.py "D:\\Drawings\\3구간 최종 철탑.dxf" --output QA_report.json --artifacts QA_images
3. Check basic preview / arc-heavy layer / INSERT ON and OFF / repeated clips.
4. Compare RGB pixel SHA-256 and RSS peak versus unchanged ThreePass source.
5. BUILD_ONEFILE.cmd (uses CMD only; no venv or PowerShell).

## Candidate-specific commands (unexecuted here)

```bat
py -3 -m unittest discover -s tests -p "test_cad_view_cache_candidate.py" -v
py -3 quality\\benchmark_cad_view_cache.py "D:\\Drawings\\3구간 최종 철탑.dxf" --layer G0022322 --output QA_ARC.json
py -3 quality\\benchmark_cad_view_cache.py "D:\\Drawings\\3구간 최종 철탑.dxf" --output QA_DEFAULT.json
```

Compare the pixel SHA-256 for every repeated clip against the untouched ThreePass source using the same script. If pixels differ, memory rises excessively or repeat views are not measurably faster, reject this candidate.

## 2026-11-12 최종 통합 소스 안전 경계

이 후보 코드는 대형 실물 도면에서 메모리 및 성능 검증을 완료하지 않았다.
따라서 최종 통합 소스에서는 원본 DXF가 96MiB를 초과하는 경우
**ThreePass에서 사용한 기존 경로**를 유지하며 CAD DisplayList 캐시를 생성하지 않는다.
작은 도면에서도 크기·객체수·레이어 상태 가드를 통과한 경우에만 후보 경로가
작동하며, 실패 시 기존 페이지 렌더러로 복귀한다. 실물 402MiB
도면에서 후보 캐시 성능이 입증됐다는 주장은 하지 않는다.
