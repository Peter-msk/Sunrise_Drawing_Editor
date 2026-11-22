"""Windows-only v1.5 final QA: four native Qt tests + one LEAN build.

A local self-signed build remains INTERNAL_QA_ONLY. This command does not
activate a release, upload binaries, or change the installed update feed.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def _digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def native_qt_tests():
    # A unittest skip is not a PASS; enforce all four expected actual Qt tests.
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    suite = unittest.defaultTestLoader.loadTestsFromName('build.test_v140_r06.QtInteractionTests')
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    print(output.getvalue())
    if result.testsRun != 4 or result.skipped or result.errors or result.failures:
        raise RuntimeError('Qt 실기 테스트 4개가 모두 실행·통과해야 합니다.')
    return True


def postbuild():
    from build.functional_gate import read_functional_qa
    from build.pe_version import verify_version_resource
    from drawing_editor.release_feed import APP_VERSION
    exe = ROOT / 'dist' / 'Sunrise Drawing Editor.exe'
    if not exe.is_file():
        raise RuntimeError('실제 Onefile EXE가 존재하지 않습니다.')
    sha = _digest(exe)
    signature = json.loads((exe.parent / 'SIGNATURE_STATUS.json').read_text(encoding='utf-8'))
    smoke = json.loads((exe.parent / 'SMOKE_STATUS.json').read_text(encoding='utf-8'))
    if (signature.get('sha256') != sha or signature.get('embedded_certificate_match') is not True
            or signature.get('trust') not in ('SELF_SIGNED_UNTRUSTED_TEST_ONLY', 'TRUSTED_BY_WINDOWS_POLICY')):
        raise RuntimeError('Authenticode 서명 증거가 EXE와 일치하지 않습니다.')
    if smoke.get('sha256') != sha or smoke.get('passed') is not True:
        raise RuntimeError('실제 EXE 실행검사 증거가 일치하지 않습니다.')
    verify_version_resource(exe)
    read_functional_qa(exe.parent / 'FUNCTIONAL_QA.json', sha, version=APP_VERSION)
    trust = signature['trust']
    status = 'INTERNAL_QA_ONLY' if trust != 'TRUSTED_BY_WINDOWS_POLICY' else 'AUTOMATED_PASS_MANUAL_PENDING'
    report = {'version': APP_VERSION, 'exe': exe.name, 'sha256': sha,
              'status': status, 'signature_trust': trust,
              'windows_qt_widget_tests': 4, 'packaged_exe_qa': 'PASS',
              'manual_remaining': ['actual_user_onmap', 'actual_dwg_converter', 'dpi_visual',
                                   'real_world_memory', 'previous_to_candidate_update_rollback']}
    destination = exe.parent / 'V150_LOCAL_QA.json'
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('Windows QA:', status, destination)
    return report


def main():
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument('--all', action='store_true', help='Run Qt tests, one LEAN build, signed EXE QA')
    arg.add_argument('--qt-only', action='store_true', help='Run exactly four real Qt tests')
    arg.add_argument('--postbuild', action='store_true', help='Verify an existing dist EXE')
    args = arg.parse_args()
    if os.name != 'nt':
        raise RuntimeError('실제 Windows에서만 최종 QA를 실행합니다.')
    sys.path.insert(0, str(ROOT))
    if args.all or args.qt_only:
        native_qt_tests()
    if args.all:
        result = subprocess.run(['cmd.exe', '/d', '/c', str(ROOT / 'BUILD_ONEFILE.cmd')],
                                cwd=ROOT, check=False)
        if result.returncode:
            raise RuntimeError(f'LEAN Onefile 빌드 실패: {result.returncode}')
    if args.all or args.postbuild:
        postbuild()
    if not (args.all or args.qt_only or args.postbuild):
        arg.error('--all, --qt-only 또는 --postbuild를 지정하세요.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print('[NOT APPROVED]', error, file=sys.stderr)
        raise SystemExit(1)
