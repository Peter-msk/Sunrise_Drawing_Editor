import json
from pathlib import Path
import tempfile
import unittest
from drawing_editor.control import (Policy, ControlDenied, check_policy, parse_control,
                                    ensure_update_allowed)

GLOBAL = '''[global]
schema_version=1
default_operation=allow
default_update=allow
fallback_operation=maintenance
fallback_update=block
cache_ttl_seconds=21600
'''
PRODUCT = '[product.sunrise_drawing_editor]\n'


def offline():
    raise OSError('offline')


class ControlTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'cache.json'

    def check(self, fetch, now=100):
        return check_policy(fetch=fetch, path=self.path, now=now)

    def test_product_overrides_global_and_other_products(self):
        p = parse_control(GLOBAL + '[product.other]\noperation=block\n' + PRODUCT + 'operation=maintenance\nmessage=점검 중\n')
        self.assertTrue(p.blocks_entry)
        self.assertEqual(p.message, '점검 중')
        self.assertEqual(p.update, 'allow')

    def test_global_and_required(self):
        self.assertTrue(parse_control(GLOBAL.replace('default_operation=allow', 'default_operation=block')).blocks_entry)
        for minimum, required in [('1.0.0', False), ('1.0.1', True), ('', False)]:
            p = parse_control(GLOBAL + PRODUCT + f'update=required\nminimum_version={minimum}\n')
            self.assertEqual(p.requires_update, required)

    def test_update_block_and_minimum(self):
        with self.assertRaises(ControlDenied):
            ensure_update_allowed(Policy(update='block'))
        p = Policy(update='required', minimum_version='1.1.0')
        with self.assertRaises(ControlDenied):
            ensure_update_allowed(p, '1.0.1')
        ensure_update_allowed(p, '1.1.0')
        ensure_update_allowed(Policy(operation='maintenance', update='allow'), '1.1.0')

    def test_invalid_policy(self):
        for body in [GLOBAL.replace('schema_version=1', 'schema_version=2'), GLOBAL + PRODUCT + 'operation=anything', GLOBAL + PRODUCT + 'minimum_version=1.2', GLOBAL + PRODUCT + 'update=allow\nupdate=block', GLOBAL + '[global]\n', 'bad']:
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_control(body)

    def test_cache_and_expired_fallback(self):
        p = self.check(lambda: GLOBAL + PRODUCT + 'operation=block\n')
        self.assertEqual(p.source, 'online')
        cached = self.check(offline, 101)
        self.assertEqual((cached.operation, cached.source), ('block', 'cache'))
        expired = self.check(offline, 21701)
        self.assertEqual((expired.operation, expired.update, expired.source), ('maintenance', 'block', 'fallback'))

    def test_cold_offline_and_invalid_cache(self):
        self.assertEqual(self.check(offline), Policy())
        self.path.write_text('{bad')
        self.assertEqual(self.check(offline), Policy())

    def test_bad_online_does_not_replace_cache(self):
        self.check(lambda: GLOBAL + PRODUCT + 'operation=block\n')
        before = self.path.read_bytes()
        p = self.check(lambda: 'invalid', 102)
        self.assertEqual(p.operation, 'block')
        self.assertEqual(self.path.read_bytes(), before)

    def test_future_timestamp_not_used_as_live_policy(self):
        self.path.write_text(json.dumps({'fetched_at': 101, 'content': GLOBAL + PRODUCT + 'operation=block'}))
        p = self.check(offline, 100)
        self.assertEqual((p.source, p.operation), ('fallback', 'maintenance'))

    def test_ttl_bounds_and_utf8_bom(self):
        self.assertEqual(parse_control('\ufeff' + GLOBAL.replace('21600', '1')).ttl, 60)
        self.assertEqual(parse_control(GLOBAL.replace('21600', '90000')).ttl, 86400)


if __name__ == '__main__':
    unittest.main()
