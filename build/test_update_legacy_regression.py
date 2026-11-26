"""Preserve the runtime 1.0.0 R03 -> 1.1.0 R03 updater contract.

Reconciled from GitHub main's historical tests for the v1.6.0 candidate:
existing feed parsing remains compatible; new public approval is not historical feed parsing.
Offline tests only: no network, file replacement, certificate installation or release activation.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from drawing_editor.release_feed import (
    APP_ID, APP_VERSION, ASSET_NAME, LOCAL_EXE_NAME, RELEASES,
    parse_release, release_download_urls, validated_download,
)
from drawing_editor.control import ControlDenied, Policy, ensure_update_allowed, parse_control
from drawing_editor import onefile_update


SHA256 = 'a' * 64


def _feed(version, url, name):
    return json.dumps({
        'schema_version': 1, 'app_id': APP_ID, 'platform': 'windows-x64',
        'package_kind': 'onefile_exe', 'latest_version': version,
        'update_endpoint_configured': True, 'official_release': True,
        'automatic_update_available': True, 'authenticode_required': True,
        'release_url': RELEASES + '/tag/v' + version,
        'download_url': url, 'download_file_name': name,
        'sha256': SHA256, 'file_size_bytes': 12345678,
    })


class LegacyUpdateContractTests(unittest.TestCase):
    def test_both_historical_asset_names_accepted_for_100_to_110(self):
        canonical, legacy = release_download_urls('1.1.0')
        self.assertTrue(canonical.endswith('/Sunrise.Drawing.Editor.exe'))
        self.assertTrue(legacy.endswith('/Sunrise%20Drawing%20Editor.exe'))
        for url, name in ((canonical, ASSET_NAME), (legacy, LOCAL_EXE_NAME)):
            with self.subTest(url=url):
                parsed = parse_release(_feed('1.1.0', url, name), current='1.0.0')
                self.assertEqual(parsed.download, url)
                self.assertTrue(parsed.automatic)
                self.assertIsNone(parse_release(_feed('1.1.0', url, name), current='1.1.0'))

    def test_same_contract_for_110_to_150(self):
        for url, name in zip(release_download_urls('1.5.0'), (ASSET_NAME, LOCAL_EXE_NAME)):
            with self.subTest(url=url):
                data=json.loads(_feed('1.5.0', url, name))
                data.update(signature_trust='SELF_SIGNED_UNTRUSTED_TEST_ONLY',
                            signature_policy='GROUP_SIGNED_AT_BUILD_FEED_SHA256')
                parsed = parse_release(json.dumps(data), current='1.1.0')
                self.assertEqual(parsed.sha256, SHA256)
                self.assertEqual(parsed.size, 12345678)
                self.assertTrue(parsed.automatic)
                self.assertIsNone(parse_release(json.dumps(data),current=APP_VERSION))

    def test_unapproved_urls_and_filename_mismatch_rejected(self):
        good, _ = release_download_urls('1.5.0')
        for url in (good + '?download=1', good.replace('github.com', 'evil.example'),
                    RELEASES + '/download/v1.5.0/other.exe'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validated_download('1.5.0', url)
        with self.assertRaises(ValueError):
            parse_release(_feed('1.5.0', good, LOCAL_EXE_NAME), current='1.1.0')

    def test_new_public_approval_does_not_treat_historical_group_feed_as_new_authority(self):
        from build.approve_update import approved_metadata
        version=APP_VERSION
        url = release_download_urls(version)[0]
        data = json.loads(_feed(version, url, ASSET_NAME))
        release = {'tag_name': 'v'+version, 'draft': False, 'prerelease': False,
                   'assets': [{'name': ASSET_NAME, 'state': 'uploaded',
                               'size': 12345678, 'digest': 'sha256:' + SHA256,
                               'browser_download_url': url}]}
        # R15 distinguishes the new group-only candidate from public approval.
        for metadata, trust in ((data,'SELF_SIGNED_UNTRUSTED_TEST_ONLY'),
                                (dict(data,signature_policy='GROUP_PINNED_INTERNAL_QA_PUBLIC_FEED_DISABLED'),
                                 'TRUSTED_BY_WINDOWS_POLICY')):
            with self.subTest(trust=trust),self.assertRaises(ValueError):
                approved_metadata(metadata, release, version=version, old_version='1.5.0',
                                  sha=SHA256, size=12345678, signature_trust=trust)
        release['assets'][0]['size'] = 12345679
        with self.assertRaises(ValueError):
            approved_metadata(data, release, version=version, old_version='1.5.0',
                              sha=SHA256, size=12345678,
                              signature_trust='TRUSTED_BY_WINDOWS_POLICY')

    def test_product_update_block_keeps_execution_allowed(self):
        policy = parse_control('''[global]\nschema_version=1\ndefault_operation=allow\ndefault_update=allow\n\n[product.sunrise_drawing_editor]\noperation=allow\nupdate=block\nminimum_version=\nmessage=검증 중 업데이트 차단\n''')
        self.assertFalse(policy.blocks_entry)
        self.assertEqual(policy.update, 'block')
        with self.assertRaises(ControlDenied):
            ensure_update_allowed(policy, '1.5.0')

    def test_block_prevents_candidate_download_or_swap(self):
        release = parse_release(_feed('1.5.0', release_download_urls('1.5.0')[0], ASSET_NAME), current='1.1.0')
        with tempfile.TemporaryDirectory() as work:
            target = Path(work) / ASSET_NAME
            target.write_bytes(b'original executable')
            with patch.object(onefile_update, 'APP_VERSION', '1.1.0'), \
                 patch.object(onefile_update.sys, 'platform', 'win32'), \
                 patch.object(onefile_update.sys, 'frozen', True, create=True), \
                 patch.object(onefile_update.sys, 'executable', str(target)), \
                 patch.object(onefile_update, 'check_policy', return_value=Policy(operation='allow', update='block')), \
                 patch.object(onefile_update, 'build_opener') as network:
                with self.assertRaises(ControlDenied):
                    onefile_update.stage_update(release)
                network.assert_not_called()
            self.assertEqual(target.read_bytes(), b'original executable')
            self.assertEqual(sorted(p.name for p in Path(work).iterdir()), [ASSET_NAME])


if __name__ == '__main__':
    unittest.main(verbosity=2)
