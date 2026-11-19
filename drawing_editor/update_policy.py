"""Product-local post-start Onefile cleanup."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import time

HEX = re.compile(r'[0-9a-f]{64}')
STAGE = re.compile(r'\.sunrise-update-[a-z0-9_]{8}')


def _digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def cleanup_after_start(target, stage, old_sha, new_sha, *, timeout=120):
    """Remove only this transaction's verified backup and temporary EXE.

    Called after the replacement GUI enters its event loop. Keep rollback if
    the helper is still locked or any identity/digest check fails.
    """
    if not (HEX.fullmatch(old_sha) and HEX.fullmatch(new_sha) and old_sha != new_sha):
        return False
    try:
        target, stage = Path(target).resolve(strict=True), Path(stage)
        if (target.name.casefold() not in ('sunrise drawing editor.exe', 'sunrise.drawing.editor.exe')
                or stage.resolve(strict=True) != stage or stage.parent != target.parent
                or not STAGE.fullmatch(stage.name) or not stage.is_dir()):
            return False
        backup, candidate = stage / 'rollback.exe', stage / 'candidate.exe'
        for item, expected in ((target, new_sha), (backup, old_sha), (candidate, new_sha)):
            if item.resolve(strict=True) != item or not item.is_file() or _digest(item) != expected:
                return False
        if set(stage.iterdir()) != {backup, candidate}:
            return False
    except (OSError, ValueError):
        return False
    deadline = time.monotonic() + timeout
    while True:
        try:
            # Delete helper first: its PyInstaller bootloader may still hold it.
            if _digest(target) != new_sha or _digest(backup) != old_sha:
                return False
            if candidate.exists():
                if _digest(candidate) != new_sha:
                    return False
                candidate.unlink()
            backup.unlink()
            stage.rmdir()
            return True
        except OSError:
            if not backup.exists() or time.monotonic() >= deadline:
                return False
            time.sleep(.5)
