"""UI render controls and theme regressions: headless-safe checks."""
from pathlib import Path
import unittest

from drawing_editor.ui_design import THEMES, panel_layout
from drawing_editor.ui_interaction import zoom_factor_for_delta, clamp_zoom_factor

ROOT = Path(__file__).resolve().parents[1]
WINDOW = (ROOT / 'drawing_editor' / 'window.py').read_text('utf-8')


class UIRefinementTests(unittest.TestCase):
    def test_file_panel_gains_width_without_hiding_layer_panel(self):
        for width in (760,900,1120,1340,1600):
            layout=panel_layout(width)
            self.assertGreaterEqual(layout.file_width,166)
            self.assertGreaterEqual(layout.layer_width,232)
            self.assertLess(layout.file_width+layout.layer_width,width-140)
        self.assertEqual(panel_layout(1340).file_width,292)

    def test_zoom_wheel_is_continuous_and_fit_relative(self):
        self.assertGreater(zoom_factor_for_delta(12),1.0)
        self.assertLess(zoom_factor_for_delta(-12),1.0)
        self.assertAlmostEqual(zoom_factor_for_delta(0,24),1.12**.1)
        self.assertAlmostEqual(clamp_zoom_factor(10,.01,1.2),1.0)
        self.assertAlmostEqual(clamp_zoom_factor(10,.01,.9),.9)
        # Fine zoom should not stop abruptly at a source-PDF-unit-dependent 200x scale.
        self.assertAlmostEqual(clamp_zoom_factor(.4,.02,1.2),1.2)

    def test_theme_text_contrast_for_file_and_layer_tables(self):
        def luminance(hex_color):
            rgb=[int(hex_color[i:i+2],16)/255.0 for i in (1,3,5)]
            vals=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in rgb]
            return sum(x*w for x,w in zip(vals,(.2126,.7152,.0722)))
        for theme in THEMES.values():
            light,dark=sorted([luminance(theme.foreground),luminance(theme.input_background)])
            ratio=(dark+.05)/(light+.05)
            self.assertGreaterEqual(ratio,4.5)
        self.assertIn('QTreeWidget::item',WINDOW)
        self.assertIn('QTreeWidget::item:selected',WINDOW)
        self.assertIn('color:{fg}',WINDOW)

    def test_preview_is_immediate_and_detail_render_is_debounced(self):
        self.assertIn('self.scale(adjusted, adjusted)',WINDOW)
        self.assertIn('self.detail_timer.setInterval(230)',WINDOW)
        self.assertIn('self.preview_timer.setInterval(135)',WINDOW)
        self.assertIn('self._detail_seq += 1',WINDOW)

    def test_png_transparency_option_explicit_and_jpg_disabled(self):
        self.assertIn("QCheckBox('투명 배경')",WINDOW)
        self.assertIn("self.transparent_png.setObjectName('transparentPngCheck')",WINDOW)
        self.assertIn('self.transparent_png.setChecked(True)',WINDOW)
        self.assertIn('self.transparent_png.setEnabled(not checked)',WINDOW)
        self.assertIn("background=('transparent' if self.png_button.isChecked()",WINDOW)


if __name__=='__main__':
    unittest.main()
