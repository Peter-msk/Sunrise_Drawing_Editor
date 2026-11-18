"""Build a separate Windows Onefile candidate; never overwrite official dist."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from lightweight_policy import PROFILES

ROOT = Path(__file__).resolve().parents[1]
NAME = 'Sunrise Drawing Editor.exe'


def run(*args):
    subprocess.run([sys.executable, *map(str, args)], cwd=ROOT,
                   env={**os.environ, 'QT_API': 'pyside6', 'PYTHONUTF8': '1'}, check=True)


def build(profile, baseline):
    from preflight import check_python, check_dependencies
    from audit_onefile import audit
    from pyz_policy import compare_pyz, excluded
    from PyInstaller import __version__
    errors = check_python() + check_dependencies()
    if errors or __version__.split('.')[0] != '6':
        raise RuntimeError('; '.join(errors) or 'PyInstaller 6.x required')
    before = audit(baseline) if baseline is not None else None
    run('build/sign_release.py', '--check-tools')
    run('-m', 'compileall', '-q', 'main.py', 'drawing_editor', 'build')
    work_base = ROOT / 'build' / 'lightwork'
    work_base.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='r18-', dir=work_base))
    stage = work / 'stage'
    plan = work / 'PLAN.json'
    print('[INFO] Candidate work:', work, flush=True)
    run('-m', 'PyInstaller', '--noconfirm', '--clean', '--distpath', stage,
        '--workpath', work / 'pyi', ROOT / 'build' / 'onefile_lightweight.spec',
        '--', '--profile', profile, '--plan', plan)
    exe = stage / NAME
    run('build/smoke_test.py', exe, '--timeout', '120')
    run('build/sign_release.py', exe)
    run('build/smoke_test.py', exe, '--timeout', '120')
    after = audit(exe)
    pyz_comparison = compare_pyz(before.get('pyz') if before else None, after.get('pyz'))
    if profile == 'pyz':
        if after.get('pyz', {}).get('status') != 'OK':
            raise RuntimeError('PYZ module inventory unavailable')
        if any(excluded(row['name']) for row in after['pyz']['entries']):
            raise RuntimeError('Excluded Python module still present in PYZ')
        if before is not None and pyz_comparison['status'] != 'OK':
            raise RuntimeError('Baseline PYZ comparison unavailable')
    policy = json.loads(plan.read_text(encoding='utf-8'))
    removed = policy['removed']
    normalize = lambda name: name.replace('\\', '/').lower()
    present = {normalize(row['name']) for row in after['entries']}
    if any(normalize(row['name']) in present for row in removed):
        raise RuntimeError('Excluded entry still present in candidate')
    if before is not None and audit(baseline)['sha256'] != before['sha256']:
        raise RuntimeError('Baseline changed during build')
    delta = before['exe_bytes'] - after['exe_bytes'] if before else None
    report = {'profile': profile, 'baseline': before, 'candidate': after,
              'removed': removed, 'saved_bytes': delta,
              'policy': policy, 'pyz_comparison': pyz_comparison,
              'pandas_archive_entries': sorted(n for n in present if n.startswith(('pandas/', 'pandas.libs/', 'pandas-'))),
              'saved_percent': 100 * delta / before['exe_bytes'] if before else None,
              'status': 'CANDIDATE_SMOKE_PASSED_FULL_QA_PENDING'}
    out = ROOT / 'dist_lightweight' / work.name
    out.mkdir(parents=True, exist_ok=False)
    # Existing signed-and-smoke-tested publishing helper targets candidate only.
    run('build/publish_release.py', exe, out)
    (out / 'SIZE_COMPARISON.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('[INFO] Candidate (not official release):', out / NAME)
    print('[INFO] Size comparison:', out / 'SIZE_COMPARISON.json')
    print('[INFO] Saved bytes:', delta if delta is not None else 'baseline absent')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILES, default='safe')
    parser.add_argument('--baseline', type=Path)
    args = parser.parse_args(argv)
    default = ROOT / 'dist' / NAME
    try:
        baseline = args.baseline.resolve(strict=True) if args.baseline else (default if default.is_file() else None)
        return build(args.profile, baseline)
    except Exception as exc:
        print('[ERROR]', exc, file=sys.stderr)
        print('[INFO] Official dist unchanged; no automatic installation or promotion.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
