"""Isolated one-process batch export: keep Qt event loop and PDF previews responsive.

The child owns all MuPDF raster work and Pillow/zlib output while the main
process only reads small JSON progress snapshots. One child handles the whole
batch sequentially; the user's drawings never cross the process boundary.
No extra executable, Qt dependency, GitHub workflow or virtualenv is needed.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .batch import BatchResult, ExportJob
from .core import DrawingError, OutputOptions


_POLL_SECONDS = 0.10
_CANCEL_GRACE_SECONDS = 12.0


def _atomic_json(path: Path, payload: dict) -> None:
    pending = path.with_name("." + path.name + ".tmp")
    pending.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(pending, path)


def _command(folder: Path) -> tuple[list[str], dict]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    if getattr(sys, "frozen", False):
        # Same onefile EXE: main.py routes --batch-worker before creating Qt.
        return [sys.executable, "--batch-worker", str(folder)], {"creationflags": flags}
    return ([sys.executable, "-m", "drawing_editor.batch_worker", str(folder)],
            {"creationflags": flags, "cwd": str(Path(__file__).resolve().parents[1])})


def run_batch_exports_isolated(jobs, options, *, progress=None, cancelled=None):
    """Run exactly one sequential batch in an independently scheduled process.

    The user can switch drawings and themes while rasterization is in flight.
    If the child fails, report the failure instead of silently falling back to
    GUI-process MuPDF calls. Existing per-file export safety stays in batch.py.
    """
    options = options.checked()
    with tempfile.TemporaryDirectory(prefix="sunrise-export-") as folder_name:
        folder = Path(folder_name)
        _atomic_json(folder / "request.json", {
            "options": asdict(options),
            "jobs": [{"source": job.source, "states": job.states,
                      "page_index": job.page_index, "target": job.target}
                     for job in jobs],
        })
        command, settings = _command(folder)
        try:
            process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, **settings)
        except OSError as exc:
            raise DrawingError(f"이미지 추출 하위 프로세스를 시작할 수 없습니다: {exc}") from exc
        last_progress = None
        cancel_since = None
        try:
            while True:
                if cancelled is not None and cancelled() and cancel_since is None:
                    (folder / "cancel.flag").touch()
                    cancel_since = time.monotonic()
                progress_file = folder / "progress.json"
                if progress is not None and progress_file.is_file():
                    try:
                        update = json.loads(progress_file.read_text(encoding="utf-8"))
                        version = (update["index"], update["total"],
                                   update["fraction"], update["name"])
                        if version != last_progress:
                            progress(*version)
                            last_progress = version
                    except (OSError, ValueError, KeyError, TypeError):
                        # The next atomic snapshot or final result is authoritative.
                        pass
                response_file = folder / "result.json"
                if response_file.is_file():
                    response = json.loads(response_file.read_text(encoding="utf-8"))
                    if not response.get("ok"):
                        raise DrawingError("일괄 추출 하위 프로세스 오류: "
                                           + str(response.get("error", "unknown")))
                    payload = response["result"]
                    return BatchResult(tuple(payload["completed"]),
                                       tuple(tuple(row) for row in payload["errors"]),
                                       bool(payload["cancelled"]))
                if process.poll() is not None:
                    raise DrawingError("이미지 추출 하위 프로세스가 완료 응답 없이 종료되었습니다.")
                if (cancel_since is not None
                        and time.monotonic() - cancel_since > _CANCEL_GRACE_SECONDS):
                    raise InterruptedError("이미지 추출 취소됨: 하위 프로세스 강제 종료")
                time.sleep(_POLL_SECONDS)
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)


def worker_main(argv=None) -> int:
    """Private worker entrypoint. It must not initialize QApplication."""
    from .batch import run_batch_exports
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        return 2
    folder = Path(argv[0])
    if not folder.is_dir():
        return 2
    output = folder / "result.json"
    try:
        request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
        options = OutputOptions(**request["options"]).checked()
        jobs = []
        for item in request["jobs"]:
            # JSON object keys are strings. PDF OCG state keys are integer
            # xrefs; without restoring their type, every visibility snapshot
            # silently falls back to the source PDF's original layer state.
            states = item["states"]
            if Path(item["source"]).suffix.casefold() == ".pdf":
                states = {int(key): bool(value) for key, value in states.items()}
            jobs.append(ExportJob(item["source"], states,
                                  int(item["page_index"]), item["target"]))
        cancel_flag = folder / "cancel.flag"
        last_update = [0.0]

        def report(index, total, fraction, name):
            now = time.monotonic()
            if fraction == 0.0 or fraction >= 1.0 or now - last_update[0] > 0.15:
                last_update[0] = now
                _atomic_json(folder / "progress.json", {
                    "index": index, "total": total,
                    "fraction": fraction, "name": name})

        result = run_batch_exports(
            jobs, options, progress=report, cancelled=cancel_flag.exists)
        payload = {"ok": True, "result": {
            "completed": list(result.completed),
            "errors": [list(row) for row in result.errors],
            "cancelled": result.cancelled}}
        _atomic_json(output, payload)
        return 0
    except Exception as exc:
        try:
            _atomic_json(output, {"ok": False, "error":
                                  f"{type(exc).__name__}: {str(exc)[:600]}"})
        except OSError:
            pass
        return 3


if __name__ == "__main__":
    raise SystemExit(worker_main())
