"""Reconstructed HiDPI/theme smoke regressions from current UI contracts.

Historical HiDPI patch contained a truncated test file; these are new
independent assertions, not reconstructed missing lines. Qt visual QA remains
required at 100/125/150/175% Windows DPI.
"""
from pathlib import Path
import math
import unittest
import xml.etree.ElementTree as ET

from drawing_editor.ui_design import THEMES
from drawing_editor.ui_interaction import preview_raster_size, detail_tile_covers

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ICON_NAMES = (
    "add", "apply", "delete", "deselect", "drawing",
    "export", "fit", "folder", "hidden", "moon",
    "next", "prev", "remove", "save", "search",
    "select_all", "sun", "visible", "zoom_in", "zoom_out",
)


def brightness(hex_code):
    channels = [int(hex_code[i:i+2], 16)/255 for i in (1, 3, 5)]
    corrected = [v/12.92 if v <= 0.04045 else ((v+0.055)/1.055)**2.4
                 for v in channels]
    return corrected[0]*0.2126 + corrected[1]*0.7152 + corrected[2]*0.0722


def contrast(a, b):
    top, low = sorted((brightness(a), brightness(b)), reverse=True)
    return (top+0.05)/(low+0.05)


class ThemeLegibilityTests(unittest.TestCase):
    def test_label_and_panel_contrast(self):
        for name, theme in THEMES.items():
            with self.subTest(theme=name):
                self.assertGreaterEqual(contrast(theme.foreground, theme.panel), 4.5)
                self.assertGreaterEqual(contrast(theme.muted, theme.panel), 4.5)
                self.assertGreaterEqual(contrast(theme.active_text, theme.selection), 4.5)

    def test_themes_are_not_the_same_palette(self):
        self.assertNotEqual(THEMES["light"].foreground, THEMES["dark"].foreground)
        self.assertNotEqual(THEMES["light"].panel, THEMES["dark"].panel)

    def test_icon_pairings_are_complete_and_valid_svg(self):
        for name in ICON_NAMES:
            for theme in ("light", "dark"):
                path = ASSETS / f"icon_{name}_{theme}.svg"
                with self.subTest(path=path.name):
                    self.assertTrue(path.is_file())
                    root = ET.fromstring(path.read_text(encoding="utf-8"))
                    self.assertEqual(root.tag.split("}")[-1], "svg")
                    self.assertEqual(root.attrib.get("viewBox"), "0 0 24 24")
                    self.assertEqual(root.attrib.get("width"), "24")
                    self.assertEqual(root.attrib.get("height"), "24")

    def test_light_and_dark_icon_strokes_are_different(self):
        a = ET.parse(ASSETS / "icon_add_light.svg").getroot()
        b = ET.parse(ASSETS / "icon_add_dark.svg").getroot()
        self.assertNotEqual(a[0].attrib["stroke"], b[0].attrib["stroke"])


class RasterReuseTests(unittest.TestCase):
    def test_high_dpi_first_pass_monotonic_until_cap(self):
        logical = (1000, 700)
        vals = [preview_raster_size(*logical, dpr) for dpr in (1.0, 1.25, 1.5, 1.75)]
        for before, after in zip(vals, vals[1:]):
            self.assertLessEqual(before[0], after[0])
            self.assertLessEqual(before[1], after[1])
        self.assertTrue(all(w <= 1600 and h <= 1300 for w, h in vals))

    def test_dpr_nan_falls_back_to_safe_value(self):
        self.assertEqual(preview_raster_size(800, 600, math.nan),
                         preview_raster_size(800, 600, 1.0))

    def test_tile_reuse_only_for_enclosing_sufficient_density(self):
        rect = (100.0, 100.0, 300.0, 300.0)
        tile = (80.0, 80.0, 320.0, 320.0)
        self.assertTrue(detail_tile_covers(rect, tile, 2.0, 2.0))
        self.assertFalse(detail_tile_covers(rect, tile, 1.0, 2.0))
        self.assertFalse(detail_tile_covers(rect, (120., 120., 320., 320.), 2.0, 2.0))


if __name__ == "__main__":
    unittest.main()
