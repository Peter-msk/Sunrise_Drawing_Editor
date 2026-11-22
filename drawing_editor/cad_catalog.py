"""Bounded, read-only metadata catalog for huge ASCII DXF files.

The LAYER table precedes modelspace entities in standard ASCII DXF. Reading
just this table avoids building a second multi-hundred-MB entity database to
populate the UI file list. Unsupported/ambiguous encodings and nonstandard
structures fall back to ezdxf's authoritative full parser.
"""
from __future__ import annotations

from pathlib import Path
from ezdxf.tools.codepage import toencoding
from ezdxf.lldxf.encoding import decode_dxf_unicode
from .core import LayerInfo

MAX_CATALOG_SCAN = 16 * 1024 * 1024


def read_ascii_dxf_layers(path: str | Path, *, cancelled=None) -> list[LayerInfo] | None:
    """Return exact layer names/default visibility, or None to request fallback.

    No file write; no skipped/guessed names. User-provided filenames and data
    are untrusted. Maximum header/table bytes read is bounded.
    """
    try:
        if cancelled and cancelled():
            raise InterruptedError("등록 취소")
        path = Path(path)
        codepage, acadver = 'ANSI_1252', None
        section = None
        expect_section = expect_table = False
        active_table = None
        layer = None
        layers = []
        header_variable = None

        def finish_layer():
            nonlocal layer
            if layer is not None:
                if layer['name'] is None or not layer['name']:
                    raise ValueError('Layer without a valid name')
                layers.append(layer)
                layer = None

        with path.open('rb') as fp:
            if fp.read(22).startswith(b'AutoCAD Binary DXF'):
                return None
            fp.seek(0)
            pairs = 0
            remaining = MAX_CATALOG_SCAN
            while remaining > 0:
                if pairs % 256 == 0 and cancelled and cancelled():
                    raise InterruptedError("등록 취소")
                pairs += 1
                raw_code = fp.readline(remaining + 1)
                remaining -= len(raw_code)
                if remaining <= 0:
                    return None
                raw_value = fp.readline(remaining + 1)
                if len(raw_value) > remaining:
                    return None
                remaining -= len(raw_value)
                if not raw_code or not raw_value:
                    return None
                code = int(raw_code.strip())
                value = raw_value.rstrip(b'\r\n')
                if code == 0:
                    finish_layer()
                    if value == b'SECTION':
                        expect_section=True
                        section=None
                    elif value == b'ENDSEC':
                        if section == 'TABLES':
                            return None
                        section=None
                    elif value == b'TABLE' and section == 'TABLES':
                        expect_table=True
                        active_table=None
                    elif value == b'ENDTAB' and section == 'TABLES':
                        if active_table == 'LAYER':
                            if not layers:
                                return None
                            # DXF layer names compare case-insensitively.
                            if len({item['name'].casefold() for item in layers}) != len(layers):
                                return None
                            if cancelled and cancelled():
                                raise InterruptedError("등록 취소")
                            return [LayerInfo(item['name'], item['name'],
                                              not (item['flags'] & 1 or item['color'] < 0))
                                    for item in layers]
                        active_table=None
                    elif value == b'LAYER' and section == 'TABLES' and active_table == 'LAYER':
                        layer={'name': None, 'flags': 0, 'color': 7}
                    elif value == b'EOF':
                        return None
                    continue

                if code == 2:
                    if expect_section:
                        section=value.decode('ascii')
                        expect_section=False
                    elif expect_table:
                        active_table=value.decode('ascii')
                        expect_table=False
                    elif layer is not None:
                        if acadver is not None and acadver >= 'AC1021':
                            encoding = 'utf-8'
                        else:
                            encoding = toencoding(codepage)
                        layer['name']=decode_dxf_unicode(value.decode(encoding, errors='strict'))
                elif section == 'HEADER' and code == 9:
                    header_variable=value
                elif section == 'HEADER' and code in (1, 3):
                    if header_variable == b'$DWGCODEPAGE':
                        codepage=value.decode('ascii', errors='strict')
                    elif header_variable == b'$ACADVER':
                        acadver=value.decode('ascii', errors='strict')
                    header_variable=None
                elif layer is not None and code == 70:
                    layer['flags']=int(value)
                elif layer is not None and code == 62:
                    layer['color']=int(value)
    except InterruptedError:
        raise
    except (OSError, UnicodeError, ValueError, OverflowError, KeyError):
        return None
    return None


# Large-file diagnostic: metadata only, never instantiate CAD entities.
# Counts are raw ENTITIES records, not ezdxf modelspace entity counts.
MAX_DIAGNOSTIC_BYTES = 512 * 1024 * 1024
MAX_DIAGNOSTIC_LINE = 1024 * 1024
MAX_DIAGNOSTIC_KEYS = 4096


