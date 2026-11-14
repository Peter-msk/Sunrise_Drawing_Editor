"""Stage12 source archive integrity regressions, no Qt or CAD runtime required."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from quality.qa_source_archive import check_archive, git_blob_digest


class ArchiveSourceIdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="sunrise-stage12-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "drawing_editor").mkdir()
        (self.root / "quality").mkdir()
        self.source = self.root / "drawing_editor" / "sample.py"
        self.source.write_text("print('safe')\n", encoding="utf-8")
        self.notice = self.root / "README.md"
        self.notice.write_text("# Fixture\n", encoding="utf-8")
        payload = {
            "version": 1,
            "algorithm": "git-blob-sha1",
            "basis": "offline fixture",
            "files": {
                "drawing_editor/sample.py": git_blob_digest(self.source),
                "README.md": git_blob_digest(self.notice),
            },
        }
        (self.root / "SOURCE_ARCHIVE_BLOBS.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8")

    def test_unmodified_archive_files_match(self):
        result = check_archive(self.root)
        self.assertEqual(result["status"], "ARCHIVE_FILES_MATCH_GIT_BLOBS")
        self.assertEqual(result["files_verified"], 2)

    def test_modified_code_fails_closed(self):
        self.source.write_text("print('altered')\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "integrity mismatch"):
            check_archive(self.root)

    def test_modified_notice_fails_closed(self):
        self.notice.write_text("# Changed\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "integrity mismatch"):
            check_archive(self.root)

    def test_missing_source_fails_closed(self):
        self.source.unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            check_archive(self.root)

    def test_untracked_executable_injection_fails_closed(self):
        (self.root / "drawing_editor" / "evil.py").write_text(
            "print('injected')", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unverified executable"):
            check_archive(self.root)

    def test_path_traversal_manifest_rejected(self):
        manifest = self.root / "SOURCE_ARCHIVE_BLOBS.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["files"]["../other.py"] = "a" * 40
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            check_archive(self.root)


if __name__ == "__main__":
    unittest.main()
