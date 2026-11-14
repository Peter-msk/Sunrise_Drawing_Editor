"""Verify a GitHub Download ZIP against the approved repository blob manifest.

A GitHub archive has no .git and therefore cannot pass a Git-branch
attestation. This separate, offline, stdlib-only check verifies every expected
file's bytes against its tracked Git blob object id, and detects injected source.
It does not claim that GitHub/author signing or Windows runtime QA passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

MANIFEST_NAME = "SOURCE_ARCHIVE_BLOBS.json"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
EXECUTABLE_SUFFIXES = frozenset({".py", ".cmd", ".bat", ".ps1", ".exe", ".dll", ".pyd", ".spec"})
CODE_DIRECTORIES = frozenset({"drawing_editor", "tests", "quality", "build", "assets"})


def git_blob_digest(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha1()
    digest.update(b"blob " + str(size).encode("ascii") + b"\0")
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_archive(root: Path, *, manifest_name: str = MANIFEST_NAME) -> dict:
    root = root.resolve()
    manifest_path = root / manifest_name
    if not manifest_path.is_file():
        raise ValueError("Source archive manifest is missing")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("algorithm") != "git-blob-sha1" or payload.get("version") != 1:
        raise ValueError("Unsupported source archive manifest")
    files = payload.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Source archive manifest is empty")
    expected = set()
    for relative, value in files.items():
        if not isinstance(relative, str) or not isinstance(value, str):
            raise ValueError("Invalid manifest file record")
        parsed = PurePosixPath(relative)
        if (not relative or relative.startswith("/") or "\\" in relative
                or ".." in parsed.parts or "." in parsed.parts
                or not HEX40.fullmatch(value)):
            raise ValueError("Unsafe source archive manifest path or digest")
        if relative == manifest_name:
            raise ValueError("Recursive source archive manifest is forbidden")
        target = root.joinpath(*parsed.parts)
        if not target.is_file() or target.is_symlink():
            raise ValueError("Expected source file missing or unsafe: " + relative)
        actual = git_blob_digest(target)
        if actual != value:
            raise ValueError("Source file integrity mismatch: " + relative)
        expected.add(relative)
    # Expected files are all verified, even non-code notices and bundled
    # assets. Untracked executable files may not bypass the archive gate.
    for folder in CODE_DIRECTORIES:
        directory = root / folder
        if not directory.is_dir():
            continue
        for candidate in directory.rglob("*"):
            if not candidate.is_file() or "__pycache__" in candidate.parts:
                continue
            if candidate.suffix.lower() not in EXECUTABLE_SUFFIXES:
                continue
            if candidate.relative_to(root).as_posix() not in expected:
                raise ValueError("Unverified executable source in ZIP: " +
                                 candidate.relative_to(root).as_posix())
    for candidate in root.iterdir():
        if (candidate.is_file() and candidate.suffix.lower() in EXECUTABLE_SUFFIXES
                and candidate.name not in expected):
            raise ValueError("Unverified top-level executable in ZIP: " + candidate.name)
    return {
        "status": "ARCHIVE_FILES_MATCH_GIT_BLOBS",
        "files_verified": len(expected),
        "basis": payload.get("basis", ""),
        "limitations": ("File-by-file Git blob integrity only; no Git branch/commit "
                        "provenance, Windows build, runtime or signing attestation"),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        result = check_archive(args.root)
        print("[PASS] Archive source files match the manifest:", result["files_verified"])
        if args.report is not None:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print("[FAIL] Archive source verification: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
