"""Focused version-resource build contract; native Windows check runs in smoke."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pe_version as version
import smoke_test
import publish_release


class VersionTests(unittest.TestCase):
    def fixture(self, value):
        root = Path(self.tmp.name)
        (root / 'drawing_editor').mkdir(exist_ok=True)
        (root / 'drawing_editor/release_feed.py').write_text(f'APP_VERSION = {value!r}\n')
        return root

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_both_versions_and_all_fields(self):
        for value, fixed in [('1.0.0', [1,0,0,0]), ('1.1.0', [1,1,0,0])]:
            root = self.fixture(value)
            path = root / 'version.txt'
            result = version.write_version_resource(path, root=root)
            expr = ast.parse(path.read_text(encoding='utf-8'), mode='eval').body
            self.assertEqual(expr.func.id, 'VSVersionInfo')
            kwargs = {x.arg: x.value for x in expr.keywords}
            ffi = {x.arg: ast.literal_eval(x.value) for x in kwargs['ffi'].keywords}
            self.assertEqual(ffi['filevers'], tuple(fixed))
            self.assertEqual(ffi['prodvers'], tuple(fixed))
            self.assertEqual(ffi['fileType'], 1)
            table = kwargs['kids'].elts[0].args[0].elts[0]
            self.assertEqual(ast.literal_eval(table.args[0]), '041204b0')
            entries = dict(tuple(ast.literal_eval(x) for x in node.args) for node in table.args[1].elts)
            self.assertEqual(entries, result['strings'])
            self.assertEqual(entries['ProductVersion'], value)
            self.assertEqual(entries['CompanyName'], 'Sunrise Group')
            self.assertEqual(entries['OriginalFilename'], 'Sunrise Drawing Editor.exe')
            var = kwargs['kids'].elts[1].args[0].elts[0]
            self.assertEqual(ast.literal_eval(var.args[1]), [1042,1200])

    def test_invalid_versions(self):
        for value in ['1.1', '01.0.0', '1.65536.0', 'v1.0.0', None]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                version.expected_version(self.fixture(value))

    def test_missing_or_duplicate_definition(self):
        root = self.fixture('1.0.0')
        path = root / 'drawing_editor/release_feed.py'
        for text in ['', "APP_VERSION='1.0.0'\nAPP_VERSION='1.1.0'\n"]:
            path.write_text(text)
            with self.assertRaises(ValueError):
                version.expected_version(root)

    def test_readback_match_and_mismatch(self):
        expected = version.expected_version()
        with patch.object(version,'read_version_resource',return_value=expected):
            self.assertEqual(version.verify_version_resource('dummy.exe'),expected)
        for key in ('fixed_file_version','fixed_product_version','translation','strings'):
            bad = copy.deepcopy(expected); bad[key] = None
            with patch.object(version,'read_version_resource',return_value=bad), self.assertRaises(ValueError):
                version.verify_version_resource('dummy.exe')
        bad = copy.deepcopy(expected); bad['strings'].pop('CompanyName')
        with patch.object(version,'read_version_resource',return_value=bad), self.assertRaises(ValueError):
            version.verify_version_resource('dummy.exe')

    def test_smoke_stops_before_launch_when_resource_missing(self):
        exe = Path(self.tmp.name)/'test.exe'; exe.write_bytes(b'MZ'+b'0'*2048)
        stamp = exe.parent/'SMOKE_STATUS.json'; stamp.write_text('old')
        with patch.object(smoke_test,'verify_version_resource',side_effect=ValueError('missing')), patch.object(smoke_test.subprocess,'run') as run:
            self.assertNotEqual(smoke_test.smoke(exe,120),0); run.assert_not_called()
        self.assertFalse(stamp.exists())

    def test_smoke_attests_metadata_and_hash(self):
        exe = Path(self.tmp.name)/'test.exe'; exe.write_bytes(b'MZ'+b'0'*2048)
        expected = version.expected_version()
        with patch.object(smoke_test,'verify_version_resource',return_value=expected), patch.object(smoke_test.subprocess,'run',return_value=__import__('types').SimpleNamespace(returncode=0)):
            self.assertEqual(smoke_test.smoke(exe,120),0)
        stamp = json.loads((exe.parent/'SMOKE_STATUS.json').read_text())
        self.assertEqual(stamp['version_resource'],expected)
        self.assertEqual(stamp['sha256'],hashlib.sha256(exe.read_bytes()).hexdigest())

    def test_publish_rejects_missing_or_mismatched_attestation(self):
        exe = Path(self.tmp.name)/'test.exe'; exe.write_bytes(b'MZ'+b'0'*2048)
        sha = hashlib.sha256(exe.read_bytes()).hexdigest()
        (exe.parent/'SIGNATURE_STATUS.json').write_text(json.dumps({'sha256': sha}))
        stamp = exe.parent/'SMOKE_STATUS.json'
        for metadata in (None, {}, {'strings': {'ProductVersion': '9.9.9'}}):
            stamp.write_text(json.dumps({'sha256': sha, 'passed': True, 'version_resource': metadata}))
            with patch.object(publish_release,'embedded_signer_certificates') as cert, patch.object(publish_release,'publish_bundle') as publish:
                with self.assertRaisesRegex(RuntimeError, 'version resource attestation'):
                    publish_release.publish(exe, exe.parent/'dist')
                cert.assert_not_called(); publish.assert_not_called()

    def test_spec_routes_resource_to_exe(self):
        spec = (version.ROOT/'build/onefile_lightweight.spec').read_text(encoding='utf-8')
        tree = ast.parse(spec)
        calls = [n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)]
        self.assertEqual(sum(n.func.id == 'write_version_resource' for n in calls),1)
        exe = next(n for n in calls if n.func.id == 'EXE')
        arg = next(n.value for n in exe.keywords if n.arg == 'version')
        self.assertEqual(ast.unparse(arg),'str(version_path)')
        self.assertIn('version_path = args.plan.parent / \'VERSIONINFO.txt\'', spec)

if __name__ == '__main__': unittest.main(verbosity=2)
