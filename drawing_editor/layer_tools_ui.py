"""Small native dialogs; the drawing state and rendering engine remain owners."""
from dataclasses import replace
from pathlib import Path
import json
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QVBoxLayout, QFormLayout,
    QLabel, QComboBox, QLineEdit, QListWidget, QListWidgetItem, QAbstractItemView,
    QTreeWidget, QTreeWidgetItem, QPushButton, QHBoxLayout, QMessageBox, QFileDialog, QPlainTextEdit, QScrollArea, QFrame, QWidget, QCheckBox, QSpinBox)

from .layer_tools import GROUP_NAMES, group_layers, common_layers, apply_group, apply_common_layers, page_indices
from .core import DrawingError, OutputOptions
from .drawing_analysis import load_profile, save_profile, structure_report
from .ui_interaction import advanced_fields
from .ui_design import THEMES
from PySide6.QtGui import QColor, QPalette
from .vector_export import check_vector_source


def export_message_box(parent, title, message, *, theme='light', ask=False):
    """Show extraction confirmations with the same body colors as the main UI."""
    t = THEMES[theme if theme in THEMES else 'light']
    dialog = QMessageBox(parent)
    dialog.setObjectName('drawingExportMessageBox')
    dialog.setWindowTitle(title)
    dialog.setText(message)
    dialog.setTextFormat(Qt.TextFormat.PlainText)
    dialog.setIcon(QMessageBox.Icon.Question if ask else QMessageBox.Icon.Warning)
    if ask:
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setObjectName('drawingConfirmYes')
    else:
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
    palette = dialog.palette()
    for role, color in ((QPalette.ColorRole.Window, t.panel),
                        (QPalette.ColorRole.WindowText, t.foreground),
                        (QPalette.ColorRole.Base, t.input_background),
                        (QPalette.ColorRole.Text, t.foreground),
                        (QPalette.ColorRole.Button, t.input_background),
                        (QPalette.ColorRole.ButtonText, t.foreground)):
        palette.setColor(role, QColor(color))
    dialog.setPalette(palette)
    dialog.setAutoFillBackground(True)
    dialog.setStyleSheet(f"""
        QMessageBox#drawingExportMessageBox {{background:{t.panel};color:{t.foreground};
            font-family:"Malgun Gothic","Noto Sans CJK KR",sans-serif;font-size:12px;}}
        QMessageBox#drawingExportMessageBox QLabel {{color:{t.foreground};background:transparent;}}
        QMessageBox#drawingExportMessageBox QPushButton {{background:{t.input_background};
            color:{t.foreground};border:1px solid {t.border};border-radius:5px;
            padding:5px 12px;min-width:78px;min-height:24px;}}
        QMessageBox#drawingExportMessageBox QPushButton:hover {{background:{t.hover};
            border-color:{t.primary};}}
        QMessageBox#drawingExportMessageBox QPushButton#drawingConfirmYes {{background:{t.primary};
            color:#FFFFFF;border-color:{t.primary};font-weight:700;}}
        QMessageBox#drawingExportMessageBox QPushButton#drawingConfirmYes:hover {{background:{t.primary_hover};}}
    """)
    return dialog


