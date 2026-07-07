"""Phase C parity gate, Task 3.5 edition. Two contracts:

1. FIRE-FREE PARITY: on a fixture with no wildfire input (no wfire grid
   rows, no wui_class), the current deployable must produce EXACTLY the
   numbers v1.13 produces across the whole computation surface: per-site
   per-peril EAD, the financial layer, adaptation, waterfall, insurance
   layering, uncertainty, and the Power BI export string byte for byte.
   This proves the wildfire structural fix moved NOTHING else.

2. THE NEW FIRE MATH, pinned to its formula (not to v1.13, whose flat
   FIRE_MDD=0.6 cell-occupancy math is deliberately retired): point burn
   probability x flame-length-conditioned damage (grid v25), the capped
   interim ratio where v25 is absent (labeled interim), and the WUI interim
   path on the same conditional ratio.

    python3 test_app_parity.py
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD = ROOT / "app/TNL_Resort_Climate_Risk_Explorer_v113.html"
NEW = ROOT / "app/TNL_Resort_Climate_Risk_Explorer_v210.html"

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
/* identical FIRE-FREE fixture world for both apps: the wfire grid is loaded
   but carries ZERO burn probability everywhere (and no site has wui_class),
   so wildfire is exactly zero in both apps while every peril stays grid-fed
   - the divergence Task 3.5 introduces is confined to nonzero fire input,
   which the FIRE_FIXTURE below pins to the new formula */
const rows=[];
for(const sc of SCEN_KEYS){
  const w=(WARMING[sc]||0);
  for(const [la,lo] of [[25.0,-80.0],[34.0,-116.5]]){
    rows.push({lat:la,lon:lo,scenario:sc,hazard:"tc",v10:20,v25:28,v50:36,v100:48+w*2,v250:60+w*2,v500:66+w*2});
    rows.push({lat:la,lon:lo,scenario:sc,hazard:"cflood",v10:0.1,v25:0.4,v50:0.9,v100:1.5+w*0.1,v250:2.2,v500:2.8});
    rows.push({lat:la,lon:lo,scenario:sc,hazard:"rflood",v10:0,v25:0.1,v50:0.3,v100:0.6,v250:1.0,v500:1.3});
    rows.push({lat:la,lon:lo,scenario:sc,hazard:"heat",v10:110+w*20,v25:35+w*15,v50:2400,v100:0,v250:0,v500:0});
    rows.push({lat:la,lon:lo,scenario:sc,hazard:"wfire",v10:0,v25:0,v50:0,v100:0,v250:0,v500:0});
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
  construction:"masonry",year_built:2001},
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


FIRE_FIXTURE = """
render=()=>{}; toast=()=>{};
function assert(c,m){ if(!c){ console.error("FAIL: "+m); process.exit(1);} console.log("ok  "+m); }
/* pin the NEW wildfire math to its formula: point burn probability x
   flame-length-conditioned damage, interim cap where v25 is absent */
const rows=[];
for(const sc of SCEN_KEYS){
  rows.push({lat:25.0,lon:-80.0,scenario:sc,hazard:"wfire",v10:0.8,v25:30,v50:0,v100:0,v250:0,v500:0});
  rows.push({lat:34.0,lon:-116.5,scenario:sc,hazard:"wfire",v10:1.5,v25:0,v50:0,v100:0,v250:0,v500:0});
}
buildGridsFromRows(rows);
const sA={id:1,name:"A",latitude:25.0,longitude:-80.0,asset_value_usd:100e6};
const sB={id:2,name:"B",latitude:34.0,longitude:-116.5,asset_value_usd:100e6,roof_class_a:true};
const rA=hzSite(sA,"wfire","present");
assert(Math.abs(rA.ead-100e6*0.008*0.30)<1e-3,
  "grid v25: EAD = value x point p x flame-length-conditioned ratio");
assert(rA.fireCondSource==="grid","a supplied v25 is used as the modeled conditional ratio");
const rB=hzSite(sB,"wfire","present");
assert(Math.abs(rB.ead-100e6*0.015*FIRE_COND_INTERIM*0.6)<1e-3,
  "v25 absent: the capped INTERIM ratio applies (with the Class A roof factor)");
assert(rB.fireCondSource==="interim","the interim conditional side is labeled");
assert(siteTrust(sB,"wfire","present").note.indexOf("interim")>=0,
  "the trust surface carries the interim-conditional label");
gridByHazard={};clearHazCache();
const sW={id:3,name:"W",latitude:34.0,longitude:-116.5,asset_value_usd:100e6,wui_class:"intermix"};
const rW=hzSite(sW,"wfire","present");
assert(Math.abs(rW.ead-100e6*0.006*FIRE_COND_INTERIM)<1e-3,
  "WUI interim path: point probability x the interim conditional ratio");
assert(FIRE_COND_INTERIM<0.6,
  "the interim ratio sits BELOW the retired flat FIRE_MDD=0.6 (capped, documented)");
console.log("FIRE MATH PINNED");
"""


def run_app(path, fixture):
    html = path.read_text()
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    js = max(blocks, key=len)
    cut = js.index("function downloadTemplate(")     # everything computable,
    harness = STUBS + js[:cut] + fixture             # wiring excluded
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(harness)
        tmp = f.name
    r = subprocess.run(["node", tmp], capture_output=True, text=True)
    if r.returncode:
        print(f"FAIL running {path.name}:\n{r.stdout[-800:]}\n{r.stderr[:1500]}")
        raise SystemExit(1)
    return r.stdout.strip()


def main():
    a, b = run_app(OLD, FIXTURE), run_app(NEW, FIXTURE)
    if a != b:
        import json
        da, db = json.loads(a), json.loads(b)
        for k in da:
            if da[k] != db.get(k):
                print(f"DIVERGENCE at '{k}':")
                print(f"  v1.13 : {str(da[k])[:300]}")
                print(f"  v2.1.0: {str(db.get(k))[:300]}")
        raise SystemExit(1)
    n = len(a)
    print(f"ok  fire-free surface IDENTICAL to v1.13 across per-peril EAD, the")
    print(f"    financial layer, adaptation, waterfall, layering, uncertainty,")
    print(f"    and the Power BI export string ({n:,} chars compared)")
    out = run_app(NEW, FIRE_FIXTURE)
    assert "FIRE MATH PINNED" in out, out
    print(out)
    print("\nAPP PARITY: v2.1.0 == v1.13 off the fire surface; "
          "new fire math pinned to its formula")


if __name__ == "__main__":
    main()
