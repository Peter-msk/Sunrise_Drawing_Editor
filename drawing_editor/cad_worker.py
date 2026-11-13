"""Isolated, cancellable CAD preview process (one worker per preview thread).

Only DXF previews above the source-size threshold use this path. The native
ThreePass rendering implementation remains in drawing_editor.core; it runs in
the CHILD process with its own ezdxf / MuPDF state. No fitz.Document crosses IPC.

Communication uses request/response files under a private TemporaryDirectory.
This also works with PyInstaller --onefile --windowed, where stdio is unreliable.
The child is reused for repeated layer toggles / pans and killed on cancellation.
"""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

DXF_PROCESS_THRESHOLD = 64 * 1024 * 1024
RENDER_TIMEOUT_SECONDS = 180.0
WORKER_IDLE_SECONDS = 120.0
MAX_RESULT_BYTES = 96 * 1024 * 1024
_POLL_SECONDS = 0.06
_SESSIONS: set["_CADSession"] = set()
_SESSIONS_LOCK = threading.RLock()
_THREAD = threading.local()


def should_isolate_cad(path: str | Path, *, threshold: int = DXF_PROCESS_THRESHOLD) -> bool:
    """Never parse or touch the CAD content just to choose the execution path."""
    source = Path(path)
    try:
        return source.suffix.casefold() == ".dxf" and source.stat().st_size >= threshold
    except OSError:
        return False


def _worker_command(folder: Path) -> tuple[list[str], dict]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    if getattr(sys, "frozen", False):
        # PyInstaller onefile child shares the parent's unpacked resources and
        # must exit before the parent. Do NOT set RESET_ENVIRONMENT here.
        command = [sys.executable, "--cad-worker", str(folder)]
        return command, {"creationflags": flags}
    # Working directory is fixed to the checked-in project root; Windows
    # users can start RUN.cmd from any directory.
    return ([sys.executable, "-m", "drawing_editor.cad_worker", str(folder)],
            {"creationflags": flags, "cwd": str(Path(__file__).resolve().parents[1])})


class _CADSession:
    def __init__(self):
        self._temp = tempfile.TemporaryDirectory(prefix="sunrise-cad-preview-")
        self.folder = Path(self._temp.name)
        self.seq = 0
        self.closed = False
        cmd, kwargs = _worker_command(self.folder)
        try:
            self.proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, close_fds=True, **kwargs)
        except BaseException:
            self._temp.cleanup()
            raise
        with _SESSIONS_LOCK:
            _SESSIONS.add(self)

    def close(self):
        if self.closed:
            return
        self.closed = True
        proc = self.proc
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=0.8)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                    proc.wait(timeout=0.8)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        with _SESSIONS_LOCK:
            _SESSIONS.discard(self)
        try:
            self._temp.cleanup()
        except OSError:
            # A failed system-level termination must never freeze the Qt close
            # path. The OS will reclaim the worker's private temporary files.
            pass

    def render(self, mode, source, states, page_index, preview_size, clip, cancelled):
        from .core import DrawingError, RenderCancelled
        if self.closed:
            raise DrawingError("CAD 렌더 프로세스가 종료되었습니다.")
        if cancelled is not None and cancelled():
            self.close()
            raise RenderCancelled("미리보기 중단됨")
        if self.proc.poll() is not None:
            self.close()
            raise DrawingError("CAD 렌더 프로세스가 비정상 종료되었습니다.")
        self.seq += 1
        key = f"{self.seq:09d}"
        request_path = self.folder / f"request-{key}.json"
        response_path = self.folder / f"response-{key}.json"
        image_path = self.folder / f"image-{key}.png"
        pending_path = self.folder / f".request-{key}.tmp"
        payload = {
            "id": key, "mode": mode, "path": str(source),
            "states": dict(states), "page": int(page_index),
            "size": list(preview_size),
            "clip": list(clip) if clip is not None else None,
        }
        try:
            pending_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(pending_path, request_path)
            deadline = time.monotonic() + RENDER_TIMEOUT_SECONDS
            while True:
                if cancelled is not None and cancelled():
                    self.close()
                    raise RenderCancelled("미리보기 중단됨")
                if response_path.is_file():
                    response = json.loads(response_path.read_text(encoding="utf-8"))
                    if not response.get("ok"):
                        raise DrawingError("CAD 렌더 프로세스 오류: " + str(response.get("error", "unknown")))
                    length = image_path.stat().st_size
                    if not 0 < length <= MAX_RESULT_BYTES:
                        raise DrawingError("CAD 미리보기 크기가 안전 제한을 초과했습니다.")
                    data = image_path.read_bytes()
                    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                        raise DrawingError("CAD 렌더 프로세스에서 올바른 PNG를 받지 못했습니다.")
                    if mode == "preview":
                        geometry = response.get("geometry")
                        if not (isinstance(geometry, list) and len(geometry) == 2
                                and all(isinstance(v, (float, int)) and v > 0 for v in geometry)):
                            raise DrawingError("CAD 페이지 크기 응답이 유효하지 않습니다.")
                        return data, (float(geometry[0]), float(geometry[1]))
                    return data
                if self.proc.poll() is not None:
                    self.close()
                    raise DrawingError("CAD 렌더 하위 프로세스가 응답 없이 종료되었습니다.")
                if time.monotonic() >= deadline:
                    self.close()
                    raise DrawingError("CAD 미리보기 시간 제한을 초과했습니다. 작업을 중단했습니다.")
                time.sleep(_POLL_SECONDS)
        finally:
            for path in (pending_path, request_path, response_path, image_path):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


