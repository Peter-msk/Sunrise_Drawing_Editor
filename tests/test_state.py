"""Fast tests for nonblocking file registration and metadata-only GUI records."""
from pathlib import Path
import tempfile
import unittest

from drawing_editor.batch import LayerRule, apply_rule, plan_exports
from drawing_editor.core import LayerInfo, OutputOptions
from drawing_editor.state import DrawingState


class DrawingStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.files = [self.root / f'big_{idx}.dxf' for idx in range(40)]
        for source in self.files:
            source.write_bytes(b'0\nEOF\n')

    def test_do_not_parse_cad_during_registration(self):
        docs = [DrawingState(path) for path in self.files]
        self.assertEqual(len(docs), 40)
        self.assertTrue(all(not doc.loaded and not doc.states() for doc in docs))

    def test_metadata_and_reusable_layer_rule(self):
        docs = [DrawingState(path) for path in self.files[:2]]
        metadata = [LayerInfo('도로', '도로', True), LayerInfo('건물', '건물', False)]
        for doc in docs:
            doc.load_metadata(metadata, 1)
        self.assertTrue(docs[0].set_visibility('도로', False))
        rule = LayerRule.from_document('도면 규칙', docs[0])
        result = apply_rule(docs[1], rule)
        self.assertTrue(result.matching_kind)
        self.assertEqual(result.changed, 1)
        self.assertFalse(docs[1].states()['도로'])
        self.assertEqual(len(plan_exports(docs, self.root, OutputOptions('png'))), 2)

    def test_locked_and_unchanged(self):
        doc = DrawingState(self.files[0])
        doc.load_metadata([LayerInfo('잠금', '잠금', True, True),
                           LayerInfo('일반', '일반', True)], 3)
        self.assertTrue(doc.set_all(False))
        self.assertTrue(doc.states()['잠금'])
        self.assertFalse(doc.states()['일반'])
        self.assertEqual(doc.pages, 3)


if __name__ == '__main__':
    unittest.main()
