"""Source-preserving vector exports, deliberately distinct from raster output.

PDF is a visibility snapshot, NOT redaction. SVG is a visual page conversion.
DXF is a fresh modelspace geometry file, not a full CAD project clone.
"""
from pathlib import Path
import os
import tempfile

from .core import DrawingError, source_signature, verify_source

VECTOR_FORMATS = frozenset(('pdf', 'svg', 'dxf'))
DXF_SOURCE_LIMIT = 16 * 1024 * 1024
DXF_ENTITIES = frozenset(('LINE', 'POINT', 'CIRCLE', 'ARC', 'LWPOLYLINE', 'ELLIPSE', 'SPLINE', '3DFACE', 'SOLID', 'TEXT', 'MTEXT', 'HATCH', 'INSERT'))


def check_vector_source(kind, options, size):
    if options.fmt not in VECTOR_FORMATS:
        return
    if (options.fmt in ('pdf', 'svg') and kind != 'pdf') or (options.fmt == 'dxf' and kind != 'dxf'):
        raise DrawingError('PDF/SVG 출력은 PDF 원본, DXF 출력은 DXF 원본만 지원합니다.')
    if options.fmt == 'dxf' and size > DXF_SOURCE_LIMIT:
        raise DrawingError('선택 DXF 출력은 16MiB 이하 원본만 지원합니다.')


def _check_states(states, original, locked=()):
    if (not isinstance(states, dict) or states.keys() != original.keys() or
            any(type(k) not in (int, str) for k in states) or
            any(type(v) is not bool for v in states.values()) or
            any(states[k] != original[k] for k in locked)):
        raise DrawingError('원본 레이어 정보 또는 잠김 상태가 일치하지 않습니다. 다시 불러오세요.')


def _pdf_export(source, states, page_index, temporary, fmt, checkpoint):
    import fitz
    scratch = None
    try:
        with fitz.open(str(source)) as pdf:
            if not pdf.is_pdf or pdf.needs_pass or not 0 <= page_index < pdf.page_count:
                raise DrawingError('읽을 수 없는 PDF 또는 페이지입니다.')
            raw = pdf.get_ocgs() or {}
            original = {key: bool(value.get('on', True)) for key, value in raw.items()}
            config = pdf.get_layer() if raw else {}
            locked = config.get('locked') or ()
            _check_states(states, original, locked)
            page = pdf[page_index]
            geometry = (tuple(page.rect), page.rotation)
            del page
            if fmt == 'svg' and not raw:
                # With no OCG configuration to persist, the original page is
                # already the requested rendering context. Avoid rewriting it.
                checkpoint()
                svg = pdf[page_index].get_svg_image(text_as_path=True)
                checkpoint()
                temporary.write_text(svg, encoding='utf-8')
                return
            pdf.select([page_index])
            if raw:
                pdf.set_layer(-1, basestate='OFF', on=[k for k,v in states.items() if v],
                              off=[k for k,v in states.items() if not v])
            checkpoint()
            # Reopen the saved snapshot so MuPDF applies the default OCG config.
            # For SVG use a disk-backed intermediate instead of a full PDF byte
            # copy in memory; do not modify the registered source file.
            if fmt == 'svg':
                with tempfile.NamedTemporaryFile(dir=temporary.parent, prefix=f'.drawing-{os.getpid()}-', suffix='.pdf', delete=False) as f:
                    scratch = Path(f.name)
            pdf.save(str(scratch or temporary), garbage=1, deflate=True)
        checkpoint()
        with fitz.open(str(scratch or temporary)) as result:
            observed = {k: bool(v.get('on', True)) for k,v in (result.get_ocgs() or {}).items()}
            if result.page_count != 1 or observed != states:
                raise DrawingError('PDF 출력 페이지 또는 레이어 상태 검증에 실패했습니다.')
            page = result[0]
            if (tuple(page.rect), page.rotation) != geometry:
                raise DrawingError('PDF 출력 페이지 크기 또는 회전정보가 일치하지 않습니다.')
            if raw:
                observed_config = result.get_layer()
                if any((observed_config.get(key) or []) != (config.get(key) or [])
                       for key in ('locked', 'rbgroups')):
                    raise DrawingError('PDF 잠김 또는 상호 배타 레이어 정보가 일치하지 않습니다.')
            if fmt == 'svg':
                svg = result[0].get_svg_image(text_as_path=True)
                checkpoint()
                temporary.write_text(svg, encoding='utf-8')
    finally:
        if scratch is not None:
            scratch.unlink(missing_ok=True)


