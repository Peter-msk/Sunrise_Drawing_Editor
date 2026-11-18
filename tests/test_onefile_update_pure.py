import hashlib
from io import BytesIO
import unittest
from drawing_editor.onefile_update import check_update_url, stream_verified, UpdateError

class OnefilePureTests(unittest.TestCase):
    def test_exact_stream(self):
        source = b'abcd'*1024
        output = BytesIO()
        stream_verified(BytesIO(source), output, len(source), hashlib.sha256(source).hexdigest())
        self.assertEqual(output.getvalue(), source)

    def test_wrong_size_hash_cancel(self):
        source = b'abc'
        for size, digest in [(2, hashlib.sha256(source).hexdigest()), (4, 'a'*64), (3, 'a'*64)]:
            with self.assertRaises(UpdateError):
                stream_verified(BytesIO(source), BytesIO(), size, digest)
        with self.assertRaises(UpdateError):
            stream_verified(BytesIO(source), BytesIO(), 3, 'a'*64, cancelled=lambda: True)

    def test_redirect_boundaries(self):
        url = 'https://github.com/Peter-msk/Sunrise_Drawing_Editor/releases/download/v1.0.1/Sunrise%20Drawing%20Editor.exe'
        check_update_url(url, url)
        check_update_url('https://release-assets.githubusercontent.com/abc?token=abc', url)
        for bad in ('http://release-assets.githubusercontent.com/abc', 'https://evil.example/abc',
                    'https://github.com/another/project/releases/download/a.exe',
                    'https://a@release-assets.githubusercontent.com/abc',
                    'https://release-assets.githubusercontent.com:8080/abc'):
            with self.assertRaises(UpdateError):
                check_update_url(bad, url)
