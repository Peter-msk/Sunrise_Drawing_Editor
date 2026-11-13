"""Verify that QA runs against a clean, identifiable Git branch.

This preflight is intentionally stdlib-only and never modifies any source file.
A standalone ZIP without .git cannot prove equivalence to the development branch:
it must not be presented as exact-branch validation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REQUIRED_BRANCH = "work/p0-render-lifecycle-audit-20261113"
REQUIRED_REPOSITORY = "peter-msk/sunrise_drawing_editor"
AUDITED_PATHS = ("drawing_editor", "tests", "assets", "quality",
                 "build", "main.py", "RUN_P0_QA.cmd", "BUILD_ONEFILE.cmd")
# Output JSON/log files are allowed. New executable test/QA Python source is not.
UNTRACKED_CODE_PATHS = (
    "drawing_editor", "tests", "assets", "main.py",
    "RUN_P0_QA.cmd", "BUILD_ONEFILE.cmd",
    ":(glob)quality/**/*.py", ":(glob)quality/*.py",
    ":(glob)build/**/*.py", ":(glob)build/*.py",
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, text=True, encoding="utf-8",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=20, check=False,
    )
    if result.returncode:
        detail = result.stderr.strip().splitlines()
        raise ValueError("Git command rejected: " + (detail[-1] if detail else "unknown"))
    return result.stdout.strip()


def _source_digest(root: Path, paths: list[str]) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for relative in paths:
        file_path = root / relative
        if not file_path.is_file():
            raise ValueError(f"Tracked source file missing: {relative}")
        file_hash = hashlib.sha256()
        with file_path.open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                file_hash.update(block)
        digest.update(relative.encode("utf-8") + b"\0" +
                      file_hash.hexdigest().encode("ascii") + b"\n")
        count += 1
    return digest.hexdigest(), count


def check_source(root: Path, *, expected_commit: str | None = None,
                 required_branch: str = REQUIRED_BRANCH,
                 required_repository: str = REQUIRED_REPOSITORY) -> dict:
    root = root.resolve()
    actual_root = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
    if actual_root != root:
        raise ValueError("QA must run from repository root")
    branch = _git(root, "symbolic-ref", "--short", "HEAD")
    if branch != required_branch:
        raise ValueError(f"Wrong branch: {branch!r}, expected {required_branch!r}")
    remote = _git(root, "remote", "get-url", "origin").rstrip("/").lower()
    allowed_prefixes = ("https://github.com/", "git@github.com:",
                        "ssh://git@github.com/")
    suffix = next((remote[len(prefix):] for prefix in allowed_prefixes
                   if remote.startswith(prefix)), None)
    if suffix is None:
        raise ValueError("Origin must be the official github.com repository")
    normalized = suffix[:-4] if suffix.endswith(".git") else suffix
    if normalized != required_repository.lower():
        raise ValueError("Origin repository does not match Sunrise Drawing Editor")
    commit = _git(root, "rev-parse", "HEAD")
    if expected_commit and commit != expected_commit:
        raise ValueError("Local HEAD does not match approved expected Git commit")
    dirty = _git(root, "status", "--porcelain", "--untracked-files=no", "--", *AUDITED_PATHS)
    if dirty:
        raise ValueError("Tracked application/test files are modified; QA source is not reproducible")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "--",
                     *UNTRACKED_CODE_PATHS)
    if untracked:
        raise ValueError("Untracked application/test files exist; commit or remove before QA")
    tracked = _git(root, "ls-files", "--", *AUDITED_PATHS).splitlines()
    if not tracked:
        raise ValueError("No source files found in Git index")
    fingerprint, count = _source_digest(root, sorted(tracked))
    return {
        "status": "SOURCE_IDENTITY_PASS",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "branch": branch, "commit": commit,
        "source_sha256": fingerprint,
        "tracked_files_hashed": count,
        "git_tree": _git(root, "rev-parse", "HEAD^{tree}"),
        "runtime_regressions": "NOT RUN BY THIS PREFLIGHT",
        "windows_gui_qa": "NOT RUN BY THIS PREFLIGHT",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report", type=Path)
    parser.add_argument("--expected-commit", default=None)
    args = parser.parse_args(argv)
    try:
        data = check_source(args.root, expected_commit=args.expected_commit)
    except (ValueError, OSError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        print("[FAIL] Exact Git-branch source identity: " + str(exc), file=sys.stderr)
        return 1
    print("[PASS] Exact source identity", data["commit"], "files", data["tracked_files_hashed"])
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
