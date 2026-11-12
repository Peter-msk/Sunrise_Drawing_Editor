"""Streaming DXF catalog has identical layer names/states to full ezdxf parse."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import ezdxf

from drawing_editor.cad_catalog import read_ascii_dxf_layers
from drawing_editor.core import DrawingDocument

class FastCatalogTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'full.dxf'

    def test_fast_catalog_matches_full_model(self):
        doc = ezdxf.new('R2013')
        doc.layers.new('ROAD')
        doc.layers.new('BUILDING')
        doc.layers.new('INACTIVE')
        doc.layers.get('INACTIVE').off()
        doc.layers.get('BUILDING').freeze()
        msp=doc.modelspace()
        for i in range(4000):
            msp.add_line((i,0),(i,10),dxfattribs={'layer':'ROAD'})
        doc.saveas(self.path)
        from_fast=read_ascii_dxf_layers(self.path)
        self.assertIsNotNone(from_fast)
        with DrawingDocument(self.path) as slow:
            self.assertEqual([(x.name,x.visible) for x in from_fast],
                             [(x.name,x.visible) for x in slow.layers()])

    def test_native_unicode_layer(self):
        doc=ezdxf.new('R2013')
        doc.layers.new('하천')
        doc.saveas(self.path)
        result=read_ascii_dxf_layers(self.path)
        self.assertIsNotNone(result)
        self.assertIn('하천',[i.name for i in result])

    def test_fallback_on_bad_or_unknown_input(self):
        self.path.write_bytes(b'AutoCAD Binary DXF\r\nunknown')
        self.assertIsNone(read_ascii_dxf_layers(self.path))
        self.path.write_bytes(b'0\nSECTION\n2\nTABLES\n0\nTABLE\n2\nLAYER\n0\nLAYER\n2\nfoo\n')
        self.assertIsNone(read_ascii_dxf_layers(self.path))

    def test_only_bounded_prefix_is_read(self):
        doc=ezdxf.new('R2013');doc.layers.new('L')
        for i in range(35000):
            doc.modelspace().add_line((i,0),(i,1))
        doc.saveas(self.path)
        self.assertIsNotNone(read_ascii_dxf_layers(self.path))

if __name__=='__main__': unittest.main()
