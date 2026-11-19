"""Offline confirmed-start cleanup regressions."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drawing_editor.update_policy import cleanup_after_start


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.target = self.root / 'Sunrise.Drawing.Editor.exe'
        self.stage = self.root / '.sunrise-update-abcdefgh'
        self.stage.mkdir()
        self.old = self.stage / 'rollback.exe'
        self.new = self.stage / 'candidate.exe'
        self.target.write_bytes(b'new')
        self.new.write_bytes(b'new')
        self.old.write_bytes(b'old')
        self.old_sha = hashlib.sha256(b'old').hexdigest()
        self.new_sha = hashlib.sha256(b'new').hexdigest()

    def clean(self):
        return cleanup_after_start(self.target, self.stage, self.old_sha, self.new_sha, timeout=0)

    def test_success_removes_both_temporary_exes(self):
        self.assertTrue(self.clean())
        self.assertFalse(self.stage.exists())
        self.assertEqual(self.target.read_bytes(), b'new')

    def test_unconfirmed_target_keeps_backup(self):
        self.target.write_bytes(b'wrong')
        self.assertFalse(self.clean())
        self.assertEqual(self.old.read_bytes(), b'old')

    def test_candidate_mismatch_keeps_backup(self):
        self.new.write_bytes(b'wrong')
        self.assertFalse(self.clean())
        self.assertTrue(self.old.exists())

    def test_backup_mismatch_preserved(self):
        self.old.write_bytes(b'wrong')
        self.assertFalse(self.clean())
        self.assertEqual(self.old.read_bytes(), b'wrong')

    def test_other_directory_not_touched(self):
        self.stage = self.root / 'other'
        self.stage.mkdir()
        (self.stage / 'rollback.exe').write_bytes(b'old')
        self.assertFalse(self.clean())
        self.assertTrue((self.stage / 'rollback.exe').exists())

    def test_unrelated_file_preserved(self):
        unrelated = self.stage / 'user.txt'
        unrelated.write_bytes(b'user data')
        self.assertFalse(self.clean())
        self.assertEqual(unrelated.read_bytes(), b'user data')
        self.assertTrue(self.old.exists())

    def test_failed_unlink_keeps_backup(self):
        with patch.object(Path, 'unlink', side_effect=PermissionError('locked')):
            self.assertFalse(self.clean())
            self.assertTrue(self.old.exists())
            self.assertTrue(self.new.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
