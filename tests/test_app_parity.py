"""Phase C parity gate: the assembled v2.0.0 app must produce EXACTLY the
numbers v1.13 produces, on identical fixtures, across the whole computation
surface: per-site per-peril EAD, the financial layer, adaptation, waterfall,
insurance layering, uncertainty, and the Power BI export string byte for
byte. This is the executable spec MASTER_PLAN's Phase C demands before any
visual work: the refactor (registry-driven peril math, source-split build)
is only real if this cannot tell the two apps apart.

    python3 test_app_parity.py
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD = ROOT / "app/TNL_Resort_Climate_Risk_Explorer_v113.html"
NEW = ROOT / "app/TNL_Resort_Climate_Risk_Explorer_v200.html"

STUBS = """
const _els={};
function _mkEl(){return {classList:{_s:new Set(),add(c){this._s.add(c)},remove(c){this._s.delete(c)},contains(c){return this._s.has(c)}},
  style:{},innerHTML:"",textContent:"",title:"",value:"",href:"",download:"",addEventListener(){},onclick:null,appendChild(){},click(){},querySelectorAll:()=>[]};}
const document={createElement:()=>_mkEl(),body:{appendChild(){}},
  getElementById:id=>(_els[id]||(_els[id]=_mkEl())),querySelectorAll:()=>[],
  addEventListener(){},documentElement:{clientWidth:1000,clientHeight:800}};
const window={scrollX:0,scrollY:0,addEventListener(){}};
const navigator={};
const _ls={};
const localStorage={getItem:k=>(k in _ls?_ls[k]:null),setItem(k,v){_ls[k]=String(v);},removeItem(k){delete _ls[k];}};
let _lastCsv="";
function Blob(parts){_lastCsv=parts.join("");}
const URL={createObjectURL:()=>"u",revokeObjectURL:()=>{}};
"""

FIXTURE = """
render=()=>{}; toast=()=>{};
/* identical fixture world for both apps */
const rows=[];
for(const sc of SCEN_KEYS){
  const w=(WARMING[sc]||0);
  for(const [la,lo] of [[25.0,-80.0],[34.0,-116.5]]){
    rows.push({lat:la,lon:lo,scenario:sc,hazard:"tc",v10:20,v25:28,v50:36,v100:48+w*2,v250:60+w*2,v500:66+w*2});
    rows.push({lat:la,lon:lo,scenario:sc,hazard:"cflood",v10:0.1,v25:0.4,v50:0.9,v100:1.5+w*0.1,v250:2.2,v500:2.8});
    rows.push({lat:la,lon:lo,scenario:sc,hazard:"rflood",v10:0,v25:0.1,v50:0.3,v100:0.6,v250:1.0,v500:1.3});
    rows.push({lat:la,lon:lo,scenario:sc,hazard:"heat",v10:110+w*20,v25:35+w*15,v50:2400,v100:0,v250:0,v500:0});
    rows.push({lat:la,lon:lo,scenario:sc,hazard:"wfire",v10:+(0.9*(1+0.14*w)).toFixed(3),v25:0,v50:0,v100:0,v250:0,v500:0});
    rows.push({lat:la,lon:lo,scenario:sc,hazard:"prain",v10:220,v25:380,v50:600,v100:850*(1+0.07*w),v250:1250,v500:1650});
  }
}
buildGridsFromRows(rows);
hazardGrid={rows,meta:{name:"parity.csv",cells:rows.length,scenarios:SCEN_KEYS.slice(),
  hazards:["tc","cflood","rflood","heat","wfire","prain"],loaded:"x"}};
sites=[
 {id:1,name:"Reef",brand:"A",latitude:25.01,longitude:-80.01,asset_value_usd:120e6,
  construction:"engineered",year_built:2015,defended:true,roof_type:"metal",roof_year:2019,
  opening_protection:"impact",first_floor_elev_m:1.4,equipment_elevated:true},
 {id:2,name:"Dune",brand:"A",latitude:25.02,longitude:-80.02,asset_value_usd:80e6,
  construction:"frame",year_built:1988,roof_type:"shingle",roof_year:1999,opening_protection:"none",
  annual_revenue_usd:30e6},
 {id:3,name:"Ridge",brand:"B",latitude:34.01,longitude:-116.51,asset_value_usd:60e6,
  construction:"masonry",year_built:2001,wui_class:"intermix",defensible_space_m:10,roof_class_a:false},
];
const out={};
for(const sc of ["present","ssp245_2050","ssp585_2080"]){
  const per={};
  for(const s of sites){per[s.name]={};for(const hz of ["tc","cflood","rflood","prain","wfire"])per[s.name][hz]=hzSite(s,hz,sc).ead;}
  const f=finPortfolio(sites,sc);
  const agg=aggregatePortfolio(sites,sc);
  out[sc]={per,total:f.totalAal,acute:f.acuteAal,chronic:f.chronicAal,
    var100:f.var100,varByRp:f.varByRp,byPeril:agg.byPeril,
    adaptedBase:adaptedTotal(sites,sc,{}).totalAal,
    adaptedMods:adaptedTotal(sites,sc,{tcDmgMult:0.65,fbBonus:0.5,fireMult:0.6,heatMult:0.7,reopenMult:0.8}).totalAal,
    layer:layerStatsCalc(f.varByRp,f.acuteAal),
    unc:(u=>({c:u.central,l:u.low,h:u.high}))(uncRange(sites,sc))};
}
out.waterfall=waterfallData(sites,"ssp245_2050");
scenario="ssp245_2050";
exportCsv();
out.exportCsv=_lastCsv;
console.log(JSON.stringify(out));
"""


def run_app(path):
    html = path.read_text()
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    js = max(blocks, key=len)
    cut = js.index("function downloadTemplate(")     # everything computable,
    harness = STUBS + js[:cut] + FIXTURE             # wiring excluded
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(harness)
        tmp = f.name
    r = subprocess.run(["node", tmp], capture_output=True, text=True)
    if r.returncode:
        print(f"FAIL running {path.name}:\n{r.stderr[:1500]}")
        raise SystemExit(1)
    return r.stdout.strip()


def main():
    a, b = run_app(OLD), run_app(NEW)
    if a != b:
        import json
        da, db = json.loads(a), json.loads(b)
        for k in da:
            if da[k] != db.get(k):
                print(f"DIVERGENCE at '{k}':")
                print(f"  v1.13 : {str(da[k])[:300]}")
                print(f"  v2.0.0: {str(db.get(k))[:300]}")
        raise SystemExit(1)
    n = len(a)
    print(f"ok  v2.0.0 output is IDENTICAL to v1.13 across per-peril EAD, the")
    print(f"    financial layer, adaptation, waterfall, layering, uncertainty,")
    print(f"    and the Power BI export string ({n:,} chars compared)")
    print("\nAPP PARITY: v2.0.0 == v1.13")


if __name__ == "__main__":
    main()
