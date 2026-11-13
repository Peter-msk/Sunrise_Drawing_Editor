"""Smoke tests for exact Git-branch QA identity; does not require Qt/CAD."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from quality.qa_exact_branch import check_source, REQUIRED_BRANCH


@unittest.skipUnless(shutil.which("git"), "Git is not installed")
class ExactBranchIdentityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sde-git-contract-")
        self.root = Path(self.temp.name)
        (self.root / "drawing_editor").mkdir()
        (self.root / "drawing_editor" / "__init__.py").write_text("", encoding="utf-8")
        (self.root / "main.py").write_text("print('safe')\n", encoding="utf-8")
        (self.root / "RUN_P0_QA.cmd").write_text("@echo off\n", encoding="utf-8")
        self.git("init", "-q")
        self.git("checkout", "-qb", REQUIRED_BRANCH)
        self.git("remote", "add", "origin",
                 "https://github.com/Peter-msk/Sunrise_Drawing_Editor.git")
        self.git("add", ".")
        self.git("-c", "user.email=test@example.invalid",
                 "-c", "user.name=QA",
                 "commit", "-qm", "Fixture")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True,
                              capture_output=True, text=True).stdout.strip()

    def test_clean_repo_records_exact_commit_and_digest(self):
        identity = check_source(self.root)
        self.assertEqual(identity["commit"], self.git("rev-parse", "HEAD"))
        self.assertEqual(identity["branch"], REQUIRED_BRANCH)
        self.assertEqual(identity["tracked_files_hashed"], 3)
        self.assertEqual(len(identity["source_sha256"]), 64)

    def test_changed_tracked_source_fails(self):
        (self.root / "main.py").write_text("print('changed')\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "modified"):
            check_source(self.root)

    def test_untracked_runtime_code_fails(self):
        (self.root / "drawing_editor" / "unexpected.py").write_text(
            "print('override')\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Untracked"):
            check_source(self.root)

    def test_wrong_commit_fails(self):
        with self.assertRaisesRegex(ValueError, "HEAD"):
            check_source(self.root, expected_commit="0" * 40)

    def test_wrong_branch_fails(self):
        self.git("checkout", "-qb", "main")
        with self.assertRaisesRegex(ValueError, "Wrong branch"):
            check_source(self.root)

    def test_lookalike_repository_fails(self):
        self.git("remote", "set-url", "origin",
                 "https://example.invalid/Peter-msk/Sunrise_Drawing_Editor.git")
        with self.assertRaisesRegex(ValueError, "github.com"):
            check_source(self.root)


if __name__ == "__main__":
    unittest.main()
