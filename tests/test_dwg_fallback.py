import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from drawing_editor.dwg_fallback import ConverterError, read_dwg_with_librecad


@unittest.skipIf(os.name == 'nt', 'POSIX dummy executable fixture')
class LibreCadFallbackTests(unittest.TestCase):
    def test_converter_invocation_is_not_shell_and_source_is_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'large example.dwg'
            source.write_bytes(b'FAKE-DWG')
            fake_dxf = root / 'fixture.dxf'
            import ezdxf
            d = ezdxf.new('R2013')
            d.layers.new('WATER')
            d.modelspace().add_line((0, 0), (100, 20), dxfattribs={'layer': 'WATER'})
            d.saveas(fake_dxf)
            converter = root / 'mock-librecad'
            converter.write_text('#!/bin/sh\ncp "'+str(fake_dxf)+'" "$3"\n', encoding='utf-8')
            converter.chmod(0o755)
            result = read_dwg_with_librecad(source, exe=converter)
            self.assertIsNotNone(result.layers.get('WATER'))
            self.assertEqual(source.read_bytes(), b'FAKE-DWG')
            self.assertFalse((root / 'converted.dxf').exists())

    def test_missing_converter_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing.dwg'
            path.write_bytes(b'FAKE')
            with self.assertRaises(ConverterError):
                read_dwg_with_librecad(path, exe=Path(directory) / 'missing')
