"""R11 UI geometry and version contract; native Qt checks are separately gated."""
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import hashlib
import sys
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from drawing_editor.ui_interaction import clamp_zoom_factor, detail_tile_covers
from drawing_editor.release_feed import APP_VERSION, parse_release, release_download_urls, version_tuple
from build.pe_version import expected_version

ROOT = Path(__file__).resolve().parents[1]


class UIContractTests(unittest.TestCase):
    def test_nonfinite_zoom_does_not_corrupt_transform(self):
        for args in ((math.nan, 1, 2), (1, math.inf, 2), (1, 1, math.inf),
                     (1, 1, math.nan), (math.inf, 1, .5)):
            with self.subTest(args=args):
                self.assertEqual(clamp_zoom_factor(*args), 1.0)

    def test_zoom_return_from_outside_does_not_cross_opposite_bound(self):
        self.assertAlmostEqual(200 * clamp_zoom_factor(200, 1, .00001), .05)
        self.assertAlmostEqual(.01 * clamp_zoom_factor(.01, 1, 100000), 128)
        self.assertEqual(clamp_zoom_factor(200, 1, 2), 1)
        self.assertEqual(clamp_zoom_factor(.01, 1, .5), 1)
        self.assertEqual(clamp_zoom_factor(200, 1, .9), .9)
        self.assertEqual(clamp_zoom_factor(.01, 1, 1.1), 1.1)

    def test_invalid_detail_geometry_is_not_a_cache_hit(self):
        rect = (0., 0., 100., 100.)
        for visible, tile, density, requested in (
            ((20., 20., 20., 80.), rect, 2., 1.),
            ((80., 20., 20., 80.), rect, 2., 1.),
            (rect, (-math.inf, -math.inf, math.inf, math.inf), 2., 1.),
            (rect, rect, math.inf, 1.),
            (rect, rect, 2., math.nan),
        ):
            with self.subTest(visible=visible,tile=tile,density=density,requested=requested):
                self.assertFalse(detail_tile_covers(visible,tile,density,requested))
        self.assertTrue(detail_tile_covers((5,5,95,95),rect,2,2))
        self.assertFalse(detail_tile_covers(rect,rect,1,2))

    def test_candidate_version_metadata_and_native_probe(self):
        data = json.loads((ROOT/'latest.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(version_tuple(APP_VERSION), (1,5,1))
        self.assertEqual(data['latest_version'], APP_VERSION)
        self.assertEqual(data['source_version'], APP_VERSION)
        self.assertEqual(data['download_url'], release_download_urls(APP_VERSION)[0])
        self.assertEqual(data['release_url'].rsplit('/',1)[-1], 'v'+APP_VERSION)
        self.assertEqual(expected_version()['strings']['ProductVersion'], APP_VERSION)
        for flag in ('official_release','automatic_update_available','update_endpoint_configured'):
            self.assertIs(data[flag],False)
        self.assertIsNone(parse_release(json.dumps(data),current='1.5.0'))
        self.assertIn('v'+APP_VERSION, (ROOT/'notice.txt').read_text(encoding='utf-8').splitlines()[1])
        probe = subprocess.run([sys.executable, str(ROOT/'main.py'), '--verify-update-version', APP_VERSION],
                               cwd=ROOT, capture_output=True, timeout=10)
        self.assertEqual(probe.returncode,42,probe.stderr)


    def test_postbuild_does_not_attest_unrun_qt_checks(self):
        from build import final_qa_v150 as qa
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); dist = root/'dist'; dist.mkdir()
            exe = dist/'Sunrise Drawing Editor.exe'; exe.write_bytes(b'fixture, not a Windows EXE')
            sha = hashlib.sha256(exe.read_bytes()).hexdigest()
            (dist/'SIGNATURE_STATUS.json').write_text(json.dumps(dict(sha256=sha,
                embedded_certificate_match=True,trust='TRUSTED_BY_WINDOWS_POLICY')))
            (dist/'SMOKE_STATUS.json').write_text(json.dumps(dict(sha256=sha,passed=True,version_resource=expected_version())))
            from build.release_metadata import build_metadata
            sig_fixture = json.loads((dist/'SIGNATURE_STATUS.json').read_text())
            (dist/'SHA256.txt').write_bytes(f'{sha}  {exe.name}\n'.encode('utf-8'))
            (dist/'release-metadata').mkdir()
            for name, body in build_metadata(exe, sha, sig_fixture).items():
                (dist/'release-metadata'/name).write_bytes(body)
            # Native EXE evidence is deliberately mocked; this is a QA reporting test only.
            with patch.object(qa,'ROOT',root), patch('build.pe_version.verify_version_resource',return_value=expected_version()), \
                    patch('build.functional_gate.read_functional_qa'):
                pending = qa.postbuild()
                self.assertEqual(pending['windows_qt_widget_tests'],0)
                self.assertEqual(pending['windows_qt_widget_status'],'NOT_RUN')
                self.assertEqual(pending['status'],'PACKAGED_EXE_PASS_QT_PENDING')
                self.assertIn('native_qt_widget_tests',pending['manual_remaining'])
                passed = qa.postbuild(qt_tests_passed=True)
                self.assertEqual(passed['windows_qt_widget_tests'],qa.QT_TEST_COUNT)
                self.assertEqual(passed['windows_qt_widget_status'],'PASS')
                self.assertNotIn('native_qt_widget_tests',passed['manual_remaining'])


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Native Qt unavailable; not a PASS')
class R11QtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_unloaded_selection_clears_search_feedback(self):
        # Exercise the actual selection handler with real widgets, without
        # starting catalog tasks, touching user settings or contacting Control.
        from PySide6.QtWidgets import QWidget, QLineEdit, QTreeWidget, QLabel, QPushButton
        from drawing_editor.window import DrawingWindow
        host = QWidget(); self.addCleanup(host.close)
        state = SimpleNamespace(path=Path('pending.pdf'),loaded=False,catalog_error=None)
        h = SimpleNamespace(preview_timer=Mock(), detail_timer=Mock(), _analysis_cancel=None,
            _preview_seq=0,_detail_seq=0,_preview_cancel=None,_detail_cancel=None,
            current_doc=lambda:state,canvas=Mock(),_update_zoom_label=Mock(),
            layer_search=QLineEdit(host),layer_list=QTreeWidget(host),view_info=QLabel(host),
            view_status=QLabel(host),page_info=QLabel(host),layer_empty_hint=QLabel(host),
            filtered_actions=QWidget(host),filter_on_button=QPushButton(host),
            _update_layer_summary=Mock(),_sync_actions=Mock())
        h._filter_layers=lambda *args: DrawingWindow._filter_layers(h,*args)
        h.layer_search.setText('ROAD'); h.filtered_actions.show(); h.layer_empty_hint.setText('old');h.layer_empty_hint.show()
        with patch('drawing_editor.window.should_isolate_cad',return_value=True):
            DrawingWindow._selection_changed(h,None,None)
        self.assertEqual(h.layer_search.text(),'')
        self.assertTrue(h.filtered_actions.isHidden())
        self.assertTrue(h.layer_empty_hint.isHidden())
        self.assertEqual(h.layer_empty_hint.text(),'')
        self.assertEqual(h._filter_match_count,0)

if __name__=='__main__': unittest.main(verbosity=2)
