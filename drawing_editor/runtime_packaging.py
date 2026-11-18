"""Explicit Nuitka experiment boundary. Normal source/PyInstaller unchanged."""
from pathlib import Path
import os

_nuitka_exe = None


def configure_nuitka_candidate(executable):
    global _nuitka_exe
    path = Path(executable).resolve(strict=True)
    if path.suffix.lower() != '.exe' or not path.is_file():
        raise RuntimeError('Nuitka outer executable not found')
    _nuitka_exe = path


def is_nuitka_candidate():
    return _nuitka_exe is not None


def nuitka_worker_command(flag, folder, flags):
    if not is_nuitka_candidate():
        return None
    # Independent bootstrap, not reuse of a parent extraction folder.
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith('NUITKA_ONEFILE_')
           and k.upper() != 'NUITKA_ORIGINAL_ARGV0'}
    return [str(_nuitka_exe), flag, str(folder)], {'creationflags': flags, 'env': env}
