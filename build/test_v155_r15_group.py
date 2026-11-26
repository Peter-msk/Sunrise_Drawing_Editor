"""R15 signing/QA contracts; no native Windows trust claims from these fixtures."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cryptography.hazmat.primitives import hashes
from build import sign_release as signing, final_qa_v150 as qa
from build.release_metadata import publish_bundle
from build.pe_version import expected_version
from drawing_editor.release_feed import APP_VERSION


class GroupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, _, cls.cert = signing.generate_local_certificate()
        _, _, cls.other = signing.generate_local_certificate()
        cls.pin = cls.cert.fingerprint(hashes.SHA256()).hex().upper()

    def test_pin_and_no_fallback(self):
        with patch.dict(os.environ, {'SUNRISE_GROUP_CERT_SHA256': self.pin.lower()}):
            self.assertEqual(signing.group_pin(), self.pin)
        with patch.dict(os.environ, {'SUNRISE_GROUP_CERT_SHA256': 'not-a-pin'}):
            with self.assertRaises(signing.SignError): signing.group_pin()
        with patch.object(signing, 'make_cert_in_user_store') as make:
            self.assertIs(signing.select_store_signer([self.other, self.cert], self.pin), self.cert)
            for certs in ([], [self.other], [self.cert, self.cert]):
                with self.assertRaises(signing.SignError): signing.select_store_signer(certs, self.pin)
            make.assert_not_called()

    def test_group_native_verification_required(self):
        report = dict(subject='CN=Sunrise Group', certificate_thumbprint_sha256=self.pin)
        exe = Path('fixture.exe')
        with patch.object(signing, 'embedded_signer_certificates', return_value=[self.cert]) as embedded, \
                patch.object(signing, 'find_signtool', return_value=Path('signtool.exe')), \
                patch.object(signing, 'call') as call:
            self.assertTrue(signing.require_group_signature(exe, report, self.pin))
            self.assertEqual(call.call_args.args[0][1:5], ['verify','/pa','/all','/v'])
            call.side_effect = signing.SignError('native verification failure')
            with self.assertRaises(signing.SignError): signing.require_group_signature(exe, report, self.pin)
            call.reset_mock(); embedded.return_value = [self.other]
            with self.assertRaises(signing.SignError): signing.require_group_signature(exe, report, self.pin)
            call.assert_not_called()

    def test_publish_preserves_postsign_smoke_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); exe = root/'Sunrise Drawing Editor.exe'; exe.write_bytes(b'signed fixture')
            digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            sha = digest(exe); signature = dict(sha256=sha, trust='SELF_SIGNED_UNTRUSTED_TEST_ONLY')
            smoke = dict(sha256=sha, passed=True, version_resource=expected_version())
            dest = root/'dist'; dest.mkdir()
            old = dest/exe.name; old.write_bytes(b'old exe')
            stamp = dest/'SMOKE_STATUS.json'; stamp.write_bytes(b'old stamp')
            with self.assertRaises(ValueError):
                publish_bundle(exe,dest,sha,signature,digest,functional_qa={},smoke=dict(smoke,sha256='bad'))
            self.assertEqual(old.read_bytes(),b'old exe')
            real_replace = os.replace
            def fail_last(src,dst):
                if Path(dst)==old: raise OSError('simulated final replace failure')
                return real_replace(src,dst)
            with patch('os.replace',side_effect=fail_last), self.assertRaises(OSError):
                publish_bundle(exe,dest,sha,signature,digest,functional_qa={},smoke=smoke)
            self.assertEqual(old.read_bytes(),b'old exe'); self.assertEqual(stamp.read_bytes(),b'old stamp')
            publish_bundle(exe,dest,sha,signature,digest,functional_qa={},smoke=smoke)
            self.assertEqual(json.loads(stamp.read_text()),smoke)
            self.assertEqual(digest(old),sha)

    def test_internal_build_metadata_cannot_activate_public_feed(self):
        from build.approve_update import approved_metadata
        from build.release_metadata import build_metadata
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'Sunrise Drawing Editor.exe'; exe.write_bytes(b'fixture')
            sha=hashlib.sha256(exe.read_bytes()).hexdigest()
            metadata=json.loads(build_metadata(exe,sha,dict(sha256=sha,trust='TRUSTED_BY_WINDOWS_POLICY',
                group_certificate_pin_verified=True,certificate_thumbprint_sha256=self.pin))['latest.json'])
            self.assertEqual(metadata['signature_policy'],'GROUP_PINNED_INTERNAL_QA_PUBLIC_FEED_DISABLED')
            self.assertEqual(metadata['group_certificate_sha256'],self.pin)
            self.assertFalse(metadata['automatic_update_available'])
            with self.assertRaisesRegex(ValueError,'Internal group build'):
                approved_metadata(metadata,{},version=APP_VERSION,old_version='1.5.4',sha=sha,size=exe.stat().st_size,
                                  signature_trust='TRUSTED_BY_WINDOWS_POLICY')

    def test_internal_candidate_never_activates_feed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); dist=root/'dist'; dist.mkdir(); exe=dist/'Sunrise Drawing Editor.exe'; exe.write_bytes(b'fixture')
            sha=hashlib.sha256(exe.read_bytes()).hexdigest()
            sig=dict(sha256=sha,embedded_certificate_match=True,trust='SELF_SIGNED_UNTRUSTED_TEST_ONLY',certificate_thumbprint_sha256=self.pin)
            smoke=dict(sha256=sha,passed=True,version_resource=expected_version())
            (dist/'SIGNATURE_STATUS.json').write_text(json.dumps(sig))
            stamp=dist/'SMOKE_STATUS.json'; stamp.write_text(json.dumps(smoke))
            from build.release_metadata import build_metadata
            sig_fixture = json.loads((dist/'SIGNATURE_STATUS.json').read_text())
            (dist/'SHA256.txt').write_bytes(f'{sha}  {exe.name}\n'.encode('utf-8'))
            (dist/'release-metadata').mkdir()
            for name, body in build_metadata(exe, sha, sig_fixture).items():
                (dist/'release-metadata'/name).write_bytes(body)
            with patch.object(qa,'ROOT',root), patch('build.pe_version.verify_version_resource',return_value=expected_version()), \
                    patch('build.functional_gate.read_functional_qa'), patch.object(signing,'require_group_signature') as verify:
                with patch.dict(os.environ,{'SUNRISE_GROUP_CERT_SHA256':''}):
                    self.assertEqual(qa.postbuild(qt_tests_passed=True)['status'],'INTERNAL_QA_ONLY')
                    verify.assert_not_called()
                with patch.dict(os.environ,{'SUNRISE_GROUP_CERT_SHA256':self.pin}):
                    pending=qa.postbuild(); self.assertEqual(pending['status'],'GROUP_INTERNAL_CANDIDATE_QT_PENDING')
                    report=qa.postbuild(qt_tests_passed=True)
                    self.assertEqual(report['status'],'GROUP_INTERNAL_CANDIDATE_MANUAL_PENDING')
                    self.assertTrue(report['group_certificate_pin_verified'])
                    self.assertEqual(report['signature_trust'],'SELF_SIGNED_UNTRUSTED_TEST_ONLY')
                    self.assertIs(report['official_release'],False); self.assertIs(report['automatic_update_available'],False)
                    verify.side_effect=signing.SignError('not trusted')
                    with self.assertRaises(signing.SignError): qa.postbuild(qt_tests_passed=True)
                    self.assertFalse((dist/'V150_LOCAL_QA.json').exists())
                stamp.write_text(json.dumps(dict(smoke,version_resource={})))
                with self.assertRaises(RuntimeError): qa.postbuild(qt_tests_passed=True)

if __name__ == '__main__': unittest.main(verbosity=2)
