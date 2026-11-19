"""Offline policy and product feed contracts; never edit the central server."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drawing_editor import control, release_feed as feed

GLOBAL = '''[global]
schema_version=1
default_operation=allow
default_update=allow
fallback_operation=maintenance
fallback_update=block
cache_ttl_seconds=21600
'''


def policy(operation='allow', update='allow', minimum='', message=''):
    return GLOBAL + ('\n[product.sunrise_drawing_editor]\n'
                     f'operation={operation}\nupdate={update}\n'
                     f'minimum_version={minimum}\nmessage={message}\n')


def unavailable():
    raise OSError('offline')


class ControlPolicyTests(unittest.TestCase):
    def test_product_overrides_global(self):
        p = control.parse_control(policy('allow').replace('default_operation=allow', 'default_operation=block'))
        self.assertFalse(p.blocks_entry)

    def test_global_when_product_absent(self):
        p = control.parse_control(GLOBAL.replace('default_operation=allow', 'default_operation=block'))
        self.assertTrue(p.blocks_entry)

    def test_operation_modes_and_message(self):
        for op in ('allow', 'maintenance', 'block'):
            p = control.parse_control(policy(op, message='점검 중'))
            self.assertEqual(p.blocks_entry, op != 'allow')
            self.assertEqual(p.message, '점검 중')

    def test_update_modes(self):
        control.ensure_update_allowed(control.parse_control(policy()))
        with self.assertRaises(control.ControlDenied):
            control.ensure_update_allowed(control.parse_control(policy(update='block')))

    def test_required_100_to_110(self):
        p = control.parse_control(policy(update='required', minimum='1.1.0'))
        for version, required in [('1.0.0', True), ('1.1.0', False)]:
            with patch.object(control, 'APP_VERSION', version):
                self.assertEqual(p.requires_update, required)
        with self.assertRaises(control.ControlDenied):
            control.ensure_update_allowed(p, '1.0.0')
        control.ensure_update_allowed(p, '1.1.0')

    def test_cache_and_expired_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'control.json'
            original = policy('block', 'allow')
            self.assertEqual(control.check_policy(fetch=lambda: original, path=path, now=100).source, 'online')
            p = control.check_policy(fetch=unavailable, path=path, now=101)
            self.assertEqual((p.source, p.operation, p.update), ('cache', 'block', 'allow'))
            p = control.check_policy(fetch=unavailable, path=path, now=21701)
            self.assertEqual((p.source, p.operation, p.update), ('fallback', 'maintenance', 'block'))

    def test_malformed_network_does_not_replace_valid_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'control.json'
            control.check_policy(fetch=lambda: policy('block'), path=path, now=100)
            before = path.read_bytes()
            p = control.check_policy(fetch=lambda: 'invalid', path=path, now=101)
            self.assertTrue(p.blocks_entry)
            self.assertEqual(path.read_bytes(), before)

    def test_invalid_duplicate_or_version_rejected(self):
        for value in (policy('unknown'), policy(update='unknown'), policy(minimum='v1.1.0'),
                      policy() + '\noperation=allow\n', GLOBAL.replace('schema_version=1', 'schema_version=2')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                control.parse_control(value)

    def test_offline_without_cache_group_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = control.check_policy(fetch=unavailable, path=Path(tmp) / 'missing.json', now=100)
            self.assertEqual((p.source, p.operation, p.update), ('fallback', 'allow', 'allow'))

    def test_disabled_feed_not_offered(self):
        data = self.release_data()
        data['update_endpoint_configured'] = False
        info = feed.parse_update_info(json.dumps(data), current='1.0.0')
        self.assertEqual(info.latest, '1.1.0')
        self.assertIsNone(info.release)

    def test_100_to_110_approved_and_same_version(self):
        data = self.release_data()
        self.assertEqual(feed.parse_release(json.dumps(data), current='1.0.0').version, '1.1.0')
        self.assertIsNone(feed.parse_release(json.dumps(data), current='1.1.0'))

    def test_notice_identity(self):
        self.assertEqual(feed.notice_id('공지\n'), feed.notice_id('공지'))
        self.assertNotEqual(feed.notice_id('공지'), feed.notice_id('신규 공지'))

    @staticmethod
    def release_data():
        return dict(schema_version=1, app_id=feed.APP_ID, platform='windows-x64',
                    package_kind='onefile_exe', latest_version='1.1.0',
                    official_release=True, update_endpoint_configured=True,
                    automatic_update_available=True, authenticode_required=True,
                    release_url=feed.RELEASES + '/tag/v1.1.0',
                    download_url=feed.release_download_urls('1.1.0')[0],
                    download_file_name=feed.ASSET_NAME, sha256='a'*64, file_size_bytes=100)


if __name__ == '__main__':
    unittest.main(verbosity=2)
