"""Preflight for CMD-only Windows onefile builds. No arbitrary python -c quoting."""
from __future__ import annotations
import importlib
import os
import platform
import struct
import sys


def check_python(*, windows_required: bool = True) -> list[str]:
    errors = []
    if sys.version_info < (3, 11):
        errors.append(f"Python >=3.11 required; found {sys.version.split()[0]}")
    if struct.calcsize('P') * 8 != 64:
        errors.append('64-bit Python required.')
    if windows_required and os.name != 'nt':
        errors.append('Windows is required to build a Windows onefile executable.')
    return errors


def check_dependencies(*, include_build: bool = True) -> list[str]:
    modules = ['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
               'fitz', 'ezdxf', 'PIL']
    if include_build:
        modules.extend(['PyInstaller', 'cryptography'])
    errors = []
    for mod in modules:
        try:
            importlib.import_module(mod)
        except Exception as exc:
            errors.append(f'{mod}: {exc.__class__.__name__}: {exc}')
    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in ('python', 'dependencies', 'runtime'):
        print('Usage: preflight.py python|dependencies|runtime', file=sys.stderr)
        return 2
    if argv[1] == 'python':
        errors = check_python()
        print(f'Python={sys.version.split()[0]}  architecture={struct.calcsize("P") * 8}-bit  '
              f'executable={sys.executable}')
    else:
        errors = check_dependencies(include_build=(argv[1] == 'dependencies'))
        print('Dependencies: ' + ('OK' if not errors else 'MISSING / BROKEN'))
    for error in errors:
        print('[ERROR]', error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
