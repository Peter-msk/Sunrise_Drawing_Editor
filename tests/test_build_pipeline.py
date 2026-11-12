"""Cross-platform unit tests for Windows CMD build helper logic (not a Windows EXE test)."""
from __future__ import annotations

import contextlib
import io
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12, pkcs7
from build import preflight, sign_release, publish_release, smoke_test

ROOT = Path(__file__).resolve().parents[1]


class BuildPipelineStaticTests(unittest.TestCase):
    def test_cmd_entrypoint_no_powershell_or_venv_creation(self):
        code = (ROOT / 'BUILD_ONEFILE.cmd').read_text(encoding='utf-8').lower()
        self.assertNotIn('powershell.exe', code)
        self.assertNotIn(' -m venv', code)
        self.assertNotIn('.venv\\', code)
        self.assertIn('--onefile', code)
        self.assertIn('--windowed', code)
        self.assertIn('build\\sign_release.py', code)
        self.assertIn('\"%cd%\\assets;assets\"', code)
        self.assertIn('\"%cd%\\main.py\"', code)
        self.assertEqual(code.count('build\\smoke_test.py'), 2)

    def test_qt_bindings_excluded_from_pyinstaller(self):
        code = (ROOT / 'BUILD_ONEFILE.cmd').read_text(encoding='utf-8')
        for binding in ('PyQt5', 'PyQt6', 'PySide2'):
            self.assertIn(f'--exclude-module "{binding}"', code)
        self.assertIn('set "QT_API=pyside6"', code)
        self.assertNotIn('--exclude-module "PySide6"', code)
        self.assertIn('--exclude-module "matplotlib"', code)

    def test_only_required_ezdxf_drawing_backends_collected(self):
        code = (ROOT / 'BUILD_ONEFILE.cmd').read_text(encoding='utf-8')
        self.assertNotIn('--collect-submodules "ezdxf.addons.drawing"', code)
        for module in ('ezdxf.addons.drawing.pymupdf', 'ezdxf.addons.drawing.recorder'):
            self.assertIn(f'--hidden-import "{module}"', code)
        self.assertIn('--clean', code)

    def test_cmd_continuations_for_qt_flags(self):
        code = (ROOT / 'BUILD_ONEFILE.cmd').read_text(encoding='utf-8')
        lines = code.splitlines()
        for i, line in enumerate(lines):
            if '--exclude-module ' in line or '--hidden-import "ezdxf.addons.drawing.' in line:
                self.assertTrue(line.rstrip().endswith('^'), (i + 1, line))
        for i, line in enumerate(lines):
            if '--exclude-module "PyQt5"' in line:
                self.assertIn('PyQt6', lines[i + 1])
                self.assertIn('PySide2', lines[i + 2])

    def test_no_powershell_scripts_or_virtualenv_launcher(self):
        self.assertFalse(list(ROOT.rglob('*.ps1')))
        for name in ['RUN.cmd', 'INSTALL_AND_RUN.cmd']:
            content = (ROOT / name).read_text(encoding='utf-8').lower()
            self.assertNotIn(' -m venv', content)
            self.assertNotIn('powershell', content)

    def test_py_311_is_not_pinned(self):
        code = (ROOT / 'BUILD_ONEFILE.cmd').read_text(encoding='utf-8')
        self.assertIn('py -3', code)
        self.assertNotIn('py -3.11', code)

    def test_dependencies_runtime_vs_build(self):
        self.assertIn('PyInstaller', (ROOT / 'build' / 'preflight.py').read_text(encoding='utf-8'))
        self.assertIn('PySide6-Essentials', (ROOT / 'requirements.txt').read_text(encoding='utf-8'))
        self.assertNotIn('PySide6_WebEngine', (ROOT / 'requirements.txt').read_text(encoding='utf-8'))

    def test_signature_identifier_policy(self):
        self.assertEqual(sign_release.SUBJECT, 'Sunrise Group')
        self.assertTrue(callable(sign_release.embedded_signer_certificates))


class SigningDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pfx, cls.password, cls.cert = sign_release.generate_local_certificate()

    def test_pfx_contains_code_signing_certificate_and_key(self):
        key, cert, _ = pkcs12.load_key_and_certificates(self.pfx, self.password)
        self.assertIsNotNone(key)
        self.assertEqual(sign_release.signer_cn(cert), 'Sunrise Group')
        self.assertTrue(sign_release.is_code_signing(cert))
        self.assertTrue(sign_release.cert_current(cert))

    def test_pfx_password_is_not_empty(self):
        self.assertGreaterEqual(len(self.password), 32)
        with self.assertRaises((ValueError, TypeError)):
            pkcs12.load_key_and_certificates(self.pfx, b'bad')

    def test_extract_embedded_pkcs7_from_synthetic_pe(self):
        key, cert, _ = pkcs12.load_key_and_certificates(self.pfx, self.password)
        signed = (pkcs7.PKCS7SignatureBuilder().set_data(b'hello')
                  .add_signer(cert, key, hashes.SHA256())
                  .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary]))
        size = 8 + len(signed)
        padded = (size + 7) & ~7
        header = bytearray(512)
        header[:2] = b'MZ'
        struct.pack_into('<I', header, 0x3c, 128)
        header[128:132] = b'PE\0\0'
        opt = 128 + 24
        struct.pack_into('<H', header, opt, 0x20b)
        directory = opt + 112 + 8 * 4
        struct.pack_into('<II', header, directory, 512, padded)
        header += struct.pack('<IHH', size, 0x0200, 2)
        header += signed
        header += b'\0' * (padded - size)
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'test.exe'
            exe.write_bytes(header)
            embedded = sign_release.embedded_signer_certificates(exe)
        self.assertEqual(len(embedded), 1)
        self.assertEqual(embedded[0].fingerprint(hashes.SHA256()), cert.fingerprint(hashes.SHA256()))

    def test_unsigned_exe_not_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'unsigned.exe'
            f.write_bytes(b'MZ' + b'\0' * 200)
            with self.assertRaises(sign_release.SignError):
                sign_release.embedded_signer_certificates(f)


class PublicationSafetyTests(unittest.TestCase):
    def test_unsigned_exe_cannot_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'staging' / 'Sunrise Drawing Editor.exe'
            exe.parent.mkdir()
            exe.write_bytes(b'fake exe')
            with self.assertRaises(RuntimeError):
                publish_release.publish(exe, Path(tmp) / 'dist')
            self.assertFalse((Path(tmp) / 'dist' / exe.name).exists())

    def test_hash_mismatch_does_not_replace_old_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / 'staging' / 'Sunrise Drawing Editor.exe'
            exe.parent.mkdir()
            exe.write_bytes(b'new executable')
            (exe.parent / 'SIGNATURE_STATUS.json').write_text(json.dumps({'sha256': '0' * 64}))
            dist = root / 'dist'
            dist.mkdir()
            existing = dist / exe.name
            existing.write_bytes(b'previous stable release')
            with self.assertRaises(RuntimeError):
                publish_release.publish(exe, dist)
            self.assertEqual(existing.read_bytes(), b'previous stable release')

    def test_validated_publish_is_atomic_and_hash_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / 'staging' / 'Sunrise Drawing Editor.exe'
            exe.parent.mkdir()
            exe.write_bytes(b'fake signed build')
            sha = hashlib.sha256(exe.read_bytes()).hexdigest()
            (exe.parent / 'SIGNATURE_STATUS.json').write_text(json.dumps({'sha256': sha, 'trust': 'SELF_SIGNED_UNTRUSTED_TEST_ONLY'}))
            (exe.parent / 'SMOKE_STATUS.json').write_text(json.dumps({'sha256': sha, 'passed': True}))
            with patch.object(publish_release, 'embedded_signer_certificates', return_value=[sign_release.generate_local_certificate()[2]]):
                with contextlib.redirect_stdout(io.StringIO()):
                    publish_release.publish(exe, root / 'dist')
            self.assertEqual((root / 'dist' / exe.name).read_bytes(), exe.read_bytes())
            self.assertEqual((root / 'dist' / 'SIGNATURE_STATUS.json').exists(), True)
            self.assertIn(sha, (root / 'dist' / 'SHA256.txt').read_text())

    def test_smoke_refuses_tiny_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'bad.exe'
            exe.write_bytes(b'hello')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(smoke_test.smoke(exe, 5), 2)


if __name__ == '__main__':
    unittest.main()