def _dxf_export(source, states, page_index, temporary, checkpoint):
    import ezdxf
    from ezdxf.addons import Importer
    if page_index != 0:
        raise DrawingError('DXF는 모델 공간만 지원합니다.')
    cad = ezdxf.readfile(str(source))
    original = {str(layer.dxf.name): not (layer.is_off() or layer.is_frozen()) for layer in cad.layers}
    _check_states(states, original)
    selected = {name.casefold() for name, visible in states.items() if visible}
    known = {name.casefold() for name in states}
    # Validate the entire selected dependency closure before copying. A block
    # with a hidden child layer must not silently re-enable that child.
    entities = []
    used = set()
    styles = set()
    linetypes = set()
    blocks = {}
    visiting = set()
    unsupported = set()
    def check_linetype(name):
        if name not in cad.linetypes:
            raise DrawingError(f'선 유형 정의 누락: {name}')
        if cad.linetypes.get(name).pattern_tags.is_complex_type():
            raise DrawingError(f'복합 선 유형은 정확한 리소스 보존을 지원하지 않습니다: {name}')
        linetypes.add(name)

    def inspect_entity(entity, depth=0):
        name = str(entity.dxf.get('layer', '0'))
        key = name.casefold()
        if key not in known:
            raise DrawingError(f'레이어 테이블에 없는 객체: {name}')
        if key not in selected:
            raise DrawingError(f'블록 내부에 선택하지 않은 레이어가 있습니다: {name}')
        kind = entity.dxftype()
        if kind not in DXF_ENTITIES:
            unsupported.add(kind)
            return
        if kind in ('TEXT', 'MTEXT', 'HATCH', 'INSERT') and (entity.xdata or entity.appdata or entity.has_extension_dict):
            raise DrawingError(f'복합 객체의 XDATA·확장정보는 지원하지 않습니다: {kind}')
        check_linetype(entity.dxf.get('linetype', 'BYLAYER'))
        used.add(name)
        if kind in ('TEXT', 'MTEXT'):
            style = entity.dxf.get('style', 'Standard')
            if style not in cad.styles:
                raise DrawingError(f'문자 스타일 정의 누락: {style}')
            styles.add(style)
            if kind == 'MTEXT' and entity.has_columns:
                raise DrawingError('다단 MTEXT는 지원하지 않습니다.')
        elif kind == 'HATCH':
            if entity.dxf.associative or any(path.source_boundary_objects for path in entity.paths):
                raise DrawingError('연관 해치 및 경계 객체 참조는 지원하지 않습니다.')
        elif kind == 'INSERT':
            if entity.attribs or entity.has_extension_dict:
                raise DrawingError('속성 또는 확장정보가 있는 블록 참조는 지원하지 않습니다.')
            block_name = entity.dxf.name
            key = block_name.casefold()
            if key in visiting or depth >= 32:
                raise DrawingError(f'순환 또는 과도한 중첩 블록: {block_name}')
            if key in blocks:
                return
            if block_name not in cad.blocks:
                raise DrawingError(f'블록 정의 누락: {block_name}')
            block = cad.blocks.get(block_name)
            if (block_name.startswith('*') or block.block.dxf.flags or block.block.dxf.xref_path
                    or block.block.has_extension_dict or block.block_record.has_extension_dict):
                raise DrawingError(f'외부 참조·동적·특수 블록은 지원하지 않습니다: {block_name}')
            visiting.add(key)
            for i, child in enumerate(block):
                if i % 256 == 0:
                    checkpoint()
                inspect_entity(child, depth + 1)
            visiting.remove(key)
            blocks[key] = block

    for i, entity in enumerate(cad.modelspace()):
        if i % 256 == 0:
            checkpoint()
        name = str(entity.dxf.get('layer', '0'))
        key = name.casefold()
        if key not in known:
            raise DrawingError(f'레이어 테이블에 없는 객체: {name}')
        if key in selected:
            inspect_entity(entity)
            entities.append(entity)
    if unsupported:
        raise DrawingError('선택 레이어의 미지원 객체: '+', '.join(sorted(unsupported))+' (누락 없이 출력하려면 PNG/JPG를 사용하세요.)')
    if not entities:
        raise DrawingError('선택 레이어에 출력 가능한 모델 공간 객체가 없습니다.')
    for name in used:
        check_linetype(cad.layers.get(name).dxf.linetype)
    target = ezdxf.new(cad.dxfversion)
    for name in ('$INSUNITS', '$MEASUREMENT', '$LTSCALE', '$INSBASE'):
        if name in cad.header and name in target.header:
            target.header[name] = cad.header[name]
    importer = Importer(cad, target)
    model = target.modelspace()
    for i, entity in enumerate(entities):
        if i % 256 == 0:
            checkpoint()
        importer.import_entity(entity, model)
    imported = len(entities)
    # Import used layer definitions including layer 0, then resolve linetypes.
    importer.import_table('layers', used, replace=True)
    # Importer normally skips existing target defaults. Update them as well
    # (notably Standard font attributes) to preserve the source definitions.
    for name in styles:
        if name in target.styles:
            # The fresh document already references Standard by handle (e.g.
            # MLEADERSTYLE). Replacing the record invalidates those references.
            entry = target.styles.get(name)
            attributes = cad.styles.get(name).dxf.all_existing_dxf_attribs()
            for key in entry.dxf.all_existing_dxf_attribs().keys() - attributes.keys():
                entry.dxf.discard(key)
            entry.dxf.update({k: v for k, v in attributes.items() if k not in ('handle', 'owner', 'name')})
        else:
            importer.import_table('styles', [name])
    importer.import_table('linetypes', linetypes, replace=True)
    importer.finalize()
    # Importer copies the BLOCK header but not BLOCK_RECORD flags/units.
    block_fields = ('units', 'explode', 'scale')
    for block in blocks.values():
        copied = target.blocks.get(block.name)
        for field in block_fields:
            copied.block_record.dxf.set(field, block.block_record.dxf.get_default(field))
    for name in used:
        layer = target.layers.get(name)
        layer.on(); layer.thaw()
    if len(model) != imported:
        raise DrawingError('DXF 객체 복사 개수가 일치하지 않습니다.')
    checkpoint()
    target.saveas(str(temporary))
    checkpoint()
    # Do not claim full CAD validation; this catches missing entities/tables.
    result = ezdxf.readfile(str(temporary))
    audit = result.audit()
    # Audit repairs are in-memory only. A repairable invalid file is still
    # invalid on disk: never report it as a successful exact geometry export.
    if len(result.modelspace()) != imported or audit.has_errors or audit.fixes:
        raise DrawingError('DXF 결과 구조 검증에 실패했습니다 (오류 또는 자동 수정 필요).')
    # An audit alone cannot detect a dropped block child or changed font.
    from ezdxf.lldxf.tagwriter import TagCollector
    def geometry_tags(entity):
        return [(tag.code, tag.value) for tag in TagCollector.dxftags(entity)
                if tag.code not in (5, 330, 390, 347, 348)]

    def verify_entities(before, after):
        for i, (a, b) in enumerate(zip(before, after)):
            if i % 256 == 0:
                checkpoint()
            if a.dxftype() != b.dxftype() or geometry_tags(a) != geometry_tags(b):
                raise DrawingError(f'DXF 결과 객체 데이터 불일치: {a.dxftype()}')

    verify_entities(entities, result.modelspace())
    for block in blocks.values():
        checkpoint()
        name = block.name
        # Static named blocks must retain their name and ordered entity types.
        if name not in result.blocks:
            raise DrawingError(f'DXF 결과 블록 정의 누락: {name}')
        copied = result.blocks.get(name)
        if (copied.block.dxf.base_point != block.block.dxf.base_point or
                any(copied.block_record.dxf.get_default(f) != block.block_record.dxf.get_default(f) for f in block_fields) or
                [e.dxftype() for e in copied] != [e.dxftype() for e in block]):
            raise DrawingError(f'DXF 결과 블록 구성 불일치: {name}')
        verify_entities(block, copied)
    for name in styles:
        a = cad.styles.get(name).dxf
        b = result.styles.get(name).dxf
        fields = ('font', 'bigfont', 'height', 'width', 'oblique', 'flags', 'generation_flags')
        if any(a.get_default(k) != b.get_default(k) for k in fields):
            raise DrawingError(f'DXF 결과 문자 스타일 불일치: {name}')


