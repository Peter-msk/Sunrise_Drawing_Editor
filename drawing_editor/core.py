"""Layer-aware PDF/CAD viewing and native-size raster export; original file is read-only."""
from __future__ import annotations

from dataclasses import dataclass
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
import os
import tempfile
import threading
from typing import Callable
from typing import Any

import ezdxf
import fitz
from ezdxf.addons.drawing import Frontend, RenderContext, layout as cad_layout, pymupdf, recorder as cad_recorder
from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy
from PIL import Image
from .tiles import save_png_tiled, save_jpg_tiled
from .cad_spatial import CADGridIndex


class DrawingError(Exception):
    """User-visible document, render or save error."""


# Large images use disk-backed tiles rather than a fixed megapixel cap.
VECTOR_EXPORT_DPI = 300  # Vector input has no native raster pixel resolution.
# Guard the in-memory display-list cache: it is useful for repeated layer toggles
# but can double memory for huge drawings, so large/complex inputs use the original
# on-demand renderer instead. This is not a file-size limit for opening/exporting.
CAD_REPLAY_SOURCE_LIMIT = 160 * 1024 * 1024
CAD_REPLAY_ENTITY_LIMIT = 45_000
CAD_REPLAY_RECORD_LIMIT = 55_000
# A single CAD-to-OCG PDF is created only for bounded models. This is a memory
# optimization, not a maximum input file size; large CAD uses the old renderer.
CAD_OCG_PDF_LIMIT = 64 * 1024 * 1024


class _RecordingBudgetExceeded(Exception):
    """The optional reusable CAD display list would use excessive memory."""


class _BoundedRecorder(cad_recorder.Recorder):
    def store(self, record, properties):
        if len(self.records) >= CAD_REPLAY_RECORD_LIMIT:
            raise _RecordingBudgetExceeded()
        return super().store(record, properties)



@dataclass(frozen=True)
class LayerInfo:
    key: int | str
    name: str
    visible: bool
    locked: bool = False


# Display size choices are maximum bounding rectangles. The drawing's aspect
# ratio and portrait orientation are preserved, never stretched or cropped.
EXPORT_PRESETS = {
    "hd": (1280, 720), "fhd": (1920, 1080),
    "qhd": (2560, 1440), "uhd": (3840, 2160),
}


@dataclass(frozen=True)
class OutputOptions:
    fmt: str = "png"
    resolution: str = "original"  # original | hd | fhd | qhd | uhd | custom | dpi
    width: int | None = None   # max pixel width, custom mode
    height: int | None = None  # max pixel height, custom mode
    dpi: int | None = None     # explicitly requested rasterizing DPI

    def checked(self) -> "OutputOptions":
        if self.fmt not in {"png", "jpg"}:
            raise DrawingError("지원하는 출력 형식은 PNG 또는 JPG입니다.")
        if self.resolution not in {"original", "custom", "dpi", *EXPORT_PRESETS}:
            raise DrawingError("지원하지 않는 이미지 해상도 설정입니다.")
        if self.resolution == "custom":
            if (type(self.width) is not int or type(self.height) is not int
                    or not 1 <= self.width <= 2_147_483_647
                    or not 1 <= self.height <= 2_147_483_647):
                raise DrawingError("사용자 지정 가로·세로 픽셀 수는 양의 정수여야 합니다.")
        if self.resolution == "dpi":
            if type(self.dpi) is not int or not 36 <= self.dpi <= 2400:
                raise DrawingError("사용자 지정 DPI는 36~2400이어야 합니다.")
        return self


def _export_pixel_dimensions(page: fitz.Page, options: OutputOptions) -> tuple[int, int, int]:
    """Resolve full-page dimensions; do not affect viewport/preview rendering."""
    options.checked()
    if options.resolution == "original":
        return _pixel_dimensions(page)
    rect = page.rect
    if rect.is_empty or rect.width <= 0 or rect.height <= 0:
        raise DrawingError("유효한 도면 페이지 영역이 없습니다.")
    if options.resolution == "dpi":
        dpi = int(options.dpi)
        return (max(1, round(rect.width * dpi / 72)),
                max(1, round(rect.height * dpi / 72)), dpi)
    if options.resolution == "custom":
        maxw, maxh = options.width, options.height
    else:
        maxw, maxh = EXPORT_PRESETS[options.resolution]
        if rect.height > rect.width:
            maxw, maxh = maxh, maxw
    scale = min(maxw / rect.width, maxh / rect.height)
    width = min(maxw, max(1, round(rect.width * scale)))
    height = min(maxh, max(1, round(rect.height * scale)))
    return width, height, max(1, round(scale * 72))


def _image_to_bytes(image: Image.Image, fmt: str, dpi: int) -> bytes:
    destination = BytesIO()
    if fmt == "png":
        image.save(destination, format="PNG", dpi=(dpi, dpi))
    else:
        image.convert("RGB").save(destination, format="JPEG", dpi=(dpi, dpi),
                                  quality=98, subsampling=0)
    return destination.getvalue()