class AdvancedExportDialog(QDialog):
    """Compact output planner; PDF region comes from a drag on the live canvas."""
    regionPickRequested = Signal()

    def __init__(self, parent, rules, options, docs, *, viewport=None, theme='light'):
        super().__init__(parent)
        self.setObjectName('advancedExportDialog')
        self.setWindowTitle('레이어·페이지 조합 추출')
        screen = self.screen()
        area = screen.availableGeometry() if screen is not None else None
        available_width = area.width() if area else 1280
        self.setMinimumWidth(min(420, max(320, available_width-40)))
        self.resize(min(510, max(320, available_width-40)), 520)
        self.rules = rules
        self.base_options = options
        self.docs = docs
        self.viewport_region = viewport  # freshness/availability only, not export geometry
        self._selected_region = None
        self.apply_theme(theme)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 13, 14, 12)
        layout.setSpacing(9)
        # Settings always scroll; the action footer stays visible at every DPI.
        scroller = QScrollArea(self)
        scroller.setObjectName('advancedSettingsScroll')
        self.settings_scroll = scroller
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setWidgetResizable(True)
        container = QWidget(scroller)
        container.setObjectName('advancedSettingsBody')
        content = QVBoxLayout(container)
        content.setContentsMargins(1, 1, 4, 1)
        content.setSpacing(7)
        scroller.setWidget(container)
        layout.addWidget(scroller, 1)
        form = QFormLayout()
        self.form = form
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(7)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.format = QComboBox()
        self.format.addItem('기존 PNG/JPG 출력 설정', 'raster')
        if all(d.kind == 'pdf' for d in docs):
            self.format.addItem('PDF · 표시 상태 보존', 'pdf')
            self.format.addItem('SVG · 표시 결과 벡터 변환', 'svg')
        if all(d.kind == 'dxf' for d in docs):
            self.format.addItem('DXF · 선택 객체 보존', 'dxf')
        form.addRow('출력 종류', self.format)

        # Ordinary and combination exports share the exact same raster contract.
        # These controls begin with the main window's current PNG/JPG options.
        self.raster_format = QComboBox()
        self.raster_format.setObjectName('advancedRasterFormat')
        self.raster_format.addItem('PNG', 'png')
        self.raster_format.addItem('JPG', 'jpg')
        self.raster_resolution = QComboBox()
        self.raster_resolution.setObjectName('advancedRasterResolution')
        for title, value in [('원본 자동', 'original'), ('HD · 1280×720', 'hd'),
                             ('FHD · 1920×1080', 'fhd'), ('QHD · 2560×1440', 'qhd'),
                             ('4K · 3840×2160', 'uhd'), ('직접 입력', 'custom'),
                             ('DPI 직접 입력', 'dpi')]:
            self.raster_resolution.addItem(title, value)
        self.raster_dimensions = QWidget(self)
        dims = QHBoxLayout(self.raster_dimensions)
        dims.setContentsMargins(0, 0, 0, 0)
        dims.setSpacing(6)
        self.raster_width = QSpinBox(self)
        self.raster_width.setRange(1, 2_147_483_647)
        self.raster_width.setPrefix('W ')
        self.raster_width.setSuffix(' px')
        self.raster_height = QSpinBox(self)
        self.raster_height.setRange(1, 2_147_483_647)
        self.raster_height.setPrefix('H ')
        self.raster_height.setSuffix(' px')
        dims.addWidget(self.raster_width, 1)
        dims.addWidget(self.raster_height, 1)
        self.raster_dpi = QSpinBox(self)
        self.raster_dpi.setRange(36, 2400)
        self.raster_dpi.setSuffix(' DPI')
        self.raster_flags = QWidget(self)
        flags = QHBoxLayout(self.raster_flags)
        flags.setContentsMargins(0, 0, 0, 0)
        flags.setSpacing(18)
        self.raster_alpha = QCheckBox('투명 배경', self)
        self.raster_alpha.setObjectName('advancedTransparent')
        self.raster_trim = QCheckBox('흰 여백 제거', self)
        self.raster_trim.setObjectName('advancedCropMargins')
        flags.addWidget(self.raster_alpha)
        flags.addWidget(self.raster_trim)
        flags.addStretch(1)
        self.raster_note = QLabel(self)
        self.raster_note.setObjectName('advancedRasterNote')
        self.raster_note.setWordWrap(True)
        form.addRow('이미지 형식', self.raster_format)
        form.addRow('해상도', self.raster_resolution)
        form.addRow('크기 (최대)', self.raster_dimensions)
        form.addRow('DPI', self.raster_dpi)
        form.addRow('PNG 옵션', self.raster_flags)
        form.addRow('', self.raster_note)
        self._trim_preference = False
        self._load_raster_controls(options)

        self.mode = QComboBox()
        for title, value in [('현재 레이어 상태', 'current'), ('켜진 레이어 각각 분리', 'layers'),
                             ('분류 그룹별 분리', 'groups'), ('저장 규칙별 분리', 'rules')]:
            self.mode.addItem(title, value)
        form.addRow('추출 방식', self.mode)
        self.scope = QComboBox()
        for title, value in [('현재 페이지', 'current'), ('모든 페이지', 'all'), ('지정 범위', 'range')]:
            self.scope.addItem(title, value)
        form.addRow('페이지', self.scope)
        self.page_range = QLineEdit()
        self.page_range.setMaxLength(24)
        self.page_range.setPlaceholderText('예: 1-5 또는 3')
        form.addRow('페이지 범위', self.page_range)

        self.effect = QComboBox()
        self.effect.addItem('전체 페이지', 'none')
        if all(d.kind == 'pdf' for d in docs):
            self.effect.addItem('화면에서 지정한 영역', 'region')
        form.addRow('추출 영역', self.effect)
        self.region_row = QWidget(self)
        region_layout = QHBoxLayout(self.region_row)
        region_layout.setContentsMargins(0, 0, 0, 0)
        region_layout.setSpacing(8)
        self.select_region_button = QPushButton('화면에서 드래그 지정')
        self.select_region_button.setObjectName('regionPickButton')
        self.select_region_button.setToolTip('메인 PDF 미리보기에서 마우스로 사각형을 드래그하세요. Esc나 오른쪽 클릭으로 취소합니다.')
        self.select_region_button.clicked.connect(lambda _checked=False: self.regionPickRequested.emit())
        region_layout.addWidget(self.select_region_button)
        self.region_summary = QLabel('선택 영역 없음')
        self.region_summary.setObjectName('regionSummary')
        self.region_summary.setWordWrap(True)
        region_layout.addWidget(self.region_summary, 1)
        form.addRow('영역 지정', self.region_row)
        content.addLayout(form)

        self.profile_hint = QLabel()
        self.profile_hint.setObjectName('exportProfileHint')
        self.profile_hint.setWordWrap(True)
        content.addWidget(self.profile_hint)

        self.items = QListWidget()
        self.items.setObjectName('advancedExportItems')
        self.items.setAccessibleName('추출할 그룹 또는 저장 규칙')
        self.items.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.items.setMinimumHeight(94)
        self.items.setMaximumHeight(140)
        content.addWidget(self.items)
        self.check_actions = QWidget()
        checks = QHBoxLayout(self.check_actions)
        checks.setContentsMargins(0, 0, 0, 0)
        self.check_count = QLabel('선택 0개')
        checks.addWidget(self.check_count, 1)
        for title, state in [('전체 선택', Qt.CheckState.Checked), ('해제', Qt.CheckState.Unchecked)]:
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, v=state: self._check_all(v))
            checks.addWidget(button)
        content.addWidget(self.check_actions)
        self.items.itemChanged.connect(self._update_check_count)

        self.info = QLabel('')
        self.info.setObjectName('advancedExportInfo')
        self.info.setWordWrap(True)
        content.addWidget(self.info)

        profile_row = QHBoxLayout()
        profile_row.setSpacing(8)
        profile_row.addStretch(1)
        for title, handler in [('프로파일 저장', self._save_profile), ('프로파일 불러오기', self._load_profile)]:
            button = QPushButton(title)
            button.clicked.connect(handler)
            profile_row.addWidget(button)
        layout.addLayout(profile_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('추출 계획 확인')
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName('advancedExportConfirm')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소')
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.mode.currentIndexChanged.connect(self._refresh)
        self.scope.currentIndexChanged.connect(self._scope_changed)
        self.format.currentIndexChanged.connect(self._format_changed)
        self.effect.currentIndexChanged.connect(self._effect_changed)
        self.raster_format.currentIndexChanged.connect(self._raster_changed)
        self.raster_resolution.currentIndexChanged.connect(self._raster_changed)
        self.raster_alpha.toggled.connect(self._raster_changed)
        self.raster_trim.toggled.connect(self._raster_trim_toggled)
        for spin in (self.raster_width, self.raster_height, self.raster_dpi):
            spin.valueChanged.connect(self._raster_changed)
        self._refresh()
        self._format_changed()
        self._scope_changed()
        self._resize_for_mode()
        # Refresh real child-widget palettes after construction as well.
        self.apply_theme(theme)

    def apply_theme(self, mode):
        """Use the parent's actual design tokens, not native Windows dialog colors."""
        self._theme = mode if mode in THEMES else 'light'
        t = THEMES[self._theme]
        tick_icon = (Path(__file__).resolve().parents[1] / 'assets' / 'checkbox_tick_white.svg').as_posix()
        pal = self.palette()
        for role, color in ((QPalette.ColorRole.Window,t.panel),
                            (QPalette.ColorRole.WindowText,t.foreground),
                            (QPalette.ColorRole.Base,t.input_background),
                            (QPalette.ColorRole.Text,t.foreground),
                            (QPalette.ColorRole.Button,t.input_background),
                            (QPalette.ColorRole.ButtonText,t.foreground),
                            (QPalette.ColorRole.PlaceholderText,t.muted)):
            pal.setColor(role,QColor(color))
        self.setPalette(pal)
        self.setAutoFillBackground(True)
        scroller = getattr(self, 'settings_scroll', None)
        if scroller is not None:
            scroller.setPalette(pal)
            scroller.setAutoFillBackground(True)
            scroller.viewport().setPalette(pal)
            scroller.viewport().setAutoFillBackground(True)
            scroller.widget().setPalette(pal)
            scroller.widget().setAutoFillBackground(True)
        self.setStyleSheet(f'''
            QDialog#advancedExportDialog {{background:{t.panel};color:{t.foreground};
                font-family:"Malgun Gothic","Noto Sans CJK KR",sans-serif;font-size:12px;}}
            QDialog#advancedExportDialog QWidget {{color:{t.foreground};}}
            QDialog#advancedExportDialog QLabel#exportProfileHint,
            QDialog#advancedExportDialog QLabel#advancedExportInfo,
            QDialog#advancedExportDialog QLabel#regionSummary,
            QDialog#advancedExportDialog QLabel#advancedRasterNote {{color:{t.muted};}}
            QDialog#advancedExportDialog QScrollArea#advancedSettingsScroll,
            QDialog#advancedExportDialog QWidget#advancedSettingsBody,
            QDialog#advancedExportDialog QScrollArea#advancedSettingsScroll QWidget#qt_scrollarea_viewport {{background:{t.panel};}}
            QDialog#advancedExportDialog QLineEdit,
            QDialog#advancedExportDialog QSpinBox,
            QDialog#advancedExportDialog QComboBox,
            QDialog#advancedExportDialog QListWidget {{background:{t.input_background};color:{t.foreground};
                border:1px solid {t.border};border-radius:5px;padding:5px 7px;min-height:22px;}}
            QDialog#advancedExportDialog QListWidget {{padding:3px;}}
            QDialog#advancedExportDialog QComboBox::drop-down {{background:{t.input_background};border:0;width:22px;}}
            QDialog#advancedExportDialog QComboBox QAbstractItemView {{background:{t.input_background};
                color:{t.foreground};selection-background-color:{t.selection};}}
            QDialog#advancedExportDialog QPushButton {{background:{t.input_background};color:{t.foreground};
                border:1px solid {t.border};border-radius:5px;padding:5px 9px;min-height:23px;}}
            QDialog#advancedExportDialog QPushButton:hover {{background:{t.hover};border-color:{t.primary};}}
            QDialog#advancedExportDialog QPushButton:disabled {{background:{t.background};
                color:{t.muted};border-color:{t.border};}}
            QDialog#advancedExportDialog QPushButton:focus {{border:2px solid {t.primary};}}
            QDialog#advancedExportDialog QPushButton#advancedExportConfirm {{background:{t.primary};
                color:#FFFFFF;border-color:{t.primary};font-weight:700;}}
            QDialog#advancedExportDialog QPushButton#advancedExportConfirm:hover {{background:{t.primary_hover};}}
            QDialog#advancedExportDialog QPushButton#regionPickButton {{border-color:{t.primary};}}
            QDialog#advancedExportDialog QCheckBox {{color:{t.foreground};spacing:7px;}}
            QDialog#advancedExportDialog QCheckBox:disabled {{color:{t.muted};}}
            QDialog#advancedExportDialog QCheckBox::indicator {{width:16px;height:16px;
                border:1px solid {t.muted};border-radius:4px;background:{t.input_background};}}
            QDialog#advancedExportDialog QCheckBox::indicator:checked {{background:{t.primary};border-color:{t.primary};image:url("{tick_icon}");}}
            QDialog#advancedExportDialog QCheckBox::indicator:disabled {{border-color:{t.border};background:{t.background};}}
            QDialog#advancedExportDialog QListWidget::indicator {{width:16px;height:16px;}}
            QDialog#advancedExportDialog QListWidget::indicator:checked {{background:{t.primary};image:url("{tick_icon}");}}
            QDialog#advancedExportDialog QScrollBar:vertical {{background:{t.background};width:12px;}}
            QDialog#advancedExportDialog QScrollBar::handle:vertical {{background:{t.border};border-radius:5px;}}
        ''')

    def _resize_for_mode(self):
        screen = self.screen()
        limit = (screen.availableGeometry().height() - 42) if screen else 720
        target = 585 if self.mode.currentData() in ('groups', 'rules') else (555 if self.effect.currentData() == 'region' else 510)
        self.resize(self.width(), min(max(310, limit), target))

    def set_drag_region(self, region):
        """Called only after a valid drag on the current PDF canvas."""
        from .ui_interaction import normalized_drag_region
        region = normalized_drag_region((1., 1.), region[:2], region[2:]) if region is not None and len(region) == 4 else None
        if region is None:
            raise DrawingError('유효한 사각형 영역을 다시 선택하세요.')
        self._selected_region = region
        width, height = (region[2]-region[0])*100, (region[3]-region[1])*100
        self.region_summary.setText(f'선택 완료 · 가로 {width:.1f}% · 세로 {height:.1f}%')
        self.region_summary.setToolTip('현재 PDF에서 지정한 상대 영역을 출력 대상 PDF에 동일한 비율로 적용합니다. 원본 파일은 변경하지 않습니다.')

    def _load_raster_controls(self, options):
        """Restore exact ordinary-export raster values, including saved profiles."""
        self.base_options = options
        fmt = options.fmt if options.fmt in ('png', 'jpg') else 'png'
        self.raster_format.setCurrentIndex(self.raster_format.findData(fmt))
        self.raster_resolution.setCurrentIndex(self.raster_resolution.findData(options.resolution))
        self.raster_width.setValue(options.width if options.width is not None else 1920)
        self.raster_height.setValue(options.height if options.height is not None else 1080)
        self.raster_dpi.setValue(options.dpi if options.dpi is not None else 300)
        self.raster_alpha.setChecked(options.background == 'transparent')
        self._trim_preference = options.crop_margins
        self.raster_trim.setChecked(options.crop_margins)

    def _raster_trim_toggled(self, checked):
        if self.raster_trim.isEnabled():
            self._trim_preference = bool(checked)
        self._raster_changed()

    def _raster_changed(self, *_args):
        raster = self.format.currentData() == 'raster'
        png = raster and self.raster_format.currentData() == 'png'
        full_page = self.effect.currentData() != 'region'
        self.raster_alpha.setEnabled(png)
        self.raster_trim.setEnabled(png and full_page)
        self.raster_trim.blockSignals(True)
        try:
            self.raster_trim.setChecked(self._trim_preference if png and full_page else False)
        finally:
            self.raster_trim.blockSignals(False)
        size_mode = self.raster_resolution.currentData()
        self.form.setRowVisible(self.raster_dimensions, raster and size_mode == 'custom')
        self.form.setRowVisible(self.raster_dpi, raster and size_mode == 'dpi')
        self._update_hint()

    def _format_changed(self):
        raster = self.format.currentData() == 'raster'
        if not raster:
            self.effect.setCurrentIndex(0)
        self.form.setRowVisible(self.effect, raster and self.effect.count() > 1)
        for field in (self.raster_format, self.raster_resolution,
                      self.raster_flags, self.raster_note):
            self.form.setRowVisible(field, raster)
        self._effect_changed()
        self._raster_changed()

    def _update_hint(self):
        fmt = self.format.currentData()
        if fmt != 'raster':
            self.profile_hint.setText({
                'pdf':'원본 페이지·벡터·레이어 표시 상태 보존. 숨김 레이어 및 기타 원본 데이터가 남습니다. 보안 삭제용이 아닙니다.',
                'svg':'PDF 표시 결과 변환. 문자는 경로, 원본 래스터는 이미지로 남습니다. 좌표체계는 보존하지 않습니다.',
                'dxf':'16MiB 이하 DXF의 기본 객체·문자·비연관 해치·제한된 정적 블록 복사. 참조 레이어·리소스 불일치 시 실패. 도면 공간·CRS 미지원.'}[fmt])
            return
        image_fmt = self.raster_format.currentData()
        region = self.effect.currentData() == 'region'
        if image_fmt == 'jpg':
            note = 'JPG는 흰색 배경으로 저장합니다. 투명 배경과 자동 여백 제거는 PNG 전용입니다.'
        elif region:
            note = '화면에서 지정한 사각형 밖은 제외합니다. 이 동작은 흰 여백 자동 제거와 별개이며, 지정 영역에서는 자동 제거를 사용할 수 없습니다.'
        else:
            note = ('투명 배경과 흰 여백 제거는 서로 다른 기능입니다. '
                    '여백 제거를 켜면 각 출력물의 픽셀 크기가 달라질 수 있습니다.')
        self.raster_note.setText(note)
        crop = '적용' if image_fmt == 'png' and not region and self._trim_preference else '미적용'
        bg = '투명' if image_fmt == 'png' and self.raster_alpha.isChecked() else '흰색'
        self.profile_hint.setText(f'현재 설정: {image_fmt.upper()} · 배경 {bg} · 여백 제거 {crop}')

    def _scope_changed(self):
        self._sync_region_controls()

    def _sync_region_controls(self):
        page_range, region, available = advanced_fields(self.format.currentData(), self.scope.currentData(),
                                                         self.effect.currentData(), self.viewport_region is not None)
        self.form.setRowVisible(self.page_range, page_range)
        self.form.setRowVisible(self.region_row, region)
        self.select_region_button.setEnabled(available)
        if region and not available:
            self.select_region_button.setToolTip('선택된 PDF 중 현재 미리보기·현재 페이지에서만 영역을 그릴 수 있습니다.')
        else:
            self.select_region_button.setToolTip('메인 미리보기에서 드래그하여 사각형 영역을 지정합니다. Esc로 취소합니다.')

    def _effect_changed(self):
        self._sync_region_controls()
        self._raster_changed()
        self._resize_for_mode()

    def options(self):
        if self.format.currentData() != 'raster':
            return OutputOptions(fmt=self.format.currentData()).checked()
        mode = self.effect.currentData()
        if mode == 'region' and self._selected_region is None:
            raise DrawingError('영역을 지정하려면 「화면에서 드래그 지정」을 눌러 미리보기에서 사각형을 그리세요.')
        png = self.raster_format.currentData() == 'png'
        resolution = self.raster_resolution.currentData()
        return replace(self.base_options,
                       fmt=self.raster_format.currentData(), resolution=resolution,
                       width=self.raster_width.value() if resolution == 'custom' else None,
                       height=self.raster_height.value() if resolution == 'custom' else None,
                       dpi=self.raster_dpi.value() if resolution == 'dpi' else None,
                       background='transparent' if png and self.raster_alpha.isChecked() else 'opaque',
                       crop_margins=bool(png and mode != 'region' and self.raster_trim.isChecked()),
                       region=self._selected_region if mode == 'region' else None).checked()

    def _save_profile(self):
        try:
            opts, params = self._validated_settings()
            path, _ = QFileDialog.getSaveFileName(self,'작업 프로파일 저장','','Sunrise 프로파일 (*.sdeprofile)')
            if path:
                if not path.lower().endswith('.sdeprofile'): path += '.sdeprofile'
                save_profile(path,opts,mode=params['mode'],scope=params['scope'],page_range=params['page_range'],groups=params['groups'],rules=[r.name for r in params['rules']])
        except (DrawingError, OSError, ValueError) as exc: export_message_box(self,'프로파일 저장 오류',str(exc),theme=self._theme).exec()

    def _load_profile(self):
        path, _ = QFileDialog.getOpenFileName(self,'작업 프로파일 불러오기','','Sunrise 프로파일 (*.sdeprofile)')
        if not path: return
        try:
            opts, data = load_profile(path)
            effect = 'region' if opts.region else 'none'
            fmt = 'raster' if opts.fmt in ('png','jpg') else opts.fmt
            if self.format.findData(fmt) < 0 or self.effect.findData(effect) < 0 or not set(data['rules']) <= self.rules.keys():
                raise DrawingError('도면 형식 또는 저장 규칙이 현재 작업과 일치하지 않습니다.')
            for doc in self.docs:
                page_indices(doc, data['scope'], data['page_range'])
                check_vector_source(doc.kind, opts, doc.source_signature[2])
            if fmt == 'raster': self._load_raster_controls(opts)
            self.format.setCurrentIndex(self.format.findData(fmt)); self._format_changed()
            self.mode.setCurrentIndex(self.mode.findData(data['mode']))
            self.scope.setCurrentIndex(self.scope.findData(data['scope'])); self.page_range.setText(data['page_range'])
            self._refresh()
            names = set(data['groups'] + data['rules'])
            self.items.blockSignals(True)
            try:
                for i in range(self.items.count()):
                    item = self.items.item(i)
                    item.setCheckState(Qt.CheckState.Checked if item.text() in names else Qt.CheckState.Unchecked)
            finally:
                self.items.blockSignals(False)
            self._update_check_count()
            self.effect.setCurrentIndex(self.effect.findData(effect)); self._effect_changed()
            self._selected_region = None
            self.region_summary.setText('선택 영역 없음')
            if opts.region:
                self.set_drag_region(opts.region)
            self._raster_changed()
        except (DrawingError, OSError, ValueError) as exc: export_message_box(self,'프로파일 불러오기 오류',str(exc),theme=self._theme).exec()

    def _refresh(self):
        mode=self.mode.currentData()
        values=GROUP_NAMES if mode=='groups' else sorted(self.rules) if mode=='rules' else ()
        self.items.blockSignals(True)
        try:
            self.items.clear()
            for value in values:
                item = QListWidgetItem(value)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self.items.addItem(item)
        finally:
            self.items.blockSignals(False)
        self.items.setVisible(bool(values))
        self.check_actions.setVisible(bool(values))
        self._update_check_count()
        self.info.setText('그룹·규칙은 체크박스로 복수 선택합니다. 잠김·누락·중복은 계획 단계에서 안내합니다.'
                          if mode!='current' else '현재 레이어 표시 상태를 그대로 사용합니다. 원본 파일은 변경하지 않습니다.')
        self._resize_for_mode()

    def _checked_names(self):
        return [self.items.item(i).text() for i in range(self.items.count())
                if self.items.item(i).checkState() == Qt.CheckState.Checked]

    def _update_check_count(self, *_args):
        self.check_count.setText(f'선택 {len(self._checked_names())}개 / {self.items.count()}개')

    def _check_all(self, state):
        self.items.blockSignals(True)
        try:
            for i in range(self.items.count()): self.items.item(i).setCheckState(state)
        finally:
            self.items.blockSignals(False)
        self._update_check_count()

    def _validated_settings(self):
        params = self.parameters()
        if params['mode'] in ('groups','rules') and not (params['groups'] or params['rules']):
            raise DrawingError('추출할 그룹 또는 규칙을 선택하세요.')
        opts = self.options()
        for doc in self.docs:
            page_indices(doc, params['scope'], params['page_range'])
            check_vector_source(doc.kind, opts, doc.source_signature[2])
        return opts, params

    def _validate(self):
        try:
            self._validated_settings()
        except DrawingError as exc:
            export_message_box(self,'영역·출력 설정 오류',str(exc),theme=self._theme).exec(); return
        self.accept()

    def parameters(self):
        mode=self.mode.currentData(); names=self._checked_names()
        return dict(mode=mode,scope=self.scope.currentData(),page_range=self.page_range.text() if self.scope.currentData()=='range' else '',
                    groups=names if mode=='groups' else (),rules=[self.rules[n] for n in names] if mode=='rules' else ())


def group_dialog(parent, doc):
    dialog=QDialog(parent);dialog.setWindowTitle('현재 도면 레이어 그룹');dialog.resize(440,400)
    layout=QVBoxLayout(dialog);hint=QLabel('이름의 키워드 기반 분류입니다. 불확실한 레이어는 미분류로 표시하며 자동 변경하지 않습니다.');hint.setWordWrap(True);layout.addWidget(hint)
    tree=QTreeWidget();tree.setHeaderLabels(['그룹 / 레이어','상태']);tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection);layout.addWidget(tree)
    for group, layers in group_layers(doc.layers()).items():
        head=QTreeWidgetItem([f'{group} ({len(layers)})','']);head.setData(0,Qt.ItemDataRole.UserRole,group);tree.addTopLevelItem(head)
        for layer in layers:
            child=QTreeWidgetItem([layer.name,'잠김' if layer.locked else '표시' if layer.visible else '숨김']);head.addChild(child)
    actions=QHBoxLayout();layout.addLayout(actions);changed=0
    def apply(visible):
        nonlocal changed
        item=tree.currentItem()
        if item is None:
            QMessageBox.information(dialog,'그룹 선택','변경할 그룹을 선택하세요.');return
        group=(item.parent() or item).data(0,Qt.ItemDataRole.UserRole)
        if not group:return
        changed=apply_group(doc,group,visible)
        if changed:dialog.accept()
        else:QMessageBox.information(dialog,'변경 없음','변경 가능한 레이어가 없거나 이미 요청한 표시 상태입니다.')
    for title,visible in [('선택 그룹 켜기',True),('선택 그룹 끄기',False)]:
        button=QPushButton(title);button.clicked.connect(lambda checked=False,v=visible:apply(v));actions.addWidget(button)
    close=QPushButton('닫기');close.clicked.connect(dialog.reject);actions.addWidget(close)
    dialog.exec();return changed


