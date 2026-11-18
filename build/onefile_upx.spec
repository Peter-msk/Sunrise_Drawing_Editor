# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 6.x: use the same dependency scope as BUILD_ONEFILE.cmd.
import argparse
import json
from pathlib import Path
import sys

root = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(root / 'build'))
from lightweight_policy import filter_toc
from compression_policy import upx_selection

parser = argparse.ArgumentParser()
parser.add_argument('--plan', type=Path, required=True)
args = parser.parse_args()

a = Analysis(
    [str(root / 'main.py')], pathex=[str(root)], binaries=[],
    datas=[(str(root / 'assets'), 'assets')],
    hiddenimports=['ezdxf.addons.drawing.pymupdf',
                   'ezdxf.addons.drawing.recorder', 'ezdxf.addons.odafc'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'matplotlib',
              'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtWebEngineQuick', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets'],
    noarchive=False, optimize=0,
)
a.binaries, removed_binaries = filter_toc(a.binaries, 'safe')
a.datas, removed_datas = filter_toc(a.datas, 'safe')
selected, blocked = upx_selection(a.binaries)
if not selected:
    raise RuntimeError('No eligible NumPy BLAS DLLs; use the existing SAFE build')
with args.plan.open('x', encoding='utf-8') as report:
    json.dump({'profile': 'safe', 'removed': removed_binaries + removed_datas,
               'upx_eligible': selected, 'upx_excluded': blocked,
               'note': 'Eligibility is not proof of actual compression; PyInstaller may skip incompatible DLLs.'}, report, indent=2)
    report.write('\n')
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
          name='Sunrise Drawing Editor', debug=False, bootloader_ignore_signals=False,
          strip=False, upx=True, upx_exclude=blocked, console=False,
          icon=str(root / 'assets' / 'app.ico'))