def _pixel_dimensions(page: fitz.Page, *, preview: tuple[int, int] | None = None) -> tuple[int, int, int]:
    """PDF bitmap: native effective source image PPI; vector-only: explicit 300 DPI.

    Image pixels are not invented for the PDF: the native resolution of a dominant
    embedded raster is used. Mixed/vector-only pages need rasterization, so 300 DPI
    is a documented engineering default rather than a claim of intrinsic resolution.
    """
    bounds = page.rect
    if bounds.is_empty or bounds.width <= 0 or bounds.height <= 0:
        raise DrawingError("유효한 도면 페이지 영역이 없습니다.")
    if preview is not None:
        width_limit, height_limit = preview
        scale = min(max(1, width_limit) / bounds.width,
                    max(1, height_limit) / bounds.height)
        return max(1, round(bounds.width * scale)), max(1, round(bounds.height * scale)), 96

    # Dominant embedded bitmap(s) determine pixel dimensions; small logos and
    # symbols do not make a full drawing blow up to their high effective PPI.
    scale = None
    try:
        info = page.get_image_info()
    except (ValueError, RuntimeError) as exc:
        raise DrawingError(f"내장 이미지 해상도를 확인할 수 없습니다: {exc}") from exc
    for image in info:
        box = fitz.Rect(image["bbox"]) & bounds
        if box.width <= 0 or box.height <= 0:
            continue
        if (box.width * box.height < bounds.width * bounds.height * 0.015
                and image["width"] * image["height"] < 1_000_000):
            continue
        if image["width"] < 64 or image["height"] < 64:
            continue
        effective = max(image["width"] / box.width, image["height"] / box.height)
        if scale is None or effective > scale:
            scale = effective

    if scale is None:
        scale = VECTOR_EXPORT_DPI / 72
    width, height = max(1, round(bounds.width * scale)), max(1, round(bounds.height * scale))
    return width, height, max(1, round(scale * 72))


def _render_page(page: fitz.Page, fmt: str, preview: tuple[int,int] | None,
                 clip: tuple[float,float,float,float] | None = None,
                 display_list: fitz.DisplayList | None = None) -> bytes:
    bounds = page.rect
    if clip is None:
        width, height, dpi = _pixel_dimensions(page, preview=preview)
        target = bounds
    else:
        x0,y0,x1,y1 = clip  # page-local rectangle
        target = fitz.Rect(bounds.x0+x0, bounds.y0+y0,
                           bounds.x0+x1, bounds.y0+y1) & bounds
        if target.is_empty or target.width <= 0 or target.height <= 0:
            raise DrawingError('확대 영역이 비어 있습니다.')
        width,height = preview or (800,600)
        dpi = 96
    # Width / height are the output pixel contract, even for PDFs with
    # fractional MediaBox dimensions or a rotated CropBox. A single uniform
    # scale can round down one axis, making tiled and direct exports disagree.
    # Preserve the independently rounded axes; this differs by under one
    # pixel over the full page and prevents missing edge rows/columns.
    matrix = fitz.Matrix(width / target.width, height / target.height)
    if display_list is None:
        pix = page.get_pixmap(matrix=matrix, clip=target,
                              colorspace=fitz.csRGB, alpha=False, annots=True)
    else:
        # DisplayList is generated with annots=True and reused within the
        # same document/OCG state for zoom/pan requests. It is invalidated on
        # any layer change, and never retained for temporary PDF documents.
        pix = display_list.get_pixmap(matrix=matrix, clip=target,
                                       colorspace=fitz.csRGB, alpha=False)
    if fmt == 'png':
        return pix.tobytes(output='png')
    return _image_to_bytes(Image.frombytes('RGB', (pix.width,pix.height), pix.samples),fmt,dpi)


