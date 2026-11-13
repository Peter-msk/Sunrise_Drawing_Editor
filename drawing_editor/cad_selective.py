"""Lossless layer-selective ASCII DXF staging for very large, mostly hidden drawings.

This optimizer does NOT simplify coordinates, remove vertices, rasterize CAD, or
write to the original file. All selected modelspace entities are copied verbatim.
It omits BLOCKS definitions only when every selected entity is a stand-alone
primitive that cannot reference a block. Otherwise original BLOCKS are kept.

For render-only self-contained primitives, the staging path may also skip
unused OBJECTS metadata. Linked objects, blocks needing external resources,
XDATA and unsupported entities retain the original OBJECTS dictionaries.

The output is a temporary, syntactically valid DXF read by the authoritative
`ezdxf` frontend. The program retains full, non-selective `ezdxf.readfile()`
as a fallback for unsupported or nonstandard layouts.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import mmap
import re
import time
from typing import Iterable

from ezdxf.filemanagement import dxf_file_info

_ZERO = re.compile(rb'(?m)^  0\r?\n([A-Z][A-Z0-9_]*)\r?\n')
_SECTION = re.compile(rb'(?m)^  0\r?\nSECTION\r?\n  2\r?\n([A-Z]+)\r?\n')
_ENDSEC = re.compile(rb'(?m)^  0\r?\nENDSEC\r?\n')
# No indirect block references, dimensions, leaders, proxy entities or images.
# A list that includes anything else keeps the original BLOCKS section.
_BLOCK_INDEPENDENT = frozenset({
    b'LINE', b'LWPOLYLINE', b'CIRCLE', b'ARC', b'POINT', b'SOLID',
    b'TRACE', b'3DFACE',
})
_LINKED = frozenset({b'VERTEX', b'ATTRIB', b'SEQEND'})
_BLOCK_REF = re.compile(rb'(?m)^  2\r?\n([^\r\n]+)')
_BLOCK_DERIVED = frozenset({b'INSERT', b'ATTRIB', b'SEQEND'})
_OBJECT_INDIRECTIONS = (
    b'\r\n102\r\n', b'\r\n340\r\n',
    b'\r\n347\r\n', b'\r\n348\r\n',
    b'\r\n360\r\n', b'\r\n390\r\n',
)


# XDATA code 1001 registers an application name in the retained APPID table;
# code 1000 holds an inline string. These two codes alone do not depend on
# the OBJECTS section. Any other XDATA code is deliberately not optimized.
# DXF group codes and values occupy alternating CRLF-terminated lines.
# A raw search can falsely treat a handle VALUE such as "102" as group code 102.
# Only suspicious entities need this conservative, boundary-aware check.
_INDIRECT_CODES = frozenset({b'102', b'340', b'347', b'348', b'360', b'390'})
_XDATA_SCAN_LIMIT = 256 * 1024


def _needs_objects(source: mmap.mmap, start: int, end: int) -> bool:
    suspect = any(source.find(token, start, end) >= 0
                  for token in _OBJECT_INDIRECTIONS)
    xdata = source.find(b'\r\n1001\r\n', start, end) >= 0
    if not suspect and not xdata:
        return False
    # Avoid allocating a large buffer for nonstandard giant entities.
    # Retaining OBJECTS is a safe fallback, never a file-open failure.
    if end - start > _XDATA_SCAN_LIMIT:
        return True
    cursor = start
    in_xdata = False
    while cursor < end:
        code_end = source.find(b'\r\n', cursor, end)
        if code_end < 0:
            return True
        value_end = source.find(b'\r\n', code_end + 2, end)
        if value_end < 0:
            return True
        code = source[cursor:code_end]
        if code in _INDIRECT_CODES:
            return True
        if code == b'1001':
            in_xdata = True
        elif in_xdata and code != b'1000':
            return True
        cursor = value_end + 2
    return False


# Keep staged entity I/O bounded: contiguous entities can be written in one
# slice, but never copy an entire multi-hundred-MiB modelspace into RAM.
_ENTITY_WRITE_CHUNK = 4 * 1024 * 1024


def _write_selected_entities(destination, source: mmap.mmap, records, *, cancelled=None) -> None:
    """Write byte-exact selected spans in CAD order, merging adjacent spans.

    ``records`` is already sorted by source offset. The caller retains the
    original DXF bytes and all group-0 record boundaries; this is I/O batching,
    not geometry or DXF simplification.
    """
    begin = end = None
    for index, (start, stop, _, _) in enumerate(records):
        if index % 256 == 0 and cancelled and cancelled():
            raise SelectiveDXFCancelled()
        if begin is not None and start == end and stop - begin <= _ENTITY_WRITE_CHUNK:
            end = stop
            continue
        if begin is not None:
            destination.write(source[begin:end])
        begin, end = start, stop
    if begin is not None:
        destination.write(source[begin:end])


class SelectiveDXFUnsupported(ValueError):
    """Nonstandard source; caller must fall back to original DXF reader."""


class SelectiveDXFCancelled(Exception):
    """User cancelled staging; MUST NOT fall back to a full 400MiB parser."""


@dataclass(frozen=True)
class SelectedDXFStats:
    total_entities: int
    selected_entities: int
    staged_bytes: int
    blocks_pruned: bool
    elapsed_seconds: float
    objects_pruned: bool = False


class VisibleDXFSource:
    """Index entity byte ranges once; reuse for repeated layer toggle staging.

    Never retains an open mmap/file handle between renders, so the original is
    not locked indefinitely by the worker. The source file stat is verified on
    every staging request. Source mutation requires a fresh DrawingDocument.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        info = dxf_file_info(str(self.path))
        self.encoding = info.encoding
        self._signature = self._stat_signature()
        self._index: list[tuple[int, int, bytes, str]] | None = None
        # Small, ordered layer buckets: toggling only a few visible layers no
        # longer scans all 220k source records. Original mmap scanner retained
        # after the 8MiB chunking trial showed no repeatable field-file win.
        self._by_layer: dict[str, list[tuple[int, int, bytes, str]]] | None = None
        # The source is immutable for this index lifetime. Cache the distinct
        # INSERT block names for each layer after its FIRST selection, rather
        # than regex-scanning thousands of identical references on every toggle.
        # Never cache a partial result for an unrecognized INSERT.
        self._insert_blocks_by_layer: dict[str, frozenset[bytes] | None] = {}
        self._insert_layers: set[str] = set()
        self._unsafe_block_layers: set[str] = set()
        self._objects_safe_by_layer: dict[str, bool] = {}
        self._entity_start = 0
        self._entity_end = 0
        self._block_range: tuple[int, int] | None = None
        self._block_defs: dict[bytes, tuple[int, int]] | None = None
        self._objects_section: tuple[int, int] | None = None

    def _stat_signature(self) -> tuple[int, int]:
        stat = self.path.stat()
        return stat.st_size, stat.st_mtime_ns

    def _scan(self, source: mmap.mmap, cancelled=None) -> None:
        # ASCII DXF produced by AutoCAD uses CRLF and fixed-width, three-char
        # group codes. The C-level mmap.find() path avoids scanning 400MB
        # several times with large regular expressions. Different formatting
        # is unsupported *by this optimization*, not by the normal reader.
        section_start = b'  0\r\nSECTION\r\n  2\r\n'
        marker = section_start + b'ENTITIES\r\n'
        entry = source.find(marker)
        if entry < 0:
            raise SelectiveDXFUnsupported('Noncanonical ASCII DXF sections')
        self._entity_start = entry + len(marker)
        self._entity_end = source.find(b'  0\r\nENDSEC\r\n', self._entity_start)
        if self._entity_end < 0:
            raise SelectiveDXFUnsupported('Incomplete ENTITIES section')
        block_entry = source.find(section_start + b'BLOCKS\r\n', 0, entry)
        self._block_range = None
        if block_entry >= 0:
            block_start = block_entry + len(section_start + b'BLOCKS\r\n')
            block_end = source.find(b'  0\r\nENDSEC\r\n', block_start, entry)
            if block_end < 0:
                raise SelectiveDXFUnsupported('Incomplete BLOCKS section')
            self._block_range = (block_start, block_end)

        # OBJECTS is not geometry. For a strictly self-contained primitive-only
        # preview, its dictionaries can be omitted from the temporary staged
        # file. Retain it for inserts, text, annotations and indirect refs.
        obj_header = section_start + b'OBJECTS\r\n'
        obj_start = source.find(obj_header, self._entity_end)
        self._objects_section = None
        if obj_start >= 0:
            obj_end = source.find(b'  0\r\nENDSEC\r\n',
                                  obj_start + len(obj_header))
            if obj_end >= 0:
                obj_end += len(b'  0\r\nENDSEC\r\n')
                self._objects_section = (obj_start, obj_end)

        entities = []
        parent_layer = None
        layer_cache: dict[bytes, str] = {}
        start = self._entity_start
        # All record boundaries are exact group-0 lines. An entity is not
        # decoded or allocated here; only its byte range and layer are stored.
        while start < self._entity_end:
            if len(entities) % 2048 == 0 and cancelled and cancelled():
                raise SelectiveDXFCancelled()
            if source[start:start + 5] != b'  0\r\n':
                raise SelectiveDXFUnsupported('Nonstandard DXF entity boundary')
            # On the canonical CRLF path, a group-0 type token is short.
            # Read one bounded memory slice instead of a second mmap.find()
            # across every one of hundreds of thousands of entities. If a
            # nonstandard long token occurs, use the original safe parser.
            type_token = source[start + 5:start + 69]
            token_end = type_token.find(b'\r\n')
            if token_end < 0:
                raise SelectiveDXFUnsupported('Unrecognized entity type header')
            kind = type_token[:token_end]
            type_end = start + 5 + token_end
            next_tag = source.find(b'\n  0\r\n', type_end + 2, self._entity_end)
            end = (next_tag + 1) if next_tag >= 0 else self._entity_end
            if kind in _LINKED and parent_layer is not None:
                layer = parent_layer
            else:
                # The canonical group 8 is CRLF + three-character code + CRLF.
                # mmap.find() avoids regex objects for ~200K repeated lookups.
                # Search begins at type_end (the CRLF of the group-0 value).
                layer_tag = source.find(b'\n  8\r\n', type_end, end)
                if layer_tag < 0:
                    raw_layer = b'0'
                else:
                    name_start = layer_tag + len(b'\n  8\r\n')
                    name_end = source.find(b'\r\n', name_start, end)
                    if name_end < 0:
                        raise SelectiveDXFUnsupported('Truncated layer name')
                    raw_layer = source[name_start:name_end]
                layer = layer_cache.get(raw_layer)
                if layer is None:
                    try:
                        layer = raw_layer.decode(self.encoding, errors='strict').casefold()
                    except (UnicodeError, LookupError) as exc:
                        raise SelectiveDXFUnsupported('Unrecognized DXF layer encoding') from exc
                    layer_cache[raw_layer] = layer
            entities.append((start, end, kind, layer))
            if kind == b'POLYLINE':
                parent_layer = layer
            elif kind == b'INSERT':
                # ATTRIB/SEQEND may follow even when group 66 is omitted.
                # Keep their exact bytes with the parent INSERT and allow
                # ezdxf to resolve inherited layer/color semantics.
                parent_layer = layer
            elif kind == b'SEQEND':
                parent_layer = None
            elif kind not in _LINKED:
                parent_layer = None
            start = end
        if not entities:
            raise SelectiveDXFUnsupported('Empty ENTITIES section')
        self._index = entities
        buckets: dict[str, list[tuple[int, int, bytes, str]]] = {}
        for entry in entities:
            layer, kind = entry[3], entry[2]
            buckets.setdefault(layer, []).append(entry)
            if kind == b'INSERT':
                self._insert_layers.add(layer)
            elif kind not in _BLOCK_INDEPENDENT | _BLOCK_DERIVED:
                self._unsafe_block_layers.add(layer)
        self._by_layer = buckets

    def _scan_block_defs(self, source: mmap.mmap) -> None:
        """Index block byte ranges, including start and ENDBLK tags exactly."""
        if self._block_defs is not None:
            return
        result: dict[bytes, tuple[int, int]] = {}
        if self._block_range is None:
            raise SelectiveDXFUnsupported('No BLOCKS section')
        block_start, block_end = self._block_range
        cursor = block_start
        open_tag = b'  0\r\nBLOCK\r\n'
        close_tag = b'  0\r\nENDBLK\r\n'
        while cursor < block_end:
            if source[cursor:cursor + len(open_tag)] != open_tag:
                raise SelectiveDXFUnsupported('Unrecognized BLOCKS section payload')
            end_tag = source.find(close_tag, cursor + len(open_tag), block_end)
            if end_tag < 0:
                raise SelectiveDXFUnsupported('Block missing ENDBLK')
            next_block = source.find(open_tag, end_tag + len(close_tag), block_end)
            end = next_block if next_block >= 0 else block_end
            header_end = source.find(b'\n  0\r\n', cursor + len(open_tag), end_tag)
            header_end = (header_end + 1) if header_end >= 0 else end_tag
            name_match = _BLOCK_REF.search(source, cursor + len(open_tag), header_end)
            if name_match is None:
                raise SelectiveDXFUnsupported('Block missing name')
            name = name_match.group(1).lower()
            if name in result:
                raise SelectiveDXFUnsupported('Duplicate block name')
            result[name] = cursor, end
            cursor = end
        self._block_defs = result

    def _needed_blocks(self, source: mmap.mmap,
                       visible: set[str]) -> set[bytes] | None:
        """Resolve visible BLOCK dependencies without rescanning prior layers."""
        if self._block_range is None or self._unsafe_block_layers & visible:
            return None
        queue: list[bytes] = []
        # The layer buckets were indexed from one unchanged source file; only
        # whole-layer selections are supported by stage(). A second toggle
        # must not regex-decode the same 9,000 INSERT names again.
        for layer in self._insert_layers & visible:
            if layer not in self._insert_blocks_by_layer:
                names: set[bytes] = set()
                overflow = False
                for start, end, kind, _ in self._by_layer[layer]:
                    if kind != b'INSERT':
                        continue
                    match = _BLOCK_REF.search(source, start, end)
                    if match is None:
                        self._insert_blocks_by_layer[layer] = None
                        return None
                    names.add(match.group(1).lower())
                    if len(names) > 4096:
                        overflow = True
                        break
                if overflow:
                    # Memory guard: extremely diverse reference tables use
                    # the original direct path instead of growing a cache.
                    for start, end, kind, _ in self._by_layer[layer]:
                        if kind == b'INSERT':
                            hit = _BLOCK_REF.search(source, start, end)
                            if hit is None:
                                return None
                            queue.append(hit.group(1).lower())
                    continue
                self._insert_blocks_by_layer[layer] = frozenset(names)
            cached = self._insert_blocks_by_layer[layer]
            if cached is None:  # invalid INSERT: full BLOCKS fallback
                return None
            queue.extend(cached)
        if not queue:
            return set()
        self._scan_block_defs(source)
        blocks = self._block_defs or {}
        closure = set()
        while queue:
            name = queue.pop()
            if name in closure:
                continue
            span = blocks.get(name)
            if span is None:
                return None  # a missing block must not be silently discarded
            closure.add(name)
            block_start, block_end = span
            # Entities contained in needed blocks may include nested INSERTs.
            # If they use any unsupported type, retain ALL original blocks.
            cursor = block_start
            while cursor < block_end:
                if source[cursor:cursor + 5] != b'  0\r\n':
                    return None
                type_end = source.find(b'\r\n', cursor + 5, block_end)
                if type_end < 0:
                    return None
                kind = source[cursor + 5:type_end]
                next_tag = source.find(b'\n  0\r\n', type_end + 2, block_end)
                end = next_tag + 1 if next_tag >= 0 else block_end
                if kind == b'INSERT':
                    nested = _BLOCK_REF.search(source, type_end + 2, end)
                    if nested is None:
                        return None
                    queue.append(nested.group(1).lower())
                elif kind not in _BLOCK_INDEPENDENT | {b'BLOCK', b'ENDBLK', b'TEXT', b'MTEXT'}:
                    return None
                cursor = end
        return closure

    def _objects_independent_layer(self, source: mmap.mmap, layer: str) -> bool:
        """Cache only the conservative, immutable per-layer OBJECTS decision."""
        if layer not in self._objects_safe_by_layer:
            allowed = _BLOCK_INDEPENDENT | {b'INSERT'}
            self._objects_safe_by_layer[layer] = all(
                kind in allowed and not _needs_objects(source, start, end)
                for start, end, kind, _ in self._by_layer[layer]
            )
        return self._objects_safe_by_layer[layer]

    def _simple_local_blocks(self, source: mmap.mmap,
                             names: set[bytes]) -> bool:
        """Accept only plain local BLOCKs with self-contained 2D primitives.

        No nested INSERTs, ATTRIBs, text, XREFs or foreign object references.
        For everything else the complete OBJECTS section is retained.
        """
        blocks = self._block_defs or {}
        for name in names:
            span = blocks.get(name)
            if span is None:
                return False
            cursor, block_end = span
            while cursor < block_end:
                if source[cursor:cursor + 5] != b'  0\r\n':
                    return False
                end_type = source.find(b'\r\n', cursor + 5, block_end)
                if end_type < 0:
                    return False
                kind = source[cursor + 5:end_type]
                next_tag = source.find(b'\n  0\r\n', end_type + 2, block_end)
                end = next_tag + 1 if next_tag >= 0 else block_end
                if kind not in _BLOCK_INDEPENDENT | {b'BLOCK', b'ENDBLK'}:
                    return False
                if kind == b'BLOCK':
                    # A referenced XREF/overlay/anonymous block may depend on
                    # OBJECTS even though its visible contents are only lines.
                    header = source[cursor:end]
                    flag = re.search(rb'(?m)^ 70\r\n\s*([0-9]+)\r\n', header)
                    if flag is None or int(flag.group(1)) != 0:
                        return False
                if any(source.find(code, cursor, end) >= 0
                       for code in _OBJECT_INDIRECTIONS):
                    return False
                cursor = end
        return True

    def stage(self, destination: str | Path, visible_layers: Iterable[str],
              *, cancelled=None) -> SelectedDXFStats:
        started = time.perf_counter()
        if cancelled and cancelled():
            raise SelectiveDXFCancelled()
        if self._stat_signature() != self._signature:
            raise SelectiveDXFUnsupported('Source DXF changed after indexing')
        visible = {name.casefold() for name in visible_layers}

        with self.path.open('rb') as original:
            if original.read(22).startswith(b'AutoCAD Binary DXF'):
                raise SelectiveDXFUnsupported('Binary DXF requires original parser')
            original.seek(0)
            with mmap.mmap(original.fileno(), 0, access=mmap.ACCESS_READ) as contents:
                if self._index is None:
                    self._scan(contents, cancelled=cancelled)
                assert self._index is not None
                if self._by_layer is not None:
                    candidates = [entry for layer in visible
                                  for entry in self._by_layer.get(layer, ())]
                    if len(candidates) < len(self._index) // 3:
                        selected = sorted(candidates, key=lambda e: e[0])
                    else:
                        selected = [e for e in self._index if e[3] in visible]
                else:
                    selected = [e for e in self._index if e[3] in visible]
                if cancelled and cancelled():
                    raise SelectiveDXFCancelled()
                # If every selected entity is a simple self-contained primitive,
                # no instance can reference a block definition. Keeping the
                # BLOCK_RECORD/LAYER tables retains styles and entity attributes.
                block_selection = self._needed_blocks(contents, visible)
                strip_blocks = block_selection is not None
                # OBJECTS can be pruned only for entirely self-contained layers
                # and simple local blocks. The conservative decision is fixed
                # for this immutable DXF, so reuse it across layer toggles.
                strip_objects = bool(
                    self._objects_section is not None
                    and strip_blocks
                    and len(selected) <= 20000
                    and all(self._objects_independent_layer(contents, layer)
                            for layer in visible if layer in self._by_layer)
                    and (not block_selection
                         or self._simple_local_blocks(contents, block_selection))
                )
                with Path(destination).open('wb') as out:
                    if cancelled and cancelled():
                        raise SelectiveDXFCancelled()
                    if strip_blocks:
                        block_start, block_end = self._block_range
                        if not 0 < block_start < block_end < self._entity_start:
                            raise SelectiveDXFUnsupported('Unexpected BLOCKS section order')
                        out.write(contents[:block_start])
                        for name, (start, end) in sorted(
                            (item for item in self._block_defs.items()
                             if item[0] in block_selection),
                            key=lambda item: item[1][0]
                        ) if block_selection else ():
                            out.write(contents[start:end])
                        out.write(contents[block_end:self._entity_start])
                    else:
                        out.write(contents[:self._entity_start])
                    # Copy every original byte of every selected entity: no
                    # coordinate rounding, path simplifying or point omission.
                    if cancelled is None:
                        _write_selected_entities(out, contents, selected)
                    else:
                        _write_selected_entities(out, contents, selected, cancelled=cancelled)
                    if strip_objects:
                        obj_start, obj_end = self._objects_section
                        if obj_start < self._entity_end or obj_end > len(contents):
                            raise SelectiveDXFUnsupported('Unexpected OBJECTS section location')
                        out.write(contents[self._entity_end:obj_start])
                        out.write(contents[obj_end:])
                    else:
                        out.write(contents[self._entity_end:])
                    size = out.tell()
        if self._stat_signature() != self._signature:
            raise SelectiveDXFUnsupported('Source DXF changed while staging')
        return SelectedDXFStats(len(self._index), len(selected), size,
                                strip_blocks, time.perf_counter()-started,
                                strip_objects)
