"""Real-file staged CAD render benchmark, no source file mutation."""
from __future__ import annotations
import hashlib,json,sys,time
from io import BytesIO
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from drawing_editor.core import DrawingDocument,OutputOptions
try:
 import psutil
except ImportError:
 psutil=None

def checksum(data):
 with Image.open(BytesIO(data)) as im:
  im=im.convert('RGB');return {'pixel_sha256':hashlib.sha256(im.tobytes()).hexdigest(),'width':im.width,'height':im.height}

def measure(p, layer_name='C0285311'):
 proc=psutil.Process() if psutil else None
 with DrawingDocument(p) as d:
  t=time.perf_counter();first=d.render_bytes(preview=(1000,700));s1=time.perf_counter()-t
  t=time.perf_counter();d.set_visibility(layer_name,True);on=d.render_bytes(preview=(1000,700));s2=time.perf_counter()-t
  stats=d._cad_selective_last_stats
  rss=round(proc.memory_info().rss / 1024**2,2) if proc else None
  t=time.perf_counter();d.set_visibility(layer_name,False);off=d.render_bytes(preview=(1000,700));s3=time.perf_counter()-t
 return {'initial_seconds':round(s1,4),'insert_on_seconds':round(s2,4),'restored_seconds':round(s3,6),'initial':checksum(first),'insert_on':checksum(on),'restored':checksum(off),'restored_identical':first==off,'selected_entities':stats.selected_entities,'staged_bytes':stats.staged_bytes,'objects_pruned':stats.objects_pruned,'rss_mib':rss}
if __name__=='__main__':
 result=measure(Path(sys.argv[1]), sys.argv[3] if len(sys.argv)>3 else 'C0285311');print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
 if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