class DrawingDocument:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.kind = self.path.suffix.lower().lstrip(".")
        if self.kind not in ("pdf", "dxf", "dwg"):
            raise DrawingError(f"지원하지 않는 도면 형식: {self.path.suffix}")
        if not self.path.is_file():
            raise DrawingError(f"도면 파일을 찾지 못했습니다: {self.path}")
        self._pdf: fitz.Document | None = None
        self._cad: Any = None
        self._states: dict[int | str, bool] = {}
        self._original: dict[int | str, bool] = {}
        self._names: dict[int | str, str] = {}
        self._locked: set[int | str] = set()
        self._pdf_ui_map: dict[int, int] = {}
        self._serialize_fallback = False
        self._cad_pdf_cache: OrderedDict[tuple, bytes] = OrderedDict()
        self._cad_pdf_cache_bytes = 0
        self._cad_render_count = 0
        self._cad_base_rect: tuple[float, float] | None = None
        self._cad_recorder: _BoundedRecorder | None = None
        self._cad_render_box: Any = None
        self._cad_recording_attempted = False
        self._cad_layered_attempted = False
        self._cad_layered_pdf: fitz.Document | None = None
        self._cad_layer_ui: dict[str, int] = {}
        self._cad_layer_bounds: dict[str, tuple[float, float, float, float]] = {}
        # Stored only for large CAD that must use the safe full renderer.
        # The index operates on modelspace and never alters CAD source geometry.
        self._large_cad_page: dict[tuple, tuple[tuple[float, float, float, float], tuple[float, float]]] = {}
        self._cad_spatial_index: CADGridIndex | None = None
        self._cad_spatial_key: tuple | None = None
        self._cad_spatial_runs = 0
        self._preview_cache: OrderedDict[tuple, bytes] = OrderedDict()
        self._preview_cache_bytes = 0
        self._preview_geometry_cache: OrderedDict[tuple, tuple[float, float]] = OrderedDict()
        # One native DisplayList per worker. No stack of unlimited page/OCG
        # lists: a layer transition or page switch discards the previous list.
        self._preview_display_list: fitz.DisplayList | None = None
        self._preview_display_key: tuple | None = None
        self.page_index = 0
        try:
            if self.kind == "pdf":
                self._read_pdf()
            else:
                self._read_cad()
            self._original = self.states()
        except Exception as exc:
            self.close()
            if isinstance(exc, DrawingError):
                raise
            raise DrawingError(f"도면 열기 실패 ({self.path.name}): {exc}") from exc

    def _read_pdf(self):
        self._pdf = fitz.open(str(self.path))
        if not self._pdf.is_pdf or self._pdf.needs_pass or self._pdf.page_count < 1:
            raise DrawingError("읽을 수 없는 PDF이거나 암호로 보호되어 있습니다.")
        raw = self._pdf.get_ocgs() or {}
        self._states = {int(key): bool(value.get("on", True)) for key, value in raw.items()}
        self._names = {int(key): str(value.get("name") or f"레이어 {key}") for key, value in raw.items()}
        if raw:
            self._locked = set(self._pdf.get_layer().get("locked", []) or [])
        # The live UI OCG switches invalidate the rendering display list without
        # serializing/reopening the source PDF. Use this path only when unambiguous.
        configs = self._pdf.layer_ui_configs() if raw else []
        for key, name in self._names.items():
            matches = [x for x in configs if x["text"] == name and x["type"] == "checkbox"]
            if len(matches) == 1 and sum(v == name for v in self._names.values()) == 1:
                self._pdf_ui_map[key] = matches[0]["number"]
        self._serialize_fallback = bool(raw and len(self._pdf_ui_map) != len(raw))

    def _read_cad(self):
        if self.kind == "dxf":
            self._cad = ezdxf.readfile(str(self.path))
        else:
            from ezdxf.addons import odafc
            if odafc.is_installed():
                self._cad = odafc.readfile(str(self.path))
            else:
                # Optional LibreCAD CLI fallback; not bundled into our EXE.
                # Only enabled when the actual converter is discoverable.
                from .dwg_fallback import ConverterError, read_dwg_with_librecad
                try:
                    self._cad = read_dwg_with_librecad(self.path)
                except ConverterError as exc:
                    raise DrawingError(f'DWG 읽기 실패: {exc}') from exc
        for layer in self._cad.layers:
            name = str(layer.dxf.name)
            self._states[name] = not (layer.is_off() or layer.is_frozen())
            self._names[name] = name

    @property
    def pages(self):
        return self._pdf.page_count if self._pdf is not None else 1

    @property
    def dirty(self):
        return self._states != self._original

    def states(self) -> dict[int | str, bool]:
        return dict(self._states)

    def layers(self) -> list[LayerInfo]:
        return [LayerInfo(key, self._names[key], value, key in self._locked)
                for key, value in self._states.items()]

    def set_visibility(self, key: int | str, visible: bool) -> bool:
        if key not in self._states:
            raise DrawingError(f"알 수 없는 레이어: {key}")
        if key in self._locked:
            raise DrawingError(f"잠긴 레이어는 변경할 수 없습니다: {self._names[key]}")
        if self._states[key] == bool(visible):
            return False
        previous = self.states()
        self._states[key] = bool(visible)
        try:
            self._apply_changes(previous)
        except Exception:
            self._states = previous
            raise
        return True

    def set_all(self, visible: bool) -> bool:
        previous = self.states()
        for key in self._states:
            if key not in self._locked:
                self._states[key] = bool(visible)
        if self._states == previous:
            return False
        try:
            self._apply_changes(previous)
        except Exception:
            self._states = previous
            raise
        return True

    def apply_snapshot(self, states: dict[int | str, bool]):
        """Batch state changes: one apply for a snapshot, never per-layer parsing."""
        previous = self.states()
        for key, value in states.items():
            if key in self._states and key not in self._locked:
                self._states[key] = bool(value)
        if previous != self._states:
            try:
                self._apply_changes(previous)
            except Exception:
                self._states = previous
                raise

    def _apply_changes(self, previous: dict[int | str, bool]):
        # OCG toggles alter the drawing commands. Native lists compiled for an
        # earlier visibility state must never survive this transition.
        self._preview_display_list = None
        self._preview_display_key = None
        if self._pdf is not None:
            if not self._serialize_fallback:
                for key, value in self._states.items():
                    if previous.get(key) != value:
                        self._pdf.set_layer_ui_config(
                            self._pdf_ui_map[key], action=0 if value else 2)
            else:
                # Fallback only for OCGs missing from /Order or ambiguous names.
                self._pdf.set_layer(-1,
                                    on=[key for key, yes in self._states.items() if yes],
                                    off=[key for key, yes in self._states.items() if not yes],
                                    basestate="OFF")
        else:
            for key, value in self._states.items():
                if previous.get(key) == value:
                    continue
                layer = self._cad.layers.get(key)
                if layer is not None:
                    if value:
                        layer.on()
                        layer.thaw()
                    else:
                        layer.off()
            # The optional PDF-with-OCG uses native instant visibility switches;
            # never mutate the input file or serialize its PDF on each toggle.
            if self._cad_layered_pdf is not None:
                for name, value in self._states.items():
                    if previous.get(name) == value:
                        continue
                    control = self._cad_layer_ui.get(name.casefold())
                    if control is not None:
                        self._cad_layered_pdf.set_layer_ui_config(
                            control, action=0 if value else 2)
            # Old drawings remain cached within a strict memory budget.

    def _build_cad_recording(self) -> None:
        """Decode eligible CAD entities once, retaining original redraw order.

        The ezdxf recording stores the actual drawing primitives including
        nested INSERT/block output, so a layer switch filters the recording
        without reparsing all CAD geometry. Oversized models use the old path.
        """
        if self._cad_recording_attempted:
            return
        self._cad_recording_attempted = True
        if (self.path.stat().st_size > CAD_REPLAY_SOURCE_LIMIT
                or len(self._cad.modelspace()) > CAD_REPLAY_ENTITY_LIMIT):
            return
        # RenderContext snapshots visibility when constructed. Capture ALL
        # editable layers for future ON transitions, then restore exact CAD
        # in-memory flags. Source file is never written.
        saved_layer_attrs = {layer.dxf.name: (layer.dxf.flags, layer.dxf.color)
                             for layer in self._cad.layers}
        built = None
        try:
            for layer in self._cad.layers:
                layer.on()
                layer.thaw()
            built = _BoundedRecorder()
            configuration = Configuration(background_policy=BackgroundPolicy.OFF,
                                          color_policy=ColorPolicy.COLOR)
            Frontend(RenderContext(self._cad), built, config=configuration).draw_layout(
                self._cad.modelspace())
            if built.records:
                self._cad_render_box = built.player().bbox()
                self._cad_recorder = built
        except _RecordingBudgetExceeded:
            # Fully abandon this optional optimization; not an input error.
            self._cad_recorder = None
            self._cad_render_box = None
        finally:
            for layer in self._cad.layers:
                layer.dxf.flags, layer.dxf.color = saved_layer_attrs[layer.dxf.name]

    def _build_cad_layered_pdf(self) -> None:
        """Create a single internal OCG PDF for cheap CAD layer visibility switches.

        This uses ezdxf's supported output_layers backend, so the actual CAD
        draw order, block expansion, fills and fonts are still handled by the
        existing renderer. The PDF is private to this thread's document and is
        never persisted beside the original drawing. Unsupported/large models
        retain the prior recording renderer without changed semantics.
        """
        if self._cad_layered_attempted:
            return
        self._cad_layered_attempted = True
        self._build_cad_recording()
        if self._cad_recorder is None or self._cad_render_box is None:
            return
        # Validate that the layer names are unambiguous under DXF's casefold
        # semantics. Layer 0 and empty layers need not produce a PDF OCG.
        if len({name.casefold() for name in self._states}) != len(self._states):
            return
        # One bounded pass yields a per-layer bounding-box index. It detects
        # layers that define the page boundary; toggling them needs the legacy
        # auto-fit layout rather than the fixed-size OCG page.
        try:
            bounds: dict[str, tuple[float, float, float, float]] = {}
            for record, properties in self._cad_recorder.player().recordings():
                box = record.bbox()
                if not box.has_data:
                    continue
                key = properties.layer.casefold()
                val = (box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y)
                old = bounds.get(key)
                bounds[key] = val if old is None else (
                    min(old[0], val[0]), min(old[1], val[1]),
                    max(old[2], val[2]), max(old[3], val[3]))
            self._cad_layer_bounds = bounds
        except (TypeError, ValueError, RuntimeError):
            # Unknown geometry must not be incorrectly omitted/cropped.
            self._cad_layer_bounds = {}
            return
        backend = pymupdf.PyMuPdfBackend()
        try:
            self._cad_recorder.player().replay(backend)
            blob = backend.get_pdf_bytes(
                cad_layout.Page(0, 0),
                settings=cad_layout.Settings(output_layers=True),
                render_box=self._cad_render_box,
            )
            if not blob or len(blob) > CAD_OCG_PDF_LIMIT:
                return
            self._cad_render_count += 1  # One CAD-to-PDF generation for all states.
            candidate = fitz.open(stream=blob, filetype="pdf")
            try:
                layers = candidate.layer_ui_configs()
                by_name: dict[str, int] = {}
                for item in layers:
                    if item["type"] != "checkbox":
                        continue
                    key = item["text"].casefold()
                    if key in by_name:  # avoid ambiguous duplicate OCG names
                        return
                    by_name[key] = item["number"]
                if not by_name or not set(by_name).issubset(
                        {name.casefold() for name in self._states}):
                    return
                for name, value in self._states.items():
                    control = by_name.get(name.casefold())
                    if control is not None and not value:
                        candidate.set_layer_ui_config(control, action=2)
                self._cad_layered_pdf = candidate
                self._cad_layer_ui = by_name
                candidate = None
            finally:
                if candidate is not None:
                    candidate.close()
        except (ValueError, RuntimeError, KeyError, OSError):
            # Optional fast path: always retain the tested recorder fallback.
            self._cad_layer_ui.clear()

    def _cad_layered_extent_safe(self) -> bool:
        """Only reuse fixed OCG page if visibility preserves exact CAD extent."""
        canvas = self._cad_render_box
        if canvas is None or not canvas.has_data or not self._cad_layer_bounds:
            return False
        enabled = {name.casefold(): visible for name, visible in self._states.items()}
        boxes = [bbox for key, bbox in self._cad_layer_bounds.items()
                 if enabled.get(key, True)]
        if not boxes:
            return False
        x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
        x1 = max(b[2] for b in boxes); y1 = max(b[3] for b in boxes)
        target = (canvas.extmin.x, canvas.extmin.y,
                  canvas.extmax.x, canvas.extmax.y)
        epsilon = 1e-8 * max(1., x1-x0, y1-y0)
        return all(abs(a-b) <= epsilon for a,b in zip((x0,y0,x1,y1),target))

    def _cad_replay_pdf(self) -> bytes | None:
        """Filter cached graphics by layer while preserving CAD draw order."""
        recording = self._cad_recorder
        if recording is None:
            return None
        enabled = {name.casefold(): on for name, on in self._states.items()}
        backend = pymupdf.PyMuPdfBackend()
        recording.player().replay(
            backend,
            override=lambda properties: cad_recorder.Override(
                properties, enabled.get(properties.layer.casefold(), True)))
        if not backend.records:
            return None
        return backend.get_pdf_bytes(cad_layout.Page(0, 0),
                                     render_box=self._cad_render_box)

    def _cad_as_pdf(self, *, direct: bool = False) -> bytes | None:
        signature = (direct, tuple(self._states.items()))
        if signature in self._cad_pdf_cache:
            self._cad_pdf_cache.move_to_end(signature)
            return self._cad_pdf_cache[signature]
        self._cad_render_count += 1
        self._build_cad_recording()
        if self._cad_recorder is not None and not direct:
            pdf_bytes = self._cad_replay_pdf()
            if pdf_bytes is None and self._cad_render_box is not None:
                # Keep the original canvas bounds after all layers are hidden.
                # No bitmap allocation is needed for the blank preview path.
                pass
        else:
            backend = pymupdf.PyMuPdfBackend()
            configuration = Configuration(background_policy=BackgroundPolicy.OFF,
                                          color_policy=ColorPolicy.COLOR)
            Frontend(RenderContext(self._cad), backend, config=configuration).draw_layout(
                self._cad.modelspace())
            geometry = backend.player().bbox()
            if geometry.has_data:
                box = (geometry.extmin.x, geometry.extmin.y,
                       geometry.extmax.x, geometry.extmax.y)
                pdf_bytes = backend.get_pdf_bytes(cad_layout.Page(0, 0))
                if direct or self._cad_recorder is None:
                    with fitz.open(stream=pdf_bytes, filetype='pdf') as created:
                        rect = created[0].rect
                        self._large_cad_page[signature] = (
                            box, (rect.width, rect.height))
                        # Reuse at most three signatures (no indefinite metadata growth).
                        while len(self._large_cad_page) > 3:
                            self._large_cad_page.pop(next(iter(self._large_cad_page)))
            else:
                pdf_bytes = None
        if pdf_bytes is not None and len(pdf_bytes) <= 64 * 1024 * 1024:
            self._cad_pdf_cache[signature] = pdf_bytes
            self._cad_pdf_cache_bytes += len(pdf_bytes)
            while len(self._cad_pdf_cache) > 3 or self._cad_pdf_cache_bytes > 96 * 1024 * 1024:
                _, oldest = self._cad_pdf_cache.popitem(last=False)
                self._cad_pdf_cache_bytes -= len(oldest)
        return pdf_bytes

    def _get_page_context(self):
        """Return temporary (document, page) when serialization is needed."""
        if self._pdf is not None and not self._serialize_fallback:
            return None, self._pdf.load_page(self.page_index)
        if self._pdf is not None:
            temp = fitz.open(stream=self._pdf.tobytes(), filetype="pdf")
            return temp, temp.load_page(self.page_index)
        if not any(self._states.values()):
            # Preserve the established blank-state preview sizing contract.
            return None, None
        self._build_cad_layered_pdf()
        if self._cad_layered_pdf is not None and self._cad_layered_extent_safe():
            page = self._cad_layered_pdf.load_page(0)
            self._cad_base_rect = (page.rect.width, page.rect.height)
            return None, page
        # Boundary-changing layer combinations must use original auto-fit page
        # geometry so overview, viewport and native image export stay aligned.
        pdf_data = self._cad_as_pdf(direct=self._cad_layered_pdf is not None)
        if pdf_data is None:
            return None, None
        temp = fitz.open(stream=pdf_data, filetype="pdf")
        page = temp.load_page(0)
        self._cad_base_rect = (page.rect.width, page.rect.height)
        return temp, page


    def _render_large_cad_clip(self, options: OutputOptions,
                               preview: tuple[int, int] | None,
                               clip: tuple[float, float, float, float] | None) -> bytes | None:
        """Render visible simple primitives, keeping all unknown CAD objects.

        Only called after a full-page render has fixed exact CAD/PDF extents for
        this layer state. Any unsupported condition falls back to full rendering.
        """
        if (self._cad is None or self._cad_recorder is not None or
                preview is None or clip is None or options.fmt != 'png'):
            return None
        signature = (False, tuple(self._states.items()))
        saved = self._large_cad_page.get(signature)
        if saved is None or signature in self._cad_pdf_cache:
            # An already-built PDF is much faster to clip with MuPDF than
            # creating a new spatially-pruned PDF. Optimize only cache misses.
            return None
        box, pdf_size = saved
        left, bottom, right, top = box
        width, height = pdf_size
        if width <= 0 or height <= 0 or right <= left or top <= bottom:
            return None
        x0, y0, x1, y1 = clip
        if (x0 < 0 or y0 < 0 or x1 > width + .01 or y1 > height + .01 or
                x1 <= x0 or y1 <= y0):
            return None
        region = (left + x0 / width * (right-left),
                  top - y1 / height * (top-bottom),
                  left + x1 / width * (right-left),
                  top - y0 / height * (top-bottom))
        # Lineweights, anti-aliasing and tiny roundoff may extend slightly
        # beyond raw entity extents; pad conservatively in world units.
        pad = max((right-left)/max(preview[0],1),
                  (top-bottom)/max(preview[1],1)) * 4
        region = (region[0]-pad, region[1]-pad,
                  region[2]+pad, region[3]+pad)
        try:
            if self._cad_spatial_key != signature:
                self._cad_spatial_index = CADGridIndex(self._cad.modelspace(), box)
                self._cad_spatial_key = signature
            index = self._cad_spatial_index
            if index is None or index.prunable < 100:
                return None
            visible = index.visible_handles(region)
            backend = pymupdf.PyMuPdfBackend()
            config = Configuration(background_policy=BackgroundPolicy.OFF,
                                   color_policy=ColorPolicy.COLOR)
            Frontend(RenderContext(self._cad), backend, config=config).draw_layout(
                self._cad.modelspace(),
                filter_func=lambda entity: index.accept(entity, visible))
            render_box = cad_layout.BoundingBox2d([box[:2], box[2:]])
            blob = backend.get_pdf_bytes(cad_layout.Page(0, 0), render_box=render_box)
            with fitz.open(stream=blob, filetype='pdf') as temp:
                page = temp.load_page(0)
                if abs(page.rect.width-width) > 0.02 or abs(page.rect.height-height) > 0.02:
                    return None
                self._cad_spatial_runs += 1
                return _render_page(page, options.fmt, preview, clip)
        except (ValueError, RuntimeError, TypeError, KeyError, MemoryError, OSError):
            # Optional acceleration is never allowed to break rendering.
            self._cad_spatial_index = None
            self._cad_spatial_key = None
            return None

    def _get_preview_display_list(self, page: fitz.Page, temporary: fitz.Document | None,
                                  clip: tuple[float,float,float,float] | None):
        """Cache parsed PDF commands for repeated pan/zoom without stale OCGs.

        Only a document owned by this DrawingDocument may retain the list.
        For memory safety cache at most ONE list, and skip very large source
        drawings (their native command lists can require substantial RAM).
        The tiled export path uses a separate local list per export.
        """
        if temporary is not None or clip is None:
            return None
        if self._pdf is not None:
            if self._serialize_fallback or self.path.stat().st_size > 96 * 1024 * 1024:
                return None
        elif self._cad_layered_pdf is None or self.path.stat().st_size > 96 * 1024 * 1024:
            return None
        key = (self.page_index, tuple(self._states.items()),
               id(self._pdf) if self._pdf is not None else id(self._cad_layered_pdf))
        if self._preview_display_key != key:
            try:
                self._preview_display_list = page.get_displaylist(annots=True)
            except (RuntimeError, ValueError, MemoryError):
                self._preview_display_list = None
            self._preview_display_key = key
        return self._preview_display_list

    def _remember_preview(self, cache_key: tuple | None, data: bytes) -> None:
        if cache_key is None or len(data) > 6_000_000:
            return
        self._preview_cache[cache_key] = data
        self._preview_cache_bytes += len(data)
        while len(self._preview_cache) > 6 or self._preview_cache_bytes > 18_000_000:
            _, older = self._preview_cache.popitem(last=False)
            self._preview_cache_bytes -= len(older)

    def render_bytes(self, options: OutputOptions | None = None,
                     preview: tuple[int, int] | None = None,
                     clip: tuple[float,float,float,float] | None = None) -> bytes:
        opts = (options or OutputOptions()).checked()
        cache_key = None
        if preview is not None and opts.fmt == 'png':
            cache_key = (self.page_index, tuple(self._states.items()), preview, clip)
            if cache_key in self._preview_cache:
                data = self._preview_cache[cache_key]
                self._preview_cache.move_to_end(cache_key)
                return data
        # For large non-recordable CAD, avoid regenerating *all* geometry on
        # high-zoom cache misses. The stable, full-page overview is untouched.
        if clip is not None and preview is not None and self._cad is not None:
            partial = self._render_large_cad_clip(opts, preview, clip)
            if partial is not None:
                self._remember_preview(cache_key, partial)
                return partial
        temp, page = self._get_page_context()
        try:
            if page is None:
                # Preserve an empty visible layer state without treating it as error.
                if preview is None:
                    if self._cad_base_rect:
                        w = max(1, round(self._cad_base_rect[0] * VECTOR_EXPORT_DPI / 72))
                        h = max(1, round(self._cad_base_rect[1] * VECTOR_EXPORT_DPI / 72))
                    else:
                        w, h = 1600, 1000
                else:
                    w, h = preview
                image = Image.new("RGB", (max(1, w), max(1, h)), "white")
                return _image_to_bytes(image, opts.fmt, VECTOR_EXPORT_DPI)
            display = self._get_preview_display_list(page, temp, clip) if preview is not None else None
            data = _render_page(page, opts.fmt, preview, clip, display_list=display)
            self._remember_preview(cache_key, data)
            return data
        except DrawingError:
            raise
        except Exception as exc:
            raise DrawingError(f"렌더링 실패 ({self.path.name}): {exc}") from exc
        finally:
            if temp is not None:
                temp.close()

    def export_dimensions(self, options: OutputOptions | None = None) -> tuple[int, int, int]:
        opts = (options or OutputOptions()).checked()
        temp, page = self._get_page_context()
        try:
            if page is None:
                # Empty CAD has no content extent. Keep its established fallback
                # page geometry and apply the same resolution policy.
                with fitz.open() as blank:
                    page = blank.new_page(width=1600 * 72 / VECTOR_EXPORT_DPI,
                                          height=1000 * 72 / VECTOR_EXPORT_DPI)
                    return _export_pixel_dimensions(page, opts)
            return _export_pixel_dimensions(page, opts)
        finally:
            if temp is not None:
                temp.close()

    def page_size(self) -> tuple[float,float]:
        if self._pdf is not None:
            r = self._pdf.load_page(self.page_index).rect
            return r.width,r.height
        doc,page = self._get_page_context()
        try:
            return (page.rect.width,page.rect.height) if page else (self._cad_base_rect or (1600.,1000.))
        finally:
            if doc is not None: doc.close()

    def export_image(self, dest: str | Path, options: OutputOptions,
                     progress: Callable[[float],None] | None = None,
                     cancelled: Callable[[],bool] | None = None) -> Path:
        opts = options.checked()
        target = Path(dest).expanduser().resolve()
        if target.suffix.lower() != '.'+opts.fmt:
            raise DrawingError(f'확장자는 .{opts.fmt}이어야 합니다.')
        if not target.parent.is_dir():
            raise DrawingError('저장 폴더가 없습니다.')
        if target.exists():
            raise DrawingError('같은 이름의 결과물이 있습니다. 덮어쓰지 않습니다.')
        temporary, tempdoc = None,None
        try:
            tempdoc,page = self._get_page_context()
            with tempfile.NamedTemporaryFile(prefix='.drawing-', suffix='.'+opts.fmt,
                                             dir=target.parent, delete=False) as fp:
                temporary=Path(fp.name)
            if page is None:
                width,height,dpi=self.export_dimensions(opts)
                # Keep giant blank documents on the tiled path as well: don't
                # allocate gigabytes merely because every layer was hidden.
                if width * height > 12_000_000:
                    with fitz.open() as blank:
                        blank_page = blank.new_page(width=1600 * 72 / VECTOR_EXPORT_DPI,
                                                    height=1000 * 72 / VECTOR_EXPORT_DPI)
                        if opts.fmt == 'png':
                            with open(temporary, 'wb') as stream:
                                save_png_tiled(blank_page, stream, width, height, dpi,
                                               progress=progress, cancelled=cancelled)
                        else:
                            save_jpg_tiled(blank_page, temporary, width, height, dpi,
                                           progress=progress, cancelled=cancelled)
                else:
                    img=Image.new('RGB',(width,height),'white')
                    img.save(temporary,format='PNG' if opts.fmt=='png' else 'JPEG', dpi=(dpi,dpi))
                    img.close()
                if progress: progress(1.)
            else:
                width,height,dpi=_export_pixel_dimensions(page, opts)
                if width * height <= 12_000_000:
                    # Fast native path on small drawings; large images take tiles.
                    pix=page.get_pixmap(matrix=fitz.Matrix(
                                        width/page.rect.width,
                                        height/page.rect.height),
                                        colorspace=fitz.csRGB,alpha=False,annots=True)
                    if opts.fmt=='png':
                        pix.set_dpi(dpi,dpi)
                        pix.save(str(temporary))
                    else:
                        image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
                        image.save(temporary,format='JPEG',dpi=(dpi,dpi),quality=98,subsampling=0)
                        image.close()
                    if progress:progress(1.)
                elif opts.fmt=='png':
                    with open(temporary,'wb') as stream:
                        save_png_tiled(page,stream,width,height,dpi,progress=progress,cancelled=cancelled)
                        stream.flush();os.fsync(stream.fileno())
                else:
                    save_jpg_tiled(page,temporary,width,height,dpi,progress=progress,cancelled=cancelled)
            if cancelled and cancelled():
                raise InterruptedError('이미지 추출이 취소되었습니다.')
            os.link(temporary,target)  # atomic no-overwrite
            return target
        except InterruptedError as exc:
            raise DrawingError(str(exc)) from exc
        except (OSError,ValueError,MemoryError) as exc:
            raise DrawingError(f'대용량 출력 실패: {exc} (저장 공간과 시스템 메모리를 확인하세요.)') from exc
        finally:
            if tempdoc is not None: tempdoc.close()
            if temporary is not None: temporary.unlink(missing_ok=True)

    def close(self):
        if self._pdf is not None:
            self._pdf.close()
            self._pdf = None
        self._cad = None
        self._preview_cache.clear()
        self._preview_cache_bytes = 0
        self._preview_geometry_cache.clear()
        self._preview_display_list = None
        self._preview_display_key = None
        self._cad_pdf_cache.clear()
        self._cad_pdf_cache_bytes = 0
        self._cad_recorder = None
        self._cad_render_box = None
        if self._cad_layered_pdf is not None:
            self._cad_layered_pdf.close()
            self._cad_layered_pdf = None
        self._cad_layer_ui.clear()
        self._cad_layer_bounds.clear()
        self._large_cad_page.clear()
        self._cad_spatial_index = None
        self._cad_spatial_key = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# Workers never share fitz.Document between threads. Reopen only on file switch
