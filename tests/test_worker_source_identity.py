"""P1 child-worker identity and cleanup contracts (headless, no Qt)."""
from __future__ import annotations
from pathlib import Path
import hashlib
import tempfile
import unittest

import ezdxf
from drawing_editor import cad_worker


class WorkerSourceIdentityTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="sde-source-identity-")
        self.folder = Path(self._tmp.name)
        self.a, self.b = self.folder / "a.dxf", self.folder / "b.dxf"
        for path, scale in ((self.a, 1), (self.b, 3)):
            doc = ezdxf.new("R2010")
            doc.modelspace().add_line((0, 0), (scale * 20, 10))
            doc.saveas(path)

    def tearDown(self):
        cad_worker.shutdown_all_workers()
        self._tmp.cleanup()

    def preview(self, path):
        return cad_worker.render_isolated(
            "preview", str(path), {"0": True}, 0, (320, 240))

    def test_same_revision_reuses_worker_and_pixels(self):
        first, geometry = self.preview(self.a)
        session = cad_worker._THREAD.session
        second, geometry2 = self.preview(self.a)
        self.assertEqual(first, second)
        self.assertEqual(geometry, geometry2)
        self.assertIs(session, cad_worker._THREAD.session)

    def test_different_source_recycles_child(self):
        self.preview(self.a)
        previous = cad_worker._THREAD.session
        image, geometry = self.preview(self.b)
        self.assertTrue(image.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(len(geometry), 2)
        self.assertIsNot(previous, cad_worker._THREAD.session)
        self.assertTrue(previous.closed)
        self.assertIsNotNone(previous._reaper)
        previous._reaper.join(timeout=5)
        self.assertFalse(previous._reaper.is_alive())
        self.assertIsNotNone(previous.proc.poll())

    def test_rewritten_source_invalidates_worker(self):
        self.preview(self.a)
        previous = cad_worker._THREAD.session
        doc = ezdxf.readfile(self.a)
        doc.modelspace().add_circle((40, 40), radius=7)
        doc.saveas(self.a)
        self.assertNotEqual(previous.source_signature[1], self.a.stat().st_size)
        image, _ = self.preview(self.a)
        self.assertTrue(image.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(previous.closed)
        self.assertIsNot(previous, cad_worker._THREAD.session)

    def test_killed_child_can_recover(self):
        self.preview(self.a)
        previous = cad_worker._THREAD.session
        previous.proc.kill()
        previous.proc.wait(timeout=3)
        pixels, _ = self.preview(self.a)
        self.assertTrue(pixels.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(previous.closed)
        self.assertIsNot(previous, cad_worker._THREAD.session)

    def test_rendering_never_mutates_source(self):
        source_sha = [hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in (self.a, self.b)]
        self.preview(self.a)
        self.preview(self.b)
        self.assertEqual(source_sha, [
            hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (self.a, self.b)])


if __name__ == "__main__":
    unittest.main()
