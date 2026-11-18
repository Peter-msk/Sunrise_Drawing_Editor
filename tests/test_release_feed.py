import json
import unittest
from drawing_editor.release_feed import APP_ID, RELEASES, parse_release, version_tuple, notice_id


def fixture():
    return dict(schema_version=1, app_id=APP_ID, platform='windows-x64',
                package_kind='onefile_exe', latest_version='1.0.1',
                update_endpoint_configured=True, official_release=True,
                authenticode_required=True, release_url=RELEASES+'/tag/v1.0.1',
                download_url=RELEASES+'/download/v1.0.1/Sunrise%20Drawing%20Editor.exe',
                sha256='a'*64, file_size_bytes=1024)


class ReleaseFeedTests(unittest.TestCase):
    def test_numeric_versions(self):
        self.assertGreater(version_tuple('1.10.0'), version_tuple('1.9.9'))
        for bad in ('1.2', '01.0.0', 'v1.0.0', '1.0.0-rc'):
            with self.assertRaises(ValueError):
                version_tuple(bad)

    def test_enabled_newer_release(self):
        self.assertEqual(parse_release(json.dumps(fixture())).version, '1.0.1')

    def test_no_update_on_current_or_disabled(self):
        data = fixture()
        self.assertIsNone(parse_release(json.dumps(data), current='1.0.1'))
        data['update_endpoint_configured'] = False
        self.assertIsNone(parse_release(json.dumps(data)))

    def test_reject_cross_repo_and_wrong_product(self):
        for key, value in [('release_url', 'https://evil.example/'), ('download_url', 'https://evil.example/'),
                           ('sha256', 'bad'), ('file_size_bytes', True), ('app_id', 'other'),
                           ('official_release', False), ('authenticode_required', False)]:
            data = fixture()
            data[key] = value
            with self.assertRaises(ValueError):
                parse_release(json.dumps(data))

    def test_automatic_is_explicit_and_defaults_off(self):
        data = fixture()
        self.assertFalse(parse_release(json.dumps(data)).automatic)
        data['automatic_update_available'] = True
        self.assertTrue(parse_release(json.dumps(data)).automatic)
        data['automatic_update_available'] = 'true'
        with self.assertRaises(ValueError):
            parse_release(json.dumps(data))

    def test_notice_id(self):
        self.assertEqual(notice_id(' hello '), notice_id('hello'))
