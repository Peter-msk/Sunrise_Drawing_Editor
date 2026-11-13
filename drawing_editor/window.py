"""Sunrise drawing editor: fixed-panel light/dark UI and viewport-tile zoom previews."""
from __future__ import annotations

from pathlib import Path
import os
import threading
import time

from PySide6.QtCore import Qt, QRunnable, QThreadPool, QTimer, QObject, Signal, QSettings, QRectF, QStandardPaths, QSize, QEvent
from PySide6.QtGui import QColor, QBrush, QPainter, QPixmap, QIcon, QTransform, QAction, QPalette
from PySide6.QtWidgets import (
    QMainWindow, QToolBar, QWidget, QLabel, QFrame, QHBoxLayout, QVBoxLayout,
    QPushButton, QListWidget, QListWidgetItem, QAbstractItemView, QTreeWidget,
    QTreeWidgetItem, QGraphicsScene, QGraphicsView, QGraphicsPixmapItem,
    QFileDialog, QMessageBox, QComboBox, QGroupBox, QSizePolicy, QLineEdit,
    QToolButton, QRadioButton, QButtonGroup, QProgressBar, QInputDialog, QCheckBox,
    QSpinBox, QHeaderView, QApplication, QScrollArea,
)

from .core import (DrawingDocument, DrawingError, RenderCancelled, OutputOptions,
                   render_snapshot, preview_snapshot, export_snapshot)
from .batch import LayerRule, LayerRuleStore, apply_rule, plan_exports, run_batch_exports
from .icons import icon_file
from .cad_worker import should_isolate_cad, render_isolated, shutdown_all_workers
from .state import DrawingState
from .cad_catalog import read_ascii_dxf_layers
from .ui_design import THEMES, panel_layout
from .ui_interaction import (matching_editable_layers, file_add_status,
                             zoom_factor_for_delta, clamp_zoom_factor,
                             preview_raster_size, detail_tile_covers)

ASSETS = Path(__file__).resolve().parent.parent / 'assets'
# PyMuPDF's native cache is process-global. Concurrent PDF raster/metadata
# calls from separate Qt pools can hang or crash even with distinct documents.
# Keep GUI responsive but serialize only the native MuPDF work. For parallel
# rendering use independent processes, never more concurrent Python threads.
_MUPDF_GATE = threading.RLock()


