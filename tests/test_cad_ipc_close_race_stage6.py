"""P0 IPC teardown race: file selection kills the DXF child between
response_exists and response_read, so a late preview must be cancelled.
No Qt process or user's original drawing is required.
"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ezdxf
from drawing_editor.cad_worker import _CADSession, shutdown_all_workers
from drawing_editor.core import RenderCancelled


class CADIPCFileSwitchRaceTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.source = Path(self.folder.name) / "simple.dxf"
        doc = ezdxf.new("R2010")
        doc.modelspace().add_line((0, 0), (25, 15))
        doc.saveas(self.source)

    def tearDown(self):
        shutdown_all_workers()
        self.folder.cleanup()

    def test_deleted_response_after_switch_is_cancel_not_io_error(self):
        session = _CADSession()
        normal_read = Path.read_text
        reads = []

        def simulated_onmap_switch(path, *args, **kwargs):
            if path.name.startswith("response-"):
                reads.append(path.name)
                session.close(background=True)
                raise FileNotFoundError("simulated IPC teardown after OnMap selection")
            return normal_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", simulated_onmap_switch):
            with self.assertRaises(RenderCancelled):
                session.render(
                    "preview", str(self.source), {"0": True}, 0,
                    (350, 250), None, None)
        self.assertEqual(len(reads), 1)
        self.assertTrue(session.closed)
        self.assertIsNotNone(session._reaper)
        session._reaper.join(timeout=5)
        self.assertFalse(session._reaper.is_alive())
        self.assertFalse(session.folder.exists())


if __name__ == "__main__":
    unittest.main()
