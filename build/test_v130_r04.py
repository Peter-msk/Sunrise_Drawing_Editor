"""R04 bounded record census and shared export validation."""
from dataclasses import asdict, replace
from pathlib import Path
import sys, tempfile, unittest, hashlib
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from drawing_editor.cad_catalog import inspect_large_ascii_dxf, MAX_DIAGNOSTIC_BYTES
from drawing_editor.core import DrawingError, OutputOptions, source_signature
from drawing_editor.drawing_analysis import inspect_source, checked_profile
from drawing_editor.layer_tools import plan_advanced_exports
from drawing_editor import cad_worker
from test_v130 import V130Tests

HEADER=b'0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1027\n9\n$DWGCODEPAGE\n3\nANSI_949\n9\n$INSUNITS\n70\n6\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n'
TAIL=b'0\nENDSEC\n0\nEOF\n'
LINE=b'0\nLINE\n8\nROAD\n10\n1\n20\n2\n11\n3\n21\n4\n'
CIRCLE='0\nCIRCLE\n8\n수계\n10\n0\n20\n0\n40\n3\n'.encode()

class Census(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.p=Path(tmp.name)/'large.dxf'
        self.addCleanup(cad_worker.shutdown_all_workers)
    def write(self,body): self.p.write_bytes(body);return self.p.stat().st_size
    def scan(self): return inspect_large_ascii_dxf(self.p,check=lambda:None,size=self.p.stat().st_size)
    def test_raw_counts_unicode_and_records(self):
        self.write(HEADER+LINE*3+CIRCLE+b'0\nSEQEND\n'+TAIL)
        r=self.scan();self.assertEqual(r['ENTITIES 레코드 수'],5);self.assertEqual(r['레코드 유형별'],{'LINE':3,'CIRCLE':1,'SEQEND':1});self.assertEqual(r['첫 레이어 코드별 레코드 수'],{'ROAD':3,'수계':1,'(레이어 코드 없음)':1});self.assertEqual(r['INSUNITS 코드'],6)
    def test_legacy_encoding(self):
        self.write(HEADER.replace(b'AC1027',b'AC1015')+CIRCLE.decode().encode('cp949')+TAIL)
        self.assertEqual(self.scan()['첫 레이어 코드별 레코드 수'],{'수계':1})
    def test_reject_partial_binary_and_wrong_encoding(self):
        for content in (HEADER+LINE, b'AutoCAD Binary DXF\r\n\x1a\x00', HEADER+CIRCLE.replace('수계'.encode(),b'\xff')+TAIL,HEADER+LINE+b'0\nENDSEC\n0\nSECTION\n2\nENTITIES\n'+TAIL):
            self.write(content)
            with self.assertRaises(DrawingError):self.scan()
        with self.assertRaises(DrawingError):inspect_large_ascii_dxf(self.p,check=lambda:None,size=MAX_DIAGNOSTIC_BYTES+1)
    def test_cancel_and_source_change(self):
        self.write(HEADER+LINE*10000+TAIL)
        count=0
        def check():
            nonlocal count
            count+=1
            if count==2:raise DrawingError('취소')
        with self.assertRaisesRegex(DrawingError,'취소'):inspect_large_ascii_dxf(self.p,check=check,size=self.p.stat().st_size)
    def test_large_actual_worker_and_original_preserved(self):
        count=600000
        with self.p.open('wb') as fp:
            fp.write(HEADER)
            for _ in range(count//1000):fp.write(LINE*1000)
            fp.write(CIRCLE+TAIL)
        self.assertGreater(self.p.stat().st_size,16*1024*1024)
        def digest():
            with self.p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
        old=digest(); sig=source_signature(self.p)
        result=cad_worker.render_isolated('inspect',str(self.p),{},0,(1,1),expected_source=sig)
        self.assertEqual(result['ENTITIES 레코드 수'],count+1);self.assertEqual(result['첫 레이어 코드별 레코드 수'],{'ROAD':count,'수계':1});self.assertEqual(digest(),old)
        with self.p.open('ab') as f:f.write(b'\n')
        with self.assertRaises(DrawingError):inspect_source((str(self.p),{},0,sig))

class Contracts(V130Tests):
    def test_crop_rejected_consistently(self):
        d=self.pdf(); opts=replace(self.opts,crop_margins=True)
        body=dict(schema_version=1,options=asdict(opts),mode='layers',scope='current',page_range='',groups=[],rules=[])
        with self.assertRaises(DrawingError):checked_profile(body)
        with self.assertRaises(DrawingError):plan_advanced_exports([d],self.root,opts,mode='layers')
        body['mode']='current';checked_profile(body)
if __name__=='__main__':
    suite=unittest.TestLoader().loadTestsFromTestCase(Census)
    suite.addTests(Contracts(name) for name in vars(Contracts) if name.startswith('test_'))
    sys.exit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
