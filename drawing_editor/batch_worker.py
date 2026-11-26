"""Isolated one-process batch export: keep Qt event loop and PDF previews responsive.

The child owns all MuPDF raster work and Pillow/zlib output while the main
process only reads small JSON progress snapshots. One child handles the whole
batch sequentially; the user's drawings never cross the process boundary.
No extra executable, Qt dependency, GitHub workflow or virtualenv is needed.
"""
from __future__ import annotations

from dataclasses import asdict
import gc
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .batch import BatchResult, ExportJob, checked_output_parent, confirmed_output
from .core import DrawingError, OutputOptions, close_thread_document


_POLL_SECONDS = 0.10
_CANCEL_GRACE_SECONDS = 12.0


def _atomic_json(path: Path, payload: dict) -> None:
    pending = path.with_name("." + path.name + ".tmp")
    pending.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(pending, path)


def _command(folder: Path) -> tuple[list[str], dict]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    from .runtime_packaging import nuitka_worker_command
    candidate = nuitka_worker_command("--batch-worker", folder, flags)
    if candidate is not None:
        return candidate
    if getattr(sys, "frozen", False):
        # Same onefile EXE: main.py routes --batch-worker before creating Qt.
        return [sys.executable, "--batch-worker", str(folder)], {"creationflags": flags}
    return ([sys.executable, "-m", "drawing_editor.batch_worker", str(folder)],
            {"creationflags": flags, "cwd": str(Path(__file__).resolve().parents[1])})


def _cancelled_result(folder: Path, jobs, *, cancelled=True, worker_error="") -> BatchResult:
    """Recover only atomic per-job acknowledgements, never infer from existence."""
    completed, errors = [], []
    for index, job in enumerate(jobs):
        try:
            with (folder / f"receipt-{index}.json").open("rb") as stream:
                data = stream.read(65537)
            if len(data) > 65536:
                continue
            receipt = json.loads(data.decode("utf-8"))
            if not isinstance(receipt, dict):
                continue
            if (set(receipt) == {"completed"} and receipt["completed"] == job.target
                    and confirmed_output(job.target)):
                completed.append(job.target)
            elif set(receipt) == {"error"} and isinstance(receipt["error"], str):
                errors.append((job.target, receipt["error"][:2000]))
        except (OSError, ValueError, TypeError, RecursionError):
            continue
    return BatchResult(tuple(completed), tuple(errors), cancelled, worker_error)


