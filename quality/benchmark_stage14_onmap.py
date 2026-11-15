"""Field benchmark for real OnMap OCG PDFs and optional Windows startup time.

Does not mutate source PDF, run GitHub Actions or produce screenshots.
Actual timing is local machine data: never infer from synthetic test passes.
"""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import time
from datetime import datetime, timezone

from drawing_editor.core import DrawingDocument, preview_snapshot
from drawing_editor.cad_worker import render_isolated, shutdown_all_workers

SIZE = (1000, 750)

def sample(path: Path):
    stamp_before = (path.stat().st_size, path.stat().st_mtime_ns)
    with DrawingDocument(path) as doc:
        if not doc.layers():
            return {"file": path.name, "status": "NO_OCG_LAYERS"}
        keys = [layer.key for layer in doc.layers() if not layer.locked]
        if not keys:
            return {"file": path.name, "status": "ALL_LAYERS_LOCKED"}
        base = doc.states()
    key = keys[0]
    changed = dict(base)
    changed[key] = not changed[key]
    frames = []
    for label, states in (("initial",base),("one_layer_toggled",changed),
                          ("restore",base)):
        start = time.perf_counter()
        image,geometry = render_isolated('preview',str(path),states,0,SIZE)
        elapsed = time.perf_counter()-start
        frames.append({"state":label,"seconds":round(elapsed,4),
                       "sha256":hashlib.sha256(image).hexdigest(),
                       "size":len(image),"page_size":geometry})
    mismatch = (frames[0]["sha256"] != frames[2]["sha256"]
                or frames[0]["sha256"] == frames[1]["sha256"])
    stamp_after = (path.stat().st_size, path.stat().st_mtime_ns)
    return {"file":path.name, "status":"FAIL_PIXEL_PARITY" if mismatch
            else "PASS_REPEAT_STATE_PIXEL_PARITY",
            "source_stat_unchanged":stamp_before==stamp_after,
            "ocg_layers":len(base), "render_ms":frames}

def bench_exe(exe: Path, runs=3):
    records=[]
    for _ in range(runs):
        start=time.perf_counter()
        try:
            r=subprocess.run([str(exe.resolve()),'--self-test'],
                             stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,timeout=120)
            records.append({"seconds":round(time.perf_counter()-start,4),
                            "returncode":r.returncode})
        except (OSError,subprocess.TimeoutExpired) as exc:
            records.append({"error":str(exc)})
    measurements=[r["seconds"] for r in records if r.get("returncode")==0]
    return {"runs":records,"median_seconds":round(statistics.median(measurements),4)
            if measurements else None}

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pdf',type=Path,action='append',default=[])
    ap.add_argument('--pdf-dir',type=Path)
    ap.add_argument('--exe',type=Path)
    ap.add_argument('--report',type=Path,default=Path('quality/P0_runtime/STAGE14_FIELD_BENCHMARK.json'))
    args=ap.parse_args(argv)
    sources=list(args.pdf)
    if args.pdf_dir:
        sources.extend(sorted(args.pdf_dir.glob('*.pdf'))[:15])
    if not sources and not args.exe:
        ap.error('Provide --pdf, --pdf-dir or --exe')
    report={"generated_at_utc":datetime.now(timezone.utc).isoformat(),
            "source":"Stage14 field run — real source files, not synthetic proof",
            "records":[],"windows_startup":None,
            "limits":["No GUI event loop FPS or OS unresponsive diagnosis",
                      "Requires comparison with prior Stage13 timings",
                      "No pixel parity proof for unsupported OCG/non-OCG cases"]}
    try:
        for path in sources[:15]:
            if not path.is_file() or path.suffix.casefold()!='.pdf':
                report["records"].append({"file":path.name,"status":"INVALID_SOURCE"})
            else:
                try:
                    report["records"].append(sample(path))
                except Exception as exc:
                    report["records"].append({"file":path.name,"status":"ERROR",
                                              "error":f'{type(exc).__name__}: {str(exc)[:300]}'})
        if args.exe:
            report["windows_startup"]=bench_exe(args.exe)
    finally:
        shutdown_all_workers()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('STAGE14_FIELD_REPORT',args.report)
    source_ok = all(v["status"].startswith("PASS") or
                    v["status"] in ("NO_OCG_LAYERS","ALL_LAYERS_LOCKED")
                    for v in report["records"])
    startup_ok = (not args.exe or all(
        record.get("returncode") == 0
        for record in report["windows_startup"]["runs"]))
    return 0 if source_ok and startup_ok else 1

if __name__=="__main__":
    raise SystemExit(main())
