"""Field benchmark for repeated clipped views of one DXF/PDF state.

Run unchanged ThreePass sources and this candidate separately with the same
input and --layer, then compare JSON timings and per-clip SHA256 hashes.
No edits to source CAD files, no Qt GUI dependency.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import time

from drawing_editor.core import DrawingDocument, OutputOptions


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(8 * 1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def run(path: Path, layer: str | None, loops: int) -> dict:
    before = sha256_file(path)
    result = {"input_size": path.stat().st_size, "layer": layer, "loops": loops}
    with DrawingDocument(path) as document:
        if layer:
            choices = [item for item in document.layers()
                       if item.name.casefold() == layer.casefold()]
            if len(choices) != 1:
                raise ValueError(f"Layer name must match exactly one layer: {layer}")
            document.set_visibility(choices[0].key, True)
        t0 = time.perf_counter()
        first = document.render_bytes(OutputOptions("png"), preview=(1000, 700))
        result["initial_preview_seconds"] = round(time.perf_counter() - t0, 6)
        result["initial_sha256"] = hashlib.sha256(first).hexdigest()
        width, height = document.page_size()
        proportions = [
            (.02, .02, .40, .42),
            (.14, .10, .58, .52),
            (.28, .22, .76, .70),
            (.40, .32, .88, .85),
        ]
        clips = [(width*a, height*b, width*c, height*d)
                 for a, b, c, d in proportions]
        result["clipped_previews"] = []
        for repeat in range(loops):
            for index, clip in enumerate(clips):
                start = time.perf_counter()
                png = document.render_bytes(OutputOptions("png"),
                                            preview=(1000, 700), clip=clip)
                elapsed = time.perf_counter() - start
                result["clipped_previews"].append({
                    "repeat": repeat, "clip": index,
                    "seconds": round(elapsed, 6),
                    "sha256": hashlib.sha256(png).hexdigest(),
                    "bytes": len(png),
                })
    after = sha256_file(path)
    result["source_sha256"] = after
    result["source_unchanged"] = before == after
    if before != after:
        raise RuntimeError("The source DXF changed unexpectedly")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--layer", default=None)
    parser.add_argument("--loops", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("CAD_VIEW_BENCHMARK.json"))
    args = parser.parse_args()
    if args.loops < 1 or args.loops > 10:
        parser.error("--loops must be 1..10")
    report = run(args.input, args.layer, args.loops)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "initial": report["initial_preview_seconds"],
        "views": len(report["clipped_previews"]),
        "max_seconds": max(v["seconds"] for v in report["clipped_previews"]),
        "source_unchanged": report["source_unchanged"]
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
