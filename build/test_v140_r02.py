"""R02 vector safety and native SVG regressions, exercising real outputs."""
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import hashlib
from io import BytesIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz
import ezdxf
from PIL import Image
from drawing_editor.core import DrawingError, OutputOptions, source_signature
from drawing_editor.vector_export import export_vector_snapshot, _check_states
from drawing_editor.batch import ExportJob, run_batch_exports
from drawing_editor.batch_worker import run_batch_exports_isolated


class VectorStability(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def pdf(self, ocg=False):
        path = self.root / 'source.pdf'
        with fitz.open() as doc:
            a = doc.add_ocg('A', on=True) if ocg else 0
            b = doc.add_ocg('B', on=False) if ocg else 0
            if ocg:
                doc.set_layer(-1, locked=[a], rbgroups=[[a, b]])
            for i in range(2):
                page = doc.new_page(width=200, height=120)
                page.draw_rect(fitz.Rect(0, 0, 80, 80), color=None, fill=(1, 0, 0), oc=a)
                page.draw_rect(fitz.Rect(100, 0, 180, 80), color=None, fill=(0, 0, 1), oc=b)
                with Image.new('RGB', (8, 8), (0, 255, 0)) as image, BytesIO() as data:
                    image.save(data, format='PNG')
                    page.insert_image(fitz.Rect(5, 85, 20, 100), stream=data.getvalue())
                page.insert_text((30, 100), 'TEXT')
                page.set_rotation(i * 90)
            doc.save(path)
        return path, ({a: True, b: False} if ocg else {})

    def cad(self, bad_entity=False, bad_layer=False, hidden_bad=False):
        path = self.root / 'source.dxf'
        doc = ezdxf.new('R2013')
        doc.units = 6
        doc.linetypes.new('DASH_TEST', dxfattribs={'description': 'Dash', 'pattern': [0.7, 0.5, -0.2]})
        doc.layers.new('ROAD', dxfattribs={'linetype': 'DASH_TEST', 'color': 2})
        doc.layers.new('OTHER')
        if bad_layer:
            doc.layers.get('ROAD').dxf.linetype = 'MISSING_LAYER'
        model = doc.modelspace()
        model.add_line((123456, 456789, 7), (123458, 456791, 8), dxfattribs={
            'layer': 'ROAD', 'linetype': 'MISSING_ENTITY' if bad_entity else 'DASH_TEST'})
        model.add_line((0, 0), (3, 4), dxfattribs={
            'layer': 'OTHER', 'linetype': 'MISSING_HIDDEN' if hidden_bad else 'BYLAYER'})
        doc.saveas(path)
        states = {layer.dxf.name: layer.dxf.name == 'ROAD' for layer in doc.layers}
        return path, states

    def export(self, path, states, fmt, page=0, **kw):
        destination = self.root / ('output.' + fmt)
        export_vector_snapshot(path, states, page, destination, OutputOptions(fmt=fmt), **kw)
        return destination

    def test_no_ocg_svg_direct_no_intermediate_and_exact_rotation(self):
        p, states = self.pdf()
        with fitz.open(p) as doc:
            expected = doc[1].get_svg_image(text_as_path=True)
        old = hashlib.sha256(p.read_bytes()).hexdigest()
        with patch('fitz.Document.save', side_effect=AssertionError('unnecessary intermediate save')):
            result = self.export(p, states, 'svg', page=1)
        self.assertEqual(result.read_text(encoding='utf-8'), expected)
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), old)
        self.assertFalse(list(self.root.glob('.drawing-*')))

    def test_pdf_locked_radio_geometry_preserved(self):
        p, states = self.pdf(ocg=True)
        out = self.export(p, states, 'pdf', page=1)
        with fitz.open(p) as source, fitz.open(out) as result:
            for key in ('locked', 'rbgroups'):
                self.assertEqual(source.get_layer()[key], result.get_layer()[key])
            self.assertEqual(source[1].rect, result[0].rect)
            self.assertEqual(source[1].rotation, result[0].rotation)
            self.assertEqual(source[1].get_pixmap().samples, result[0].get_pixmap().samples)

    def test_missing_selected_linetype_blocks_worker_and_cleans(self):
        for bad_entity, bad_layer in ((True, False), (False, True)):
            with self.subTest(bad_entity=bad_entity, bad_layer=bad_layer):
                p, states = self.cad(bad_entity, bad_layer)
                dest = self.root / 'bad.dxf'
                job = ExportJob(str(p), states, 0, str(dest), source_signature(p))
                result = run_batch_exports_isolated([job], OutputOptions(fmt='dxf'))
                self.assertEqual(len(result.errors), 1)
                self.assertIn('선 유형 정의 누락', result.errors[0][1])
                self.assertFalse(dest.exists())
                self.assertFalse(list(self.root.glob('.drawing-*')))

    def test_hidden_bad_resource_does_not_break_selected_geometry(self):
        p, states = self.cad(hidden_bad=True)
        out = self.export(p, states, 'dxf')
        doc = ezdxf.readfile(out)
        line = doc.modelspace()[0]
        self.assertEqual(len(doc.modelspace()), 1)
        self.assertEqual(tuple(line.dxf.start), (123456, 456789, 7))
        self.assertEqual(line.dxf.linetype, 'DASH_TEST')
        self.assertEqual(doc.layers.get('ROAD').dxf.linetype, 'DASH_TEST')
        self.assertEqual(doc.linetypes.get('DASH_TEST').simplified_line_pattern(), (0.5, 0.2))
        self.assertEqual(doc.units, 6)
        audit = doc.audit()
        self.assertFalse(audit.has_errors or audit.fixes)

    def test_audit_repair_not_counted_as_success(self):
        p, states = self.cad()
        from ezdxf.addons import Importer
        import_entity = Importer.import_entity
        def corrupt(self, entity, layout=None):
            import_entity(self, entity, layout)
            self.target.modelspace()[-1].dxf.linetype = 'CORRUPT_AFTER_IMPORT'
        with patch.object(Importer, 'import_entity', corrupt):
            with self.assertRaisesRegex(DrawingError, '자동 수정 필요'):
                self.export(p, states, 'dxf')
        self.assertFalse((self.root / 'output.dxf').exists())
        self.assertFalse(list(self.root.glob('.drawing-*')))

    def test_cancel_direct_svg_no_output(self):
        p, states = self.pdf()
        source = fitz.Page.get_svg_image
        flag = False
        def cancel_after_render(page, *args, **kwargs):
            nonlocal flag
            result = source(page, *args, **kwargs)
            flag = True
            return result
        with patch.object(fitz.Page, 'get_svg_image', cancel_after_render):
            with self.assertRaises(InterruptedError):
                self.export(p, states, 'svg', cancelled=lambda: flag)
        self.assertFalse((self.root / 'output.svg').exists())
        self.assertFalse(list(self.root.glob('.drawing-*')))

    def test_batch_continues_after_invalid_dxf(self):
        p, states = self.cad(hidden_bad=True)
        first = {**states, 'OTHER': True}
        sig = source_signature(p)
        jobs = [ExportJob(str(p), s, 0, str(self.root / f'{i}.dxf'), sig)
                for i, s in enumerate((first, states))]
        result = run_batch_exports(jobs, OutputOptions(fmt='dxf'))
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.completed, (jobs[1].target,))
        self.assertFalse(Path(jobs[0].target).exists())
        self.assertTrue(Path(jobs[1].target).exists())

    def test_supported_geometry_family_roundtrip(self):
        path = self.root / 'all.dxf'
        doc = ezdxf.new('R2013')
        doc.layers.new('GEOM')
        m = doc.modelspace()
        attrs = {'layer': 'GEOM'}
        m.add_line((100, 200, 3), (110, 205, 4), dxfattribs=attrs)
        m.add_point((105, 201, 6), dxfattribs=attrs)
        m.add_circle((102, 203, 7), 4, dxfattribs=attrs)
        m.add_arc((102, 203, 7), 4, 20, 130, dxfattribs=attrs)
        m.add_lwpolyline([(100, 200, .25), (104, 206, 0)], format='xyb', dxfattribs=attrs)
        m.add_ellipse((104, 206, 1), major_axis=(5, 0, 0), ratio=.5, dxfattribs=attrs)
        m.add_spline([(100, 200, 1), (104, 203, 2), (108, 208, 1), (110, 213, 1)], dxfattribs=attrs)
        m.add_3dface([(100, 200, 1), (104, 203, 2), (108, 208, 1)], dxfattribs=attrs)
        m.add_solid([(100, 200, 0), (104, 203, 0), (108, 208, 0)], dxfattribs=attrs)
        doc.saveas(path)
        states = {layer.dxf.name: layer.dxf.name == 'GEOM' for layer in doc.layers}
        result = ezdxf.readfile(self.export(path, states, 'dxf'))
        from ezdxf.lldxf.tagwriter import TagCollector
        def geometry_tags(entity):
            # Resource handles/ownership are intentionally new in a new DXF.
            return [(tag.code, tag.value) for tag in TagCollector.dxftags(entity)
                    if tag.code not in (5, 330, 390, 347, 348)]
        original = ezdxf.readfile(path)
        self.assertEqual([geometry_tags(e) for e in original.modelspace()],
                         [geometry_tags(e) for e in result.modelspace()])
        self.assertEqual(len(result.modelspace()), 9)

    def test_invalid_vector_entrypoint_and_key_type(self):
        p, states = self.pdf()
        with self.assertRaisesRegex(DrawingError, '벡터 출력 형식'):
            self.export(p, states, 'png')
        with self.assertRaises(DrawingError):
            _check_states({True: True}, {1: True})
        with self.assertRaises(DrawingError):
            _check_states({1.0: True}, {1: True})
        self.assertFalse(list(self.root.glob('.drawing-*')))


if __name__ == '__main__':
    unittest.main(verbosity=2)