def common_dialog(parent, docs):
    common=common_layers(docs)
    if not common:
        QMessageBox.information(parent,'공통 레이어 없음','모든 선택 도면에 유일하게 존재하는 변경 가능 공통 레이어가 없습니다.');return 0
    dialog=QDialog(parent);dialog.setWindowTitle('다중 도면 공통 레이어');dialog.resize(440,400)
    layout=QVBoxLayout(dialog);hint=QLabel(f'{len(docs)}개 도면 · {len(common)}개 공통 레이어\n동일 이름이 모든 도면에 한 번씩 존재하고 잠겨 있지 않은 항목만 표시합니다.');hint.setWordWrap(True);layout.addWidget(hint)
    listing=QListWidget();listing.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection);layout.addWidget(listing)
    for key,name in common.items():
        item=QListWidgetItem(name);item.setData(Qt.ItemDataRole.UserRole,key);listing.addItem(item)
    actions=QHBoxLayout();layout.addLayout(actions);changed=0
    def apply(visible):
        nonlocal changed
        keys=[item.data(Qt.ItemDataRole.UserRole) for item in listing.selectedItems()]
        if not keys:
            QMessageBox.information(dialog,'레이어 선택','변경할 공통 레이어를 선택하세요.');return
        changed=apply_common_layers(docs,keys,visible)
        if changed:dialog.accept()
        else:QMessageBox.information(dialog,'변경 없음','선택 레이어가 이미 요청한 표시 상태입니다.')
    for title,visible in [('선택 레이어 켜기',True),('선택 레이어 끄기',False)]:
        button=QPushButton(title);button.clicked.connect(lambda checked=False,v=visible:apply(v));actions.addWidget(button)
    close=QPushButton('닫기');close.clicked.connect(dialog.reject);actions.addWidget(close)
    dialog.exec();return changed


