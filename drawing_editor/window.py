"""Sunrise drawing editor: fixed-panel light/dark UI and viewport-tile zoom previews."""
from __future__ import annotations

from pathlib import Path
import threading
import time

from PySide6.QtCore import Qt, QRunnable, QThreadPool, QTimer, QObject, Signal, QSettings, QRectF, QStandardPaths, QSize
from PySide6.QtGui import QColor, QBrush, QPainter, QPixmap, QIcon, QTransform
from PySide6.QtWidgets import (
    QMainWindow, QToolBar, QWidget, QLabel, QFrame, QHBoxLayout, QVBoxLayout,
    QPushButton, QListWidget, QListWidgetItem, QAbstractItemView, QTreeWidget,
    QTreeWidgetItem, QGraphicsScene, QGraphicsView, QGraphicsPixmapItem,
    QFileDialog, QMessageBox, QComboBox, QGroupBox, QSizePolicy, QLineEdit,
    QToolButton, QRadioButton, QButtonGroup, QProgressBar, QInputDialog, QCheckBox,
    QSpinBox,
)

from .core import (DrawingDocument, DrawingError, OutputOptions,
                   render_snapshot, preview_snapshot, export_snapshot)
from .batch import LayerRule, LayerRuleStore, apply_rule, plan_exports, run_batch_exports
from .icons import icon_file
from .state import DrawingState
from .cad_catalog import read_ascii_dxf_layers

ASSETS = Path(__file__).resolve().parent.parent / 'assets'


class ImageCanvas(QGraphicsView):
    """Scene units = PDF page coordinates; zoom requests clip only visible region."""
    viewChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.auto_fit = True
        self.page_size = (0., 0.)
        self._base = None
        self._detail = None
        self._base_density = 0.
        self.horizontalScrollBar().valueChanged.connect(self.viewChanged.emit)
        self.verticalScrollBar().valueChanged.connect(self.viewChanged.emit)

    def clear_preview(self):
        self.scene().clear()
        self._base = self._detail = None
        self._base_density = 0.
        self.page_size = (0., 0.)
        self.resetTransform()
        self.auto_fit = True

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

    def clear_detail(self):
        if self._detail is not None:
            self.scene().removeItem(self._detail)
            self._detail=None

    def fit_image(self):
        if self._base is not None:
            self.fitInView(self.scene().sceneRect(),Qt.AspectRatioMode.KeepAspectRatio)
            self.auto_fit=True
            self.viewChanged.emit()

    def zoom(self, factor):
        if self._base is None:return
        scale=self.transform().m11()
        if (factor>1 and scale>200) or (factor<1 and scale<.03):return
        self.auto_fit=False
        self.scale(factor,factor)
        self.viewChanged.emit()

    def wheelEvent(self,event):
        if event.angleDelta().y():
            self.zoom(1.2 if event.angleDelta().y()>0 else 1/1.2)
            event.accept()
        else:super().wheelEvent(event)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if self.auto_fit:self.fit_image()
        else:self.viewChanged.emit()

    def visible_clip(self):
        w,h=self.page_size
        if w<=0 or h<=0:return None
        r=self.mapToScene(self.viewport().rect()).boundingRect().intersected(QRectF(0,0,w,h))
        if r.isEmpty():return None
        return (r.left(),r.top(),r.right(),r.bottom())

    def needs_detail(self):
        # Request real PDF pixels only when the overview bitmap has become blurry.
        return (self._base is not None and
                self.transform().m11()*self.devicePixelRatioF() > self._base_density*1.14)


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
        self.signals=Signals()

    def run(self):
        try:
            if self.mode=='preview':
                value=preview_snapshot(self.path,self.states,self.page,self.preview_size)
            elif self.mode=='detail':
                value=(render_snapshot(self.path,self.states,self.page,self.preview_size,clip=self.clip),self.clip)
            elif self.mode=='batch_export':
                last_update=[0.0]
                def progress(index,total,fraction,name):
                    now=time.monotonic()
                    if fraction==0.0 or fraction>=1.0 or now-last_update[0]>=0.15:
                        last_update[0]=now
                        self.signals.batch_progress.emit(self.seq,index,total,fraction,name)
                value=run_batch_exports(self.jobs,self.options,progress=progress,
                       cancelled=self.cancel_event.is_set if self.cancel_event else None)
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
    def __init__(self, seq: int, path: str):
        super().__init__()
        self.seq, self.path = seq, path
        self.signals = Signals()

    def run(self):
        try:
            # Large ASCII DXF: read only the layer table. Do not construct an
            # extra full CAD model just to populate the file list.
            layers = (read_ascii_dxf_layers(self.path)
                      if Path(self.path).suffix.lower() == '.dxf' else None)
            if layers is not None:
                value = (self.path, layers, 1)
            else:
                with DrawingDocument(self.path) as document:
                    value = (self.path, document.layers(), document.pages)
            self.signals.success.emit('catalog', self.seq, value)
        except Exception as exc:
            self.signals.error.emit('catalog', self.seq, f'{Path(self.path).name}: {exc}')


