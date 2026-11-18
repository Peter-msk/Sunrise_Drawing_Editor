import unittest
from types import SimpleNamespace
from build.pyz_policy import audit_pyz, compare_pyz, excluded, inventory_pyz


class PyzPolicyTests(unittest.TestCase):
    def test_accounting(self):
        result = inventory_pyz({'PIL.Image': (0, 20, 30), 'PIL.ImageTk': (0, 50, 10),
                                'numpy': (1, 60, 20), 'namespace': (3, 0, 0)}, 100)
        self.assertEqual(result['module_packed_bytes'], 60)
        self.assertEqual(result['overhead_bytes'], 40)
        self.assertEqual(result['groups']['PIL']['packed_bytes'], 40)
        self.assertEqual(result['entries'][0]['name'], 'PIL.Image')

    def test_exclusions_exact(self):
        for name in ('IPython.core', 'PIL.ImageTk', 'ezdxf.addons.drawing.qtviewer'):
            self.assertTrue(excluded(name))
        for name in ('PIL.Image', 'PIL.AvifImagePlugin', 'lxml.etree', 'numpy',
                     'ezdxf.addons.drawing.pymupdf', 'pytest_extra', 'drawing_editor.core'):
            self.assertFalse(excluded(name))

    def test_bad_ranges(self):
        for toc in ({}, {'a': (0, -1, 4)}, {'a': (0, 90, 20)},
                    {'a': (0, 20, 30), 'b': (0, 40, 10)}):
            with self.assertRaises(ValueError):
                inventory_pyz(toc, 100)

    def test_nested_reader(self):
        reader = SimpleNamespace(toc={'PYZ.pyz': (0, 100, 100, 0, 'z')},
                                 open_embedded_archive=lambda n: SimpleNamespace(toc={'a': (0, 20, 30)}))
        result = audit_pyz(reader)
        self.assertEqual(result['status'], 'OK')
        reader.toc['PYZ.pyz'] = (0, 50, 100, 1, 'z')
        with self.assertRaises(ValueError):
            audit_pyz(reader)

    def test_comparison_no_double_count(self):
        a = {'status': 'OK', **inventory_pyz({'PIL.ImageTk': (0, 20, 30), 'a': (0, 50, 20)}, 100)}
        b = {'status': 'OK', **inventory_pyz({'a': (0, 20, 20)}, 65)}
        result = compare_pyz(a, b)
        self.assertEqual(result['saved_archive_bytes'], 35)
        self.assertEqual(result['removed_module_bytes'], 30)
        self.assertEqual(result['removed_modules'], ['PIL.ImageTk'])
        self.assertEqual(compare_pyz(None, b)['status'], 'NOT AVAILABLE')


if __name__ == '__main__':
    unittest.main()
