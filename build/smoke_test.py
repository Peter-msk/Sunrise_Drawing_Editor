"""Launch the actual onefile EXE with a timeout (no PowerShell, no venv)."""
from __future__ import annotations
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys

try:
    from build.pe_version import verify_version_resource
except ModuleNotFoundError:
    from pe_version import verify_version_resource


def smoke(exe: pathlib.Path, timeout: int) -> int:
    (exe.parent / 'SMOKE_STATUS.json').unlink(missing_ok=True)
    if not exe.is_file() or exe.stat().st_size < 1024:
        print(f'[ERROR] Executable not found or unexpectedly small: {exe}')
        return 2
    try:
        version_resource = verify_version_resource(exe)
    except (OSError, ValueError) as exc:
        print(f'[ERROR] Windows EXE version resource: {exc}')
        return 6
    print('[PASS] Windows version resource:', version_resource['strings']['ProductVersion'])
    try:
        result = subprocess.run([str(exe.resolve()), '--self-test'],
                                capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        print(f'[ERROR] Packaged EXE did not exit within {timeout} seconds.')
        return 3
    except OSError as exc:
        print(f'[ERROR] Could not start packaged EXE: {exc}')
        return 4
    if result.returncode != 0:
        print(f'[ERROR] EXE self-test failed. code={result.returncode}')
        if result.stdout:
            print(result.stdout.decode('utf-8', errors='replace')[-4000:])
        if result.stderr:
            print(result.stderr.decode('utf-8', errors='replace')[-4000:])
        return 5
    # The second invocation after signing will replace the pre-sign stamp.
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    (exe.parent / 'SMOKE_STATUS.json').write_text(
        json.dumps({'sha256': digest, 'passed': True, 'argument': '--self-test',
                    'version_resource': version_resource},
                   indent=2) + '\n', encoding='utf-8')
    print(f'[PASS] Actual packaged EXE self-test passed: {exe.name}')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('exe', type=pathlib.Path)
    parser.add_argument('--timeout', type=int, default=120)
    args = parser.parse_args()
    return smoke(args.exe, args.timeout)


if __name__ == '__main__':
    sys.exit(main())
