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


def zoom_factor_for_delta(angle_delta: int, pixel_delta: int = 0) -> float:
    """Continuous pointer zoom; fractional wheel steps are not discarded."""
    steps = angle_delta / 120 if angle_delta else pixel_delta / 240
    steps = max(-6.0, min(6.0, steps))
    return 1.12 ** steps


def clamp_zoom_factor(current_scale: float, fit_scale: float, requested: float) -> float:
    """Limit zoom in fit-relative units without truncating the gesture abruptly.

    The lower bound of 5% keeps navigation usable; the upper bound permits
    inspection of tiny linework. Both are independent of original PDF units.
    """
    if current_scale <= 0 or fit_scale <= 0 or requested <= 0:
        return 1.0
    lower, upper = fit_scale * 0.05, fit_scale * 128.0
    # If fitInView or a previous desktop size left the view outside the new
    # bounds, do not snap abruptly across the entire zoom range on one tick.
    if current_scale >= upper:
        # Resizing the window can move an already zoomed view beyond the new
        # limit. Allow smooth inward motion, never snap back in one wheel tick.
        return 1.0 if requested > 1 else requested
    if current_scale <= lower:
        return 1.0 if requested < 1 else requested
    target = max(lower, min(upper, current_scale * requested))
    return target / current_scale


def preview_raster_size(logical_width: int, logical_height: int, dpr: float) -> tuple[int, int]:
    """Build the overview at screen-pixel density, within the existing RAM caps.

    A logical-pixel overview followed immediately by a HiDPI detail render
    wasted a second full native rasterization at 125-175% Windows scaling.
    """
    from math import ceil, isfinite
    density = max(1.0, min(4.0, dpr)) if isfinite(dpr) else 1.0
    return (max(240, min(1600, ceil(max(1, logical_width - 10) * density))),
            max(240, min(1300, ceil(max(1, logical_height - 10) * density))))


def detail_tile_covers(visible: tuple[float, float, float, float] | None,
                       tile: tuple[float, float, float, float] | None,
                       tile_density: float, requested_density: float) -> bool:
    """Skip a native raster pass when an existing overscan tile is sufficient.

    Work in page coordinates. Avoid accepting a low-resolution tile after zoom.
    """
    if visible is None or tile is None or tile_density <= 0 or requested_density <= 0:
        return False
    x0, y0, x1, y1 = visible
    a0, b0, a1, b1 = tile
    epsilon = 0.01  # floating-point viewport conversion tolerance in PDF points
    return (a0 <= x0 + epsilon and b0 <= y0 + epsilon and
            a1 + epsilon >= x1 and b1 + epsilon >= y1 and
            tile_density * 1.01 >= requested_density)


def catalog_result_is_current(seq: int, actual_path: str | None,
                              expected_path: str | None,
                              latest: dict[str, int],
                              documents: dict) -> bool:
    """Reject late responses for removed/replaced file registrations.

    A pathname alone cannot identify a registration: the user can remove a file
    and add the same path while an earlier catalog job remains in flight.
    """
    return (bool(actual_path) and actual_path == expected_path
            and latest.get(actual_path) == seq and actual_path in documents)
