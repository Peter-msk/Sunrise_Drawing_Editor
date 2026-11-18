"""R19 experimental build, isolated from official dist and release metadata."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
NAME = 'Sunrise Drawing Editor.exe'


def snapshot(path):
    with path.open('rb') as stream:
        if stream.read(2) != b'MZ':
            raise ValueError('Expected Windows EXE')
        stream.seek(0)
        return {'exe_bytes': path.stat().st_size,
                'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}


def comparison(before, after):
    if before is None:
        return {'saved_bytes': None, 'saved_percent': None}
    delta = before['exe_bytes'] - after['exe_bytes']
    return {'saved_bytes': delta, 'saved_percent': 100 * delta / before['exe_bytes']}


def command(*args):
    subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, check=True,
                   env={**os.environ, 'QT_API': 'pyside6', 'PYTHONUTF8': '1'})


def versions():
    result = {}
    for name in ('PyInstaller', 'Nuitka', 'PySide6-Essentials', 'PyMuPDF', 'ezdxf', 'Pillow', 'numpy', 'ordered-set', 'zstandard'):
        try:
            result[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            result[name] = None
    return result


def build(backend, baseline, upx_dir):
    from preflight import check_python, check_dependencies
    errors = check_python() + check_dependencies()
    if errors:
        raise RuntimeError('; '.join(errors))
    tools = versions()
    if backend == 'upx':
        if not tools['PyInstaller'] or tools['PyInstaller'].split('.')[0] != '6':
            raise RuntimeError('PyInstaller 6.x required')
        if upx_dir is None:
            raise ValueError('Provide --upx-dir with trusted UPX executable')
        upx_dir = upx_dir.resolve(strict=True)
        upx = upx_dir / 'upx.exe'
        tool = subprocess.run([str(upx), '--version'], check=True, capture_output=True, text=True, timeout=10)
        tools['UPX'] = tool.stdout.strip()
        tools['UPX_SHA256'] = snapshot(upx)['sha256']
    elif backend == 'nuitka':
        if not all(tools[x] for x in ('Nuitka', 'ordered-set', 'zstandard')):
            raise RuntimeError('Install Nuitka, ordered-set and zstandard explicitly; no automatic install')
    else:
        raise ValueError('Unknown backend')
    before = snapshot(baseline) if baseline else None
    command('build/sign_release.py', '--check-tools')
    base = ROOT / 'build' / 'compression_work'
    base.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='r19-', dir=base))
    stage = work / 'stage'
    stage.mkdir()
    plan = work / 'PLAN.json'
    started = time.perf_counter()
    if backend == 'upx':
        command('-m', 'PyInstaller', '--noconfirm', '--clean', '--upx-dir', upx_dir,
                '--distpath', stage, '--workpath', work / 'pyi', ROOT / 'build' / 'onefile_upx.spec',
                '--', '--plan', plan)
    else:
        command('-m', 'nuitka', '--mode=onefile', '--enable-plugin=pyside6',
                '--windows-console-mode=disable', '--msvc=latest',
                '--include-data-dir=' + str(ROOT / 'assets') + '=assets',
                '--windows-icon-from-ico=' + str(ROOT / 'assets' / 'app.ico'),
                '--output-dir=' + str(stage), '--output-filename=' + NAME,
                '--report=' + str(work / 'NUITKA_REPORT.xml'), ROOT / 'nuitka_entry.py')
    build_seconds = time.perf_counter() - started
    exe = stage / NAME
    command('build/smoke_test.py', exe, '--timeout', '120')
    command('build/sign_release.py', exe)
    started = time.perf_counter()
    command('build/smoke_test.py', exe, '--timeout', '120')
    smoke_seconds = time.perf_counter() - started
    after = snapshot(exe)
    report = {'backend': backend, 'baseline': before, 'candidate': after,
              **comparison(before, after), 'build_seconds': build_seconds,
              'post_sign_smoke_seconds': smoke_seconds, 'tools': tools,
              'status': 'CANDIDATE_SMOKE_PASSED_FULL_QA_PENDING'}
    if backend == 'upx':
        from audit_onefile import audit
        report['candidate_archive'] = audit(exe)
        report['policy'] = json.loads(plan.read_text(encoding='utf-8'))
    if baseline and snapshot(baseline) != before:
        raise RuntimeError('Baseline changed during build')
    # Publish only to a unique experimental directory, never to dist.
    out = ROOT / 'dist_compression' / work.name
    out.mkdir(parents=True, exist_ok=False)
    command('build/publish_release.py', exe, out)
    (out / 'SIZE_COMPARISON.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('[INFO] Candidate only:', out / NAME)
    print('[INFO] Saved bytes:', report['saved_bytes'])
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backend', choices=('upx', 'nuitka'), required=True)
    p.add_argument('--baseline', type=Path)
    p.add_argument('--upx-dir', type=Path)
    args = p.parse_args(argv)
    default = ROOT / 'dist' / NAME
    try:
        baseline = args.baseline.resolve(strict=True) if args.baseline else (default if default.is_file() else None)
        return build(args.backend, baseline, args.upx_dir)
    except Exception as exc:
        print('[ERROR]', exc, file=sys.stderr)
        print('[INFO] Official distribution unchanged.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