class ImageCanvas(QGraphicsView):
    """Scene units = PDF page coordinates; zoom requests clip only visible region."""
    viewChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        # An overview bitmap remains visible throughout interaction; raster
        # upgrades are scheduled after the gesture, never inside wheelEvent.
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.empty_label = QLabel('도면을 추가하면 여기에 미리보기가 표시됩니다.\n'
                                  'PDF · DXF · DWG 파일을 이 화면으로 끌어 놓을 수도 있습니다.',
                                  self.viewport())
        self.empty_label.setObjectName('canvasEmpty')
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.empty_label.show()
        self.auto_fit = True
        self.page_size = (0., 0.)
        self._base = None
        self._detail = None
        self._base_density = 0.
        self._detail_clip = None
        self._detail_density = 0.
        self.horizontalScrollBar().valueChanged.connect(self.viewChanged.emit)
        self.verticalScrollBar().valueChanged.connect(self.viewChanged.emit)

    def clear_preview(self):
        self.scene().clear()
        self._base = self._detail = None
        self._base_density = 0.
        self.page_size = (0., 0.)
        self.resetTransform()
        self.auto_fit = True
        self.empty_label.show()

    def show_png(self, data: bytes, page_size: tuple[float,float]):
        pix = QPixmap()
        if not pix.loadFromData(data, 'PNG'):
            raise DrawingError('PDF 미리보기 이미지 디코딩 실패')
        w,h = page_size
        if w <= 0 or h <= 0: raise DrawingError('유효하지 않은 페이지 크기')
        resized = self.page_size != page_size or self._base is None
        if resized:
            self.clear_preview()
            self.page_size = (w,h)
            self.scene().setSceneRect(QRectF(0,0,w,h))
            self._base = QGraphicsPixmapItem()
            self._base.setZValue(0)
            self.scene().addItem(self._base)
        self._base.setPixmap(pix)
        self.empty_label.hide()
        self._base.setTransform(QTransform.fromScale(w / pix.width(), h / pix.height()))
        self._base_density = pix.width() / w
        self.clear_detail()
        if self.auto_fit or resized:
            self.fit_image()

    def show_detail(self, data: bytes, clip: tuple[float,float,float,float]):
        pix = QPixmap()
        if not pix.loadFromData(data,'PNG'):
            raise DrawingError('확대 이미지 디코딩 실패')
        self.clear_detail()
        x0,y0,x1,y1=clip
        item=QGraphicsPixmapItem(pix)
        item.setZValue(1)
        item.setPos(x0,y0)
        item.setTransform(QTransform.fromScale((x1-x0)/pix.width(),
                                                (y1-y0)/pix.height()))
        self.scene().addItem(item)
        self._detail=item
        self._detail_clip = clip
        self._detail_density = min(pix.width() / (x1-x0), pix.height() / (y1-y0))

    def clear_detail(self):
        if self._detail is not None:
            self.scene().removeItem(self._detail)
            self._detail=None
        self._detail_clip = None
        self._detail_density = 0.

    def fit_image(self):
        if self._base is not None:
            self.fitInView(self.scene().sceneRect(),Qt.AspectRatioMode.KeepAspectRatio)
            self.auto_fit=True
            self.viewChanged.emit()

    def zoom(self, factor):
        if self._base is None:
            return
        w, h = self.page_size
        viewport = self.viewport().size()
        if w <= 0 or h <= 0 or viewport.width() < 1 or viewport.height() < 1:
            return
        fit = min(viewport.width() / w, viewport.height() / h)
        # Relative-to-fit limits are invariant to source PDF units and avoid
        # absolute-transform cutoffs. Zoom never invokes the CAD renderer.
        adjusted = clamp_zoom_factor(self.transform().m11(), fit, factor)
        if adjusted == 1.0:
            return
        self.auto_fit = False
        self.scale(adjusted, adjusted)
        self.viewChanged.emit()

    def wheelEvent(self,event):
        dy = event.angleDelta().y()
        pixel_dy = event.pixelDelta().y()
        if dy or pixel_dy:
            # Fractional wheel deltas support smooth precision trackpads.
            self.zoom(zoom_factor_for_delta(dy, pixel_dy))
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        inset = min(24, max(8, self.viewport().width() // 15))
        self.empty_label.setGeometry(inset, 0,
            max(0, self.viewport().width() - 2 * inset), self.viewport().height())
        if self.auto_fit:self.fit_image()
        else:self.viewChanged.emit()

    def visible_clip(self, padding: float = 0.):
        w,h=self.page_size
        if w<=0 or h<=0:return None
        r=self.mapToScene(self.viewport().rect()).boundingRect()
        if padding > 0:
            # Cache a small halo for smooth panning. It never leaves the page.
            r=r.adjusted(-r.width()*padding, -r.height()*padding,
                         r.width()*padding, r.height()*padding)
        r=r.intersected(QRectF(0,0,w,h))
        if r.isEmpty():return None
        return (r.left(),r.top(),r.right(),r.bottom())

    def needs_detail(self):
        # Request real PDF pixels only when the overview bitmap has become blurry.
        if self._base is None:
            return False
        density = self.transform().m11() * self.devicePixelRatioF()
        if density <= self._base_density * 1.14:
            return False
        # A cached native-resolution overscan tile already covers the view:
        # pan/scroll does not need to repeat the same expensive CAD/PDF pass.
        return not self.detail_covers_view()

    def detail_covers_view(self):
        density = self.transform().m11() * self.devicePixelRatioF()
        return detail_tile_covers(self.visible_clip(), self._detail_clip,
                                  self._detail_density, density)


class ElidedLabel(QLabel):
    """Keep complete file names accessible without allowing them to push controls out."""
    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self._complete_text = ''
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text):
        self._complete_text = str(text)
        self.setToolTip(self._complete_text)
        self._update_elision()

    def _update_elision(self):
        width = max(24, self.width() - 4)
        QLabel.setText(self, self.fontMetrics().elidedText(
            self._complete_text, Qt.TextElideMode.ElideMiddle, width))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elision()


class FileDropList(QListWidget):
    """Accept only local drawings dropped from Explorer; never modify a source."""
    filesDropped = Signal(object)
    _supported = frozenset(('.pdf', '.dxf', '.dwg'))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    @classmethod
    def _paths(cls, mime_data):
        if not mime_data.hasUrls():
            return ()
        paths = []
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.suffix.lower() in cls._supported:
                paths.append(str(path))
        return tuple(dict.fromkeys(paths))

    def dragEnterEvent(self, event):
        if self._paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = self._paths(event.mimeData())
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class Signals(QObject):
    success=Signal(str,int,object)
    error=Signal(str,int,str)
    progress=Signal(str,int,float)
    batch_progress=Signal(int,int,int,float,str)


class RenderTask(QRunnable):
    def __init__(self, mode, seq, path, states, page, preview_size=(1000,750),
                 output='', options=None, clip=None, cancel_event=None, jobs=None):
        super().__init__()
        self.mode,self.seq=mode,seq
        self.path,self.states,self.page=path,dict(states),page
        self.preview_size,self.output=preview_size,output
        self.options=options or OutputOptions()
        self.clip=clip
        self.cancel_event=cancel_event
        self.jobs=tuple(jobs or ())
        self._isolated_cad=False
        self.signals=Signals()

    def run(self):
        # A large DXF runs in its own process: no GUI-process MuPDF gate.
        # Its native renderer can be terminated when the user selects OnMap.
        self._isolated_cad = (self.mode in ('preview', 'detail')
                              and should_isolate_cad(self.path))
        if self._isolated_cad:
            self._run_guarded()
            return
        if self.mode == 'batch_export':
            # Allow preview/catalog tasks to acquire MuPDF between file exports.
            self._run_guarded()
            return
        # A cancelled queued task must be able to leave the MuPDF gate without
        # waiting behind a long native renderer, especially during shutdown.
        while not _MUPDF_GATE.acquire(timeout=0.15):
            if self.cancel_event is not None and self.cancel_event.is_set():
                self.signals.error.emit(self.mode, self.seq, '미리보기 중단됨')
                return
        try:
            self._run_guarded()
        finally:
            _MUPDF_GATE.release()

    def _run_guarded(self):
        try:
            if self.cancel_event is not None and self.cancel_event.is_set():
                raise RenderCancelled('미리보기 중단됨')
            if self.mode=='preview':
                if self._isolated_cad:
                    value=render_isolated('preview',self.path,self.states,self.page,
                                          self.preview_size,
                                          cancelled=self.cancel_event.is_set if self.cancel_event else None)
                else:
                    value=preview_snapshot(self.path,self.states,self.page,self.preview_size,
                                           cancelled=self.cancel_event.is_set if self.cancel_event else None)
            elif self.mode=='detail':
                if self._isolated_cad:
                    pixels=render_isolated('detail',self.path,self.states,self.page,
                                            self.preview_size,clip=self.clip,
                                            cancelled=self.cancel_event.is_set if self.cancel_event else None)
                    value=(pixels,self.clip)
                else:
                    value=(render_snapshot(self.path,self.states,self.page,self.preview_size,
                                           clip=self.clip,
                                           cancelled=self.cancel_event.is_set if self.cancel_event else None),self.clip)
            elif self.mode=='batch_export':
                last_update=[0.0]
                def progress(index,total,fraction,name):
                    now=time.monotonic()
                    if fraction==0.0 or fraction>=1.0 or now-last_update[0]>=0.15:
                        last_update[0]=now
                        self.signals.batch_progress.emit(self.seq,index,total,fraction,name)
                value=run_batch_exports(self.jobs,self.options,progress=progress,
                       cancelled=self.cancel_event.is_set if self.cancel_event else None,
                       render_gate=_MUPDF_GATE)
            else:
                progress=lambda p:self.signals.progress.emit(self.mode,self.seq,p)
                cancelled=self.cancel_event.is_set if self.cancel_event else None
                value=export_snapshot(self.path,self.states,self.page,self.output,self.options,
                                      progress=progress,cancelled=cancelled)
            self.signals.success.emit(self.mode,self.seq,value)
        except Exception as exc:
            self.signals.error.emit(self.mode,self.seq,str(exc))


class CatalogTask(QRunnable):
    """Parse one large document in a dedicated one-worker queue.

    Return only primitive layer metadata; never give a QWidget a MuPDF document
    created in a different thread, and never keep dozens of large CAD objects.
    """
    def __init__(self, seq: int, path: str, cancel_event=None):
        super().__init__()
        self.seq, self.path = seq, path
        self.cancel_event = cancel_event
        self.signals = Signals()

    def run(self):
        try:
            if self.cancel_event is not None and self.cancel_event.is_set():
                raise InterruptedError('등록 취소')
            # Large ASCII DXF: read only the layer table. Do not construct an
            # extra full CAD model just to populate the file list.
            kind = Path(self.path).suffix.lower()
            layers = read_ascii_dxf_layers(self.path) if kind == '.dxf' else None
            if layers is not None:
                value = (self.path, layers, 1)
            else:
                # Only PDFs need the MuPDF gate for metadata. CAD metadata
                # loading is independent, so Explorer batch adds stay fast.
                if kind == '.pdf':
                    while not _MUPDF_GATE.acquire(timeout=0.15):
                        if self.cancel_event is not None and self.cancel_event.is_set():
                            raise InterruptedError('등록 취소')
                    try:
                        with DrawingDocument(self.path) as document:
                            value = (self.path, document.layers(), document.pages)
                    finally:
                        _MUPDF_GATE.release()
                else:
                    with DrawingDocument(self.path) as document:
                        value = (self.path, document.layers(), document.pages)
            if self.cancel_event is not None and self.cancel_event.is_set():
                raise InterruptedError('등록 취소')
            self.signals.success.emit('catalog', self.seq, value)
        except Exception as exc:
            self.signals.error.emit('catalog', self.seq, f'{Path(self.path).name}: {exc}')


class DrawingWindow(QMainWindow):
    def __init__(self, initial_paths=None):
        super().__init__()
        self.setWindowTitle('Sunrise Drawing Editor  |  도면 편집기')
        self.setWindowIcon(QIcon(str(ASSETS/'app.ico')))
        # Use logical screen coordinates so 150–175% scaling doesn't place
        # the bottom export buttons below the available desktop work area.
        self.setMinimumSize(760,410)
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.resize(min(1510, max(760, available.width()-24)),
                        min(880, max(410, available.height()-32)))
        else:
            self.resize(1400,820)
        self.documents={}
        self._catalog_seq=0
        self._catalog_paths={}
        self._catalog_latest={}
        self._catalog_cancellations={}
        self.catalog_pool=QThreadPool(self)
        self.catalog_pool.setMaxThreadCount(1)
        self._layer_change_guard=False
        self._preview_seq=self._detail_seq=self._export_seq=0
        self._preview_busy=self._detail_busy=self._export_busy=False
        self._preview_pending=self._detail_pending=False
        self._preview_cancel=self._detail_cancel=None
        self._preview_started=0.0
        self._closing=False
        self._close_prompted=False
        self._active_tasks={}
        self._export_cancel=None
        # Keep previews on one worker to reuse its thread-local multi-MB CAD
        # document; batch exports use a separate worker to avoid UI blocking.
        self.pool=QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.export_pool=QThreadPool(self)
        self.export_pool.setMaxThreadCount(1)
        self.preview_timer=QTimer(self)
        self.preview_timer.setSingleShot(True)
        # Coalesce repeated layer clicks; the last layer state wins.
        self.preview_timer.setInterval(135)
        self.preview_timer.timeout.connect(self._start_preview)
        self.detail_timer=QTimer(self)
        self.detail_timer.setSingleShot(True)
        # Wait for zoom/pan to settle instead of serially rendering stale clips.
        self.detail_timer.setInterval(230)
        self.detail_timer.timeout.connect(self._start_detail)
        self.task_watchdog=QTimer(self)
        self.task_watchdog.setInterval(1000)
        self.task_watchdog.timeout.connect(self._check_background_tasks)
        self.task_watchdog.start()
        self._settings=QSettings('Sunrise','DrawingEditor')
        data_dir=QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        self._rule_store=LayerRuleStore(Path(data_dir or (Path.home()/'.sunrise_drawing_editor'))/'layer_rules.json')
        self._rule_load_error=None
        try:
            self._rules=self._rule_store.load()
        except DrawingError as exc:
            self._rules={}
            self._rule_load_error=str(exc)
        theme=self._settings.value('theme','light')
        self._theme=theme if theme in ('light','dark') else 'light'
        self._build_ui()
        # Explorer drops work on the main window and the drawing canvas, not
        # exclusively on the narrow left-hand file list.
        self.setAcceptDrops(True)
        self.centralWidget().setAcceptDrops(True)
        self.centralWidget().installEventFilter(self)
        self.canvas.viewport().setAcceptDrops(True)
        self.canvas.viewport().installEventFilter(self)
        self._refresh_rule_names()
        self._apply_theme()
        self.statusBar().showMessage('원본 비파괴 · 선택 도면 일괄 규칙 적용 · 대용량 이미지 일괄 추출')
        if self.auto_apply_rules.isChecked() and self._selected_rule() is None:
            self.auto_apply_rules.setChecked(False)
        if self._rule_load_error:
            QTimer.singleShot(0,lambda:QMessageBox.warning(self,'규칙 불러오기 오류',
                self._rule_load_error+'\n규칙 파일을 확인하기 전에는 저장/삭제를 할 수 없습니다.'))
        if initial_paths:
            QTimer.singleShot(0,lambda:self.add_files(initial_paths))

    def _icon(self,name):
        # Every action icon follows light/dark contrast. Primary buttons
        # retain white glyphs against the accent background.
        theme = None if name in ('export_white', 'stop_white') else self._theme
        return QIcon(icon_file(name, ASSETS, theme))

    def eventFilter(self, obj, event):
        if obj in (self.canvas.viewport(), self.centralWidget()) and event.type() in (
                QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            return self._handle_file_drop(event)
        return super().eventFilter(obj, event)

    def _handle_file_drop(self, event):
        paths = FileDropList._paths(event.mimeData())
        if not paths or self._closing:
            event.ignore()
            return False
        if event.type() == QEvent.Type.Drop:
            self.add_files(paths)
        event.acceptProposedAction()
        return True

    def dragEnterEvent(self, event):
        self._handle_file_drop(event)

    def dragMoveEvent(self, event):
        self._handle_file_drop(event)

    def dropEvent(self, event):
        self._handle_file_drop(event)

    @staticmethod
    def _panel(name):
        frame=QFrame();frame.setObjectName('pane')
        layout=QVBoxLayout(frame);layout.setContentsMargins(13,11,13,12);layout.setSpacing(8)
        head=QLabel(name);head.setObjectName('panelHeader');layout.addWidget(head)
        return frame,layout

    def _build_ui(self):
        # Primary commands are in one compact toolbar; page navigation belongs
        # beside the preview, and exporting belongs beside output settings.
        toolbar = QToolBar('도면 작업', self)
        toolbar.setObjectName('toolbar')
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.setIconSize(QSize(18, 18))
        self.addToolBar(toolbar)
        self.add_action = toolbar.addAction(self._icon('add'), '도면 추가')
        self.add_action.setObjectName('addDrawingAction')
        self.add_action.setToolTip('PDF, DXF, DWG 도면 추가 (Ctrl+O)')
        self.add_action.setShortcut('Ctrl+O')
        self.add_action.triggered.connect(self.open_files)
        self.remove_action = toolbar.addAction(self._icon('remove'), '현재 도면 제거')
        self.remove_action.setObjectName('removeCurrentDrawingAction')
        self.remove_action.setToolTip('왼쪽 목록에서 현재 활성 도면 1개만 제거합니다. 원본 파일은 삭제되지 않습니다.')
        self.remove_action.triggered.connect(self.remove_current)
        toolbar.addSeparator()
        self.brand_label = QLabel('SUNRISE  /  DRAWING EDITOR')
        self.brand_label.setObjectName('brand')
        toolbar.addWidget(self.brand_label)
        stretch = QWidget()
        stretch.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(stretch)
        self.light_button = QPushButton('라이트')
        self.dark_button = QPushButton('다크')
        for button, icon_name in ((self.light_button, 'sun'), (self.dark_button, 'moon')):
            button.setObjectName(f'{icon_name}ThemeButton')
            button.setProperty('uxRole', 'themeButton')
            button.setCheckable(True)
            button.setIcon(self._icon(icon_name))
            button.setIconSize(QSize(16,16))
        self.light_button.setToolTip('밝은 화면 테마')
        self.light_button.setAccessibleName('밝은 테마 전환')
        self.dark_button.setToolTip('어두운 화면 테마')
        self.dark_button.setAccessibleName('어두운 테마 전환')
        self.light_button.clicked.connect(lambda:self.set_theme('light'))
        self.dark_button.clicked.connect(lambda:self.set_theme('dark'))
        toolbar.addWidget(self.light_button)
        toolbar.addWidget(self.dark_button)

        # Shortcuts operate on the same buttons; don't add duplicate toolbar UI.
        self._shortcuts = []
        for shortcut, callback in (
            ('Ctrl+S', self.export_selected),
            ('Ctrl+F', self.focus_layer_search),
            ('Ctrl+0', self.canvas_fit),
            ('Ctrl+PgUp', lambda:self.change_page(-1)),
            ('Ctrl+PgDown', lambda:self.change_page(1)),
        ):
            action = QAction(self)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            self.addAction(action)
            self._shortcuts.append(action)

        root_widget = QWidget()
        root_widget.setObjectName('drawingRoot')
        root = QVBoxLayout(root_widget)
        root.setContentsMargins(10,10,10,7)
        root.setSpacing(8)
        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(8)

        # File navigation. The number of selected documents is visible at the top.
        files_frame, files_layout = self._panel('01   도면 파일')
        files_frame.setFixedWidth(248)
        self._files_panel = files_frame
        files_frame.setObjectName('filesPane')
        self.file_count = QLabel('전체 0개 · 선택 0개')
        self.file_count.setObjectName('hint')
        files_layout.addWidget(self.file_count)
        self.file_list = FileDropList()
        self.file_list.setObjectName('fileList')
        self.file_list.setAccessibleName('도면 파일 목록')
        self.file_list.setToolTip('PDF · DXF · DWG 파일을 여기로 끌어 놓거나, Ctrl+O로 추가하세요.')
        self.file_list.filesDropped.connect(self.add_files)
        self.file_list.setAlternatingRowColors(True)
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_list.setUniformItemSizes(True)
        self.file_list.setSpacing(1)
        self.file_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.file_list.currentItemChanged.connect(self._selection_changed)
        self.file_list.itemSelectionChanged.connect(self._update_file_selection_count)
        files_layout.addWidget(self.file_list, 1)
        file_actions = QHBoxLayout()
        file_actions.setSpacing(5)
        self.select_all_button = QPushButton('전체 선택')
        self.select_all_button.setObjectName('fileSelectAllButton')
        self.select_all_button.setProperty('uxRole', 'subAction')
        self.select_all_button.setIcon(self._icon('select_all'))
        self.select_all_button.setToolTip('목록의 모든 파일을 일괄 작업 대상으로 선택')
        self.select_all_button.clicked.connect(self.file_list.selectAll)
        file_actions.addWidget(self.select_all_button)
        self.clear_selection_button = QPushButton('선택 해제')
        self.clear_selection_button.setObjectName('fileClearSelectionButton')
        self.clear_selection_button.setProperty('uxRole', 'subAction')
        self.clear_selection_button.setIcon(self._icon('deselect'))
        self.clear_selection_button.setToolTip('선택한 일괄 작업 대상을 해제')
        self.clear_selection_button.clicked.connect(self.file_list.clearSelection)
        file_actions.addWidget(self.clear_selection_button)
        files_layout.addLayout(file_actions)
        self.remove_selected_button = QPushButton('선택 도면 제거')
        self.remove_selected_button.setObjectName('fileRemoveSelectedButton')
        self.remove_selected_button.setProperty('uxRole', 'subAction')
        self.remove_selected_button.setIcon(self._icon('remove'))
        self.remove_selected_button.setToolTip('선택한 항목을 목록에서 제거합니다. 원본 파일은 삭제하지 않습니다. (파일 목록에서 Delete)')
        self.remove_selected_button.setAccessibleName('선택한 도면을 작업 목록에서 제거')
        self.remove_selected_button.clicked.connect(self.remove_selected_files)
        files_layout.addWidget(self.remove_selected_button)
        self.remove_selected_action = QAction('선택 도면 제거', self.file_list)
        self.remove_selected_action.setObjectName('fileRemoveSelectedAction')
        self.remove_selected_action.setShortcut('Delete')
        self.remove_selected_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.remove_selected_action.triggered.connect(self.remove_selected_files)
        self.file_list.addAction(self.remove_selected_action)
        self.file_selection_hint = QLabel('Ctrl: 개별 선택  ·  Shift: 연속 선택')
        self.file_selection_hint.setObjectName('hint')
        files_layout.addWidget(self.file_selection_hint)
        columns.addWidget(files_frame)

        # Layer work: search does NOT change the document's layer visibility.
        layers_frame, layers_layout = self._panel('02   레이어 및 규칙')
        layers_frame.setFixedWidth(350)
        self._layers_panel = layers_frame
        layers_frame.setObjectName('layersPane')
        self.layer_help = QLabel('도면을 선택하면 레이어가 나타납니다.')
        self.layer_help.setObjectName('hint')
        layers_layout.addWidget(self.layer_help)
        self.layer_search = QLineEdit()
        self.layer_search.setObjectName('layerSearch')
        self.layer_search.setAccessibleName('레이어명 검색')
        self.layer_search.setPlaceholderText('레이어명 검색 (Ctrl+F)')
        self.layer_search.setClearButtonEnabled(True)
        self.layer_search.setToolTip('레이어 목록만 검색합니다. ON/OFF 상태는 변경하지 않습니다.')
        self.layer_search.addAction(self._icon('search'), QLineEdit.ActionPosition.LeadingPosition)
        layers_layout.addWidget(self.layer_search)
        layer_actions = QHBoxLayout()
        layer_actions.setSpacing(5)
        self.layer_on_button = QPushButton('전체 켜기')
        self.layer_on_button.setObjectName('allLayersOnButton')
        self.layer_on_button.setProperty('uxRole', 'subAction')
        self.layer_on_button.setIcon(self._icon('visible'))
        self.layer_on_button.setToolTip('검색 결과와 관계없이 현재 도면의 모든 변경 가능한 레이어를 켭니다.')
        self.layer_on_button.clicked.connect(lambda:self.set_all_layers(True))
        layer_actions.addWidget(self.layer_on_button)
        self.layer_off_button = QPushButton('전체 끄기')
        self.layer_off_button.setObjectName('allLayersOffButton')
        self.layer_off_button.setProperty('uxRole', 'subAction')
        self.layer_off_button.setIcon(self._icon('hidden'))
        self.layer_off_button.setToolTip('검색 결과와 관계없이 현재 도면의 모든 변경 가능한 레이어를 끕니다.')
        self.layer_off_button.clicked.connect(lambda:self.set_all_layers(False))
        layer_actions.addWidget(self.layer_off_button)
        layers_layout.addLayout(layer_actions)
        # Explicit search-scope actions. Global ON/OFF buttons stay global.
        # Filtered actions are not shown until a query has actual matches.
        self.filtered_actions = QWidget()
        self.filtered_actions.setObjectName('filteredLayerActions')
        filtered_layout = QHBoxLayout(self.filtered_actions)
        filtered_layout.setContentsMargins(0, 0, 0, 0)
        filtered_layout.setSpacing(5)
        self.filter_on_button = QPushButton('검색 결과 켜기')
        self.filter_on_button.setObjectName('filteredLayersOnButton')
        self.filter_on_button.setProperty('uxRole', 'subAction')
        self.filter_on_button.setAccessibleName('검색한 레이어만 켜기')
        self.filter_on_button.setToolTip('현재 검색에 일치하는 변경 가능한 레이어만 켭니다. 숨겨진 다른 레이어는 그대로 유지합니다.')
        self.filter_on_button.clicked.connect(lambda: self.set_filtered_layers(True))
        self.filter_off_button = QPushButton('검색 결과 끄기')
        self.filter_off_button.setObjectName('filteredLayersOffButton')
        self.filter_off_button.setProperty('uxRole', 'subAction')
        self.filter_off_button.setAccessibleName('검색한 레이어만 끄기')
        self.filter_off_button.setToolTip('현재 검색에 일치하는 변경 가능한 레이어만 끕니다. 숨겨진 다른 레이어는 그대로 유지합니다.')
        self.filter_off_button.clicked.connect(lambda: self.set_filtered_layers(False))
        filtered_layout.addWidget(self.filter_on_button)
        filtered_layout.addWidget(self.filter_off_button)
        layers_layout.addWidget(self.filtered_actions)
        self.filtered_actions.hide()
        self.rule_selector = QComboBox()
        self.rule_selector.setObjectName('ruleSelector')
        self.rule_selector.setToolTip('현재 도면에서 저장한 레이어 ON/OFF 규칙을 선택합니다.')
        self.rule_selector.currentTextChanged.connect(self._rule_selection_changed)
        layers_layout.addWidget(self.rule_selector)
        rule_actions = QHBoxLayout()
        rule_actions.setSpacing(5)
        self.save_rule_button = QPushButton('저장')
        self.save_rule_button.setObjectName('saveLayerRuleButton')
        self.save_rule_button.setProperty('uxRole', 'subAction')
        self.save_rule_button.setIcon(self._icon('save'))
        self.save_rule_button.setToolTip('현재 도면의 레이어 ON/OFF 설정을 규칙으로 저장')
        self.save_rule_button.clicked.connect(self.save_rule)
        rule_actions.addWidget(self.save_rule_button)
        self.apply_rule_button = QPushButton('선택 적용')
        self.apply_rule_button.setObjectName('applyLayerRuleButton')
        self.apply_rule_button.setProperty('uxRole', 'subAction')
        self.apply_rule_button.setIcon(self._icon('apply'))
        self.apply_rule_button.setToolTip('저장된 규칙을 왼쪽에서 선택한 도면들에 적용')
        self.apply_rule_button.clicked.connect(self.apply_rule_to_selected)
        rule_actions.addWidget(self.apply_rule_button)
        self.delete_rule_button = QPushButton('삭제')
        self.delete_rule_button.setObjectName('deleteLayerRuleButton')
        self.delete_rule_button.setProperty('uxRole', 'subAction')
        self.delete_rule_button.setIcon(self._icon('delete'))
        self.delete_rule_button.setToolTip('현재 선택한 저장 규칙 삭제. 원본 도면은 변경되지 않습니다.')
        self.delete_rule_button.clicked.connect(self.delete_rule)
        rule_actions.addWidget(self.delete_rule_button)
        layers_layout.addLayout(rule_actions)
        self.auto_apply_rules = QCheckBox('새 도면에 선택 규칙 자동 적용')
        self.auto_apply_rules.setObjectName('autoApplyLayerRule')
        self.auto_apply_rules.setChecked(self._settings.value('auto_apply_rules',False,type=bool))
        self.auto_apply_rules.toggled.connect(self._toggle_auto_apply)
        layers_layout.addWidget(self.auto_apply_rules)
        self.layer_list = QTreeWidget()
        self.layer_list.setObjectName('layerList')
        self.layer_list.setHeaderLabels(['레이어', '상태'])
        self.layer_list.setRootIsDecorated(False)
        self.layer_list.setAlternatingRowColors(True)
        self.layer_list.setUniformRowHeights(True)
        self.layer_list.setAnimated(False)
        self.layer_list.setIconSize(QSize(15, 15))
        self.layer_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.layer_list.header().setStretchLastSection(False)
        self.layer_list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.layer_list.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.layer_list.setColumnWidth(1, 66)
        self.layer_list.itemChanged.connect(self._layer_changed)
        layers_layout.addWidget(self.layer_list, 1)
        self.layer_empty_hint = QLabel('검색된 레이어가 없습니다. 검색어를 지우면 전체 목록이 다시 표시됩니다.')
        self.layer_empty_hint.setObjectName('layerEmpty')
        self.layer_empty_hint.setWordWrap(True)
        self.layer_empty_hint.hide()
        layers_layout.addWidget(self.layer_empty_hint)
        self.layer_list.setAccessibleName('현재 도면 레이어 목록')
        self.layer_search.textChanged.connect(self._filter_layers)
        columns.addWidget(layers_frame)

        # Preview actions stay next to the document they control.
        preview_frame, preview_layout = self._panel('03   도면 미리보기')
        self.view_info = ElidedLabel('도면을 추가해 주세요')
        self.view_info.setObjectName('panelSubheader')
        preview_layout.addWidget(self.view_info)
        preview_controls = QHBoxLayout()
        preview_controls.setSpacing(5)
        self.page_prev_button = QToolButton()
        self.page_prev_button.setObjectName('previousPageButton')
        self.page_prev_button.setProperty('uxRole', 'viewButton')
        self.page_prev_button.setIcon(self._icon('prev'))
        self.page_prev_button.setToolTip('이전 페이지 (Ctrl+PgUp)')
        self.page_prev_button.setAccessibleName('이전 페이지')
        self.page_prev_button.clicked.connect(lambda:self.change_page(-1))
        preview_controls.addWidget(self.page_prev_button)
        self.page_info = QLabel('0 / 0')
        self.page_info.setObjectName('pageInfo')
        self.page_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_info.setMinimumWidth(54)
        preview_controls.addWidget(self.page_info)
        self.page_next_button = QToolButton()
        self.page_next_button.setObjectName('nextPageButton')
        self.page_next_button.setProperty('uxRole', 'viewButton')
        self.page_next_button.setIcon(self._icon('next'))
        self.page_next_button.setToolTip('다음 페이지 (Ctrl+PgDown)')
        self.page_next_button.setAccessibleName('다음 페이지')
        self.page_next_button.clicked.connect(lambda:self.change_page(1))
        preview_controls.addWidget(self.page_next_button)
        preview_controls.addStretch(1)
        self.zoom_out_button = QToolButton()
        self.zoom_out_button.setObjectName('zoomOutButton')
        self.zoom_out_button.setProperty('uxRole', 'viewButton')
        self.zoom_out_button.setIcon(self._icon('zoom_out'))
        self.zoom_out_button.setToolTip('축소')
        self.zoom_out_button.setAccessibleName('미리보기 축소')
        self.zoom_out_button.clicked.connect(lambda:self.canvas.zoom(1/1.16))
        self.zoom_out_button.setIconSize(QSize(18, 18))
        self.zoom_out_button.setMinimumWidth(34)
        preview_controls.addWidget(self.zoom_out_button)
        self.zoom_label = QLabel('맞춤')
        self.zoom_label.setObjectName('zoomInfo')
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setMinimumWidth(64)
        preview_controls.addWidget(self.zoom_label)
        self.zoom_in_button = QToolButton()
        self.zoom_in_button.setObjectName('zoomInButton')
        self.zoom_in_button.setProperty('uxRole', 'viewButton')
        self.zoom_in_button.setIcon(self._icon('zoom_in'))
        self.zoom_in_button.setToolTip('확대')
        self.zoom_in_button.setAccessibleName('미리보기 확대')
        self.zoom_in_button.clicked.connect(lambda:self.canvas.zoom(1.16))
        self.zoom_in_button.setIconSize(QSize(18, 18))
        self.zoom_in_button.setMinimumWidth(34)
        preview_controls.addWidget(self.zoom_in_button)
        self.fit_button = QPushButton('맞춤')
        self.fit_button.setObjectName('fitPreviewButton')
        self.fit_button.setProperty('uxRole', 'viewButton')
        self.fit_button.setIcon(self._icon('fit'))
        self.fit_button.setToolTip('전체 도면을 화면에 맞춤 (Ctrl+0)')
        self.fit_button.setAccessibleName('화면에 전체 도면 맞춤')
        self.fit_button.clicked.connect(self.canvas_fit)
        self.fit_button.setIconSize(QSize(17, 17))
        preview_controls.addWidget(self.fit_button)
        preview_layout.addLayout(preview_controls)
        self.canvas = ImageCanvas()
        self.canvas.setObjectName('previewCanvas')
        self.canvas.setAccessibleName('도면 미리보기, 휠 확대 및 마우스 드래그 이동')
        self.canvas.viewChanged.connect(self._update_zoom_label)
        self.canvas.viewChanged.connect(self.request_detail)
        preview_layout.addWidget(self.canvas, 1)
        self.view_status = ElidedLabel('레이어를 변경하면 자동 갱신 · 마우스 휠로 확대/축소')
        self.view_status.setObjectName('hint')
        preview_status_row=QHBoxLayout()
        preview_status_row.addWidget(self.view_status, 1)
        self.retry_preview_button=QPushButton('다시 렌더')
        self.retry_preview_button.setObjectName('retryPreviewButton')
        self.retry_preview_button.setToolTip('현재 레이어로 미리보기를 다시 그립니다.')
        self.retry_preview_button.clicked.connect(self.request_preview)
        preview_status_row.addWidget(self.retry_preview_button)
        self.cancel_preview_button=QPushButton('중단')
        self.cancel_preview_button.setObjectName('cancelPreviewButton')
        self.cancel_preview_button.setToolTip('오래된 렌더를 취소 요청합니다. 원본 파일은 변경되지 않습니다.')
        self.cancel_preview_button.clicked.connect(self.cancel_preview)
        self.cancel_preview_button.hide()
        preview_status_row.addWidget(self.cancel_preview_button)
        preview_layout.addLayout(preview_status_row)
        columns.addWidget(preview_frame, 1)
        # With 150–175% DPI the work area can scroll vertically while the
        # export actions remain permanently visible at the bottom.
        main_area = QWidget()
        main_area.setObjectName('workArea')
        main_area.setLayout(columns)
        self.work_scroll = QScrollArea()
        self.work_scroll.setObjectName('workAreaScroll')
        self.work_scroll.setWidgetResizable(True)
        self.work_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.work_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.work_scroll.setWidget(main_area)
        root.addWidget(self.work_scroll, 1)

        # Export settings are permanently visible, including the primary CTA.
        footer = QGroupBox('04   이미지 추출')
        footer.setObjectName('exportPanel')
        footer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        export_layout = QVBoxLayout(footer)
        export_layout.setContentsMargins(13,16,13,10)
        export_layout.setSpacing(6)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(QLabel('형식'))
        self.png_button = QRadioButton('PNG')
        self.png_button.setObjectName('exportPngRadio')
        self.jpg_button = QRadioButton('JPG')
        self.jpg_button.setObjectName('exportJpgRadio')
        self.png_button.setChecked(True)
        group = QButtonGroup(footer)
        group.addButton(self.png_button)
        group.addButton(self.jpg_button)
        controls.addWidget(self.png_button)
        controls.addWidget(self.jpg_button)
        self.transparent_png = QCheckBox('투명 배경')
        self.transparent_png.setObjectName('transparentPngCheck')
        # The GUI defaults to alpha output for PNG per user request. Direct
        # API callers retain the historical opaque OutputOptions() default.
        self.transparent_png.setChecked(True)
        self.transparent_png.setAccessibleName('PNG 페이지 배경 투명하게 출력')
        self.transparent_png.setToolTip(
            'PDF 페이지의 빈 배경을 투명하게 저장합니다.\n'
            '원본 PDF에 실제로 그려진 흰색 바탕·도형은 제거하지 않습니다.')
        self.crop_png = QCheckBox('흰 여백 제거')
        self.crop_png.setObjectName('cropPngMarginsCheck')
        self.crop_png.setChecked(True)
        self.crop_png.setAccessibleName('PNG 도면 외곽의 흰 용지 여백 제거')
        self.crop_png.setToolTip(
            'PNG 저장 시 빈 용지의 바깥쪽 흰 여백만 잘라냅니다.\n'
            '원본 도면, 지도 내부 흰색 요소, 해상도 밀도는 유지합니다.\n'
            '검출이 불확실하면 원본 페이지 전체로 저장합니다.')
        self.jpg_button.toggled.connect(
            lambda checked: (self.transparent_png.setEnabled(not checked),
                             self.crop_png.setEnabled(not checked)))
        controls.addWidget(QLabel('해상도'))
        self.resolution_combo = QComboBox()
        self.resolution_combo.setObjectName('resolutionCombo')
        self.resolution_combo.setAccessibleName('이미지 추출 해상도 선택')
        for name, mode in [('원본 자동 (기본)', 'original'),
                           ('HD · 1280×720', 'hd'),
                           ('FHD · 1920×1080', 'fhd'),
                           ('QHD · 2560×1440', 'qhd'),
                           ('4K · 3840×2160', 'uhd'),
                           ('직접 입력 · 최대 픽셀', 'custom'),
                           ('DPI 직접 입력', 'dpi')]:
            self.resolution_combo.addItem(name, mode)
        self.resolution_combo.setMinimumWidth(190)
        controls.addWidget(self.resolution_combo)
        self.custom_width = QSpinBox()
        self.custom_width.setObjectName('customExportWidth')
        self.custom_width.setRange(1, 2_147_483_647)
        self.custom_width.setValue(1920)
        self.custom_width.setSuffix(' px')
        self.custom_width.setPrefix('W ')
        self.custom_width.setMinimumWidth(116)
        self.custom_height = QSpinBox()
        self.custom_height.setObjectName('customExportHeight')
        self.custom_height.setRange(1, 2_147_483_647)
        self.custom_height.setValue(1080)
        self.custom_height.setSuffix(' px')
        self.custom_height.setPrefix('H ')
        self.custom_height.setMinimumWidth(116)
        self.custom_dpi = QSpinBox()
        self.custom_dpi.setObjectName('customExportDpi')
        self.custom_dpi.setRange(36, 2400)
        self.custom_dpi.setValue(300)
        self.custom_dpi.setSuffix(' DPI')
        self.custom_dpi.setMinimumWidth(110)
        controls.addWidget(self.custom_width)
        controls.addWidget(self.custom_height)
        controls.addWidget(self.custom_dpi)
        controls.addStretch(1)
        export_layout.addLayout(controls)
        extra_options = QHBoxLayout()
        extra_options.setSpacing(12)
        extra_options.addWidget(self.transparent_png)
        extra_options.addWidget(self.crop_png)
        extra_options.addSpacing(8)
        self.resolution_hint = QLabel('원본 자동: 래스터 원본 밀도 유지 · 벡터 도면 300DPI')
        self.resolution_hint.setObjectName('hint')
        extra_options.addWidget(self.resolution_hint)
        extra_options.addStretch(1)
        export_layout.addLayout(extra_options)
        self.resolution_combo.currentIndexChanged.connect(self._update_resolution_controls)
        self._update_resolution_controls()
        destination = QHBoxLayout()
        destination.setSpacing(7)
        destination.addWidget(QLabel('저장 위치'))
        self.output_folder = QLineEdit()
        self.output_folder.setObjectName('outputFolderPath')
        default_dir = (QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
                       or str(Path.home()))
        self.output_folder.setText(str(self._settings.value('output_folder',default_dir)))
        self.output_folder.setPlaceholderText('이미지 저장 폴더')
        self.output_folder.setAccessibleName('이미지 저장 경로')
        self.output_folder.setToolTip(self.output_folder.text())
        self.output_folder.textChanged.connect(self.output_folder.setToolTip)
        destination.addWidget(self.output_folder, 1)
        self.browse_button = QPushButton('찾아보기')
        self.browse_button.setObjectName('browseOutputFolderButton')
        self.browse_button.setProperty('uxRole', 'subAction')
        self.browse_button.setIcon(self._icon('folder'))
        self.browse_button.setIconSize(QSize(18, 18))
        self.browse_button.setToolTip('이미지 저장 폴더 선택')
        self.browse_button.clicked.connect(self.pick_output_dir)
        destination.addWidget(self.browse_button)
        self.export_target_hint = QLabel('추출 대상 0개')
        self.export_target_hint.setObjectName('exportTarget')
        self.export_target_hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        destination.addWidget(self.export_target_hint)
        self.export_button = QPushButton('선택 도면 추출')
        self.export_button.setObjectName('exportDrawingsButton')
        self.export_button.setProperty('uxRole', 'primary')
        self.export_button.setIcon(self._icon('export_white'))
        self.export_button.setIconSize(QSize(18, 18))
        self.export_button.setMinimumWidth(166)
        self.export_button.setAccessibleName('선택한 도면 이미지 추출')
        self.export_button.clicked.connect(self.export_selected)
        self.export_button.setToolTip('왼쪽에서 선택한 도면을 현재 해상도로 PNG/JPG 추출 (Ctrl+S)')
        destination.addWidget(self.export_button)
        export_layout.addLayout(destination)
        root.addWidget(footer)
        self.progress = QProgressBar()
        self.progress.setRange(0,100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.hide()
        root.addWidget(self.progress)
        self.setCentralWidget(root_widget)
        for control in (self.select_all_button, self.clear_selection_button,
                        self.remove_selected_button, self.layer_on_button,
                        self.layer_off_button, self.save_rule_button,
                        self.apply_rule_button, self.delete_rule_button):
            control.setIconSize(QSize(16, 16))
        self._apply_responsive_layout(self.width())
        self._configure_tab_order()
        self._sync_actions()

    def _apply_responsive_layout(self, width):
        # Responsive, non-draggable panels keep the preview usable at 800px.
        layout = panel_layout(width)
        self._files_panel.setFixedWidth(layout.file_width)
        self._layers_panel.setFixedWidth(layout.layer_width)
        self.brand_label.setVisible(layout.show_brand)
        self.file_selection_hint.setVisible(layout.show_selection_help)
        self.export_target_hint.setVisible(width >= 1050)
        narrow = width < 900
        self.select_all_button.setText('전체' if narrow else '전체 선택')
        self.remove_selected_button.setText('선택 제거' if narrow else '선택 도면 제거')
        self.filter_on_button.setText('검색 켜기' if narrow else '검색 결과 켜기')
        self.filter_off_button.setText('검색 끄기' if narrow else '검색 결과 끄기')
        self.clear_selection_button.setText('해제' if narrow else '선택 해제')
        self.layer_on_button.setText('켜기' if narrow else '전체 켜기')
        self.layer_off_button.setText('끄기' if narrow else '전체 끄기')
        self.apply_rule_button.setText('적용' if narrow else '선택 적용')

    def _configure_tab_order(self):
        order = (self.file_list, self.select_all_button, self.clear_selection_button,
                 self.remove_selected_button,
                 self.layer_search, self.layer_on_button, self.layer_off_button,
                 self.filter_on_button, self.filter_off_button,
                 self.rule_selector, self.save_rule_button, self.apply_rule_button,
                 self.delete_rule_button, self.auto_apply_rules, self.layer_list,
                 self.page_prev_button, self.page_next_button, self.zoom_out_button,
                 self.zoom_in_button, self.fit_button, self.png_button,
                 self.jpg_button, self.transparent_png, self.crop_png,
                 self.resolution_combo, self.output_folder,
                 self.browse_button, self.export_button)
        for before, after in zip(order, order[1:]):
            QWidget.setTabOrder(before, after)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_files_panel') and hasattr(self, '_layers_panel'):
            self._apply_responsive_layout(self.width())

    def focus_layer_search(self):
        self.layer_search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.layer_search.selectAll()

    def _rule_selection_changed(self, name):
        self._settings.setValue('selected_rule', name)
        self._sync_actions()

    def _filter_layers(self, text=''):
        text = str(text).strip().casefold()
        total = self.layer_list.topLevelItemCount()
        matches = 0
        for i in range(total):
            item = self.layer_list.topLevelItem(i)
            visible = not text or text in item.text(0).casefold()
            item.setHidden(not visible)
            if visible:
                matches += 1
        self._update_layer_summary(matches=matches)
        self.layer_empty_hint.setVisible(bool(text) and matches == 0 and total > 0)
        self.filtered_actions.setVisible(bool(text) and matches > 0 and self.current_doc() is not None
                                         and self.current_doc().loaded)
        self._sync_actions()

    def _update_layer_summary(self, matches=None):
        doc = self.current_doc()
        if doc is None or not doc.loaded:
            self.layer_help.setText('도면을 선택하면 레이어가 나타납니다.' if doc is None
                                    else '레이어 정보를 읽는 중입니다…')
            return
        layers = doc.layers()
        on = sum(layer.visible for layer in layers)
        total = len(layers)
        if matches is None:
            matches = sum(not self.layer_list.topLevelItem(i).isHidden()
                          for i in range(self.layer_list.topLevelItemCount()))
        suffix = f' · 검색 {matches}개' if self.layer_search.text().strip() else ''
        self.layer_help.setText(f'전체 {total}개 · ON {on}개{suffix}')

    def _sync_actions(self):
        # Incomplete catalog reads never enable an invalid export operation.
        if not hasattr(self, 'export_button'):
            return
        doc = self.current_doc()
        valid_current = doc is not None and doc.loaded
        selected = self.selected_docs()
        can_export = bool(selected) and all(d.loaded for d in selected)
        has_rule = self._selected_rule() is not None
        self.remove_action.setEnabled(doc is not None and not self._export_busy)
        self.select_all_button.setEnabled(self.file_list.count() > 0)
        has_selection = bool(self.file_list.selectedItems())
        self.clear_selection_button.setEnabled(has_selection)
        self.remove_selected_button.setEnabled(has_selection and not self._export_busy)
        self.remove_selected_action.setEnabled(has_selection and not self._export_busy)
        for button in (self.layer_on_button, self.layer_off_button, self.save_rule_button,
                       self.layer_search):
            button.setEnabled(valid_current)
        filtered_keys = matching_editable_layers(doc.layers(), self.layer_search.text()) if valid_current else ()
        self.filter_on_button.setEnabled(bool(filtered_keys))
        self.filter_off_button.setEnabled(bool(filtered_keys))
        self.apply_rule_button.setEnabled(has_rule and can_export)
        self.delete_rule_button.setEnabled(has_rule and not self._rule_load_error)
        self.page_prev_button.setEnabled(valid_current and doc.page_index > 0)
        self.page_next_button.setEnabled(valid_current and doc.page_index < doc.pages - 1)
        for button in (self.zoom_in_button, self.zoom_out_button, self.fit_button):
            button.setEnabled(valid_current)
        self.export_button.setEnabled(self._export_busy or can_export)
        if not self._export_busy:
            count = len(selected)
            self.export_button.setText(f'{count}개 도면 추출' if count > 1 else '선택 도면 추출')
            self.export_target_hint.setText(f'추출 대상 {count}개' +
                (' · 읽는 중' if count and not can_export else ''))
            self.export_button.setAccessibleDescription(
                f'현재 선택한 {count}개 도면을 이미지로 저장합니다.' if can_export else
                '파일 목록에서 출력할 도면을 선택하고 읽기가 완료되면 사용할 수 있습니다.')

    def _update_zoom_label(self):
        if self.canvas._base is None:
            self.zoom_label.setText('맞춤')
            return
        if self.canvas.auto_fit:
            self.zoom_label.setText('맞춤')
            return
        width, height = self.canvas.page_size
        view = self.canvas.viewport().size()
        if width <= 0 or height <= 0:
            self.zoom_label.setText('맞춤')
            return
        fit_scale = min(view.width() / width, view.height() / height)
        percent = round(100 * self.canvas.transform().m11() / max(fit_scale, 1e-8))
        self.zoom_label.setText(f'{percent}%')
        self.zoom_label.setToolTip('화면 맞춤 기준 확대 배율')

    def _apply_theme(self):
        # Tokens are scoped to this application's root/toolbar; avoid letting
        # per-control geometry rules leak into separate Qt dialogs.
        light = self._theme == 'light'
        palette = THEMES[self._theme]
        bg, panel, fg, muted = (palette.background, palette.panel,
                                palette.foreground, palette.muted)
        border, input_bg, hover = (palette.border, palette.input_background,
                                   palette.hover)
        highlight, canvas = palette.selection, palette.canvas
        primary, primary_hover = palette.primary, palette.primary_hover
        active_text = palette.active_text
        # Explicit Qt palette roles are the fallback for native/embedded
        # controls which do not inherit the stylesheet's color selector.
        qt_palette = self.palette()
        for role, value in (
            (QPalette.ColorRole.Window, bg),
            (QPalette.ColorRole.WindowText, fg),
            (QPalette.ColorRole.Base, input_bg),
            (QPalette.ColorRole.Text, fg),
            (QPalette.ColorRole.Button, input_bg),
            (QPalette.ColorRole.ButtonText, fg),
            (QPalette.ColorRole.PlaceholderText, muted),
        ):
            qt_palette.setColor(role, QColor(value))
        for role in (QPalette.ColorRole.WindowText,
                     QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
            qt_palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(muted))
        self.setPalette(qt_palette)
        self.canvas.setBackgroundBrush(QBrush(QColor(canvas)))
        self.light_button.setProperty('active', light)
        self.dark_button.setProperty('active', not light)
        self.light_button.setChecked(light)
        self.dark_button.setChecked(not light)
        self.setStyleSheet(f'''
            QMainWindow,QWidget#drawingRoot,QWidget#workArea,QScrollArea#workAreaScroll {{background:{bg};}}
            QWidget#drawingRoot,QToolBar#toolbar {{color:{fg};font-family:"Malgun Gothic","Noto Sans CJK KR",sans-serif;font-size:12px;}}
            QToolBar#toolbar {{background:{panel};border-bottom:1px solid {border};spacing:5px;padding:6px 10px;}}
            QToolBar#toolbar QToolButton {{padding:7px 9px;border:1px solid transparent;border-radius:6px;color:{fg};}}
            QToolBar#toolbar QToolButton:disabled {{color:{muted};}}
            QToolBar#toolbar QToolButton:hover {{background:{hover};border-color:{border};}}
            QLabel#brand {{font-size:10px;color:{muted};font-weight:700;}}
            QWidget#drawingRoot QPushButton,QWidget#drawingRoot QToolButton,QToolBar#toolbar QPushButton {{
                background:{input_bg};border:1px solid {border};border-radius:6px;padding:6px 9px;min-height:23px;color:{fg};
            }}
            QWidget#drawingRoot QPushButton:hover,QWidget#drawingRoot QToolButton:hover,QToolBar#toolbar QPushButton:hover {{background:{hover};border-color:{primary};}}
            QWidget#drawingRoot QPushButton:focus,QWidget#drawingRoot QToolButton:focus,QToolBar#toolbar QPushButton:focus {{border:2px solid {primary};padding:5px 8px;}}
            QWidget#drawingRoot QPushButton:disabled,QWidget#drawingRoot QToolButton:disabled,QToolBar#toolbar QPushButton:disabled {{color:{muted};background:{bg};border-color:{border};}}
            QToolBar#toolbar QPushButton[uxRole="themeButton"] {{padding:6px 10px;}}
            QToolBar#toolbar QPushButton[uxRole="themeButton"][active="true"] {{color:{active_text};background:{highlight};border-color:{primary};font-weight:700;}}
            QWidget#drawingRoot QPushButton[uxRole="subAction"] {{padding:5px 7px;min-height:25px;}}
            QWidget#drawingRoot QPushButton[uxRole="subAction"]:disabled {{color:{muted};}}
            QWidget#drawingRoot QPushButton[uxRole="viewButton"],QWidget#drawingRoot QToolButton[uxRole="viewButton"] {{padding:4px 6px;min-height:26px;}}
            QWidget#drawingRoot QPushButton[uxRole="primary"] {{background:{primary};border-color:{primary};color:#FFFFFF;font-weight:700;padding:8px 12px;min-height:26px;}}
            QWidget#drawingRoot QPushButton[uxRole="primary"]:hover {{background:{primary_hover};border-color:{primary_hover};}}
            QWidget#drawingRoot QPushButton[uxRole="primary"]:focus {{border:2px solid {fg};padding:7px 11px;}}
            QWidget#drawingRoot QPushButton[uxRole="primary"]:disabled {{background:#80746E;border-color:#80746E;color:#FFFFFF;}}
            QFrame#filesPane,QFrame#layersPane,QFrame#pane,QGroupBox#exportPanel {{background:{panel};border:1px solid {border};border-radius:8px;}}
            QGroupBox#exportPanel {{margin-top:11px;font-weight:700;}}
            QGroupBox#exportPanel::title {{subcontrol-origin:margin;left:12px;padding:0 6px;color:{fg};}}
            QLabel#panelHeader {{font-size:14px;font-weight:700;color:{fg};}}
            QLabel#panelSubheader {{font-weight:600;color:{fg};}}
            QLabel#hint {{color:{muted};font-size:11px;}}
            QLabel#layerEmpty {{color:{muted};font-size:11px;padding:4px 2px;}}
            QLabel#canvasEmpty {{color:{muted};font-size:13px;}}
            QLabel#exportTarget {{color:{muted};font-size:11px;}}
            QLabel#zoomInfo,QLabel#pageInfo {{color:{fg};font-size:11px;font-weight:600;}}
            QWidget#drawingRoot QLabel,QWidget#drawingRoot QCheckBox,QWidget#drawingRoot QRadioButton,
            QWidget#drawingRoot QGroupBox {{color:{fg};}}
            QWidget#drawingRoot QLabel:disabled,QWidget#drawingRoot QCheckBox:disabled,
            QWidget#drawingRoot QRadioButton:disabled {{color:{muted};}}
            QListWidget,QTreeWidget {{background:{input_bg};color:{fg};alternate-background-color:{bg};border:1px solid {border};border-radius:5px;outline:none;selection-background-color:{highlight};selection-color:{fg};}}
            QListWidget::item,QTreeWidget::item {{color:{fg};}}
            QListWidget::item:hover,QTreeWidget::item:hover {{background:{hover};color:{fg};}}
            QListWidget:focus,QTreeWidget:focus {{border:2px solid {primary};}}
            QListWidget::item {{padding:6px 3px;border-bottom:1px solid {border};}}
            QListWidget::item:selected,QTreeWidget::item:selected {{background:{highlight};color:{fg};}}
            QTreeWidget::item {{padding:4px 2px;color:{fg};}}
            QTreeWidget::item:alternate {{background:{bg};color:{fg};}}
            QTreeWidget::item:selected,QListWidget::item:selected {{background:{highlight};color:{fg};}}
            QTreeWidget::indicator,QCheckBox::indicator {{width:14px;height:14px;}}
            QHeaderView::section {{background:{bg};border:0;border-bottom:1px solid {border};color:{muted};padding:5px;}}
            QGraphicsView#previewCanvas {{border:1px solid {border};border-radius:5px;}}
            QWidget#drawingRoot QLineEdit,QWidget#drawingRoot QComboBox,QWidget#drawingRoot QSpinBox {{background:{input_bg};color:{fg};border:1px solid {border};border-radius:5px;padding:5px 7px;min-height:23px;}}
            QWidget#drawingRoot QComboBox QAbstractItemView {{background:{input_bg};color:{fg};selection-background-color:{highlight};selection-color:{fg};}}
            QWidget#drawingRoot QComboBox QAbstractItemView::item {{color:{fg};min-height:22px;}}
            QWidget#drawingRoot QLineEdit:disabled,QWidget#drawingRoot QComboBox:disabled {{color:{muted};background:{bg};}}
            QScrollBar:vertical {{background:{bg};width:12px;margin:1px;border:0;}}
            QScrollBar:horizontal {{background:{bg};height:12px;margin:1px;border:0;}}
            QScrollBar::handle:vertical,QScrollBar::handle:horizontal {{background:{border};border-radius:5px;min-height:24px;min-width:24px;}}
            QScrollBar::handle:vertical:hover,QScrollBar::handle:horizontal:hover {{background:{muted};}}
            QScrollBar::add-line,QScrollBar::sub-line {{border:0;width:0;height:0;}}
            QWidget#drawingRoot QLineEdit:focus,QWidget#drawingRoot QComboBox:focus,QWidget#drawingRoot QSpinBox:focus {{border:2px solid {primary};padding:4px 6px;}}
            QWidget#drawingRoot QCheckBox::indicator:checked {{background:{primary};border:2px solid {primary};border-radius:3px;}}
            QWidget#drawingRoot QRadioButton::indicator:checked {{background:{primary};border:2px solid {primary};border-radius:7px;}}
            QStatusBar {{background:{panel};color:{muted};border-top:1px solid {border};}}
            QProgressBar {{background:{border};border:none;border-radius:3px;}}
            QProgressBar::chunk {{background:{primary};border-radius:3px;}}
        ''')
        # Theme state is a dynamic Qt property; repolish both buttons.
        # All loaded buttons must refresh their SVG variant when the theme
        # changes; otherwise a dark icon could stay on a light background.
        self.add_action.setIcon(self._icon('add'))
        self.remove_action.setIcon(self._icon('remove'))
        for button, name in (
            (self.light_button, 'sun'), (self.dark_button, 'moon'),
            (self.select_all_button, 'select_all'),
            (self.clear_selection_button, 'deselect'),
            (self.remove_selected_button, 'remove'),
            (self.layer_on_button, 'visible'), (self.layer_off_button, 'hidden'),
            (self.save_rule_button, 'save'), (self.apply_rule_button, 'apply'),
            (self.delete_rule_button, 'delete'),
            (self.page_prev_button, 'prev'), (self.page_next_button, 'next'),
            (self.zoom_out_button, 'zoom_out'),
            (self.zoom_in_button, 'zoom_in'), (self.fit_button, 'fit'),
            (self.browse_button, 'folder')):
            button.setIcon(self._icon(name))
        drawing_icon = self._icon('drawing')
        for row in range(self.file_list.count()):
            self.file_list.item(row).setIcon(drawing_icon)
        for button in (self.light_button, self.dark_button):
            button.style().unpolish(button)
            button.style().polish(button)
        # A single physical icon slot keeps SVG glyph/text baselines aligned
        # across all toolbar/form buttons at 100-175% Windows DPI.
        for button in self.findChildren(QPushButton):
            if not button.icon().isNull():
                button.setIconSize(QSize(18, 18))

    def set_theme(self,value):
        if self._theme!=value:
            self._theme=value;self._settings.setValue('theme',value);self._apply_theme()

    def pick_output_dir(self):
        path=QFileDialog.getExistingDirectory(self,'이미지 저장 폴더 선택',self.output_folder.text())
        if path:self.output_folder.setText(path)

    def current_doc(self):
        item=self.file_list.currentItem()
        return self.documents.get(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _update_file_selection_count(self):
        self.file_count.setText(
            f'전체 {len(self.documents)}개 · 선택 {len(self.file_list.selectedItems())}개')
        self._sync_actions()

    def selected_docs(self):
        # QListWidget selection is deliberate: current focus alone is not batch intent.
        return [self.documents[item.data(Qt.ItemDataRole.UserRole)]
                for item in self.file_list.selectedItems()
                if item.data(Qt.ItemDataRole.UserRole) in self.documents]

    def _selected_rule(self):
        return self._rules.get(self.rule_selector.currentText())

    def _refresh_rule_names(self,selected=None):
        name=selected if selected is not None else str(self._settings.value('selected_rule',''))
        self.rule_selector.blockSignals(True)
        self.rule_selector.clear()
        self.rule_selector.addItem('규칙 선택…')
        for label in sorted(self._rules):
            self.rule_selector.addItem(label)
        index=self.rule_selector.findText(name)
        self.rule_selector.setCurrentIndex(index if index>=0 else 0)
        self.rule_selector.blockSignals(False)
        self._settings.setValue('selected_rule',self.rule_selector.currentText())
        self._sync_actions()

    def _toggle_auto_apply(self,checked):
        if checked and self._selected_rule() is None:
            QMessageBox.information(self,'규칙 선택 필요',
                '자동 적용 전에 레이어 규칙을 저장하거나 저장된 규칙을 선택하세요.')
            self.auto_apply_rules.setChecked(False)
            return
        self._settings.setValue('auto_apply_rules',checked)

    def save_rule(self):
        if self._rule_load_error:
            QMessageBox.warning(self,'규칙 저장 불가',self._rule_load_error)
            return
        doc=self.current_doc()
        if not doc:
            QMessageBox.information(self,'도면 없음','규칙을 만들 기준 도면을 선택하세요.')
            return
        name,ok=QInputDialog.getText(self,'레이어 규칙 저장','규칙 이름:',
                                     text=self.rule_selector.currentText() if self._selected_rule() else '')
        if not ok:return
        try:
            rule=LayerRule.from_document(name,doc)
            if rule.name in self._rules and QMessageBox.question(
                self,'규칙 교체 확인',f'「{rule.name}」 규칙이 이미 있습니다. 현재 설정으로 교체할까요?',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No
            )!=QMessageBox.StandardButton.Yes:
                return
            updated=dict(self._rules);updated[rule.name]=rule
            self._rule_store.save_all(updated)
            self._rules=updated
            self._refresh_rule_names(rule.name)
            self.statusBar().showMessage(f'규칙 「{rule.name}」 저장 완료 · {len(rule.layers)}개 레이어',12000)
        except DrawingError as exc:
            QMessageBox.warning(self,'규칙 저장 실패',str(exc))

    def delete_rule(self):
        if self._rule_load_error:
            QMessageBox.warning(self,'규칙 삭제 불가',self._rule_load_error)
            return
        rule=self._selected_rule()
        if rule is None:return
        if QMessageBox.question(self,'규칙 삭제 확인',
            f'저장된 규칙 「{rule.name}」을 삭제할까요? 도면 원본은 변경되지 않습니다.',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No
        )!=QMessageBox.StandardButton.Yes:return
        try:
            updated=dict(self._rules);del updated[rule.name]
            self._rule_store.save_all(updated)
            self._rules=updated;self._refresh_rule_names('')
            if self.auto_apply_rules.isChecked():self.auto_apply_rules.setChecked(False)
        except DrawingError as exc:
            QMessageBox.warning(self,'규칙 삭제 실패',str(exc))

    def _sync_current_layer_rows(self):
        doc=self.current_doc()
        if not doc:return
        state=doc.states()
        self._layer_change_guard=True
        self.layer_list.setUpdatesEnabled(False)
        try:
            for index in range(self.layer_list.topLevelItemCount()):
                item=self.layer_list.topLevelItem(index)
                key=item.data(0,Qt.ItemDataRole.UserRole)
                if key not in state:continue
                on=state[key]
                item.setCheckState(0,Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
                if item.text(1)!='잠김':
                    item.setText(1,'표시' if on else '숨김')
        finally:
            self.layer_list.setUpdatesEnabled(True)
            self._layer_change_guard=False

    def apply_rule_to_selected(self):
        rule=self._selected_rule()
        if rule is None:
            QMessageBox.information(self,'규칙 없음','먼저 저장된 레이어 규칙을 선택하세요.')
            return
        docs=self.selected_docs()
        if any(not doc.loaded for doc in docs):
            QMessageBox.information(self,'도면 읽는 중',
                '선택한 도면의 레이어 목록을 백그라운드에서 읽는 중입니다. 읽기 완료 후 적용하세요.')
            return
        if not docs:
            QMessageBox.information(self,'선택 도면 없음','좌측에서 Ctrl/Shift로 적용할 도면을 선택하세요.')
            return
        matched_docs=modified_docs=unmatched=missing=ambiguous=locked=0
        failures=[];changed_current=False
        for doc in docs:
            try:
                outcome=apply_rule(doc,rule)
                if not outcome.matching_kind:
                    unmatched+=1;continue
                matched_docs+=1
                missing+=outcome.missing;ambiguous+=outcome.ambiguous;locked+=outcome.locked
                if outcome.changed:
                    modified_docs+=1
                    if doc is self.current_doc():changed_current=True
            except DrawingError as exc:
                failures.append(f'{doc.path.name}: {exc}')
        self._sync_current_layer_rows()
        self._update_layer_summary()
        if changed_current:self.request_preview()
        message=(f'선택 {len(docs)}개 · 형식 일치 {matched_docs}개 · 변경 {modified_docs}개\n'
                 f'형식 불일치 {unmatched}개 · 없는 레이어 {missing}개 · 중복 이름 {ambiguous}개 · 잠김 {locked}개')
        if failures:message+='\n\n오류:\n'+'\n'.join(failures[:6])
        self.statusBar().showMessage(message.replace('\n',' / '),15000)
        QMessageBox.information(self,'레이어 규칙 일괄 적용 결과',message)

    def open_files(self):
        files,_=QFileDialog.getOpenFileNames(self,'도면 파일 선택','',
                            '도면 (*.pdf *.dxf *.dwg);;모든 파일 (*.*)')
        if files:self.add_files(files)

    def add_files(self, paths):
        """Register files immediately; parse large CAD/PDF metadata off the GUI thread."""
        if self._closing:
            return
        first, errors, added, duplicates = None, [], 0, 0
        # A large Explorer drop must not trigger a repaint + SVG disk load for
        # every row. Preserve the existing one-document-per-worker contract.
        drawing_icon = self._icon('drawing')
        rule = self._selected_rule() if self.auto_apply_rules.isChecked() else None
        self.file_list.setUpdatesEnabled(False)
        try:
            for path in paths:
                try:
                    key = str(Path(path).expanduser().resolve())
                    if key in self.documents:
                        duplicates += 1
                        continue
                    state = DrawingState(key)
                    state.pending_rule = rule
                    self.documents[key] = state
                    added += 1
                    item = QListWidgetItem(f'[{state.kind.upper()}]  {state.path.name}  (읽는 중)')
                    item.setIcon(drawing_icon)
                    item.setData(Qt.ItemDataRole.UserRole, key)
                    item.setToolTip(key)
                    self.file_list.addItem(item)
                    if first is None:
                        first = item
                    self._catalog_seq += 1
                    cancel_event=threading.Event()
                    task = CatalogTask(self._catalog_seq, key, cancel_event=cancel_event)
                    self._catalog_paths[task.seq] = key
                    self._catalog_latest[key] = task.seq
                    self._catalog_cancellations[key] = cancel_event
                    self._submit_catalog(task)
                except (DrawingError, OSError, ValueError) as exc:
                    errors.append(str(exc))
        finally:
            self.file_list.setUpdatesEnabled(True)
        self._update_file_selection_count()
        if first is not None and self.file_list.currentItem() is None:
            self.file_list.setCurrentItem(first)
        if added or duplicates or errors:
            self.statusBar().showMessage(
                file_add_status(added=added, duplicates=duplicates, rejected=len(errors)), 10000)
        if errors:
            QMessageBox.warning(self, '도면 추가 결과', '\n\n'.join(errors[:7]))

    def _submit_catalog(self, task):
        self._active_tasks[('catalog', task.seq)] = task
        task.signals.success.connect(self._success)
        task.signals.error.connect(self._error)
        self.catalog_pool.start(task)

    def _catalog_ready(self, path, layers, pages):
        state = self.documents.get(path)
        if state is None:
            return
        state.load_metadata(layers, pages)
        if state.pending_rule is not None:
            try:
                if state.pending_rule.kind == state.kind:
                    apply_rule(state, state.pending_rule)
            except DrawingError as exc:
                self.statusBar().showMessage(f'{state.path.name}: 자동 규칙 적용 실패: {exc}', 10000)
            finally:
                state.pending_rule = None
        for row in range(self.file_list.count()):
            item = self.file_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                item.setText(f'[{state.kind.upper()}]  {state.path.name}')
                if item is self.file_list.currentItem():
                    self._selection_changed(item, None)
                break
        self._update_file_selection_count()

    def remove_current(self):
        """Toolbar command removes exactly the active row, not a batch selection."""
        item = self.file_list.currentItem()
        if item is not None:
            self._remove_file_items((item,))

    def remove_selected_files(self):
        """Explicit multi-selection command; never deletes an input file on disk."""
        items = tuple(self.file_list.selectedItems())
        if not items:
            self.statusBar().showMessage('먼저 파일 목록에서 제거할 도면을 선택하세요.', 6000)
            return
        if len(items) > 1:
            answer = QMessageBox.question(
                self, '선택 도면 제거 확인',
                f'{len(items)}개 도면을 작업 목록에서 제거할까요?\n원본 파일은 삭제되지 않습니다.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._remove_file_items(items)

    def _remove_file_items(self, items):
        """Prevent intermediate currentChanged signals from rendering removed files."""
        if self._export_busy:
            self.statusBar().showMessage('이미지 추출 중에는 파일을 제거할 수 없습니다. 완료 또는 취소 후 다시 시도하세요.', 7000)
            return
        rows = sorted({self.file_list.row(item) for item in items if self.file_list.row(item) >= 0},
                      reverse=True)
        if not rows:
            return
        self.file_list.blockSignals(True)
        try:
            for row in rows:
                item = self.file_list.takeItem(row)
                key = item.data(Qt.ItemDataRole.UserRole)
                self._catalog_latest.pop(key, None)
                event = self._catalog_cancellations.pop(key, None)
                if event is not None:
                    event.set()
                doc = self.documents.pop(key, None)
                if doc is not None:
                    doc.close()
            if self.file_list.count() > 0 and self.file_list.currentItem() is None:
                self.file_list.setCurrentRow(0)
        finally:
            self.file_list.blockSignals(False)
        # Invalidate in-flight previews, even if the new active row is not loaded.
        self._preview_seq += 1
        self._detail_seq += 1
        self.canvas.clear_preview()
        self.layer_list.clear()
        self._selection_changed(self.file_list.currentItem(), None)
        if self.current_doc() is None:
            self.view_info.setText('도면을 추가해 주세요')
            self.view_status.setText('미리보기 대기')
            self.page_info.setText('0 / 0')
            self._update_layer_summary()
            self._update_zoom_label()
        self._update_file_selection_count()
        self.statusBar().showMessage(f'{len(rows)}개 도면을 목록에서 제거했습니다. 원본은 유지됩니다.', 8000)

    def _selection_changed(self,current,previous):
        # Signal cancellation at the very beginning of a file switch. Parsing
        # hundreds of DXF/OCG layer rows before requesting a preview otherwise
        # keeps the old 400MiB render alive for the entire UI rebuild.
        if self._preview_cancel is not None:
            self._preview_cancel.set()
        if self._detail_cancel is not None:
            self._detail_cancel.set()
        doc=self.current_doc()
        self.canvas.clear_preview()
        self._update_zoom_label()
        self.layer_search.blockSignals(True)
        self.layer_search.clear()
        self.layer_search.blockSignals(False)
        if doc is None:
            self.view_info.setText('도면을 추가해 주세요')
            self.page_info.setText('0 / 0')
            self.view_status.setText('미리보기 대기')
        if doc is not None and not doc.loaded:
            self.layer_list.clear()
            self.view_info.setText(doc.path.name)
            self.view_status.setText('대용량 도면 원본 레이어 정보 백그라운드 분석 중…')
            self.page_info.setText('읽는 중')
            self._preview_seq += 1
            self._detail_seq += 1
            self._update_layer_summary()
            self._sync_actions()
            return
        self._layer_change_guard=True
        self.layer_list.setUpdatesEnabled(False)
        try:
            self.layer_list.clear()
            if doc:
                for layer in doc.layers():
                    item=QTreeWidgetItem([layer.name,'잠김' if layer.locked else '표시' if layer.visible else '숨김'])
                    item.setData(0,Qt.ItemDataRole.UserRole,layer.key)
                    item.setToolTip(0, layer.name)
                    if layer.locked:
                        item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsUserCheckable)
                    else:
                        item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(0,Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked)
                    self.layer_list.addTopLevelItem(item)
                self.layer_help.setText(f'{len(doc.layers())}개 레이어 · 원본 파일 유지' if doc.layers() else '내부 레이어가 없습니다.')
                self.view_info.setText(doc.path.name)
                self.page_info.setText(f'{doc.page_index+1} / {doc.pages}')
        finally:
            self.layer_list.setUpdatesEnabled(True)
            self._layer_change_guard=False
        self._filter_layers()
        self._sync_actions()
        self.request_preview()

    def _layer_changed(self,item,column):
        if self._layer_change_guard or column!=0:return
        doc=self.current_doc()
        if not doc:return
        key=item.data(0,Qt.ItemDataRole.UserRole)
        try:
            active=item.checkState(0)==Qt.CheckState.Checked
            if doc.set_visibility(key,active):
                item.setText(1,'표시' if active else '숨김')
                self._update_layer_summary()
                self.request_preview()
        except DrawingError as exc:
            QMessageBox.warning(self,'레이어 오류',str(exc))
            self._selection_changed(self.file_list.currentItem(),None)

    def set_filtered_layers(self, visible):
        """Change only matched unlocked layers; preserve invisible search exclusions."""
        doc = self.current_doc()
        if doc is None or not doc.loaded:
            return
        matches = matching_editable_layers(doc.layers(), self.layer_search.text())
        if not matches:
            self.statusBar().showMessage('검색과 일치하는 변경 가능한 레이어가 없습니다.', 6000)
            return
        current = doc.states()
        changes = {key: bool(visible) for key in matches if current[key] != bool(visible)}
        if not changes:
            self.statusBar().showMessage('검색된 레이어가 이미 요청한 상태입니다.', 6000)
            return
        doc.apply_snapshot(changes)
        self._sync_current_layer_rows()
        self._update_layer_summary()
        self.request_preview()
        self.statusBar().showMessage(
            f'검색 결과 {len(matches)}개 중 {len(changes)}개 레이어 ' +
            ('표시' if visible else '숨김') + ' · 다른 레이어는 변경하지 않음', 9000)

    def set_all_layers(self,visible):
        doc=self.current_doc()
        if not doc:return
        try:
            if doc.set_all(visible):
                self._sync_current_layer_rows()
                self._update_layer_summary()
                self.request_preview()
        except DrawingError as exc:QMessageBox.warning(self,'레이어 오류',str(exc))

    def change_page(self,delta):
        doc=self.current_doc()
        if doc:
            new=max(0,min(doc.page_index+delta,doc.pages-1))
            if new!=doc.page_index:
                doc.page_index=new
                self.canvas.clear_preview()
                self.page_info.setText(f'{new+1} / {doc.pages}')
                self.request_preview()
        self._sync_actions()

    def canvas_fit(self):
        self.canvas.fit_image();self.request_detail()

    def request_preview(self):
        if self._closing:
            return
        self._preview_seq+=1
        self._detail_seq+=1
        self._preview_pending=True
        self._detail_pending=False
        if self._preview_cancel is not None:
            self._preview_cancel.set()  # obsolete layer/page/file snapshot
        if self._detail_cancel is not None:
            self._detail_cancel.set()
        # A changed layer state invalidates an in-flight detail render.
        if self._preview_busy:
            self.view_status.setText('이전 도면 렌더 취소 요청 · 선택한 도면 미리보기 대기')
        else:
            self.view_status.setText('레이어 변경 대기 · 연속 조작을 모아 미리보기 갱신')
        self.detail_timer.stop()
        self.canvas.clear_detail()
        self.preview_timer.start()

    def _start_preview(self):
        if self._closing or self._preview_busy or not self._preview_pending:return
        doc=self.current_doc()
        self._preview_pending=False
        if not doc or not doc.loaded:return
        self._preview_busy=True
        self.cancel_preview_button.show()
        self._preview_cancel=threading.Event()
        self._preview_started=time.monotonic()
        self.view_status.setText('레이어 미리보기 렌더링 중…')
        viewport=self.canvas.viewport().size()
        size=preview_raster_size(viewport.width(), viewport.height(),
                                 self.canvas.devicePixelRatioF())
        self._submit(RenderTask('preview',self._preview_seq,str(doc.path),doc.states(),doc.page_index,
                                size,cancel_event=self._preview_cancel))

    def request_detail(self):
        if self._closing:
            return
        # Every view change invalidates old clip results, including changes
        # while a background raster job is already running.
        self._detail_seq += 1
        if self._detail_cancel is not None:
            self._detail_cancel.set()
        if self.canvas.needs_detail():
            self._detail_pending = True
            self.detail_timer.start()
        else:
            self._detail_pending = False
            self.detail_timer.stop()
            # Keep an adequate cached tile on small pans; remove it only when
            # the overview itself is sharp enough (zoom out / fit view).
            density = self.canvas.transform().m11() * self.canvas.devicePixelRatioF()
            if (density <= self.canvas._base_density * 1.14 or
                    not self.canvas.detail_covers_view()):
                self.canvas.clear_detail()

    def _start_detail(self):
        if self._closing or self._detail_busy or not self._detail_pending or self._preview_busy or self._preview_pending:return
        doc=self.current_doc()
        if doc is None:return
        clip=self.canvas.visible_clip(padding=0.15)
        if clip is None:return
        self._detail_pending=False
        self._detail_busy=True
        self._detail_cancel=threading.Event()
        viewport=self.canvas.viewport().size()
        # Raster at native monitor density over the padded clip. A 15% halo
        # avoids re-rendering for small scrolls; cap each dimension to 4000px.
        page_pixels = self.canvas.transform().m11() * self.canvas.devicePixelRatioF()
        w=max(64,min(4000,round((clip[2]-clip[0])*page_pixels)))
        h=max(64,min(4000,round((clip[3]-clip[1])*page_pixels)))
        self.view_status.setText('확대 영역 고해상도 렌더링 중…')
        self._submit(RenderTask('detail',self._detail_seq,str(doc.path),doc.states(),doc.page_index,
                                (w,h),clip=clip,cancel_event=self._detail_cancel))

    def cancel_preview(self):
        """Cancel stale preview/detail work without mutating document layers."""
        self.preview_timer.stop();self.detail_timer.stop()
        self._preview_seq += 1
        self._detail_seq += 1
        self._preview_pending=self._detail_pending=False
        if self._preview_cancel is not None:
            self._preview_cancel.set()
        if self._detail_cancel is not None:
            self._detail_cancel.set()
        self.view_status.setText('미리보기 중단 요청됨 · 다시 렌더를 눌러 재시도')
        if not self._preview_busy:
            self.cancel_preview_button.hide()

    def _update_resolution_controls(self, *_args):
        mode = self.resolution_combo.currentData()
        custom = mode == 'custom'
        self.custom_width.setVisible(custom)
        self.custom_height.setVisible(custom)
        self.custom_dpi.setVisible(mode == 'dpi')
        self.resolution_hint.setText({
            'original': '원본 자동: 래스터 원본 밀도 유지 · 벡터 도면 300DPI',
            'hd': 'HD: 도면 비율을 유지하며 1280×720 이내',
            'fhd': 'FHD: 도면 비율을 유지하며 1920×1080 이내',
            'qhd': 'QHD: 도면 비율을 유지하며 2560×1440 이내',
            'uhd': '4K: 도면 비율을 유지하며 3840×2160 이내',
            'custom': '직접 입력: 입력한 가로·세로의 최대 범위 안에서 비율 유지',
            'dpi': 'DPI 직접 입력: 벡터 품질과 출력 크기를 지정',
        }.get(mode, '도면의 가로세로 비율을 유지합니다.'))

    def _output_options(self) -> OutputOptions:
        mode = self.resolution_combo.currentData() or 'original'
        return OutputOptions(
            fmt='png' if self.png_button.isChecked() else 'jpg',
            resolution=mode,
            width=self.custom_width.value() if mode == 'custom' else None,
            height=self.custom_height.value() if mode == 'custom' else None,
            dpi=self.custom_dpi.value() if mode == 'dpi' else None,
            background=('transparent' if self.png_button.isChecked()
                        and self.transparent_png.isChecked() else 'opaque'),
            crop_margins=(self.png_button.isChecked() and self.crop_png.isChecked()),
        ).checked()

    def export_current(self):
        # Keep the old public entry point for callers; selection drives batch intent.
        self.export_selected()

    def export_selected(self):
        if self._export_busy:
            if self._export_cancel:self._export_cancel.set()
            self.export_button.setEnabled(False)
            self.export_button.setText('취소 요청됨')
            return
        docs=self.selected_docs()
        if any(not doc.loaded for doc in docs):
            QMessageBox.information(self,'도면 읽는 중',
                '선택한 도면의 레이어 목록을 백그라운드에서 읽는 중입니다. 읽기 완료 후 추출하세요.')
            return
        if not docs:
            QMessageBox.information(self,'도면 미선택','좌측에서 추출할 도면을 선택하세요. Ctrl/Shift 복수 선택이 가능합니다.')
            return
        directory=Path(self.output_folder.text().strip()).expanduser()
        opts=self._output_options()
        try:
            jobs=plan_exports(docs,directory,opts)
        except DrawingError as exc:
            QMessageBox.warning(self,'이미지 추출 준비 오류',str(exc))
            return
        if len(jobs)>1:
            answer=QMessageBox.question(self,'일괄 이미지 추출',
                f'선택한 {len(jobs)}개 도면을 {opts.fmt.upper()} 이미지로 각각 저장합니다.\n'
                '각 도면의 현재 페이지 1장 및 현재 레이어 ON/OFF 상태를 사용합니다.\n'
                f'저장 폴더: {directory.resolve()}\n\n계속할까요?',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
            if answer!=QMessageBox.StandardButton.Yes:return
        self._settings.setValue('output_folder',str(directory))
        self._export_seq+=1
        self._export_busy=True
        self._export_cancel=threading.Event()
        self.export_button.setText('일괄 추출 취소' if len(jobs)>1 else '추출 취소')
        self.export_button.setIcon(self._icon('stop_white'))
        self.progress.setValue(0);self.progress.show()
        self.statusBar().showMessage(f'선택 도면 {len(jobs)}개 · {self.resolution_combo.currentText()} 추출 중…')
        self._sync_actions()
        self._submit(RenderTask('batch_export',self._export_seq,'',{},0,
                     options=opts,cancel_event=self._export_cancel,jobs=jobs))

    def _submit(self,task):
        self._active_tasks[(task.mode,task.seq)]=task
        task.signals.success.connect(self._success)
        task.signals.error.connect(self._error)
        task.signals.progress.connect(self._progress)
        task.signals.batch_progress.connect(self._batch_progress)
        (self.export_pool if task.mode in ('batch_export','export') else self.pool).start(task)

    def _progress(self,mode,seq,value):
        if mode=='export' and seq==self._export_seq:
            pct=max(0,min(100,round(value*100)))
            self.progress.setValue(pct)
            self.statusBar().showMessage(f'이미지 추출 중… {pct}%')

    def _batch_progress(self,seq,index,total,fraction,name):
        if seq != self._export_seq or not self._export_busy:return
        amount=0 if total==0 else (index+fraction)/total
        self.progress.setValue(max(0,min(100,round(amount*100))))
        self.statusBar().showMessage(f'일괄 이미지 추출 {min(index+1,total)}/{total} · {name} · {round(amount*100)}%')

    def _restore_export_ui(self):
        self._export_busy=False
        self._export_cancel=None
        self.export_button.setEnabled(True)
        self.export_button.setText('선택 도면 추출')
        self.export_button.setIcon(self._icon('export_white'))
        self.progress.hide()
        self._sync_actions()

    def _success(self,mode,seq,result):
        self._active_tasks.pop((mode,seq),None)
        if self._closing:
            if mode == 'preview':
                self._preview_busy=False
            elif mode == 'detail':
                self._detail_busy=False
            elif mode in ('batch_export','export'):
                self._export_busy=False
            return
        if mode=='catalog':
            expected_path = self._catalog_paths.pop(seq, None)
            path, layers, pages = result
            if expected_path != path or self._catalog_latest.get(path) != seq:
                return
            self._catalog_latest.pop(path, None)
            self._catalog_cancellations.pop(path, None)
            self._catalog_ready(path, layers, pages)
        elif mode=='preview':
            self._preview_busy=False
            self._preview_cancel=None
            self.cancel_preview_button.hide()
            if seq==self._preview_seq and not self._preview_pending:
                try:
                    data,size=result
                    self.canvas.show_png(data,size)
                    doc=self.current_doc()
                    if doc:
                        self.view_status.setText(f'{doc.kind.upper()} · {len(doc.layers())}개 레이어 · '+
                                                 ('표시 변경 반영' if doc.dirty else '원본 표시'))
                    self.request_detail()
                except (DrawingError, RuntimeError, ValueError) as exc:
                    self.view_status.setText('미리보기 표시 실패: '+str(exc))
            if self._preview_pending:self._start_preview()
        elif mode=='detail':
            self._detail_busy=False
            self._detail_cancel=None
            if seq==self._detail_seq and not self._detail_pending and not self._preview_busy:
                try:
                    data,clip=result
                    self.canvas.show_detail(data,clip)
                    self.view_status.setText('확대 영역 원본에서 고해상도 갱신 완료')
                except (DrawingError, RuntimeError, ValueError) as exc:
                    self.view_status.setText('확대 이미지 표시 실패: '+str(exc))
            if self._detail_pending and not self.detail_timer.isActive():
                self.detail_timer.start()
        elif mode=='batch_export':
            self._restore_export_ui()
            self.statusBar().showMessage(
                f'일괄 추출 결과 · 완료 {len(result.completed)}개 · 실패 {len(result.errors)}개'+
                (' · 취소됨' if result.cancelled else ''),15000)
            detail=('\n'.join(result.completed[:5]) + ('\n…' if len(result.completed)>5 else ''))
            failures='\n'.join(f'{name}: {error}' for name,error in result.errors[:8])
            summary=(f'저장 완료: {len(result.completed)}개\n실패: {len(result.errors)}개'
                     +('\n사용자가 중단한 작업입니다.' if result.cancelled else '')
                     +(f'\n\n완료된 파일:\n{detail}' if detail else '')
                     +(f'\n\n실패 항목:\n{failures}' if failures else ''))
            if result.errors:
                QMessageBox.warning(self,'일괄 이미지 추출 결과',summary)
            else:
                QMessageBox.information(self,'일괄 이미지 추출 결과',summary)
        else:
            self._restore_export_ui()
            self.statusBar().showMessage(f'추출 완료: {result}',12000)
            QMessageBox.information(self,'이미지 추출 완료',f'레이어 표시 상태로 저장했습니다.\n{result}')

    def _error(self,mode,seq,error):
        self._active_tasks.pop((mode,seq),None)
        if self._closing:
            if mode == 'preview':
                self._preview_busy=False
            elif mode == 'detail':
                self._detail_busy=False
            elif mode in ('batch_export','export'):
                self._export_busy=False
            return
        if mode=='catalog':
            path = self._catalog_paths.pop(seq, None)
            if path is None or self._catalog_latest.get(path) != seq:
                return
            self._catalog_latest.pop(path, None)
            self._catalog_cancellations.pop(path, None)
            if path is not None:
                for row in range(self.file_list.count()):
                    item = self.file_list.item(row)
                    if item.data(Qt.ItemDataRole.UserRole) == path:
                        item.setText(f'[오류] {Path(path).name}')
                        item.setToolTip(error)
                        break
            if self.current_doc() is not None and str(self.current_doc().path) == path:
                self.view_status.setText('파일 읽기 실패: ' + error)
            self.statusBar().showMessage('파일 읽기 실패: ' + error, 12000)
        elif mode=='preview':
            self._preview_busy=False
            self._preview_cancel=None
            self.cancel_preview_button.hide()
            if seq==self._preview_seq and '중단' not in error:
                self.view_status.setText('미리보기 실패: '+error)
            if self._preview_pending:self._start_preview()
        elif mode=='detail':
            self._detail_busy=False
            self._detail_cancel=None
            if seq==self._detail_seq:self.view_status.setText('확대 렌더링 오류: '+error)
            if self._detail_pending and not self.detail_timer.isActive():
                self.detail_timer.start()
        else:
            self._restore_export_ui()
            if '취소' in error:
                self.statusBar().showMessage('이미지 추출 취소됨. 불완전 파일은 삭제했습니다.',10000)
            else:
                QMessageBox.warning(self,'이미지 추출 실패',error)

    def _pools_idle(self):
        return (self.pool.waitForDone(0) and self.export_pool.waitForDone(0)
                and self.catalog_pool.waitForDone(0))

    def _check_background_tasks(self):
        if self._closing:
            if self._pools_idle():
                self.close()
            elif (not self._close_prompted and
                  time.monotonic() - self._close_requested_at > 4):
                self._offer_force_exit()
            return
        # Distinguish a slow native renderer from a completed preview: never
        # claim success, and always leave cancel/retry/close accessible.
        if self._preview_busy and self._preview_started:
            elapsed=int(time.monotonic()-self._preview_started)
            if elapsed>=12:
                if self._preview_pending:
                    self.view_status.setText(
                        f'이전 대형 도면 처리 {elapsed}초 · 취소 응답 후 최신 온맵 표시')
                elif self._preview_cancel is not None and self._preview_cancel.is_set():
                    self.view_status.setText(f'중단 요청 후 {elapsed}초 · 네이티브 작업 응답 대기')
                else:
                    self.view_status.setText(
                        f'렌더링 응답 지연 {elapsed}초 · 중단/다시 렌더 또는 창 닫기 가능')

    def _offer_force_exit(self):
        if self._close_prompted or self._pools_idle():
            return
        self._close_prompted=True
        answer=QMessageBox.question(
            self,'렌더링 작업 응답 없음',
            '렌더링 작업이 종료 요청에 응답하지 않습니다.\n'
            '강제 종료하면 저장 중인 이미지의 임시파일이 남을 수 있습니다.\n'
            '입력 PDF/DXF/DWG 원본은 수정하지 않습니다.\n\n'
            '프로그램을 즉시 강제 종료할까요?',
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer==QMessageBox.StandardButton.Yes:
            # Python/Qt cannot kill an arbitrary blocked native QThread safely.
            # This explicit, user-confirmed emergency exit prevents a permanent
            # unclosable window. Never use for normal shutdown.
            shutdown_all_workers()
            os._exit(0)
        # Continue waiting quietly. A second close click offers this choice
        # again; the watchdog never opens repeated modal dialogs by itself.
        self._close_prompted=True

    def closeEvent(self,event):
        self.preview_timer.stop();self.detail_timer.stop()
        for event_to_cancel in self._catalog_cancellations.values():
            event_to_cancel.set()
        if not self._pools_idle():
            if self._closing:
                self._close_prompted=False
                self._offer_force_exit()
                event.ignore()
                return
            self._closing=True
            self._close_requested_at=time.monotonic()
            self.cancel_preview()
            if self._export_cancel is not None:
                self._export_cancel.set()
            self.pool.clear();self.export_pool.clear();self.catalog_pool.clear()
            self.view_status.setText('종료 요청됨 · 백그라운드 렌더 작업 정리 중…')
            self.statusBar().showMessage('종료 요청됨 · 작업이 응답하지 않으면 강제 종료를 선택할 수 있습니다.')
            event.ignore()
            return
        self.task_watchdog.stop()
        shutdown_all_workers()
        for doc in self.documents.values():doc.close()
        super().closeEvent(event)
