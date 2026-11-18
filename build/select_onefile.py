"""R20: compare local candidates; never publish or replace the official EXE."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
NAME = 'Sunrise Drawing Editor.exe'
MIN_SAVING = 5
GATES = ('pdf_ocg', 'dxf_dwg', 'batch_png_jpg_crop', 'large_dxf_performance',
         'worker_cancel_cleanup', 'light_dark_dpi', 'remote_low_gpu',
         'external_raster', 'github_tls_notice_update', 'update_replace_rollback',
         'startup_memory_antivirus', 'license_review', 'trusted_signer_review')
MODES = ('safe', 'compact', 'lean', 'upx', 'nuitka')
STATUS = 'CANDIDATE_SMOKE_PASSED_FULL_QA_PENDING'


def read_json(path):
    with path.open(encoding='utf-8-sig') as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise ValueError('Expected JSON object')
    return value


def snapshot(path):
    with path.open('rb') as f:
        if f.read(2) != b'MZ':
            raise ValueError('Expected Windows executable')
        f.seek(0)
        return {'exe_bytes': path.stat().st_size, 'sha256': hashlib.file_digest(f, 'sha256').hexdigest()}


def matches(record, real):
    return (isinstance(record, dict) and record.get('sha256') == real['sha256']
            and type(record.get('exe_bytes')) is int and record['exe_bytes'] == real['exe_bytes'])


def evaluate(folder, baseline):
    report = read_json(folder / 'SIZE_COMPARISON.json')
    mode = report.get('profile', report.get('backend'))
    if mode not in MODES or report.get('status') != STATUS:
        raise ValueError('Unknown candidate or missing build smoke status')
    actual = snapshot(folder / NAME)
    sign = read_json(folder / 'SIGNATURE_STATUS.json')
    if not matches(report.get('candidate'), actual):
        raise ValueError('Candidate report does not match actual executable')
    if sign.get('sha256') != actual['sha256'] or sign.get('windows_exe_smoke_pass') is not True:
        raise ValueError('Signature/smoke record mismatch')
    reasons = []
    comparable = matches(report.get('baseline'), baseline)
    saving = 100 * (baseline['exe_bytes'] - actual['exe_bytes']) / baseline['exe_bytes'] if comparable else None
    if not comparable:
        reasons.append('Different or absent baseline')
    elif saving < MIN_SAVING:
        reasons.append('Below minimum size-saving threshold')
    if mode == 'nuitka':
        reasons.append('Nuitka updater is not compatible; experimental only')
    if sign.get('trust') != 'TRUSTED_BY_WINDOWS_POLICY':
        reasons.append('Trusted Windows signing evidence absent')
    qa_path = folder / 'QA_APPROVAL.json'
    qa = read_json(qa_path) if qa_path.is_file() else {}
    gates = qa.get('gates', {})
    approved = (qa.get('schema_version') == 1 and qa.get('candidate_sha256') == actual['sha256']
                and qa.get('baseline_sha256') == baseline['sha256']
                and isinstance(qa.get('reviewer'), str) and bool(qa['reviewer'].strip())
                and isinstance(gates, dict) and all(gates.get(g) == 'PASS' for g in GATES))
    if not approved:
        reasons.append('Hash-bound human QA approval missing or incomplete')
    return {'folder': folder.name, 'mode': mode, **actual, 'saving_percent': saving,
            'eligible_for_review': not reasons, 'reasons': reasons}


def decide(rows):
    eligible = [r for r in rows if r.get('eligible_for_review') is True]
    if not eligible:
        return {'official_default': 'baseline', 'recommendation': None, 'status': 'KEEP_BASELINE'}
    winner = min(eligible, key=lambda r: (r['exe_bytes'], MODES.index(r['mode']), r['sha256']))
    return {'official_default': 'baseline', 'recommendation': winner, 'status': 'REVIEW_REQUIRED'}


def collect(root, baseline):
    rows = []
    for parent in ('dist_lightweight', 'dist_compression'):
        base = root / parent
        if not base.is_dir():
            continue
        for folder in sorted(base.iterdir()):
            if not folder.is_dir():
                continue
            try:
                row = evaluate(folder, baseline)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                row = {'folder': folder.name, 'eligible_for_review': False, 'reasons': [str(exc)]}
            row['location'] = parent + '/' + folder.name
            rows.append(row)
    return rows


def run_matrix(baseline, upx_dir=None, nuitka=False):
    commands = [(m, ['build/build_lightweight.py', '--profile', m]) for m in ('safe', 'compact', 'lean')]
    if upx_dir is not None:
        commands.append(('upx', ['build/build_compression.py', '--backend', 'upx', '--upx-dir', str(upx_dir)]))
    if nuitka:
        commands.append(('nuitka', ['build/build_compression.py', '--backend', 'nuitka']))
    results = []
    for mode, args in commands:
        print('[INFO] Candidate:', mode, flush=True)
        result = subprocess.run([sys.executable, *args, '--baseline', str(baseline)], cwd=ROOT, check=False)
        results.append({'mode': mode, 'returncode': result.returncode})
    return results


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('compare', 'evaluate'))
    p.add_argument('--baseline', type=Path, default=ROOT / 'dist' / NAME)
    p.add_argument('--upx-dir', type=Path)
    p.add_argument('--nuitka', action='store_true')
    args = p.parse_args(argv)
    try:
        path = args.baseline.resolve(strict=True)
        before = snapshot(path)
        if args.action == 'compare' and (args.upx_dir or args.nuitka):
            raise ValueError('Optional backends require evaluate')
        if args.action == 'evaluate' and sys.platform != 'win32':
            raise ValueError('Windows required for candidate builds')
        results = run_matrix(path, args.upx_dir, args.nuitka) if args.action == 'evaluate' else []
        rows = collect(ROOT, before)
        if snapshot(path) != before:
            raise ValueError('Baseline changed during evaluation')
        report = {'schema_version': 1, 'baseline': before, 'minimum_saving_percent': MIN_SAVING,
                  'build_results': results, 'candidates': rows, **decide(rows),
                  'warning': 'Local evidence review only; no native trust re-verification or publication performed.'}
        directory = ROOT / 'quality' / 'onefile_selection'
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / ('R20_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f') + '.json')
        with target.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print('[INFO]', report['status'], '| Official default remains baseline')
        print('[INFO] Comparison:', target)
        return 1 if any(r['returncode'] for r in results) else 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print('[ERROR]', exc, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
