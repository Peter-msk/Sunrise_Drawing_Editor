"""Packaged original drafting icons for the application."""
from pathlib import Path


def icon_file(name: str, base: Path) -> str:
    path = base / f'icon_{name}.svg'
    if not path.is_file():
        raise FileNotFoundError(f'Icon asset missing: {path}')
    return str(path)
