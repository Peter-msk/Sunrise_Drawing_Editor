"""Packaged, scale-independent drafting icons with theme-aware contrast."""
from pathlib import Path


def icon_file(name: str, base: Path, theme: str | None = None) -> str:
    variant = base / f'icon_{name}_{theme}.svg' if theme in ('light', 'dark') else None
    path = variant if variant is not None and variant.is_file() else base / f'icon_{name}.svg'
    if not path.is_file():
        raise FileNotFoundError(f'Icon asset missing: {path}')
    return str(path)
