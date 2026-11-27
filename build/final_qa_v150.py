"""Windows-only v1.5 final QA: ten native Qt tests + one LEAN build.

Unpinned or untrusted local builds remain INTERNAL_QA_ONLY. A pinned,
Windows-policy-verified group build is an internal candidate, never a public release.
This command does not
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
QT_TEST_COUNT = 10


def _digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def prepare_build_dependencies():
    """Use the same preflight contract as BUILD_ONEFILE before native Qt tests."""
    from build.preflight import check_python, check_dependencies
    errors = check_python()
    if errors:
        raise RuntimeError('Python preflight failed: ' + '; '.join(errors))
    errors = check_dependencies()
    if not errors:
        return
    if os.environ.get('BUILD_NO_INSTALL') == '1':
        raise RuntimeError('BUILD_NO_INSTALL=1: ' + '; '.join(errors))
    print('[INFO] Preparing missing dependencies in current Python before Qt QA.')
    result = subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt',
                             '-r', 'build/requirements-build.txt'], cwd=ROOT, check=False)
    if result.returncode:
        raise RuntimeError(f'Dependency installation failed: {result.returncode}')
    from importlib import invalidate_caches
    invalidate_caches()
    errors = check_dependencies()
    if errors:
        raise RuntimeError('Dependency preflight failed after installation: ' + '; '.join(errors))


def native_qt_tests():
    # A unittest skip is not a PASS; enforce all ten actual widget, drag and raster settings tests.
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    suite = unittest.TestSuite([
        unittest.defaultTestLoader.loadTestsFromName('build.test_v140_r06.QtInteractionTests'),
        unittest.defaultTestLoader.loadTestsFromName('build.test_v150_drag_region.QtDragTests'),
        unittest.defaultTestLoader.loadTestsFromName('build.test_v150_combo_options.CombinationRasterQtTests'),
        unittest.defaultTestLoader.loadTestsFromName('build.test_v151_r11_ui.R11QtTests'),
    ])
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    print(output.getvalue())
    if result.testsRun != QT_TEST_COUNT or result.skipped or result.errors or result.failures:
        raise RuntimeError('Qt 실기 테스트 10개(드래그·팝업 다크 테마·조합 PNG 옵션 포함)가 모두 실행·통과해야 합니다.')
    return True


def postbuild(*, qt_tests_passed=False):
    from build.functional_gate import read_functional_qa
    from build.pe_version import verify_version_resource
    from drawing_editor.release_feed import APP_VERSION
    exe = ROOT / 'dist' / 'Sunrise Drawing Editor.exe'
    destination = exe.parent / 'V150_LOCAL_QA.json'
    destination.unlink(missing_ok=True)
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
    version_resource = verify_version_resource(exe)
    if smoke.get('version_resource') != version_resource:
        raise RuntimeError('실행검사 버전 리소스 증거가 일치하지 않습니다.')
    read_functional_qa(exe.parent / 'FUNCTIONAL_QA.json', sha, version=APP_VERSION)
    # All distribution sidecars must belong to this exact signed candidate.
    from build.release_metadata import build_metadata
    expected_files = {'SHA256.txt': f'{sha}  {exe.name}\n'.encode('utf-8')}
    expected_files.update({'release-metadata/' + name: body for name, body in
                           build_metadata(exe, sha, signature).items()})
    for name, expected in expected_files.items():
        try:
            with (exe.parent / name).open('rb') as stream:
                matches = stream.read(len(expected) + 1) == expected
        except OSError as exc:
            raise RuntimeError(f'Published bundle evidence missing: {name}') from exc
        if not matches:
            raise RuntimeError(f'Published bundle evidence mismatch: {name}')
    trust = signature['trust']
    status = ('INTERNAL_QA_ONLY' if trust != 'TRUSTED_BY_WINDOWS_POLICY' else
              'AUTOMATED_PASS_MANUAL_PENDING' if qt_tests_passed else 'PACKAGED_EXE_PASS_QT_PENDING')
    from build.sign_release import group_pin, require_group_signature
    pin = group_pin()
    if not pin and signature.get('group_certificate_pin_verified') is True:
        raise RuntimeError('Group signing fingerprint must remain configured during final QA.')
    if pin:
        require_group_signature(exe, signature, pin)
        status = ('GROUP_INTERNAL_CANDIDATE_MANUAL_PENDING' if qt_tests_passed else
                  'GROUP_INTERNAL_CANDIDATE_QT_PENDING')
    if _digest(exe) != sha:
        raise RuntimeError('EXE changed during final QA.')
    remaining = ['actual_user_onmap', 'actual_dwg_converter', 'dpi_visual',
                 'real_world_memory', 'previous_to_candidate_update_rollback', 'redistribution_license_review']
    if not qt_tests_passed:
        remaining.insert(0, 'native_qt_widget_tests')
    report = {'version': APP_VERSION, 'exe': exe.name, 'sha256': sha,
              'status': status, 'signature_trust': trust,
              'group_certificate_pin_verified': bool(pin),
              'group_certificate_sha256': pin or None,
              'official_release': False, 'automatic_update_available': False,
              'windows_qt_widget_tests': QT_TEST_COUNT if qt_tests_passed else 0,
              'windows_qt_widget_status': 'PASS' if qt_tests_passed else 'NOT_RUN',
              'packaged_exe_qa': 'PASS', 'manual_remaining': remaining}
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('Windows QA:', status, destination)
    return report


def main():
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument('--all', action='store_true', help='Run Qt tests, one LEAN build, signed EXE QA')
    arg.add_argument('--qt-only', action='store_true', help='Run ten real Qt tests (including region drag)')
    arg.add_argument('--postbuild', action='store_true', help='Verify an existing dist EXE')
    args = arg.parse_args()
    if os.name != 'nt':
        raise RuntimeError('실제 Windows에서만 최종 QA를 실행합니다.')
    sys.path.insert(0, str(ROOT))
    qt_tests_passed = False
    if args.all:
        prepare_build_dependencies()
    if args.all or args.qt_only:
        qt_tests_passed = native_qt_tests()
    if args.all:
        result = subprocess.run(['cmd.exe', '/d', '/c', str(ROOT / 'BUILD_ONEFILE.cmd')],
                                cwd=ROOT, check=False)
        if result.returncode:
            raise RuntimeError(f'LEAN Onefile 빌드 실패: {result.returncode}')
    if args.all or args.postbuild:
        postbuild(qt_tests_passed=qt_tests_passed)
    if not (args.all or args.qt_only or args.postbuild):
        arg.error('--all, --qt-only 또는 --postbuild를 지정하세요.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print('[NOT APPROVED]', error, file=sys.stderr)
        raise SystemExit(1)
