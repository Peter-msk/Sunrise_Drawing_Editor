# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 6.x: use the same dependency scope as BUILD_ONEFILE.cmd.
import argparse
import json
from pathlib import Path
import sys

root = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(root / 'build'))
from lightweight_policy import PROFILES, filter_toc
from lean_policy import LEAN_EXCLUDES, prune_qt

parser = argparse.ArgumentParser()
parser.add_argument('--profile', choices=PROFILES, required=True)
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
              'PySide6.QtWebEngineQuick', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets']
             + (list(LEAN_EXCLUDES) if args.profile == 'lean' else []),
    noarchive=False, optimize=0,
)
a.binaries, removed_binaries = filter_toc(a.binaries, args.profile)
a.datas, removed_datas = filter_toc(a.datas, args.profile)
blocked_qt = []
if args.profile == 'lean':
    a.binaries, extra_removed, blocked_qt = prune_qt(a.binaries)
    removed_binaries += extra_removed
with args.plan.open('x', encoding='utf-8') as report:
    json.dump({'profile': args.profile, 'removed': removed_binaries + removed_datas,
               'graph_excludes': list(LEAN_EXCLUDES) if args.profile == 'lean' else [],
               'dependency_blocked_qt': blocked_qt,
               'note': 'Source bytes are not compressed EXE savings; native import checks do not establish runtime compatibility.'}, report, indent=2)
    report.write('\n')
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
          name='Sunrise Drawing Editor', debug=False, bootloader_ignore_signals=False,
          strip=False, upx=False, console=False,
          icon=str(root / 'assets' / 'app.ico'))
