"""Product-local post-start Onefile cleanup."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import time

HEX = re.compile(r'[0-9a-f]{64}')
STAGE = re.compile(r'\.sunrise-update-[a-z0-9_]{8}')
STARTUP_PENDING = 'startup.pending'


def _digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _transaction(target, stage, old_sha, new_sha):
    if not (HEX.fullmatch(old_sha) and HEX.fullmatch(new_sha) and old_sha != new_sha):
        raise ValueError('Invalid transaction digest')
    target, stage = Path(target).resolve(strict=True), Path(stage)
    if (target.name.casefold() not in ('sunrise drawing editor.exe', 'sunrise.drawing.editor.exe')
            or stage.resolve(strict=True) != stage or stage.parent != target.parent
            or not STAGE.fullmatch(stage.name) or not stage.is_dir()):
        raise ValueError('Invalid transaction path')
    backup, candidate = stage / 'rollback.exe', stage / 'candidate.exe'
    for item, expected in ((target, new_sha), (backup, old_sha)):
        if item.resolve(strict=True) != item or not item.is_file() or _digest(item) != expected:
            raise ValueError('Invalid transaction digest')
    if candidate.exists() and (candidate.resolve(strict=True) != candidate or
                               not candidate.is_file() or _digest(candidate) != new_sha):
        raise ValueError('Invalid helper digest')
    return target, stage, backup, candidate


def acknowledge_start(target, stage, old_sha, new_sha):
    """Acknowledge only a verified transaction after GUI event-loop entry.

    R03 helpers did not create a marker; those transactions remain compatible.
    """
    try:
        _, stage, backup, candidate = _transaction(target, stage, old_sha, new_sha)
        pending = stage / STARTUP_PENDING
        entries = set(stage.iterdir())
        if not pending.exists():
            return entries in ({backup, candidate}, {backup})
        if (entries != {backup, candidate, pending} or pending.resolve(strict=True) != pending
                or not pending.is_file() or pending.stat().st_size != 64
                or pending.read_text(encoding='ascii') != new_sha):
            return False
        pending.unlink()
        return True
    except (OSError, ValueError):
        return False


def cleanup_after_start(target, stage, old_sha, new_sha, *, timeout=120):
    """Remove verified helper first, then backup, without touching other files.

    Accept a missing helper after partial cleanup; never delete a pending
    startup marker or any unknown file. Retry Windows file locks.
    """
    try:
        target, stage, backup, candidate = _transaction(target, stage, old_sha, new_sha)
        if set(stage.iterdir()) not in ({backup, candidate}, {backup}):
            return False
    except (OSError, ValueError):
        return False
    deadline = time.monotonic() + timeout
    while True:
        try:
            if _digest(target) != new_sha or _digest(backup) != old_sha:
                return False
            if candidate.exists():
                if _digest(candidate) != new_sha:
                    return False
                candidate.unlink()
            if set(stage.iterdir()) != {backup}:
                return False
            backup.unlink()
            stage.rmdir()
            return True
        except OSError:
            if not backup.exists() or time.monotonic() >= deadline:
                return False
            time.sleep(.5)