def render_isolated(mode: str, source: str, states: dict, page_index: int,
                    preview_size: tuple[int, int], *, clip=None, cancelled=None):
    """Call from the SINGLE preview QRunnable worker, never from the GUI thread."""
    if mode not in ("preview", "detail"):
        raise ValueError("Only CAD preview/detail may run in a child process")
    from .core import RenderCancelled
    if cancelled is not None and cancelled():
        raise RenderCancelled("미리보기 중단됨")
    session = getattr(_THREAD, "session", None)
    if session is None or session.closed or session.proc.poll() is not None:
        if session is not None:
            session.close()
        session = _CADSession()
        _THREAD.session = session
    try:
        return session.render(mode, source, states, page_index, preview_size, clip, cancelled)
    except BaseException:
        if session.closed:
            _THREAD.session = None
        raise


def shutdown_all_workers():
    """Called on graceful Qt close and before user-approved emergency exit."""
    with _SESSIONS_LOCK:
        pending = tuple(_SESSIONS)
    for session in pending:
        session.close()


atexit.register(shutdown_all_workers)


def worker_main(argv=None) -> int:
    """Internal entrypoint: python -m ... <private-dir> or frozen --cad-worker."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1:
        return 2
    root = Path(argv[0])
    if not root.is_dir():
        return 2
    # Only this subprocess opens the native CAD objects. A child crash cannot
    # poison the Qt process or block the next onmap PDF selection.
    from .core import preview_snapshot, render_snapshot
    activity = time.monotonic()
    while time.monotonic() - activity < WORKER_IDLE_SECONDS:
        requests = sorted(root.glob("request-*.json"))
        if not requests:
            time.sleep(_POLL_SECONDS)
            continue
        for request_path in requests:
            activity = time.monotonic()
            started = activity
            key = request_path.stem.removeprefix("request-")
            result_path = root / f"response-{key}.json"
            image_path = root / f"image-{key}.png"
            temp_response = root / f".response-{key}.tmp"
            try:
                req = json.loads(request_path.read_text(encoding="utf-8"))
                if req["id"] != key:
                    raise ValueError("Mismatched worker request ID")
                size = req["size"]
                if (not isinstance(size, list) or len(size) != 2
                        or not all(type(v) is int and 1 <= v <= 4000 for v in size)):
                    raise ValueError("Invalid raster dimensions")
                if req["mode"] == "preview":
                    pixels, geometry = preview_snapshot(
                        req["path"], req["states"], int(req["page"]), tuple(size))
                elif req["mode"] == "detail":
                    clip = req["clip"]
                    if not (isinstance(clip, list) and len(clip) == 4):
                        raise ValueError("Invalid CAD clip")
                    pixels = render_snapshot(req["path"], req["states"],
                                             int(req["page"]), tuple(size), clip=tuple(clip))
                    geometry = None
                else:
                    raise ValueError("Unsupported CAD worker mode")
                if not 0 < len(pixels) <= MAX_RESULT_BYTES:
                    raise ValueError("Invalid CAD PNG size")
                image_path.write_bytes(pixels)
                answer = {"ok": True, "geometry": geometry,
                          "elapsed_ms": round((time.monotonic() - started) * 1000)}
            except Exception as exc:
                try:
                    image_path.unlink(missing_ok=True)
                except OSError:
                    pass
                answer = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:500]}"}
            try:
                temp_response.write_text(json.dumps(answer, ensure_ascii=False), encoding="utf-8")
                os.replace(temp_response, result_path)
            except OSError:
                return 3
            finally:
                try:
                    request_path.unlink(missing_ok=True)
                except OSError:
                    pass
    return 0


if __name__ == "__main__":
    raise SystemExit(worker_main())
