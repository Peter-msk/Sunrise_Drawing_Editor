"""Pure UI action scopes for testable, predictable desktop workflows.

The helpers are independent of Qt and do not access original drawing files.
"""
from __future__ import annotations


def matching_editable_layers(layers, query: str) -> tuple:
    """Resolve only matched, unlocked layer keys; empty query means no filter action."""
    needle = str(query).strip().casefold()
    if not needle:
        return ()
    return tuple(layer.key for layer in layers
                 if not layer.locked and needle in layer.name.casefold())


def file_add_status(*, added: int, duplicates: int, rejected: int) -> str:
    """Explain skipped duplicates and invalid files rather than silently ignoring them."""
    parts = [f'추가 {added}개']
    if duplicates:
        parts.append(f'중복 건너뜀 {duplicates}개')
    if rejected:
        parts.append(f'추가 실패 {rejected}개')
    return ' · '.join(parts) + (' · 원본 분석은 백그라운드 진행' if added else '')
