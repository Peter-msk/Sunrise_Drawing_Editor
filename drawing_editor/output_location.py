"""Resolve the actual completed export directory, never the editable UI field."""
from pathlib import Path


def completed_folder(paths, *, errors=(), cancelled=False):
    if cancelled or errors or not paths:
        return None
    folder = None
    try:
        for value in paths:
            path = Path(value)
            if not path.is_absolute() or not path.is_file():
                return None
            parent = path.parent.resolve(strict=True)
            if not parent.is_dir() or (folder is not None and parent != folder):
                return None
            folder = parent
    except (OSError, ValueError, TypeError, RuntimeError):
        return None
    return folder
