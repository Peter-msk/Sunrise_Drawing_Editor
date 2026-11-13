"""Windows CMD handoff QA: large DXF -> OnMap PDF preview without source writes.

Usage:
  python quality\qa_dxf_onmap_handoff.py "D:\drawings\3구간 최종 철탑.dxf" "D:\drawings\B090온맵.pdf" --repeats 3 --report "D:\QA\handoff.json"

This is NOT a GUI test and does not claim a successful Onefile/SignTool run.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from drawing_editor.cad_catalog import read_ascii_dxf_layers
from drawing_editor.cad_worker import render_isolated, shutdown_all_workers
from drawing_editor.core import DrawingDocument, preview_snapshot


def sha256_file(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def preview_png(value) -> bool:
    return isinstance(value, bytes) and value.startswith(b"\x89PNG\r\n\x1a\n")


def process_rss_bytes():
    try:
        import psutil  # optional, never required by the program itself
        return psutil.Process().memory_info().rss
    except (ImportError, OSError):
        return None


def run(dxf_path: Path, pdf_path: Path, repeats: int) -> dict:
    if not dxf_path.is_file() or dxf_path.suffix.lower() != ".dxf":
        raise ValueError("First input must be a real DXF file")
    if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
        raise ValueError("Second input must be a real OnMap PDF")
    layers = read_ascii_dxf_layers(dxf_path)
    if not layers:
        raise ValueError("DXF has no quick layer catalog; do not run full 400MB fallback in QA")
    dx_states = {layer.key: layer.visible for layer in layers}
    with DrawingDocument(pdf_path) as pdf:
        pdf_states = pdf.states()
        pdf_layers = len(pdf.layers())
    originals = {str(p): sha256_file(p) for p in (dxf_path, pdf_path)}
    runs = []
    reference_sha = None
    status = "PASS"
    try:
        for number in range(1, repeats + 1):
            t0 = time.monotonic()
            dx_png, dx_geometry = render_isolated(
                "preview", str(dxf_path), dx_states, 0, (900, 700))
            dx_seconds = time.monotonic() - t0
            if not preview_png(dx_png):
                raise RuntimeError("DXF render returned an invalid PNG")
            # Emulate file-selection handoff: release large native worker,
            # including cached decoded CAD objects, before reading the PDF.
            shutdown_all_workers()
            t1 = time.monotonic()
            pdf_png, pdf_geometry = preview_snapshot(
                str(pdf_path), pdf_states, 0, (900, 700))
            pdf_seconds = time.monotonic() - t1
            if not preview_png(pdf_png):
                raise RuntimeError("OnMap render returned an invalid PNG")
            pdf_hash = hashlib.sha256(pdf_png).hexdigest()
            if reference_sha is None:
                reference_sha = pdf_hash
            if pdf_hash != reference_sha:
                status = "FAIL"
            runs.append({
                "cycle": number,
                "dxf_preview_seconds": round(dx_seconds, 4),
                "dxf_png_sha256": hashlib.sha256(dx_png).hexdigest(),
                "dxf_geometry": list(dx_geometry),
                "onmap_preview_seconds": round(pdf_seconds, 4),
                "onmap_png_sha256": pdf_hash,
                "onmap_geometry": list(pdf_geometry),
                "rss_bytes_optional_psutil": process_rss_bytes(),
            })
    finally:
        shutdown_all_workers()
    latest = {str(p): sha256_file(p) for p in (dxf_path, pdf_path)}
    if latest != originals:
        status = "FAIL"
    return {
        "date_utc": datetime.now(timezone.utc).isoformat(),
        "status_engine_only": status,
        "source": "real-local-DXF-and-PDF",
        "dxf_size_bytes": dxf_path.stat().st_size,
        "dxf_layer_count": len(layers),
        "onmap_layer_count": pdf_layers,
        "runs": runs,
        "source_sha256_before": originals,
        "source_sha256_after": latest,
        "input_files_unchanged": latest == originals,
        "gui_qa": "NOT RUN",
        "windows_onefile_signing": "NOT RUN",
        "notes": "GUI click/drag and forced native cancellation require separate Windows manual QA",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dxf", type=Path)
    parser.add_argument("onmap_pdf", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 1 <= args.repeats <= 20:
        parser.error("--repeats must be from 1 to 20")
    try:
        result = run(args.dxf.resolve(), args.onmap_pdf.resolve(), args.repeats)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
        print("QA", result["status_engine_only"], "report:", args.report)
        return 0 if result["status_engine_only"] == "PASS" else 1
    except Exception as exc:
        print("QA FAILED:", type(exc).__name__, str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
