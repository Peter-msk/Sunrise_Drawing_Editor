"""Capture reproducible Windows PySide6 light/dark UI evidence.

Run once per QT_SCALE_FACTOR. This program never changes source DXF/PDF/DWG.
Real operator review is required; screenshot success != UI acceptance.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scale', type=float, choices=(1.0, 1.25, 1.5, 1.75), required=True)
    parser.add_argument('--output', type=Path, default=Path('quality/P0_runtime/UI_STAGE8'))
    parser.add_argument('--width', type=int, default=1180)
    parser.add_argument('--height', type=int, default=760)
    args = parser.parse_args(argv)
    os.environ['QT_SCALE_FACTOR'] = str(args.scale)

    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
    from PySide6 import __version__ as qt_version
    from drawing_editor.window import DrawingWindow

    app = QApplication([sys.argv[0]])
    window = DrawingWindow()
    window.resize(args.width, args.height)
    window.show()
    app.processEvents()
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    try:
        for theme in ('light', 'dark'):
            window.set_theme(theme)
            app.processEvents()
            out = args.output / f'UI_STAGE8_{theme}_{str(args.scale).replace(".", "p")}.png'
            pix = window.grab()
            ok = pix.save(str(out), 'PNG')
            issues = []
            for label in window.findChildren(QLabel):
                if not label.isVisible() or not label.text().strip():
                    continue
                if label.objectName() in {'panelHeader', 'panelSubheader', 'zoomInfo', 'pageInfo'}:
                    rect = label.contentsRect()
                    if rect.width() <= 0 or rect.height() <= 0:
                        issues.append(f'{label.objectName()} has an invalid drawing area')
            records.append({'theme': theme, 'scale_requested': args.scale,
                            'screenshot': str(out), 'saved': bool(ok),
                            'pixel_size': [pix.width(), pix.height()],
                            'visible_labels': sum(x.isVisible() for x in window.findChildren(QLabel)),
                            'visible_buttons': sum(x.isVisible() for x in window.findChildren(QPushButton)),
                            'basic_geometry_warnings': issues})
            if not ok:
                raise RuntimeError(f'Qt screenshot failed: {out}')
    finally:
        window.close()
        app.processEvents()
        app.quit()
    report = {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'os_name': os.name, 'qt_version': qt_version,
              'status': 'SCREENSHOTS_CAPTURED_NOT_VISUALLY_APPROVED',
              'source_state': 'Use quality/qa_exact_branch.py before running this script',
              'records': records,
              'remaining': ['human screenshot comparison', 'real DXF and OnMap visual layer QA',
                            'Windows onedir/onefile installer and signature']}
    target = args.output / f'UI_STAGE8_{str(args.scale).replace(".", "p")}.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('SAVED', target)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