# or source mtime/size change; retain at most one drawing per worker thread.
_cache = threading.local()


def _thread_document(path: str) -> DrawingDocument:
    normalized = str(Path(path).expanduser().resolve())
    stat = Path(normalized).stat()
    signature = (normalized, stat.st_size, stat.st_mtime_ns)
    if getattr(_cache, "signature", None) != signature:
        previous = getattr(_cache, "document", None)
        if previous is not None:
            previous.close()
        _cache.document = DrawingDocument(normalized)
        _cache.signature = signature
    return _cache.document


def render_snapshot(path: str, states: dict[int | str, bool], page_index: int,
                    preview_size: tuple[int, int],
                    clip: tuple[float,float,float,float] | None = None) -> bytes:
    doc = _thread_document(path)
    doc.apply_snapshot(states)
    doc.page_index = page_index
    return doc.render_bytes(OutputOptions("png"), preview=preview_size, clip=clip)


def export_snapshot(path: str, states: dict[int | str, bool], page_index: int,
                    destination: str, options: OutputOptions, progress=None, cancelled=None) -> str:
    doc = _thread_document(path)
    doc.apply_snapshot(states)
    doc.page_index = page_index
    return str(doc.export_image(destination, options, progress=progress, cancelled=cancelled))


def preview_snapshot(path: str, states: dict[int | str,bool], page_index: int,
                     preview_size: tuple[int,int]) -> tuple[bytes, tuple[float,float]]:
    """Fetch preview + page geometry from the SAME document/render context."""
    doc = _thread_document(path)
    doc.apply_snapshot(states)
    doc.page_index = page_index
    cache_key = (page_index, tuple(doc._states.items()), preview_size, None)
    # Repeated overview requests need neither the CAD/PDF intermediate page
    # construction nor a second rasterization. Geometry is cached alongside
    # the pixels; source changes instantiate a new thread document.
    if cache_key in doc._preview_cache and cache_key in doc._preview_geometry_cache:
        doc._preview_cache.move_to_end(cache_key)
        doc._preview_geometry_cache.move_to_end(cache_key)
        return doc._preview_cache[cache_key], doc._preview_geometry_cache[cache_key]
    temp,page = doc._get_page_context()
    try:
        if page is None:
            w,h = preview_size
            image = Image.new('RGB',(max(1,w),max(1,h)),'white')
            return _image_to_bytes(image,'png',96),(doc._cad_base_rect or (1600.,1000.))
        if cache_key in doc._preview_cache:
            data = doc._preview_cache[cache_key]
            doc._preview_cache.move_to_end(cache_key)
        else:
            data = _render_page(page, 'png', preview_size)
            if len(data) <= 6_000_000:
                doc._remember_preview(cache_key, data)
        geometry = (page.rect.width,page.rect.height)
        if cache_key in doc._preview_cache:
            doc._preview_geometry_cache[cache_key] = geometry
            doc._preview_geometry_cache.move_to_end(cache_key)
            while len(doc._preview_geometry_cache) > 8:
                doc._preview_geometry_cache.popitem(last=False)
        return data, geometry
    finally:
        if temp is not None:temp.close()
