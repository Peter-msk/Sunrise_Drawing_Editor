"""Build-only Windows version resource generation and read-only verification."""
from __future__ import annotations

import ast
import ctypes
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
TRANSLATION = (0x0412, 1200)  # Korean (Korea), Unicode
TABLE = '041204b0'


def expected_version(root=ROOT):
    # One source of truth; do not import the application or trigger network I/O.
    tree = ast.parse((root / 'drawing_editor/release_feed.py').read_text(encoding='utf-8'))
    assignments = [n.value for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'APP_VERSION' for t in n.targets)]
    if len(assignments) != 1:
        raise ValueError('Expected exactly one APP_VERSION definition')
    version = ast.literal_eval(assignments[0])
    if not isinstance(version, str) or not re.fullmatch(r'(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})', version):
        raise ValueError('Invalid APP_VERSION for Windows resource')
    fixed = [*map(int, version.split('.')), 0]
    if max(fixed) > 65535:
        raise ValueError('Windows version components must be <= 65535')
    return {'fixed_file_version': fixed, 'fixed_product_version': fixed.copy(),
            'translation': list(TRANSLATION), 'strings': {
                'CompanyName': 'Sunrise Group',
                'FileDescription': 'Sunrise Drawing Editor',
                'FileVersion': '.'.join(map(str, fixed)),
                'InternalName': 'Sunrise Drawing Editor',
                'LegalCopyright': '© 2026 Sunrise Group. All rights reserved.',
                'OriginalFilename': 'Sunrise Drawing Editor.exe',
                'ProductName': 'Sunrise Drawing Editor',
                'ProductVersion': version,
            }}


def write_version_resource(path, *, root=ROOT):
    expected = expected_version(root)
    v = tuple(expected['fixed_file_version'])
    strings = ',\n      '.join(f'StringStruct({k!r}, {value!r})' for k, value in expected['strings'].items())
    path.write_text(
        f'VSVersionInfo(ffi=FixedFileInfo(filevers={v!r}, prodvers={v!r}, '\
        'mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n'\
        f'  kids=[StringFileInfo([StringTable({TABLE!r}, [\n      {strings}\n  ])]),\n'\
        f'    VarFileInfo([VarStruct(\'Translation\', {list(TRANSLATION)!r})])])\n',
        encoding='utf-8')
    return expected


def read_version_resource(exe):
    """Use Windows' native version.dll (the same resource Explorer reads)."""
    if sys.platform != 'win32':
        raise OSError('Native Windows version-resource verification requires Windows')
    from ctypes import wintypes as w
    api = ctypes.WinDLL('version', use_last_error=True)
    size_fn = api.GetFileVersionInfoSizeW
    size_fn.argtypes = [w.LPCWSTR, ctypes.POINTER(w.DWORD)]
    size_fn.restype = w.DWORD
    get_fn = api.GetFileVersionInfoW
    get_fn.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p]
    get_fn.restype = w.BOOL
    query_fn = api.VerQueryValueW
    query_fn.argtypes = [ctypes.c_void_p, w.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.UINT)]
    query_fn.restype = w.BOOL
    name = str(Path(exe).resolve())
    handle = w.DWORD()
    size = size_fn(name, ctypes.byref(handle))
    if not size:
        raise ValueError('Missing Windows VERSIONINFO resource')
    buffer = ctypes.create_string_buffer(size)
    if not get_fn(name, 0, size, buffer):
        raise ctypes.WinError(ctypes.get_last_error())

    def query(key):
        ptr, count = ctypes.c_void_p(), w.UINT()
        if not query_fn(buffer, key, ctypes.byref(ptr), ctypes.byref(count)) or not ptr.value or not count.value:
            raise ValueError('Missing VERSIONINFO field: ' + key)
        return ptr, count.value

    ptr, count = query('\\')
    if count < 52:
        raise ValueError('Truncated VS_FIXEDFILEINFO')
    fixed = struct.unpack('<13I', ctypes.string_at(ptr, 52))
    if fixed[0] != 0xFEEF04BD or fixed[9] != 1:
        raise ValueError('Invalid executable fixed version resource')

    def components(ms, ls):
        return [ms >> 16, ms & 0xffff, ls >> 16, ls & 0xffff]

    ptr, count = query('\\VarFileInfo\\Translation')
    if count != 4:
        raise ValueError('Unexpected version translation size')
    translation = list(struct.unpack('<HH', ctypes.string_at(ptr, count)))
    table = '%04x%04x' % tuple(translation)
    strings = {}
    for key in expected_version()['strings']:
        ptr, count = query('\\StringFileInfo\\' + table + '\\' + key)
        strings[key] = ctypes.wstring_at(ptr, count).rstrip('\x00')
    return {'fixed_file_version': components(fixed[2], fixed[3]),
            'fixed_product_version': components(fixed[4], fixed[5]),
            'translation': translation, 'strings': strings}


def verify_version_resource(exe, *, root=ROOT):
    expected = expected_version(root)
    actual = read_version_resource(exe)
    if actual != expected:
        mismatches = [key for key in expected if actual.get(key) != expected[key]]
        raise ValueError('EXE version resource mismatch: ' + ', '.join(mismatches))
    return actual
