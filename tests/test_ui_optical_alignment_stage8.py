"""Static Qt style-order and SVG optical-alignment tests.

Real Windows PySide6 screenshots (100/125/150/175% DPI) are a separate gate.
CairoSVG is optional; no product dependency added.
"""
from __future__ import annotations
from pathlib import Path
from io import BytesIO
import importlib.util
import unittest
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


class ThemePrecedence(unittest.TestCase):
    def test_specific_labels_follow_generic_fallback(self):
        code = (ROOT / 'drawing_editor' / 'window.py').read_text('utf-8')
        broad = code.index('QWidget#drawingRoot QLabel,QWidget#drawingRoot QCheckBox')
        specific = code.index('QLabel#panelHeader {{font-size:14px')
        hint = code.index('QLabel#hint {{color:{muted}')
        self.assertLess(broad, specific)
        self.assertLess(broad, hint)

    def test_disabled_text_is_explicitly_muted(self):
        code = (ROOT / 'drawing_editor' / 'window.py').read_text('utf-8')
        self.assertIn('QWidget#drawingRoot QLabel:disabled', code)
        self.assertIn('QWidget#drawingRoot QRadioButton:disabled', code)

    def test_transformed_icons_have_24_viewbox(self):
        for stem in ('next', 'prev', 'add', 'delete', 'export', 'zoom_in', 'zoom_out'):
            for theme in ('light', 'dark'):
                svg = ET.parse(ROOT / 'assets' / f'icon_{stem}_{theme}.svg').getroot()
                group = next(iter(svg))
                self.assertEqual(svg.attrib['viewBox'], '0 0 24 24')
                self.assertTrue(group.attrib.get('transform', '').startswith('translate('))

    @unittest.skipUnless(importlib.util.find_spec('cairosvg'), 'optional CairoSVG unavailable')
    def test_icon_visible_ink_optically_centered(self):
        import cairosvg
        from PIL import Image
        for theme in ('light', 'dark'):
            for p in sorted((ROOT / 'assets').glob(f'icon_*_{theme}.svg')):
                output = cairosvg.svg2png(bytestring=p.read_bytes(),
                                          output_width=96, output_height=96)
                box = Image.open(BytesIO(output)).getchannel('A').getbbox()
                self.assertIsNotNone(box, p.name)
                cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                self.assertLessEqual(abs(cx - 48), 2.1, f'{p.name} x axis')
                self.assertLessEqual(abs(cy - 48), 2.1, f'{p.name} y axis')


if __name__ == '__main__':
    unittest.main()
