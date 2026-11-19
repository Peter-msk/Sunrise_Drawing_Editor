"""Explicit pre-GUI update protocol version handshake."""
from __future__ import annotations

import subprocess

PROBE = '--verify-update-version'


def version_probe_exit(argv, current):
    # Distinct success code proves the new executable recognized this protocol;
    # older binaries may ignore unknown arguments and exit zero on window close.
    return 42 if len(argv) == 3 and argv[1] == PROBE and argv[2] == current else 2


def verify_candidate_version(exe, version, env):
    result = subprocess.run([str(exe), PROBE, version], env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=120,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode != 42:
        raise ValueError('Update executable did not attest the requested version/protocol')
