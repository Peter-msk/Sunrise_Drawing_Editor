"""Conservative screen-space pruning for large, simple CAD drawings.

Only coordinate-safe primitives are indexed. INSERT, HATCH, TEXT, splines,
XREFs and unsupported / transformed objects are *always* drawn; omitting them
based on an approximate bounding box can irreversibly corrupt a preview.
The grid is optional and bounded; a failed/over-budget index means full render.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

GRID = 32
MAX_INDEX_ENTITIES = 350_000
MAX_CELL_VISITS = 48


def _default_ocs(entity: Any) -> bool:
    try:
        direction = entity.dxf.get('extrusion', (0, 0, 1))
        return (abs(direction[0]) < 1e-10 and abs(direction[1]) < 1e-10
                and abs(direction[2] - 1) < 1e-10)
    except (TypeError, ValueError, IndexError):
        return False


def _cheap_box(entity: Any) -> tuple[float, float, float, float] | None:
    """Conservative 2D world bounds; None means *never cull* this entity."""
    try:
        kind = entity.dxftype()
        if kind == 'LINE':
            start, end = entity.dxf.start, entity.dxf.end
            result = (min(start.x, end.x), min(start.y, end.y),
                      max(start.x, end.x), max(start.y, end.y))
        elif kind in {'CIRCLE', 'ARC'} and _default_ocs(entity):
            p, r = entity.dxf.center, float(entity.dxf.radius)
            if r < 0:
                return None
            # Full circle bounds deliberately enclose the whole arc.
            result = (p.x - r, p.y - r, p.x + r, p.y + r)
        elif kind == 'LWPOLYLINE' and _default_ocs(entity):
            # Bulges and widths can extend far beyond vertices: never cull them.
            if entity.has_arc or entity.has_width:
                return None
            vertices = list(entity.get_points('xy'))
            if not vertices:
                return None
            xs, ys = zip(*vertices)
            result = (min(xs), min(ys), max(xs), max(ys))
        else:
            return None
        if not all(math.isfinite(value) for value in result):
            return None
        return result
    except (AttributeError, TypeError, ValueError, IndexError, OverflowError):
        return None


class CADGridIndex:
    """Bounded fixed grid and conservative draw filter.

    Indexing has no effect on source entities, renderer order or layer flags.
    Unknown objects remain in the renderer regardless of the search window.
    """

    def __init__(self, entities: Any, bounds: tuple[float, float, float, float]):
        x0, y0, x1, y1 = bounds
        if not all(map(math.isfinite, bounds)) or x1 <= x0 or y1 <= y0:
            raise ValueError('Invalid fixed CAD render box')
        if len(entities) > MAX_INDEX_ENTITIES:
            raise ValueError('Model exceeds safe spatial index budget')
        self.bounds = bounds
        self._indexed: set[str] = set()
        self._cells: dict[tuple[int, int], list[str]] = defaultdict(list)
        self.total = len(entities)
        self.prunable = 0
        for entity in entities:
            handle = entity.dxf.get('handle')
            if not isinstance(handle, str) or not handle:
                continue
            box = _cheap_box(entity)
            if box is None:
                continue
            # Oversized objects are left unindexed and always drawn.
            coords = self._cells_for(box)
            if not coords or len(coords) > MAX_CELL_VISITS:
                # Outside known page bounds or too broad: always render.
                continue
            for cell in coords:
                self._cells[cell].append(handle)
            self._indexed.add(handle)
            self.prunable += 1

    def _cells_for(self, box: tuple[float, float, float, float]) -> list[tuple[int, int]]:
        x0, y0, x1, y1 = self.bounds
        ax, ay, bx, by = box
        if bx < x0 or ax > x1 or by < y0 or ay > y1:
            return []
        grid = GRID
        c0 = max(0, min(grid - 1, int((max(ax, x0) - x0) / (x1 - x0) * grid)))
        c1 = max(0, min(grid - 1, int((min(bx, x1) - x0) / (x1 - x0) * grid)))
        r0 = max(0, min(grid - 1, int((max(ay, y0) - y0) / (y1 - y0) * grid)))
        r1 = max(0, min(grid - 1, int((min(by, y1) - y0) / (y1 - y0) * grid)))
        return [(i, j) for i in range(c0, c1 + 1) for j in range(r0, r1 + 1)]

    def visible_handles(self, region: tuple[float, float, float, float]) -> set[str]:
        return {handle for cell in self._cells_for(region)
                for handle in self._cells.get(cell, ())}

    def accept(self, entity: Any, visible_handles: set[str]) -> bool:
        handle = entity.dxf.get('handle')
        return handle not in self._indexed or handle in visible_handles