def report_dialog(parent, docs):
    try:
        report = {'drawings': [structure_report(d) for d in docs],
                  'note': '등록 정보 기반 추출 진단입니다. 객체·CRS·좌표 범위는 확인하지 않습니다.'}
    except (DrawingError, OSError, ValueError) as exc:
        QMessageBox.warning(parent,'도면 분석 오류',str(exc)); return
    dialog=QDialog(parent); dialog.setWindowTitle('도면 정보 및 추출 진단'); dialog.resize(600,460)
    layout=QVBoxLayout(dialog)
    hint=QLabel('선택 도면의 등록 정보와 현재 표시 상태입니다.');hint.setWordWrap(True);layout.addWidget(hint)
    def describe(row):
        return (f'{row["name"]} · {row["format"]} · {row["bytes"]:,} bytes\n'
                f'페이지 {row["pages"]} · 레이어 {row["layers"]} · 표시 {row["visible"]} · 잠김 {row["locked"]}\n'
                '그룹: '+', '.join(f'{k} {v}개' for k,v in row['groups'].items())+'\n'
                '중복 이름: '+(', '.join(row['duplicate_names']) or '없음')+f' · 이름 없음 {row["unnamed"]}개')
    body='\n\n'.join(describe(row) for row in report['drawings'])+'\n\n'
    text=QPlainTextEdit();text.setReadOnly(True);text.setPlainText(body+'\n'+report['note']);layout.addWidget(text,1)
    actions=QHBoxLayout()
    if len(docs)==1 and docs[0].kind in ('pdf','dxf'):
        button=QPushButton('원본 상세 분석');button.clicked.connect(lambda:dialog.done(2));actions.addWidget(button)
    close=QPushButton('닫기');close.clicked.connect(dialog.reject);actions.addWidget(close);layout.addLayout(actions)
    return dialog.exec()


def detail_report_dialog(parent, result):
    dialog=QDialog(parent);dialog.setWindowTitle('원본 상세 분석');dialog.resize(580,440)
    layout=QVBoxLayout(dialog);text=QPlainTextEdit();text.setReadOnly(True)
    text.setPlainText('\n'.join(f'{key}: '+(json.dumps(value,ensure_ascii=False,indent=2) if isinstance(value,(dict,list)) else str(value)) for key,value in result.items()));layout.addWidget(text,1)
    close=QPushButton('닫기');close.clicked.connect(dialog.accept);layout.addWidget(close);dialog.exec()

