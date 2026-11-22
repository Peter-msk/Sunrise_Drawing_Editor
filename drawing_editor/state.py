"""Lightweight GUI-side drawing state.

Large CAD/PDF files must not be fully parsed and retained for every row in the
file list. The actual parser lives in a bounded background catalog/renderer.
"""
from __future__ import annotations

from pathlib import Path

from .core import DrawingError, LayerInfo, source_signature


class DrawingState:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.kind = self.path.suffix.lower().lstrip('.')
        if self.kind not in {'pdf', 'dxf', 'dwg'} or not self.path.is_file():
            raise DrawingError(f'지원하지 않거나 찾을 수 없는 도면: {self.path}')
        self.source_signature = source_signature(self.path)
        self.page_index = 0
        self.pages = 1
        self.loaded = False
        self.catalog_error = None
        self._names: dict[int | str, str] = {}
        self._states: dict[int | str, bool] = {}
        self._original: dict[int | str, bool] = {}
        self._locked: set[int | str] = set()
        self._visible_count = 0
        self.pending_rule = None

    def load_metadata(self, layers: list[LayerInfo], pages: int):
        if self.loaded:
            return
        self.pages = pages
        self._names = {layer.key: layer.name for layer in layers}
        self._states = {layer.key: layer.visible for layer in layers}
        self._original = dict(self._states)
        self._locked = {layer.key for layer in layers if layer.locked}
        self._visible_count = sum(self._states.values())
        self.catalog_error = None
        self.loaded = True

    @property
    def dirty(self):
        return self._states != self._original

    def states(self):
        return dict(self._states)

    def layers(self):
        return [LayerInfo(key, self._names[key], state, key in self._locked)
                for key, state in self._states.items()]

    @property
    def layer_count(self):
        return len(self._states)

    @property
    def visible_count(self):
        return self._visible_count

    def matching_editable_keys(self, query):
        needle = str(query).strip().casefold()
        if not needle:
            return ()
        return tuple(key for key, name in self._names.items()
                     if key not in self._locked and needle in name.casefold())

    def _set_state(self, key, flag):
        flag = bool(flag)
        if self._states[key] == flag:
            return False
        self._states[key] = flag
        self._visible_count += 1 if flag else -1
        return True

    def apply_snapshot(self, states):
        for key, flag in states.items():
            if key in self._states and key not in self._locked:
                self._set_state(key, flag)

    def set_visibility(self, key, flag):
        if not self.loaded:
            raise DrawingError('도면 레이어를 읽는 중입니다.')
        if key not in self._states or key in self._locked:
            raise DrawingError('알 수 없거나 잠긴 레이어입니다.')
        return self._set_state(key, flag)

    def set_all(self, flag):
        changed = False
        for key in self._states:
            if key not in self._locked:
                changed = self._set_state(key, flag) or changed
        return changed

    def close(self):
        # Worker-owned PDF/DXF objects are never stored in a QWidget.
        pass
