"""R18: source-worker evidence is not a packaged Windows EXE result."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from build.functional_gate import EXTRACTION_REQUIRED, STATUS, read_functional_qa
from build import verify_lean

ROOT = Path(__file__).resolve().parents[1]
CHECK = 'png_alpha_crop_independent_pixel_exact'


def source_worker(exe, folder, jobs, options, cancel=False):
    folder.mkdir()
    (folder / 'request.json').write_text(json.dumps({'jobs': jobs, 'options': options}), encoding='utf-8')
    if cancel:
        (folder / 'cancel.flag').touch()
    proc = subprocess.run([sys.executable, str(ROOT / 'main.py'), '--batch-worker', str(folder)],
                          cwd=ROOT, capture_output=True, timeout=60)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr.decode(errors='replace'))
    reply = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
    assert reply['ok'] is True, reply
    result = reply['result']
    assert not result['errors'] and result['cancelled'] is cancel, result
    assert len(result['completed']) == (0 if cancel else len(jobs)), result


class RasterGateTests(unittest.TestCase):
    def test_new_gate_requires_raster_evidence_and_retains_old_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'FUNCTIONAL_QA.json'
            sha = 'a' * 64
            report = dict(schema_version=1, sha256=sha, status=STATUS,
                          checks_passed=sorted(EXTRACTION_REQUIRED), not_run=[])
            def write():
                path.write_text(json.dumps(report), encoding='utf-8')
            write()
            self.assertEqual(read_functional_qa(path, sha, version='1.5.7'), report)
            with self.assertRaises(RuntimeError):
                read_functional_qa(path, sha, version='1.5.8')
            report['checks_passed'].append(CHECK); write()
            self.assertEqual(read_functional_qa(path, sha, version='1.5.8'), report)
            report['not_run'].append(CHECK); write()
            with self.assertRaises(RuntimeError):
                read_functional_qa(path, sha, version='1.5.8')

    def test_four_raster_modes_real_source_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            originals = {}
            verify_lean.check_alpha_crop(None, Path(tmp), originals, source_worker)
            self.assertEqual(len(originals), 1)
            for path, expected in originals.items():
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)

    def test_entire_packaged_qa_protocol_with_source_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            checks = verify_lean.exercise(None, Path(tmp), worker=source_worker)
            self.assertEqual(set(checks), EXTRACTION_REQUIRED | {CHECK})
            self.assertEqual(len(checks), len(set(checks)))

    def test_bad_alpha_and_size_rejected(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            for kind in ('wrong-alpha', 'wrong-size'):
                with self.subTest(kind=kind):
                    root = Path(tmp) / kind; root.mkdir()
                    def broken(exe, folder, jobs, options):
                        source_worker(exe, folder, jobs, options)
                        target = jobs[0]['target']
                        with Image.open(target) as im:
                            bad = im.convert('RGB') if kind == 'wrong-alpha' else im.resize((20,20))
                        bad.save(target); bad.close()
                    with self.assertRaises(RuntimeError):
                        verify_lean.check_alpha_crop(None, root, {}, broken)


if __name__ == '__main__': unittest.main(verbosity=2)