def run_batch_exports_isolated(jobs, options, *, progress=None, cancelled=None):
    """Run exactly one sequential batch in an independently scheduled process.

    The user can switch drawings and themes while rasterization is in flight.
    If the child fails, report the failure instead of silently falling back to
    GUI-process MuPDF calls. Existing per-file export safety stays in batch.py.
    """
    jobs = tuple(jobs)
    options = options.checked()
    if cancelled is not None and cancelled():
        return BatchResult((), (), True)
    with tempfile.TemporaryDirectory(prefix="sunrise-export-") as folder_name:
        folder = Path(folder_name)
        _atomic_json(folder / "request.json", {
            "options": asdict(options),
            "jobs": [{"source": job.source, "states": job.states,
                      "page_index": job.page_index, "target": job.target,
                      "source_signature": job.source_signature}
                     for job in jobs],
        })
        command, settings = _command(folder)
        try:
            process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, **settings)
        except OSError as exc:
            raise DrawingError(f"도면 출력 하위 프로세스를 시작할 수 없습니다: {exc}") from exc
        last_progress = None
        cancel_since = None
        worker_error = ""
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
                        worker_error = "일괄 추출 하위 프로세스 오류: " + str(response.get("error", "unknown"))
                        break
                    payload = response["result"]
                    return BatchResult(tuple(payload["completed"]),
                                       tuple(tuple(row) for row in payload["errors"]),
                                       bool(payload["cancelled"]))
                exit_code = process.poll()
                if exit_code is not None:
                    # A child can publish result.json and exit between the first
                    # existence test and poll(). Re-read the authoritative result.
                    if response_file.is_file():
                        continue
                    worker_error = f"도면 출력 하위 프로세스가 완료 응답 없이 종료되었습니다. (종료 코드: {exit_code})"
                    break
                if (cancel_since is not None
                        and time.monotonic() - cancel_since > _CANCEL_GRACE_SECONDS):
                    # Reap the child before reading committed job receipts.
                    break
                time.sleep(_POLL_SECONDS)
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
            # A forced kill bypasses the child's Python finally. The exported
            # file itself remains atomic, but temporary PNG/JPG/raw fragments
            # may remain. Only delete paths tagged with this exact child PID.
            # Other sessions and user-created output are never touched.
            for target in {Path(job.target).parent: job.target for job in jobs}.values():
                try:
                    parent = checked_output_parent(target)
                except (DrawingError, OSError, ValueError, RuntimeError):
                    continue
                for pattern in (f".drawing-{process.pid}-*",
                                f".drawing-rgb-{process.pid}-*"):
                    try:
                        for partial in parent.glob(pattern):
                            try:
                                partial.unlink(missing_ok=True)
                            except OSError:
                                pass
                    except OSError:
                        pass

        result = _cancelled_result(folder, jobs, cancelled=cancel_since is not None,
                                   worker_error=worker_error)
        if worker_error and not (result.completed or result.errors):
            raise DrawingError(worker_error)
        return result


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
        def unique(pairs):
            value = dict(pairs)
            if len(value) != len(pairs):
                raise ValueError("Duplicate batch request JSON key")
            return value
        request = json.loads((folder / "request.json").read_text(encoding="utf-8"),
                             object_pairs_hook=unique)
        options = OutputOptions(**request["options"]).checked()
        jobs = []
        for item in request["jobs"]:
            # JSON object keys are strings. PDF OCG state keys are integer
            # xrefs; without restoring their type, every visibility snapshot
            # silently falls back to the source PDF's original layer state.
            states = item["states"]
            if Path(item["source"]).suffix.casefold() == ".pdf":
                decoded = {int(key): value for key, value in states.items()}
                if len(decoded) != len(states):
                    raise ValueError("Duplicate PDF layer key")
                states = decoded
            jobs.append(ExportJob(item["source"], states,
                                  item["page_index"], item["target"],
                                  tuple(item["source_signature"]) if item.get("source_signature") is not None else None))
        cancel_flag = folder / "cancel.flag"
        last_update = float('-inf')

        def report(index, total, fraction, name):
            nonlocal last_update
            now = time.monotonic()
            # A fast batch may complete many files before the GUI's next poll.
            # The final result is authoritative; progress is only telemetry.
            if index < total and now - last_update < 0.15:
                return
            last_update = now
            try:
                _atomic_json(folder / "progress.json", {
                    "index": index, "total": total,
                    "fraction": fraction, "name": name})
            except OSError:
                # Windows reader/antivirus may temporarily lock this file.
                # Failure to report progress must not abort a valid export.
                pass

        def acknowledge(index, completed, error):
            # Each small receipt is atomically published after the job returns.
            # A sharing violation must not invalidate an already saved output;
            # in that case only the final result can confirm that job.
            payload = ({"completed": completed} if completed is not None
                       else {"error": str(error)[:2000]})
            try:
                _atomic_json(folder / f"receipt-{index}.json", payload)
            except OSError:
                pass

            # ezdxf owns cyclic document/entity graphs. Release a retired CAD
            # source before opening the next one, but preserve same-source
            # raster reuse. Vector exports create independent graphs per job.
            # Collect only in this isolated worker, after the receipt is
            # published, never on the GUI/preview thread.
            job = jobs[index]
            if Path(job.source).suffix.casefold() in ('.dxf', '.dwg'):
                following = jobs[index + 1] if index + 1 < len(jobs) else None
                if (options.fmt not in ('png', 'jpg') or following is None
                        or (following.source, following.source_signature)
                        != (job.source, job.source_signature)):
                    close_thread_document()
                    gc.collect()

        result = run_batch_exports(
            jobs, options, progress=report, cancelled=cancel_flag.exists,
            outcome=acknowledge)
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
