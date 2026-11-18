"""Single-entry build orchestration; never automatically promote a candidate."""
from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
NAME = 'Sunrise Drawing Editor.exe'


def installed(name):
    try:
        metadata.version(name)
        return True
    except metadata.PackageNotFoundError:
        return False


def plans(upx_dir, nuitka_ready):
    return [
        ('safe', ['build/build_lightweight.py', '--profile', 'safe'], ''),
        ('compact', ['build/build_lightweight.py', '--profile', 'compact'], ''),
        ('lean', ['build/build_lightweight.py', '--profile', 'lean'], ''),
        ('pyz', ['build/build_lightweight.py', '--profile', 'pyz'], ''),
        ('upx', ['build/build_compression.py', '--backend', 'upx', '--upx-dir', str(upx_dir)] if upx_dir else None, 'UPX not installed/configured'),
        ('nuitka', ['build/build_compression.py', '--backend', 'nuitka'] if nuitka_ready else None, 'Nuitka build packages not installed'),
    ]


def locations(root):
    return {p for name in ('dist_lightweight', 'dist_compression')
            for p in (root / name).glob('*') if p.is_dir()}


def execute(root, baseline, jobs, evaluate, evidence):
    rows, results = [], []
    for mode, args, reason in jobs:
        if args is None:
            results.append({'mode': mode, 'status': 'NOT RUN', 'reason': reason})
            continue
        existing = locations(root)
        print('[INFO] Building candidate:', mode, flush=True)
        try:
            rc = subprocess.run([sys.executable, *args, '--baseline', str(baseline)],
                                cwd=root, stdin=subprocess.DEVNULL, check=False).returncode
        except OSError as exc:
            results.append({'mode': mode, 'status': 'FAILED', 'reason': str(exc)})
            continue
        fresh = sorted(locations(root) - existing)
        accepted = []
        for folder in fresh:
            try:
                row = evaluate(folder, evidence)
                if row['mode'] != mode or rc != 0:
                    raise ValueError('Candidate mode or build return code mismatch')
                row['location'] = folder.relative_to(root).as_posix()
                accepted.append(row)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                print('[WARN]', folder.name, str(exc), flush=True)
        rows.extend(accepted)
        results.append({'mode': mode, 'status': 'BUILT_QA_PENDING' if accepted else 'FAILED',
                        'returncode': rc, 'candidate_count': len(accepted)})
    return rows, results


def run_all(baseline):
    from audit_onefile import audit
    from select_onefile import decide, evaluate, snapshot, read_json
    from pyz_policy import compare_pyz
    evidence = audit(baseline)
    upx = Path(os.environ.get('SUNRISE_UPX_DIR', r'C:\Tools\UPX'))
    upx = upx.resolve() if (upx / 'upx.exe').is_file() else None
    jobs = plans(upx, all(installed(p) for p in ('Nuitka', 'ordered-set', 'zstandard')))
    rows, results = execute(ROOT, baseline, jobs, evaluate, evidence)
    if snapshot(baseline) != {k: evidence[k] for k in ('exe_bytes', 'sha256')}:
        raise RuntimeError('Staged baseline changed; refusing publication')
    pairs = {mode: [r for r in rows if r['mode'] == mode] for mode in ('lean', 'pyz')}
    delta = {'status': 'NOT AVAILABLE'}
    if all(len(v) == 1 for v in pairs.values()):
        lean = read_json(ROOT / pairs['lean'][0]['location'] / 'SIZE_COMPARISON.json')['candidate']
        pyz = read_json(ROOT / pairs['pyz'][0]['location'] / 'SIZE_COMPARISON.json')['candidate']
        delta = compare_pyz(lean.get('pyz'), pyz.get('pyz'))
        delta['saved_exe_bytes'] = lean['exe_bytes'] - pyz['exe_bytes']
    report = {'schema_version': 1, 'baseline': evidence, 'build_results': results,
              'lean_to_pyz': delta,
              'candidates': rows, **decide(rows),
              'matrix_complete': all(r['status'] == 'BUILT_QA_PENDING' for r in results),
              'publication': 'BASELINE_PENDING_EXISTING_SIGNED_PUBLISH_GATE',
              'note': 'Candidate size ranking is not functional QA or release approval.'}
    parent = ROOT / 'quality' / 'onefile_selection'
    parent.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix='r23-', dir=parent))
    with (folder / 'BUILD_REPORT.json').open('x', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write('\n')
    for result in results:
        print('[INFO]', result['mode'], result['status'], result.get('reason', ''))
    for row in sorted(rows, key=lambda r: r['exe_bytes']):
        print('[SIZE]', row['mode'], row['exe_bytes'], 'bytes; QA:', row['eligible_for_review'])
    print('[INFO] Report:', folder / 'BUILD_REPORT.json')
    print('[INFO] Only the signed baseline may be published by this invocation.')
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path)
    args = p.parse_args(argv)
    try:
        return run_all(args.baseline.resolve(strict=True))
    except Exception as exc:
        print('[ERROR]', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
