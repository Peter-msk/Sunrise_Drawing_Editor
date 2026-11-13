"""Regression for cancellable, persistent out-of-process DXF preview.

Runs with: python -m unittest tests.test_cad_worker_process -v
No Qt GUI is required for these engine tests. Windows onefile QA is separate.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import threading
import unittest

import ezdxf

from drawing_editor.cad_worker import (
    render_isolated, should_isolate_cad, shutdown_all_workers, _THREAD,
)
from drawing_editor.core import RenderCancelled


class IsolatedCADPreviewTest(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="sde-worker-qa-")
        self.path = Path(self.scratch.name) / "sample_insert_arc.dxf"
        doc = ezdxf.new("R2010")
        block = doc.blocks.new(name="CIRCLE_TEST")
        block.add_circle((0, 0), radius=4)
        block.add_arc((5, 5), radius=2, start_angle=0, end_angle=130)
        model = doc.modelspace()
        model.add_insert("CIRCLE_TEST", (20, 20))
        model.add_line((0, 0), (50, 20))
        doc.saveas(self.path)

    def tearDown(self):
        shutdown_all_workers()
        self.scratch.cleanup()

    def test_source_threshold_only_changes_routing(self):
        self.assertFalse(should_isolate_cad(self.path))
        self.assertTrue(should_isolate_cad(self.path, threshold=1))
        self.assertFalse(should_isolate_cad(Path(self.scratch.name) / "missing.dxf"))

    def test_reuses_one_worker_and_matches_pdf_render(self):
        from drawing_editor.core import preview_snapshot, render_snapshot
        states = {"0": True}
        reference, ref_geometry = preview_snapshot(str(self.path), states, 0, (640, 480))
        preview, geometry = render_isolated(
            "preview", str(self.path), states, 0, (640, 480))
        self.assertEqual(preview, reference)
        self.assertEqual(tuple(geometry), tuple(ref_geometry))
        session = _THREAD.session
        pid = session.proc.pid

        clip = (0.0, 0.0, float(geometry[0]), float(geometry[1]))
        native_detail = render_snapshot(str(self.path), states, 0,
                                        (400, 300), clip=clip)
        isolated_detail = render_isolated(
            "detail", str(self.path), states, 0, (400, 300), clip=clip)
        self.assertEqual(isolated_detail, native_detail)
        self.assertEqual(_THREAD.session.proc.pid, pid)

    def test_cancel_stops_old_process_and_next_request_recovers(self):
        event = threading.Event()
        states = {"0": True}
        _, geometry = render_isolated(
            "preview", str(self.path), states, 0, (500, 400))
        session = _THREAD.session
        event.set()
        with self.assertRaises(RenderCancelled):
            session.render("preview", str(self.path), states, 0, (500, 400),
                           None, event.is_set)
        self.assertTrue(session.closed)
        event.clear()
        result, _ = render_isolated(
            "preview", str(self.path), states, 0, (500, 400))
        self.assertTrue(result.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIsNot(session, _THREAD.session)

    def test_close_reclaims_worker_session(self):
        states = {"0": True}
        render_isolated("preview", str(self.path), states, 0, (500, 400))
        session = _THREAD.session
        shutdown_all_workers()
        self.assertTrue(session.closed)
        self.assertIsNotNone(session.proc.poll())

    def test_background_close_does_not_block_on_process_wait(self):
        states = {"0": True}
        render_isolated("preview", str(self.path), states, 0, (500, 400))
        session = _THREAD.session
        shutdown_all_workers(background=True)
        self.assertTrue(session.closed)
        self.assertIsNotNone(session._reaper)
        # Unlike synchronous shutdown, the GUI does not wait for child reaping.
        session._reaper.join(timeout=5)
        self.assertFalse(session._reaper.is_alive())
        self.assertIsNotNone(session.proc.poll())


class EntrypointContractTest(unittest.TestCase):
    def test_gui_routes_large_dxf_without_mupdf_gate(self):
        window = (Path(__file__).resolve().parents[1] /
                  "drawing_editor" / "window.py").read_text(encoding="utf-8")
        self.assertIn("should_isolate_cad(self.path)", window)
        self.assertIn("render_isolated('preview'", window)
        self.assertIn("render_isolated('detail'", window)
        self.assertIn("shutdown_all_workers()", window)

    def test_onmap_switch_releases_idle_dxf_worker(self):
        window = (Path(__file__).resolve().parents[1] /
                  "drawing_editor" / "window.py").read_text(encoding="utf-8")
        head = window.index("    def _selection_changed(self,current,previous):")
        tail = window.index("    def _layer_changed(", head)
        switch = window[head:tail]
        self.assertIn("if doc is None or not should_isolate_cad(str(doc.path)):", switch)
        self.assertIn("shutdown_all_workers(background=True)", switch)

    def test_frozen_worker_bypasses_qt(self):
        main = (Path(__file__).resolve().parents[1] /
                "main.py").read_text(encoding="utf-8")
        self.assertLess(main.index("if len(sys.argv) > 1 and sys.argv[1] == '--cad-worker'"),
                        main.index("from PySide6.QtWidgets import QApplication"))


if __name__ == "__main__":
    unittest.main()