class DrawingWindow(QMainWindow):
    def __init__(self, initial_paths=None):
        super().__init__()
        self.setWindowTitle('Sunrise Drawing Editor  |  도면 편집기')
        self.setWindowIcon(QIcon(str(ASSETS/'app.ico')))
        self.resize(1510,920)
        self.setMinimumSize(1090,680)
        self.documents={}
        self._catalog_seq=0
        self._catalog_paths={}
        self.catalog_pool=QThreadPool(self)
        self.catalog_pool.setMaxThreadCount(1)
        self._layer_change_guard=False
        self._preview_seq=self._detail_seq=self._export_seq=0
        self._preview_busy=self._detail_busy=self._export_busy=False
        self._preview_pending=self._detail_pending=False
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
        self.preview_timer.setInterval(45)
        self.preview_timer.timeout.connect(self._start_preview)
        self.detail_timer=QTimer(self)
        self.detail_timer.setSingleShot(True)
        self.detail_timer.setInterval(105)
        self.detail_timer.timeout.connect(self._start_detail)
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

    def _icon(self,name):return QIcon(icon_file(name,ASSETS))

    @staticmethod
    def _panel(name):
        frame=QFrame();frame.setObjectName('pane')
        layout=QVBoxLayout(frame);layout.setContentsMargins(13,11,13,12);layout.setSpacing(8)
        head=QLabel(name);head.setObjectName('panelHeader');layout.addWidget(head)
        return frame,layout

    def _build_ui(self):
        toolbar=QToolBar('도면 편집',self)
        toolbar.setObjectName('toolbar');toolbar.setMovable(False);toolbar.setFloatable(False)
        toolbar.setIconSize(QSize(20,20))
        self.addToolBar(toolbar)
        for icon,label,callback,shortcut in (
            ('add','도면 추가',self.open_files,'Ctrl+O'),
            ('remove','선택 파일 제거',self.remove_current,''),
            ('prev','이전 페이지',lambda:self.change_page(-1),''),
            ('next','다음 페이지',lambda:self.change_page(1),''),
            ('fit','미리보기 맞춤',self.canvas_fit,''),
            ('export','선택 도면 추출',self.export_selected,'Ctrl+S'),
        ):
            a=toolbar.addAction(self._icon(icon),label);a.triggered.connect(callback)
            if shortcut:a.setShortcut(shortcut)
        spacer=QWidget();spacer.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        self.light_button=QPushButton('☼  라이트')
        self.dark_button=QPushButton('◕  다크')
        self.light_button.clicked.connect(lambda:self.set_theme('light'))
        self.dark_button.clicked.connect(lambda:self.set_theme('dark'))
        toolbar.addWidget(self.light_button);toolbar.addWidget(self.dark_button)

        root_widget=QWidget();root=QVBoxLayout(root_widget)
        root.setContentsMargins(12,12,12,8);root.setSpacing(10)
        columns=QHBoxLayout();columns.setSpacing(9)
        files_frame,files_layout=self._panel('01  도면 파일')
        files_frame.setMinimumWidth(215)
        self.file_list=QListWidget();self.file_list.setObjectName('fileList')
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_list.currentItemChanged.connect(self._selection_changed)
        files_layout.addWidget(self.file_list,1)
        files_actions=QHBoxLayout()
        select_all=QPushButton('전체 선택')
        select_all.setToolTip('모든 도면을 일괄 규칙 적용/추출 대상으로 선택합니다.')
        select_all.clicked.connect(self.file_list.selectAll)
        files_actions.addWidget(select_all)
        clear_selection=QPushButton('선택 해제')
        clear_selection.clicked.connect(self.file_list.clearSelection)
        files_actions.addWidget(clear_selection)
        files_layout.addLayout(files_actions)
        self.file_selection_hint=QLabel('Ctrl 개별 선택 · Shift 연속 선택')
        self.file_selection_hint.setObjectName('hint')
        files_layout.addWidget(self.file_selection_hint)
        self.file_count=QLabel('0개 도면 파일');self.file_count.setObjectName('hint')
        files_layout.addWidget(self.file_count)
        self.file_list.itemSelectionChanged.connect(self._update_file_selection_count)
        columns.addWidget(files_frame,22)

        layers_frame,layers_layout=self._panel('02  도면 레이어')
        layers_frame.setMinimumWidth(255)
        self.layer_help=QLabel('도면을 선택하면 레이어가 나타납니다.')
        self.layer_help.setObjectName('hint');self.layer_help.setWordWrap(True)
        layers_layout.addWidget(self.layer_help)
        line=QHBoxLayout();line.setSpacing(7)
        for name,value in [('☑  모두 켜기',True),('☐  모두 끄기',False)]:
            button=QPushButton(name);button.clicked.connect(lambda _=False,flag=value:self.set_all_layers(flag))
            line.addWidget(button)
        layers_layout.addLayout(line)
        self.rule_selector=QComboBox()
        self.rule_selector.setToolTip('현재 도면에서 저장한 레이어 ON/OFF 규칙을 선택합니다.')
        self.rule_selector.currentTextChanged.connect(
            lambda name:self._settings.setValue('selected_rule',name))
        layers_layout.addWidget(self.rule_selector)
        rule_actions=QHBoxLayout();rule_actions.setSpacing(5)
        for label,handler in (('규칙 저장',self.save_rule),('선택 도면 적용',self.apply_rule_to_selected),
                              ('규칙 삭제',self.delete_rule)):
            button=QPushButton(label);button.clicked.connect(handler)
            rule_actions.addWidget(button)
        layers_layout.addLayout(rule_actions)
        self.auto_apply_rules=QCheckBox('신규 도면 추가 시 선택 규칙 자동 적용')
        self.auto_apply_rules.setChecked(self._settings.value('auto_apply_rules',False,type=bool))
        self.auto_apply_rules.toggled.connect(self._toggle_auto_apply)
        layers_layout.addWidget(self.auto_apply_rules)
        self.layer_list=QTreeWidget();self.layer_list.setObjectName('layerList')
        self.layer_list.setHeaderLabels(['레이어','표시 상태'])
        self.layer_list.setRootIsDecorated(False);self.layer_list.setAlternatingRowColors(True)
        self.layer_list.itemChanged.connect(self._layer_changed)
        self.layer_list.setColumnWidth(0,235)
        layers_layout.addWidget(self.layer_list,1)
        columns.addWidget(layers_frame,27)

        preview_frame,preview_layout=self._panel('03  미리보기')
        header=QHBoxLayout();header.setSpacing(7)
        self.view_info=QLabel('도면을 추가해 주세요');self.view_info.setObjectName('panelSubheader')
        self.view_info.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Preferred)
        header.addWidget(self.view_info,1)
        self.page_info=QLabel('0 / 0');self.page_info.setObjectName('hint');header.addWidget(self.page_info)
        for label,func in [('−',lambda:self.canvas.zoom(1/1.25)),
                           ('+',lambda:self.canvas.zoom(1.25)),('□',self.canvas_fit)]:
            btn=QPushButton(label);btn.setObjectName('miniButton')
            btn.setToolTip('축소' if label=='−' else '확대' if label=='+' else '화면 맞춤')
            btn.setFixedWidth(32);btn.clicked.connect(func);header.addWidget(btn)
        preview_layout.addLayout(header)
        self.canvas=ImageCanvas();self.canvas.setObjectName('previewCanvas')
        self.canvas.viewChanged.connect(self.request_detail)
        preview_layout.addWidget(self.canvas,1)
        self.view_status=QLabel('레이어 변경 시 자동 렌더링 · 확대 시 선명하게 재렌더링')
        self.view_status.setObjectName('hint');preview_layout.addWidget(self.view_status)
        columns.addWidget(preview_frame,66)
        root.addLayout(columns,1)

        footer=QGroupBox('04  이미지 추출 설정');footer.setObjectName('exportPanel')
        export_layout=QVBoxLayout(footer)
        export_layout.setContentsMargins(15,17,15,13);export_layout.setSpacing(7)
        controls=QHBoxLayout();controls.setSpacing(9)
        controls.addWidget(QLabel('출력 형식'))
        self.png_button=QRadioButton('PNG');self.jpg_button=QRadioButton('JPG')
        self.png_button.setChecked(True)
        group=QButtonGroup(footer);group.addButton(self.png_button);group.addButton(self.jpg_button)
        controls.addWidget(self.png_button);controls.addWidget(self.jpg_button)
        controls.addSpacing(9);controls.addWidget(QLabel('해상도'))
        self.resolution_combo=QComboBox()
        for name, mode in [('원본 자동 (기본)', 'original'),
                           ('HD (최대 1280×720)', 'hd'),
                           ('FHD (최대 1920×1080)', 'fhd'),
                           ('QHD (최대 2560×1440)', 'qhd'),
                           ('4K (최대 3840×2160)', 'uhd'),
                           ('사용자 지정 (최대 픽셀)', 'custom'),
                           ('DPI 직접 지정', 'dpi')]:
            self.resolution_combo.addItem(name, mode)
        self.resolution_combo.setMinimumWidth(195)
        controls.addWidget(self.resolution_combo)
        self.custom_width=QSpinBox();self.custom_width.setRange(1,2_147_483_647)
        self.custom_width.setValue(1920);self.custom_width.setSuffix(' px')
        self.custom_width.setPrefix('W ');self.custom_width.setFixedWidth(116)
        self.custom_height=QSpinBox();self.custom_height.setRange(1,2_147_483_647)
        self.custom_height.setValue(1080);self.custom_height.setSuffix(' px')
        self.custom_height.setPrefix('H ');self.custom_height.setFixedWidth(116)
        self.custom_dpi=QSpinBox();self.custom_dpi.setRange(36,2400)
        self.custom_dpi.setValue(300);self.custom_dpi.setSuffix(' DPI')
        self.custom_dpi.setFixedWidth(116)
        controls.addWidget(self.custom_width);controls.addWidget(self.custom_height)
        controls.addWidget(self.custom_dpi)
        controls.addStretch(1)
        self.resolution_combo.currentIndexChanged.connect(self._update_resolution_controls)
        self._update_resolution_controls()
        export_layout.addLayout(controls)
        row=QHBoxLayout();row.setSpacing(10)
        info=QLabel('기본값은 원본 자동 · 선택 크기는 도면 비율을 유지하며 최대값으로 적용')
        info.setObjectName('exportHint');info.setWordWrap(True)
        row.addWidget(info,2)
        path_area=QHBoxLayout();path_area.setSpacing(5)
        self.output_folder=QLineEdit()
        default_dir=QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation) or str(Path.home())
        self.output_folder.setText(str(self._settings.value('output_folder',default_dir)))
        self.output_folder.setPlaceholderText('이미지 저장 폴더')
        path_area.addWidget(self.output_folder,1)
        browse=QToolButton();browse.setText('…');browse.setToolTip('저장 폴더 선택')
        browse.clicked.connect(self.pick_output_dir);path_area.addWidget(browse)
        path_widget=QWidget();path_widget.setLayout(path_area)
        row.addWidget(path_widget,3)
        self.export_button=QPushButton('선택 도면 추출')
        self.export_button.setObjectName('primary');self.export_button.setIcon(self._icon('export'))
        self.export_button.setMinimumWidth(170)
        self.export_button.clicked.connect(self.export_selected)
        row.addWidget(self.export_button)
        export_layout.addLayout(row)
        root.addWidget(footer)
        self.progress=QProgressBar()
        self.progress.setRange(0,100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(7)
        self.progress.setTextVisible(False)
        self.progress.hide()
        root.addWidget(self.progress)
        self.setCentralWidget(root_widget)

    def _apply_theme(self):
        light=self._theme=='light'
        bg,panel,fg,muted=('#F7F9FC','#FFFFFF','#243D60','#637389') if light else ('#121B28','#1D2939','#E9F1FB','#ACC0D6')
        border,input_bg,hover=('#DCE3EB','#FFFFFF','#FFF0E4') if light else ('#344559','#253447','#3E3A37')
        highlight='#FFEDDE' if light else '#4C3429'
        canvas='#E9EEF4' if light else '#101A29'
        self.canvas.setBackgroundBrush(QBrush(QColor(canvas)))
        self.light_button.setProperty('active',light)
        self.dark_button.setProperty('active',not light)
        self.setStyleSheet(f'''
            QWidget {{color:{fg};font-family:"Malgun Gothic","Noto Sans CJK KR",sans-serif;font-size:12px;}}
            QMainWindow,QMainWindow>QWidget {{background:{bg};}}
            QToolBar#toolbar {{background:{panel};border-bottom:1px solid {border};spacing:7px;padding:9px 12px;}}
            QToolButton,QPushButton {{background:{input_bg};border:1px solid {border};border-radius:7px;padding:8px 11px;}}
            QToolButton:hover,QPushButton:hover {{background:{hover};border-color:#F46A22;}}
            QPushButton[active="true"] {{color:#F46A22;background:{highlight};border-color:#F46A22;font-weight:700;}}
            QPushButton#miniButton {{padding:3px;font-size:15px;font-weight:700;}}
            QPushButton#primary {{background:#F46A22;border-color:#F46A22;color:#FFFFFF;font-weight:700;padding:12px;}}
            QPushButton#primary:hover {{background:#E65B0B;}}
            QFrame#pane,QGroupBox#exportPanel {{background:{panel};border:1px solid {border};border-radius:8px;}}
            QGroupBox#exportPanel {{margin-top:13px;font-weight:700;}}
            QGroupBox#exportPanel::title {{subcontrol-origin:margin;left:13px;padding:0 7px;}}
            QLabel#panelHeader {{font-size:14px;font-weight:700;}}
            QLabel#panelSubheader {{font-weight:600;}}
            QLabel#hint {{color:{muted};font-size:11px;}}
            QLabel#exportHint {{background:{highlight};color:{fg};border-radius:6px;padding:10px;}}
            QListWidget,QTreeWidget {{background:{input_bg};alternate-background-color:{bg};border:1px solid {border};border-radius:5px;outline:none;}}
            QListWidget::item {{padding:8px 5px;border-bottom:1px solid {border};}}
            QListWidget::item:selected,QTreeWidget::item:selected {{background:{highlight};color:{fg};}}
            QTreeWidget::item {{padding:4px 2px;}}
            QHeaderView::section {{background:{bg};border:0;border-bottom:1px solid {border};color:{muted};padding:7px;}}
            QGraphicsView#previewCanvas {{border:1px solid {border};border-radius:5px;}}
            QLineEdit,QComboBox,QSpinBox {{background:{input_bg};color:{fg};border:1px solid {border};border-radius:5px;padding:8px;}}
            QCheckBox::indicator:checked {{background:#F46A22;border:2px solid #F46A22;border-radius:3px;}}
            QRadioButton::indicator:checked {{background:#F46A22;border:2px solid #F46A22;border-radius:7px;}}
            QStatusBar {{background:{panel};color:{muted};border-top:1px solid {border};}}
            QProgressBar {{background:{border};border:none;border-radius:3px;}}
            QProgressBar::chunk {{background:#F46A22;border-radius:3px;}}
        ''')
        # Dynamic property style cache requires repolish after theme switch.
        for button in (self.light_button,self.dark_button):
            button.style().unpolish(button);button.style().polish(button)

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
        first, errors = None, []
        for path in paths:
            key = str(Path(path).expanduser().resolve())
            if key in self.documents:
                continue
            try:
                state = DrawingState(key)
                state.pending_rule = (self._selected_rule()
                    if self.auto_apply_rules.isChecked() else None)
                self.documents[key] = state
                item = QListWidgetItem(f'[{state.kind.upper()}]  {state.path.name}  (읽는 중)')
                item.setData(Qt.ItemDataRole.UserRole, key)
                item.setToolTip(key)
                self.file_list.addItem(item)
                if first is None:
                    first = item
                self._catalog_seq += 1
                task = CatalogTask(self._catalog_seq, key)
                self._catalog_paths[task.seq] = key
                self._submit_catalog(task)
            except DrawingError as exc:
                errors.append(str(exc))
        self._update_file_selection_count()
        if first is not None and self.file_list.currentItem() is None:
            self.file_list.setCurrentItem(first)
        if first is not None:
            self.statusBar().showMessage(
                f'도면 {len(self.documents)}개 등록 · 원본 분석은 백그라운드에서 순차 진행', 10000)
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
        item=self.file_list.currentItem()
        if not item:return
        key=item.data(Qt.ItemDataRole.UserRole)
        doc=self.documents.pop(key,None)
        if doc:doc.close()
        self.file_list.takeItem(self.file_list.row(item))
        self._update_file_selection_count()
        if self.current_doc() is None:
            self.canvas.clear_preview();self.layer_list.clear()
            self.view_info.setText('도면을 추가해 주세요')
            self.view_status.setText('미리보기 대기');self.page_info.setText('0 / 0')
            self._preview_seq+=1;self._detail_seq+=1

    def _selection_changed(self,current,previous):
        doc=self.current_doc()
        self.canvas.clear_preview()
        if doc is not None and not doc.loaded:
            self.layer_list.clear()
            self.view_info.setText(doc.path.name)
            self.view_status.setText('대용량 도면 원본 레이어 정보 백그라운드 분석 중…')
            self.page_info.setText('읽는 중')
            self._preview_seq += 1
            self._detail_seq += 1
            return
        self._layer_change_guard=True
        try:
            self.layer_list.clear()
            if doc:
                for layer in doc.layers():
                    item=QTreeWidgetItem([layer.name,'잠김' if layer.locked else '표시' if layer.visible else '숨김'])
                    item.setData(0,Qt.ItemDataRole.UserRole,layer.key)
                    if layer.locked:
                        item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsUserCheckable)
                    else:
                        item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(0,Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked)
                    self.layer_list.addTopLevelItem(item)
                self.layer_help.setText(f'{len(doc.layers())}개 레이어 · 원본 파일 유지' if doc.layers() else '내부 레이어가 없습니다.')
                self.view_info.setText(doc.path.name)
                self.page_info.setText(f'{doc.page_index+1} / {doc.pages}')
        finally:self._layer_change_guard=False
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
                self.request_preview()
        except DrawingError as exc:
            QMessageBox.warning(self,'레이어 오류',str(exc))
            self._selection_changed(self.file_list.currentItem(),None)

    def set_all_layers(self,visible):
        doc=self.current_doc()
        if not doc:return
        try:
            if doc.set_all(visible):
                self._layer_change_guard=True
                try:
                    states=doc.states()
                    for n in range(self.layer_list.topLevelItemCount()):
                        row=self.layer_list.topLevelItem(n)
                        state=states[row.data(0,Qt.ItemDataRole.UserRole)]
                        row.setCheckState(0,Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)
                        row.setText(1,'표시' if state else '숨김')
                finally:self._layer_change_guard=False
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

    def canvas_fit(self):
        self.canvas.fit_image();self.request_detail()

    def request_preview(self):
        self._preview_seq+=1
        self._detail_seq+=1
        self._preview_pending=True
        self._detail_pending=False
        self.detail_timer.stop()
        self.canvas.clear_detail()
        self.preview_timer.start()

    def _start_preview(self):
        if self._preview_busy or not self._preview_pending:return
        doc=self.current_doc()
        self._preview_pending=False
        if not doc or not doc.loaded:return
        self._preview_busy=True
        self.view_status.setText('레이어 미리보기 렌더링 중…')
        viewport=self.canvas.viewport().size()
        size=(max(240,min(1600,viewport.width()-10)),max(240,min(1300,viewport.height()-10)))
        self._submit(RenderTask('preview',self._preview_seq,str(doc.path),doc.states(),doc.page_index,size))

    def request_detail(self):
        if self.canvas.needs_detail():
            self._detail_pending=True
            self.detail_timer.start()
        else:
            self._detail_pending=False
            self.detail_timer.stop()
            self.canvas.clear_detail()

    def _start_detail(self):
        if self._detail_busy or not self._detail_pending or self._preview_busy or self._preview_pending:return
        doc=self.current_doc()
        if doc is None:return
        clip=self.canvas.visible_clip()
        if clip is None:return
        self._detail_pending=False
        self._detail_busy=True
        self._detail_seq+=1
        viewport=self.canvas.viewport().size()
        w=max(64,round(min(4000,viewport.width()*self.canvas.devicePixelRatioF())))
        h=max(64,round(min(4000,viewport.height()*self.canvas.devicePixelRatioF())))
        self.view_status.setText('확대 영역 고해상도 렌더링 중…')
        self._submit(RenderTask('detail',self._detail_seq,str(doc.path),doc.states(),doc.page_index,(w,h),clip=clip))

    def _update_resolution_controls(self, *_args):
        mode = self.resolution_combo.currentData()
        custom = mode == 'custom'
        self.custom_width.setVisible(custom)
        self.custom_height.setVisible(custom)
        self.custom_dpi.setVisible(mode == 'dpi')

    def _output_options(self) -> OutputOptions:
        mode = self.resolution_combo.currentData() or 'original'
        return OutputOptions(
            fmt='png' if self.png_button.isChecked() else 'jpg',
            resolution=mode,
            width=self.custom_width.value() if mode == 'custom' else None,
            height=self.custom_height.value() if mode == 'custom' else None,
            dpi=self.custom_dpi.value() if mode == 'dpi' else None,
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
        self.progress.setValue(0);self.progress.show()
        self.statusBar().showMessage(f'선택 도면 {len(jobs)}개 원본 해상도로 추출 중…')
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
            self.statusBar().showMessage(f'원본 해상도 이미지 추출 중… {pct}%')

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
        self.progress.hide()

    def _success(self,mode,seq,result):
        self._active_tasks.pop((mode,seq),None)
        if mode=='catalog':
            self._catalog_paths.pop(seq, None)
            path, layers, pages = result
            self._catalog_ready(path, layers, pages)
        elif mode=='preview':
            self._preview_busy=False
            if seq==self._preview_seq and not self._preview_pending:
                try:
                    data,size=result
                    self.canvas.show_png(data,size)
                    doc=self.current_doc()
                    if doc:
                        self.view_status.setText(f'{doc.kind.upper()} · {len(doc.layers())}개 레이어 · '+
                                                 ('표시 변경 반영' if doc.dirty else '원본 표시'))
                    self.request_detail()
                except DrawingError as exc:self.view_status.setText(str(exc))
            if self._preview_pending:self._start_preview()
        elif mode=='detail':
            self._detail_busy=False
            if seq==self._detail_seq and not self._detail_pending and not self._preview_busy:
                try:
                    data,clip=result
                    self.canvas.show_detail(data,clip)
                    self.view_status.setText('확대 영역 원본에서 고해상도 갱신 완료')
                except DrawingError as exc:self.view_status.setText(str(exc))
            if self._detail_pending:self._start_detail()
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
        if mode=='catalog':
            path = self._catalog_paths.pop(seq, None)
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
            if seq==self._preview_seq:self.view_status.setText('미리보기 실패: '+error)
            if self._preview_pending:self._start_preview()
        elif mode=='detail':
            self._detail_busy=False
            if seq==self._detail_seq:self.view_status.setText('확대 렌더링 오류: '+error)
            if self._detail_pending:self._start_detail()
        else:
            self._restore_export_ui()
            if '취소' in error:
                self.statusBar().showMessage('이미지 추출 취소됨. 불완전 파일은 삭제했습니다.',10000)
            else:
                QMessageBox.warning(self,'이미지 추출 실패',error)

    def closeEvent(self,event):
        self.preview_timer.stop();self.detail_timer.stop()
        if self._export_busy and self._export_cancel:self._export_cancel.set()
        if (not self.pool.waitForDone(0) or
                not self.export_pool.waitForDone(0) or
                not self.catalog_pool.waitForDone(0)):
            self.statusBar().showMessage('렌더링 종료 중입니다. 완료 후 다시 닫아주세요.')
            event.ignore();return
        for doc in self.documents.values():doc.close()
        super().closeEvent(event)
