"""Compound DXF support: real round trips, dependency rejection and worker recovery."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ezdxf
from ezdxf.lldxf.tagwriter import TagCollector
from drawing_editor.core import DrawingError, OutputOptions, source_signature
from drawing_editor.vector_export import export_vector_snapshot
from drawing_editor.batch import ExportJob
from drawing_editor.batch_worker import run_batch_exports_isolated


def tags(entity):
    return [(t.code, t.value) for t in TagCollector.dxftags(entity)
            if t.code not in (5, 330, 390, 347, 348)]


class CompoundDXF(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.doc = ezdxf.new('R2013')
        self.doc.units = 6
        self.doc.layers.new('ROAD')
        self.doc.layers.new('OTHER')
        self.model = self.doc.modelspace()

    def save(self):
        p = self.root / 'source.dxf'
        self.doc.saveas(p)
        return p

    def states(self, hidden=()):
        return {layer.dxf.name: layer.dxf.name not in hidden for layer in self.doc.layers}

    def output(self, hidden=()):
        p = self.save()
        old = hashlib.sha256(p.read_bytes()).hexdigest()
        destination = self.root / 'out.dxf'
        export_vector_snapshot(p, self.states(hidden), 0, destination, OutputOptions(fmt='dxf'))
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), old)
        self.assertFalse(list(self.root.glob('.drawing-*')))
        result = ezdxf.readfile(destination)
        audit = result.audit()
        self.assertFalse(audit.has_errors or audit.fixes)
        return ezdxf.readfile(p), result

    def reject(self, message, hidden=()):
        p = self.save()
        with self.assertRaisesRegex(DrawingError, message):
            export_vector_snapshot(p, self.states(hidden), 0, self.root / 'out.dxf', OutputOptions(fmt='dxf'))
        self.assertFalse((self.root / 'out.dxf').exists())
        self.assertFalse(list(self.root.glob('.drawing-*')))

    def test_text_and_mtext_with_custom_standard_font(self):
        self.doc.styles.get('Standard').dxf.font = 'custom.shx'
        self.doc.styles.get('Standard').dxf.width = 0.85
        self.doc.styles.new('KOR', dxfattribs={'font': 'example.ttf', 'bigfont': 'hangul.shx', 'oblique': 12})
        self.model.add_text('사업지구', dxfattribs={'layer': 'ROAD', 'insert': (123456, 432100, 7), 'height': 2.5, 'rotation': 21})
        self.model.add_mtext('조사 지점\\P환경영향평가', dxfattribs={'layer': 'ROAD', 'style': 'KOR', 'insert': (123450, 432100), 'char_height': 3, 'width': 80})
        a,b = self.output()
        self.assertEqual([tags(e) for e in a.modelspace()], [tags(e) for e in b.modelspace()])
        for style in ('Standard','KOR'):
            for field in ('font','bigfont','width','oblique'):
                self.assertEqual(a.styles.get(style).dxf.get_default(field), b.styles.get(style).dxf.get_default(field))

    def test_pattern_hatch_roundtrip(self):
        h=self.model.add_hatch(dxfattribs={'layer':'ROAD'})
        h.set_pattern_fill('ANSI31', scale=2.5, angle=23)
        h.paths.add_polyline_path([(1,2,0),(3,4,.25),(5,2,0)], is_closed=True)
        h.paths.add_polyline_path([(2,2.5),(2.5,3),(3,2.5)], is_closed=True)
        a,b=self.output()
        self.assertEqual(tags(a.modelspace()[0]),tags(b.modelspace()[0]))

    def test_static_nested_blocks_roundtrip(self):
        inner=self.doc.blocks.new('INNER',base_point=(1,2,3))
        inner.block_record.dxf.units=6
        inner.block_record.dxf.explode=0
        inner.add_circle((10,15,3),2,dxfattribs={'layer':'0'})
        outer=self.doc.blocks.new('OUTER',base_point=(7,8,0))
        outer.add_blockref('INNER',(100,200,3),dxfattribs={'layer':'ROAD','rotation':17})
        outer.add_line((1,2),(3,4),dxfattribs={'layer':'ROAD'})
        self.model.add_blockref('OUTER',(123456,432100,9),dxfattribs={'layer':'ROAD','rotation':35,'xscale':2,'yscale':2})
        self.model.add_blockref('OUTER',(123457,432101),dxfattribs={'layer':'ROAD'})
        self.model.add_point((9,9),dxfattribs={'layer':'OTHER'})
        a,b=self.output(('OTHER',))
        self.assertEqual([tags(e) for e in a.modelspace()][:2],[tags(e) for e in b.modelspace()])
        for name in ('INNER','OUTER'):
            self.assertEqual(a.blocks[name].block.dxf.base_point,b.blocks[name].block.dxf.base_point)
            self.assertEqual([tags(e) for e in a.blocks[name]],[tags(e) for e in b.blocks[name]])
            for field in ('units','explode','scale'):
                self.assertEqual(a.blocks[name].block_record.dxf.get_default(field),b.blocks[name].block_record.dxf.get_default(field))

    def test_block_child_geometry_corruption_rejected(self):
        from ezdxf.addons import Importer
        b=self.doc.blocks.new('B')
        b.add_line((0,0),(1,1))
        self.model.add_blockref('B',(0,0),dxfattribs={'layer':'ROAD'})
        original=Importer.import_entity
        def corrupt(self,entity,target_layout=None):
            original(self,entity,target_layout)
            if entity.dxftype()=='LINE':target_layout[-1].dxf.end=(99,99,0)
        with patch.object(Importer,'import_entity',corrupt):
            self.reject('객체 데이터 불일치')

    def test_missing_style_rejected(self):
        self.model.add_text('text',dxfattribs={'layer':'ROAD','style':'MISSING'})
        self.reject('문자 스타일 정의 누락')

    def test_associated_hatch_rejected(self):
        h=self.model.add_hatch(dxfattribs={'layer':'ROAD','associative':1})
        h.paths.add_polyline_path([(0,0),(0,1),(1,1)],is_closed=True)
        self.reject('연관 해치')

    def test_hidden_block_child_rejected_and_worker_continues(self):
        b=self.doc.blocks.new('B')
        b.add_line((1,1),(2,2),dxfattribs={'layer':'OTHER'})
        self.model.add_blockref('B',(0,0),dxfattribs={'layer':'ROAD'})
        p=self.save()
        jobs=[ExportJob(str(p),self.states(hidden),0,str(self.root/f'{i}.dxf'),source_signature(p)) for i,hidden in enumerate((('OTHER',),()))]
        result=run_batch_exports_isolated(jobs,OutputOptions(fmt='dxf'))
        self.assertEqual(len(result.errors),1)
        self.assertIn('선택하지 않은 레이어',result.errors[0][1])
        self.assertEqual(result.completed,(jobs[1].target,))
        self.assertFalse(list(self.root.glob('.drawing-*')))

    def test_unsupported_child_and_cycle_rejected(self):
        b=self.doc.blocks.new('B')
        b.add_xline((0,0),(1,0))
        self.model.add_blockref('B',(0,0),dxfattribs={'layer':'ROAD'})
        self.reject('XLINE')
        b.delete_all_entities()
        b.add_blockref('B',(0,0))
        self.reject('순환')

    def test_external_reference_rejected(self):
        b=self.doc.blocks.new('EXT',dxfattribs={'flags':4,'xref_path':'external.dxf'})
        self.model.add_blockref(b.name,(0,0),dxfattribs={'layer':'ROAD'})
        self.reject('외부 참조')

    def test_attribute_insert_rejected(self):
        self.doc.blocks.new('B')
        e=self.model.add_blockref('B',(0,0),dxfattribs={'layer':'ROAD'})
        e.add_attrib('ID','1')
        self.reject('속성 또는 확장정보')

    def test_block_child_drop_detected_even_when_audit_clean(self):
        from ezdxf.addons import Importer
        b=self.doc.blocks.new('B')
        b.add_line((0,0),(1,1))
        self.model.add_blockref('B',(0,0),dxfattribs={'layer':'ROAD'})
        original=Importer.import_entity
        def drop(self,entity,target_layout=None):
            if entity.dxftype()=='LINE':return
            return original(self,entity,target_layout)
        with patch.object(Importer,'import_entity',drop):
            self.reject('블록 구성 불일치')


if __name__ == '__main__':
    unittest.main(verbosity=2)
