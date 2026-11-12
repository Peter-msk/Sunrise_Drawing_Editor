"""Manual Windows/Qt UI visual QA: screenshot plus widget geometry evidence.

Example (Windows CMD, with PySide6 installed):
    python quality/qa_gui_layout.py --width 1100 --height 700 --scale-label 125

This test uses the actual PySide6 widgets. It does not depend on the MCP server.
For a simulated scaling pass set QT_SCALE_FACTOR in the shell *before*
launching Python; this is not a substitute for Windows OS DPI QA.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QWidget, QPushButton, QLineEdit, QComboBox, QListWidget, QTreeWidget, QSpinBox, QRadioButton, QCheckBox

# Allow invocation from the repository root or an arbitrary working directory.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from drawing_editor.window import DrawingWindow  # noqa: E402


def capture(width: int, height: int, output: Path, scale_label: str) -> bool:
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName('Sunrise Drawing Editor UI QA')
    window = DrawingWindow()
    window.resize(width, height)
    window.show()
    app.processEvents()
    app.processEvents()
    targets = {
        'files': window.file_list,
        'selected_remove': window.remove_selected_button,
        'all_layers_on': window.layer_on_button,
        'all_layers_off': window.layer_off_button,
        'layer_search': window.layer_search,
        'layers': window.layer_list,
        'rule_apply': window.apply_rule_button,
        'preview': window.canvas,
        'export': window.export_button,
        'output_browse': window.browse_button,
        'output_folder': window.output_folder,
        'resolution': window.resolution_combo,
        'png_transparency': window.transparent_png,
    }
    results = {}
    client_rect = window.rect()
    for name, widget in targets.items():
        origin = widget.mapTo(window, QPoint(0, 0))
        rect = QRect(origin, widget.size())
        # A nested scroll area may intentionally clip long lists. Primary
        # export controls and settings must *always* remain fully reachable.
        must_fit = name in {'export', 'output_folder', 'resolution', 'png_transparency'}
        results[name] = {
            'visible': widget.isVisibleTo(window),
            'rect': [rect.x(), rect.y(), rect.width(), rect.height()],
            'inside_main_window': client_rect.contains(rect),
            'accessible_name': widget.accessibleName(),
            'pass': widget.isVisibleTo(window) and rect.width() > 50 and
                    rect.height() > 15 and (not must_fit or client_rect.contains(rect)),
        }
    if window.canvas.width() < 300:
        results['preview']['pass'] = False
    # Qt-MCP-inspired introspection: stable object names, visibility, geometry,
    # enabled state and accessibility, not just a screenshot of the top window.
    classes = (QPushButton, QLineEdit, QComboBox, QListWidget, QTreeWidget,
               QSpinBox, QRadioButton, QCheckBox)
    interactive = []
    for widget in window.findChildren(QWidget):
        if not isinstance(widget, classes):
            continue
        name = widget.objectName()
        if not name or name.startswith('qt_'):
            continue
        point = widget.mapTo(window, QPoint(0, 0))
        interactive.append({
            'name': name,
            'type': type(widget).__name__,
            'parent': widget.parentWidget().objectName() if widget.parentWidget() else '',
            'geometry': [point.x(), point.y(), widget.width(), widget.height()],
            'visible': widget.isVisibleTo(window),
            'enabled': widget.isEnabled(),
            'accessible_name': widget.accessibleName(),
        })
    names = [entry['name'] for entry in interactive]
    repeated = sorted({name for name in names if names.count(name) > 1})
    output.mkdir(parents=True, exist_ok=True)
    screenshot = output / f'ui_{scale_label}_{width}x{height}.png'
    screenshot_ok = window.grab().save(str(screenshot), 'PNG')
    report = {
        'tool': 'Sunrise native Qt layout QA',
        'scale_label': scale_label,
        'python': sys.version.split()[0],
        'platform': platform.platform(),
        'screen_dpr': window.devicePixelRatioF(),
        'window_logical_size': [window.width(), window.height()],
        'viewport_scroll_needed': window.work_scroll.verticalScrollBar().maximum() > 0,
        'widgets': results,
        'interactive_widget_tree': interactive,
        'duplicate_interactive_object_names': repeated,
        'screenshot': screenshot.name if screenshot_ok else None,
        'pass': bool(screenshot_ok) and not repeated and all(v['pass'] for v in results.values()),
        'limitations': 'Screen capture and geometry only; Windows DPI and visual clipping must be manually reviewed.',
    }
    (output / f'ui_{scale_label}_{width}x{height}.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    window.close()
    return report['pass']


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--width', type=int, default=1100)
    parser.add_argument('--height', type=int, default=700)
    parser.add_argument('--scale-label', default='system')
    parser.add_argument('--output', type=Path, default=ROOT / 'quality' / 'ui_qa_artifacts')
    args = parser.parse_args()
    passed = capture(args.width, args.height, args.output, str(args.scale_label))
    print(f'GUI geometry/capture: {"PASS" if passed else "FAIL"}; see {args.output}')
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
