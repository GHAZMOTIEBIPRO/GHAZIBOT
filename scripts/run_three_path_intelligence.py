from __future__ import annotations
import argparse, json
from options_radar.three_path_intelligence import run
p=argparse.ArgumentParser(description="Run the three independent BLACK BOX research paths.")
p.add_argument("--explosion",default="data/live/fast_explosion_scan.json")
p.add_argument("--latest",default="public/data/latest.json")
p.add_argument("--options",default="public/data/options_latest.json")
p.add_argument("--output",default="data/live/three_path_intelligence.json")
a=p.parse_args()
r=run(explosion_path=a.explosion,latest_path=a.latest,options_path=a.options,output_path=a.output)
print(json.dumps({k:len(v) for k,v in r.items() if isinstance(v,list)},ensure_ascii=False))
