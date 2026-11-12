# PyInstaller Qt Binding Collision — Build Fix Audit

## Observed Windows failure

PyInstaller logs show `hook-PyQt5.py` after `hook-PySide6.py` then abort with `attempt to collect multiple Qt bindings packages`. Python 3.12 is already available and does not need reinstallation.

## Correction in BUILD_ONEFILE.cmd

1. Remove `--collect-submodules ezdxf.addons.drawing`: it can pull optional Qt viewer and matplotlib backends even though this program uses only the PyMuPDF drawing backend.
2. Explicitly include `ezdxf.addons.drawing.pymupdf` and `ezdxf.addons.drawing.recorder`.
3. Exclude `PyQt5`, `PyQt6`, `PySide2` and unused `matplotlib` from the PyInstaller analysis. Keep PySide6 as the only Qt binding.
4. Set `QT_API=pyside6` for any conditional Qt imports and run PyInstaller with `--clean` to avoid stale hook analysis.
5. Keep system Python 3.11+ x64 (including 3.12), CMD only, no `.venv`, no PowerShell. Do not uninstall PyQt5 from the system Python.
6. Preserve staging, onefile EXE smoke tests, SignTool signing, SHA-256 validation, and protected publish to dist.

## Direct validation performed

- Python unit tests: 77/77 PASS; full output `quality/QT_CONFLICT_FIX_UNITTESTS.log`.
- CMD PyInstaller command continuation and all three exclusions: static regression tests PASS.
- Syntax/compileall: PASS.
- Existing drawing engine unchanged. Input documents remain read-only.
- Archive names ASCII; ZIP CRC and manifest hashes checked after packaging.
- Windows `.exe` creation, real PyInstaller hook execution, code signing and GUI operation: **NOT RUN** (Linux verification environment).

## How to use in Windows CMD

Unzip into a new empty folder, open it and run `BUILD_ONEFILE.cmd`. Existing Python 3.12 and PyQt5 can remain installed. On success output is `dist\Sunrise Drawing Editor.exe`. No virtual environment or PowerShell is used.

If the error returns, send the complete PyInstaller log starting at the first executed hook, including the exact command line and the first `ERROR:` line. Avoid deleting packages used by other programs. Code signing requires Windows SDK `signtool.exe`; local self-signing is not a trusted publisher certificate.
