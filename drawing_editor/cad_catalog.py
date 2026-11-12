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


def read_ascii_dxf_layers(path: str | Path) -> list[LayerInfo] | None:
    """Return exact layer names/default visibility, or None to request fallback.

    No file write; no skipped/guessed names. User-provided filenames and data
    are untrusted. Maximum header/table bytes read is bounded.
    """
    try:
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
            while fp.tell() < MAX_CATALOG_SCAN:
                raw_code = fp.readline()
                raw_value = fp.readline()
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
    except (OSError, UnicodeError, ValueError, OverflowError, KeyError):
        return None
    return None
