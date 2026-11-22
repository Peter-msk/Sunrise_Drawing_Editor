"""Small native dialogs; the drawing state and rendering engine remain owners."""
from dataclasses import replace
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QVBoxLayout, QFormLayout,
    QLabel, QComboBox, QLineEdit, QListWidget, QListWidgetItem, QAbstractItemView,
    QTreeWidget, QTreeWidgetItem, QPushButton, QHBoxLayout, QMessageBox, QFileDialog, QPlainTextEdit, QScrollArea, QWidget)

from .layer_tools import GROUP_NAMES, group_layers, common_layers, apply_group, apply_common_layers, page_indices
from .core import DrawingError, OutputOptions
from .drawing_analysis import load_profile, save_profile, structure_report
from .ui_interaction import advanced_fields
from .vector_export import check_vector_source


class AdvancedExportDialog(QDialog):
    def __init__(self, parent, rules, options, docs, *, viewport=None):
        super().__init__(parent)
        self.setWindowTitle('레이어·페이지 조합 추출')
        self.setMinimumSize(340, 260)
        screen = self.screen()
        if screen is not None:
            area = screen.availableGeometry()
            self.resize(min(500, max(340, area.width()-32)),
                        min(440, max(260, area.height()-48)))
        else:
            self.resize(500, 440)
        self.rules = rules
        self.base_options = options
        self.docs = docs
        self.viewport_region = viewport
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(6)
        scroll = QScrollArea(self); scroll.setWidgetResizable(True)
        body = QWidget(); content = QVBoxLayout(body)
        content.setContentsMargins(2, 2, 2, 2); content.setSpacing(6)
        scroll.setWidget(body); layout.addWidget(scroll, 1)
        form = QFormLayout(); self.form = form
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.format = QComboBox()
        self.format.addItem('기존 PNG/JPG 출력 설정', 'raster')
        if all(d.kind == 'pdf' for d in docs):
            self.format.addItem('PDF · 표시 상태 보존', 'pdf')
            self.format.addItem('SVG · 표시 결과 벡터 변환', 'svg')
        if all(d.kind == 'dxf' for d in docs):
            self.format.addItem('DXF · 선택 객체 보존', 'dxf')
        form.addRow('출력 형식', self.format)
        self.mode = QComboBox()
        for title, value in [('현재 레이어 상태', 'current'), ('켜진 레이어 각각 분리', 'layers'),
                             ('분류 그룹별 분리', 'groups'), ('저장 규칙별 분리', 'rules')]:
            self.mode.addItem(title, value)
        self.scope = QComboBox()
        for title, value in [('현재 페이지', 'current'), ('모든 페이지', 'all'), ('지정 범위', 'range')]:
            self.scope.addItem(title, value)
        self.page_range = QLineEdit(); self.page_range.setMaxLength(24); self.page_range.setPlaceholderText('예: 1-5 또는 3')
        form.addRow('추출 방식', self.mode);form.addRow('페이지', self.scope);form.addRow('범위', self.page_range)
        self.effect = QComboBox()
        self.effect.addItem('전체 페이지', 'none')
        if all(d.kind == 'pdf' for d in docs): self.effect.addItem('PDF 지정 영역', 'region')
        self.effect_value = QLineEdit(); self.effect_value.setMaxLength(1100)
        form.addRow('추출 영역', self.effect); form.addRow('영역 좌표 (%)', self.effect_value)
        self.viewport_button = QPushButton('현재 미리보기 범위 사용')
        self.viewport_button.setToolTip('메인 화면에서 확대·이동한 현재 PDF 페이지의 표시 범위를 사용합니다. 화면 캡처가 아닌 원본 영역 출력입니다.')
        self.viewport_button.clicked.connect(self._use_viewport)
        form.addRow('', self.viewport_button)
        self.effect.currentIndexChanged.connect(self._effect_changed)
        content.addLayout(form)
        self.profile_hint = QLabel(); self.profile_hint.setWordWrap(True); content.addWidget(self.profile_hint)
        profiles = QHBoxLayout()
        for title, handler in [('프로파일 저장…', self._save_profile), ('프로파일 불러오기…', self._load_profile)]:
            b = QPushButton(title); b.clicked.connect(handler); profiles.addWidget(b)
        content.addLayout(profiles)
        self.items = QListWidget();self.items.setAccessibleName('추출할 그룹 또는 저장 규칙')
        self.items.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.items.setMinimumHeight(100)
        content.addWidget(self.items, 1)
        self.check_actions = QWidget(); checks = QHBoxLayout(self.check_actions)
        checks.setContentsMargins(0, 0, 0, 0)
        self.check_count = QLabel('선택 0개'); checks.addWidget(self.check_count, 1)
        for title, state in [('전체 선택', Qt.CheckState.Checked), ('해제', Qt.CheckState.Unchecked)]:
            button = QPushButton(title); button.clicked.connect(lambda checked=False, v=state: self._check_all(v)); checks.addWidget(button)
        content.addWidget(self.check_actions)
        self.items.itemChanged.connect(self._update_check_count)
        self.info = QLabel('');self.info.setWordWrap(True);content.addWidget(self.info)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('추출 계획 확인')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소')
        buttons.accepted.connect(self._validate);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.mode.currentIndexChanged.connect(self._refresh)
        self.scope.currentIndexChanged.connect(self._scope_changed)
        self.format.currentIndexChanged.connect(self._format_changed)
        self._refresh(); self._format_changed(); self._scope_changed()

    def _format_changed(self):
        raster = self.format.currentData() == 'raster'
        if not raster:
            self.effect.setCurrentIndex(0)
        self.form.setRowVisible(self.effect, raster and self.effect.count() > 1)
        self._effect_changed()
        self._update_hint()

    def _update_hint(self):
        fmt = self.format.currentData()
        if fmt != 'raster':
            self.profile_hint.setText({
                'pdf':'원본 페이지·벡터·레이어 표시 상태 보존. 숨김 레이어 및 기타 원본 데이터가 남습니다. 보안 삭제용이 아닙니다.',
                'svg':'PDF 표시 결과 변환. 문자는 경로, 원본 래스터는 이미지로 남습니다. 좌표체계는 보존하지 않습니다.',
                'dxf':'16MiB 이하 DXF의 기본 객체·문자·비연관 해치·제한된 정적 블록 복사. 참조 레이어·리소스 불일치 시 실패. 도면 공간·CRS 미지원.'}[fmt])
            return
        o = self.base_options
        size = f'{o.width}×{o.height}' if o.resolution == 'custom' else f'{o.dpi} DPI' if o.resolution == 'dpi' else o.resolution
        self.profile_hint.setText(f'출력 설정: {o.fmt.upper()} / {size} / {o.background} · 프로파일은 이 창의 출력 조건만 변경합니다.')

    def _scope_changed(self):
        self._sync_viewport_button()

    def _sync_viewport_button(self):
        page_range, region, viewport = advanced_fields(self.format.currentData(), self.scope.currentData(),
                                                        self.effect.currentData(), self.viewport_region is not None)
        self.form.setRowVisible(self.page_range, page_range)
        self.form.setRowVisible(self.effect_value, region)
        self.form.setRowVisible(self.viewport_button, region)
        self.viewport_button.setEnabled(viewport)

    def _use_viewport(self):
        if self.viewport_button.isEnabled():
            self.effect_value.setText(','.join(format(v*100,'.15g') for v in self.viewport_region))

    def _effect_changed(self):
        mode = self.effect.currentData()
        self._sync_viewport_button()
        self.effect_value.setPlaceholderText('왼쪽, 위, 오른쪽, 아래 % (예: 10,20,80,90)' if mode == 'region' else '')

    def options(self):
        if self.format.currentData() != 'raster':
            return OutputOptions(fmt=self.format.currentData()).checked()
        mode, raw = self.effect.currentData(), self.effect_value.text().strip()
        region = None
        if mode == 'region':
            try: region = tuple(float(v.strip())/100 for v in raw.split(','))
            except ValueError as exc: raise DrawingError('영역 좌표 4개를 %로 입력하세요.') from exc
        return replace(self.base_options, region=region,
                       crop_margins=self.base_options.crop_margins and mode != 'region' and self.mode.currentData() == 'current').checked()

    def _save_profile(self):
        try:
            opts, params = self._validated_settings()
            path, _ = QFileDialog.getSaveFileName(self,'작업 프로파일 저장','','Sunrise 프로파일 (*.sdeprofile)')
            if path:
                if not path.lower().endswith('.sdeprofile'): path += '.sdeprofile'
                save_profile(path,opts,mode=params['mode'],scope=params['scope'],page_range=params['page_range'],groups=params['groups'],rules=[r.name for r in params['rules']])
        except (DrawingError, OSError, ValueError) as exc: QMessageBox.warning(self,'프로파일 저장 오류',str(exc))

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
            if fmt == 'raster': self.base_options = opts
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
            self.effect_value.setText(','.join(format(v*100,'.15g') for v in opts.region) if opts.region else '')
            self._update_hint()
        except (DrawingError, OSError, ValueError) as exc: QMessageBox.warning(self,'프로파일 불러오기 오류',str(exc))

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
        self.info.setText('그룹·규칙은 체크박스로 복수 선택합니다. 단독 추출은 지정 이외 레이어를 끄며, '
                          '잠김·누락·중복은 계획 오류로 안내합니다. PDF의 비레이어 콘텐츠는 남을 수 있습니다. '
                          'CAD의 좌표 정렬은 보장하지 않습니다.' if mode!='current' else
                          '현재 레이어 상태를 유지하고 지정 페이지를 원본에서 다시 렌더링합니다.')

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
            QMessageBox.warning(self,'영역·출력 설정 오류',str(exc)); return
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

