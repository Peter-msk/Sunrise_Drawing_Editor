from pathlib import Path
from io import BytesIO
from PIL import Image
import hashlib,json,sys,time,os
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drawing_editor.core import DrawingDocument
p=Path(sys.argv[1]);out={"source_bytes":p.stat().st_size}
with DrawingDocument(p) as d:
 for tag,enable in [('default',None),('insert_layer',True),('restored',False)]:
  if enable is not None:d.set_visibility('C0285311', enable)
  ts=time.perf_counter();b=d.render_bytes(preview=(1000,700));dur=time.perf_counter()-ts
  i=Image.open(BytesIO(b)).convert('RGB')
  out[tag]={"seconds":round(dur,4),"pixels":list(i.size),"sha256":hashlib.sha256(i.tobytes()).hexdigest(),"png_bytes":len(b)}
  if d._cad_selective_last_stats:
   x=d._cad_selective_last_stats
   out[tag].update({"staged_bytes":x.staged_bytes,"objects_pruned":getattr(x,"objects_pruned",False)})
print(json.dumps(out,ensure_ascii=False,indent=2),flush=True)
