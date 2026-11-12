# Sunrise Drawing Editor — Rendering / Export Improvement Report

## Scope

- Current base: `Sunrise_Drawing_Editor_QtFix.zip`. Existing Windows CMD-only onefile, Qt binding exclusions, Sunrise Group SignTool workflow, drawing/layer workflow retained.
- **Original resolution remains the default**, not a claim that vector PDF/DXF/DWG possesses native pixels. For vector-only sources, the existing 300 DPI engineering default remains.
- User-selectable modes: original, HD, Full HD, QHD, 4K, custom maximum pixel bounding box, explicit 36–2400 DPI. Pixel-bounds modes preserve aspect ratio and portrait orientation; no stretching/cropping/upscaling-to-both-axes.
- Fast repeat preview: cache bitmap together with page-geometry for identical document/page/layer-state/viewport requests. 6 PNGs / 18MB cache budget retained, geometry cache limited to 8 keys. Same worker-thread document and existing debounced viewport/detail render preserved.
- Faster raster exports: larger full-width stripe clipping when within a per-render ~12MB RGB budget. Extremely wide pages revert to 512 px horizontal tiles. This avoids repeated PDF display-list traversal for every narrow column without introducing a maximum export pixel cap.
- Output atomic non-overwrite and cancellation maintained; PNG lossless encoding and JPEG quality 98 remain.

## Controlled benchmark (synthesized vector PDF, not a customer OnMap)

See `quality/EXPORT_STRIPE_BENCHMARK.json` and rerun `python -m quality.benchmark_export_stripes` from the project root. Same page, dimensions, compression and Python process; two trials each.

- 2,500 × 3,542 output pixels, 1,100 vector lines, Linux local Python engine.
- Legacy 512px horizontal tiled path: median **0.28223 seconds**, `page.get_pixmap()` **35** calls.
- Adaptive full-width stripe path: median **0.19766 seconds**, `page.get_pixmap()` **7** calls.
- Median wall-time improvement **1.43×** on this synthetic case, **80% fewer render calls**. This is **not** a guaranteed speedup for real large PDF/DXF/DWG, UI, image decoding, file-system I/O or batch export.
- Both images exactly 2,500×3,542. Against one-shot full-page raster reference, changed-pixel fraction: legacy **5.446%**, optimized **0.0446%**. Max per-channel error legacy **25**, optimized **2**. These figures reflect tile-edge rasterization antialiasing and are not proof of complete bitwise fidelity on arbitrary input.

## Regression and runtime scope

- 86 unit tests passed: baseline 77 + 9 new resolution/render/cache test cases.
- PNG/JPEG actual file sizes, metadata DPI, portrait orientation, custom bounds, batch resolution, layer state and immutable originals tested.
- Windows packaged onefile and Authenticode signature, on-screen PySide6 layout, and real 100MB+ customer CAD **NOT RUN** in current Linux environment; require Windows end-to-end verification.
- No PowerShell, `.venv`, app updates, notices or version labels added.
