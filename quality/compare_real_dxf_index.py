"""Read-only real-file regression: old and new DXF staging byte equivalence."""
from __future__ import annotations
import argparse,hashlib,importlib.util,json,sys,tempfile,time,statistics
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from drawing_editor.cad_catalog import read_ascii_dxf_layers
from drawing_editor.cad_selective import VisibleDXFSource


def sha(p):
 d=hashlib.sha256()
 with open(p,'rb') as f:
  for buf in iter(lambda:f.read(4<<20),b''):d.update(buf)
 return d.hexdigest()

def load_baseline(file):
 spec=importlib.util.spec_from_file_location('_original_cad_selective',str(file));mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
 return mod.VisibleDXFSource

def run(path,previous,output):
 cls_old=load_baseline(previous)
 visible=[x.name for x in read_ascii_dxf_layers(path) if x.visible]
 records={}
 with tempfile.TemporaryDirectory(prefix='sunrise-three-pass-') as td:
  for scene,layers in [('default',visible),('insert_on',visible+['C0285311'])]:
   scene_out={}
   for name,cls in [('prior',cls_old),('new',VisibleDXFSource)]:
    measurements=[]
    for rep in range(3):
     t=time.perf_counter();v=cls(path);stats=v.stage(Path(td)/f'{scene}_{name}_{rep}.dxf',layers)
     delta=time.perf_counter()-t
     measurements.append(delta)
     if rep==0:
      scene_out[name]={'sha256':sha(Path(td)/f'{scene}_{name}_{rep}.dxf'),
                       'staged_bytes':stats.staged_bytes,
                       'total_records':stats.total_entities,
                       'selected_records':stats.selected_entities,
                       'blocks_pruned':stats.blocks_pruned,
                       'objects_pruned':stats.objects_pruned}
    scene_out[name]['seconds_runs']=[round(x,5) for x in measurements]
    scene_out[name]['seconds_median']=round(statistics.median(measurements),5)
   scene_out['byte_equal']=scene_out['prior']['sha256']==scene_out['new']['sha256']
   records[scene]=scene_out
 output.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps({k:{'equal':v['byte_equal'],'old':v['prior']['seconds_median'],'new':v['new']['seconds_median']} for k,v in records.items()},ensure_ascii=False),flush=True)
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('source');ap.add_argument('baseline_module');ap.add_argument('report');a=ap.parse_args()
 run(Path(a.source),Path(a.baseline_module),Path(a.report))