def export_vector_snapshot(path, states, page_index, destination, options, *, progress=None,
                           cancelled=None, expected_source=None):
    source = Path(path).expanduser().resolve(strict=True)
    expected = source_signature(source) if expected_source is None else expected_source
    def checkpoint():
        if cancelled and cancelled():
            raise InterruptedError('도면 출력이 취소되었습니다.')
        verify_source(source, expected)
    checkpoint()
    options.checked()
    if options.fmt not in VECTOR_FORMATS:
        raise DrawingError('벡터 출력 형식만 지원합니다.')
    check_vector_source(source.suffix.lower().lstrip('.'), options, expected[2])
    if type(page_index) is not int:
        raise DrawingError('페이지 번호가 유효하지 않습니다.')
    requested = Path(destination).expanduser()
    target = requested.parent.resolve() / requested.name
    if target.suffix.lower() != '.'+options.fmt or not target.parent.is_dir() or os.path.lexists(target):
        raise DrawingError('출력 확장자·경로를 확인하세요. 기존 파일은 덮어쓰지 않습니다.')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f'.drawing-{os.getpid()}-', suffix=target.suffix, delete=False) as f:
            temporary = Path(f.name)
        if options.fmt == 'dxf':
            _dxf_export(source, states, page_index, temporary, checkpoint)
        else:
            _pdf_export(source, states, page_index, temporary, options.fmt, checkpoint)
        if progress:
            progress(1.)
        checkpoint()
        os.link(temporary, target)
        return str(target)
    except InterruptedError:
        raise
    except (OSError, ValueError, MemoryError) as exc:
        raise DrawingError(f'벡터 출력 실패: {exc}') from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