def inspect_large_ascii_dxf(path, *, check, size):
    """Stream a bounded ASCII DXF record census, rejecting partial/ambiguous scans."""
    from collections import Counter
    from .core import DrawingError
    from ezdxf.tools.codepage import codepage_to_encoding

    if size > MAX_DIAGNOSTIC_BYTES:
        raise DrawingError('대형 DXF 진단은 512MiB 이하 ASCII 형식만 지원합니다.')
    path = Path(path)
    types, layers = Counter(), Counter()
    version = codepage = None
    section = variable = record = layer = None
    units = None
    seen_entities = closed_entities = eof = False
    records = pairs = 0
    remaining = size

    def fail():
        raise DrawingError('대형 ASCII DXF의 레코드 구조 또는 인코딩을 확인할 수 없습니다. 부분 결과는 표시하지 않습니다.')

    def finish():
        nonlocal records, record, layer
        if record is None:
            return
        if layer is None:
            name = '(레이어 코드 없음)'
        else:
            if version is None:
                fail()
            if version >= 'AC1021':
                encoding = 'utf-8'
            elif codepage is None:
                fail()
            else:
                encoding = codepage_to_encoding.get(codepage.removeprefix('ANSI_'))
                if encoding is None:
                    fail()
            name = decode_dxf_unicode(layer.decode(encoding, errors='strict'))
            if not name or len(name) > 1024 or any(ord(c) < 32 for c in name):
                fail()
        types[record] += 1
        layers[name] += 1
        records += 1
        if len(types)+len(layers) > MAX_DIAGNOSTIC_KEYS:
            raise DrawingError('대형 DXF 진단의 레코드 종류·레이어 수가 안전 한도를 초과했습니다.')
        record = layer = None

    try:
        with path.open('rb') as fp:
            if fp.read(22).startswith(b'AutoCAD Binary DXF'):
                raise DrawingError('대형 바이너리 DXF 상세 진단은 지원하지 않습니다.')
            fp.seek(0)
            def line():
                nonlocal remaining
                raw = fp.readline(min(MAX_DIAGNOSTIC_LINE, remaining)+1)
                if len(raw) > min(MAX_DIAGNOSTIC_LINE, remaining):
                    fail()
                remaining -= len(raw)
                return raw
            while remaining:
                if pairs % 4096 == 0:
                    check()
                pairs += 1
                raw_code, raw_value = line(), line()
                if not raw_code or not raw_value:
                    fail()
                code = int(raw_code.strip())
                value = raw_value.rstrip(b'\r\n')
                if code == 999:
                    continue
                if section == 'NEXT':
                    if code != 2:
                        fail()
                    section = value.decode('ascii')
                    if section == 'ENTITIES':
                        if seen_entities:
                            fail()
                        seen_entities = True
                    variable = None
                    continue
                if code == 0:
                    if section == 'ENTITIES':
                        finish()
                    if value == b'SECTION':
                        if section is not None:
                            fail()
                        section = 'NEXT'
                    elif value == b'ENDSEC':
                        if section is None:
                            fail()
                        if section == 'ENTITIES':
                            closed_entities = True
                        section = None
                    elif value == b'EOF':
                        if section is not None or not closed_entities:
                            fail()
                        eof = True
                        break
                    elif section == 'ENTITIES':
                        record = value.decode('ascii')
                        if not record or len(record) > 80 or not record.replace('_','').isalnum():
                            fail()
                    continue
                if section == 'HEADER':
                    if code == 9:
                        variable = value
                    elif variable == b'$ACADVER' and code == 1:
                        version = value.decode('ascii')
                        if len(version) != 6 or not version.startswith('AC') or not version[2:].isdigit():
                            fail()
                    elif variable == b'$DWGCODEPAGE' and code == 3:
                        codepage = value.decode('ascii')
                    elif variable == b'$INSUNITS' and code == 70:
                        units = int(value)
                elif record is not None and code == 8 and layer is None:
                    layer = value
        if not eof or not seen_entities or not closed_entities:
            fail()
    except (ValueError, UnicodeError, OSError, OverflowError) as exc:
        raise DrawingError('대형 ASCII DXF 진단 실패: '+str(exc)[:200]) from exc
    check()
    return {'파일':path.name, '진단 방식':'대형 ASCII DXF 원시 레코드 집계 (정밀 객체 파싱 아님)',
            'DXF 버전':version, 'INSUNITS 코드':units,
            'ENTITIES 레코드 수':records, '레코드 유형별':dict(types),
            '첫 레이어 코드별 레코드 수':dict(layers),
            '주의':'모델 공간·도면 공간·연결 레코드 포함. 미지원 객체도 원시 레코드로 집계하며 정밀 객체 수, 블록 확장, 렌더링 가능 여부, CRS를 판정하지 않습니다.'}
