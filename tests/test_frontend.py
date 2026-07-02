"""
test_frontend.py  (v2) : functional tests for the patched browser app (node).

Extracts the app's REAL inline JavaScript up to the end of restore(), stubs
the DOM minimally, then asserts the Phase 2-3 behaviours (heat grid-first
with formula fallback, outside-coverage fallback to interim, fbRiver toggle,
no-grid regression) AND the Phase 4 trust surface (CSV loader per-peril
bookkeeping, provenance sidecar intake and rejection, badge and Method-tab
rendering, partial-coverage flagging, persistence round trip).

Usage:  python test_frontend.py TNL_Resort_Climate_Risk_Explorer_v17.html
Rerun after ANY future edit to the HTML.
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

STUBS = """
const _els={};
function _mkEl(){return {classList:{_s:new Set(),add(c){this._s.add(c)},remove(c){this._s.delete(c)},contains(c){return this._s.has(c)}},
  style:{},innerHTML:"",textContent:"",title:"",value:"",addEventListener(){},onclick:null,appendChild(){},querySelectorAll:()=>[]};}
const document={createElement:()=>_mkEl(),body:{appendChild(){}},
  getElementById:id=>(_els[id]||(_els[id]=_mkEl())),querySelectorAll:()=>[],
  addEventListener(){},documentElement:{clientWidth:1000,clientHeight:800}};
const window={scrollX:0,scrollY:0,addEventListener(){}};
const navigator={};
const _ls={};
const localStorage={getItem:k=>(k in _ls?_ls[k]:null),setItem(k,v){_ls[k]=String(v);},removeItem(k){delete _ls[k];}};
"""

TESTS = """
function assert(c,m){ if(!c){ console.error("FAIL: "+m); process.exit(1);} console.log("ok  "+m); }
render=()=>{};                       // neutralise the full DOM renderer
let _lastToast=""; toast=m=>{_lastToast=String(m);};

/* ---------------- Phase 2-3 behaviours (regression) ---------------- */
const rows=[];
for(const sc of SCEN_KEYS){
  rows.push({lat:29.5,lon:-98.5,scenario:sc,hazard:"heat",v10:120+(WARMING[sc]||0)*20,v25:40+(WARMING[sc]||0)*15,v50:2600,v100:0,v250:0,v500:0});
  rows.push({lat:25.0,lon:-80.0,scenario:sc,hazard:"tc",v10:20,v25:28,v50:36,v100:48,v250:60,v500:66});
  rows.push({lat:25.0,lon:-80.0,scenario:sc,hazard:"rflood",v10:0,v25:0,v50:0.1,v100:0.4,v250:0.9,v500:1.2});
}
buildGridsFromRows(rows);
const hSA=heatIndicators(29.45,-98.45,"present");
assert(hSA.source==="grid"&&hSA.daysOver32===120&&hSA.daysOver35===40&&hSA.cdd===2600,
  "heatIndicators reads the grid (d32=120, d35=40, cdd=2600)");
assert(heatIndicators(29.45,-98.45,"ssp585_2080").daysOver35===Math.round(40+3.6*15),
  "heat grid scenario rows resolve per key");
assert(heatIndicators(19.64,-155.99,"present").source===undefined,"outside heat coverage -> formula fallback");
assert(Math.abs(hzVector("rflood",25.05,-80.05,"present")[100]-0.4)<1e-9,"rflood grid served near cell");
assert(hzVector("rflood",21.3,-157.8,"present")[100]>0,"rflood outside coverage -> interim, not silent zero");
assert(hzVector("cflood",21.3,-157.8,"present")[100]>0,"cflood absent from grid -> interim as before");
clearHazCache();
assert(provider()(19.64,-155.99,"present").meta.source==="interim","tc outside coverage -> interim");
assert(provider()(25.0,-80.0,"present").vec[100]===48,"tc in-coverage served from grid");
assert(fbRiver()===FB_RIVER,"fbRiver()==FB_RIVER while protection flag is false");

/* ---------------- Phase 4: CSV loader bookkeeping ---------------- */
function csvOf(list){
  const head="lat,lon,scenario,hazard,v10,v25,v50,v100,v250,v500";
  return [head].concat(list.map(r=>[r.lat,r.lon,r.scenario,r.hazard,r.v10,r.v25,r.v50,r.v100,r.v250,r.v500].join(","))).join("\\n");
}
loadHazardCsv(csvOf(rows),"hazard_grid.csv");
assert(hazardGrid&&hazardGrid.meta.perHaz,"loadHazardCsv records per-peril bookkeeping");
assert(hazardGrid.meta.perHaz.tc.cells===SCEN_KEYS.length&&hazardGrid.meta.perHaz.heat.scenarios.length===SCEN_KEYS.length,
  "perHaz counts cells and scenario coverage per peril");

/* ---------------- Phase 4: rendering without the sidecar ---------------- */
renderHazProv();
const badge=document.getElementById("hazBadge"),htext=document.getElementById("hazText");
const prov=document.getElementById("hazProv"),note=document.getElementById("hazNote");
assert(badge.classList.contains("authoritative"),"badge turns authoritative with a grid");
assert(htext.textContent.indexOf("3/4")>=0,"badge counts live perils (tc, rflood, heat = 3/4)");
assert(prov.innerHTML.indexOf("hazard_grid_meta.json")>=0,"panel invites the sidecar when absent");
assert(note.textContent.indexOf("coastal flood")>=0&&note.textContent.indexOf("Still on the interim model")>=0,
  "hazNote narrows the caveat peril by peril");

/* ---------------- Phase 4: sidecar intake and rendering ---------------- */
const goodMeta={combined:true,generated_utc:"2026-07-02T03:00:00+00:00",
  sources:[{script:"refresh_hazard.py v3 (Phases 0+1+2)",generated_utc:"2026-07-02T02:00:00+00:00",
            climada_version:"6.1.0",climada_petals_version:"6.1.0",nb_synth_tracks:"10",
            surge:{dem_path:"/data/dems/SRTM15+V2.0.tiff"}},
           {script:"refresh_heat.py (Phase 3)",generated_utc:"2026-07-02T02:30:00+00:00",
            method:"CPC daily climatology + AR6 warming deltas",years:[2005,2024]}],
  layers:[],skipped:[{country:"USA",layer:"rflood",scenario:"ssp126_2030",reason:"sim"}]};
loadHazardMeta(JSON.stringify(goodMeta),"hazard_grid_meta.json");
assert(hazardMeta&&hazardMeta.data.combined===true,"valid sidecar accepted and stored");
renderHazProv();
assert(prov.innerHTML.indexOf("climada 6.1.0 + petals 6.1.0")>=0,"panel shows producer versions");
assert(prov.innerHTML.indexOf("SRTM15+V2.0.tiff")>=0,"panel shows the DEM basename");
assert(prov.innerHTML.indexOf("CPC daily climatology")>=0,"panel shows the heat method");
assert(prov.innerHTML.indexOf("Skipped")>=0,"panel surfaces skipped layers");
assert(badge.title.indexOf("2026-07-02")>=0,"badge hover carries the run date");
assert(note.textContent.indexOf("Pipeline run 2026-07-02")>=0,"hazNote carries the run date");

/* ---------------- Phase 4: rejection paths ---------------- */
loadHazardMeta("{not json","x.json");
assert(_lastToast.indexOf("parse")>=0&&hazardMeta.data.combined===true,"broken JSON rejected, state untouched");
loadHazardMeta(JSON.stringify({foo:1}),"x.json");
assert(_lastToast.indexOf("does not look like")>=0&&hazardMeta.data.combined===true,"wrong-shape JSON rejected");

/* ---------------- Phase 4: persistence round trip ---------------- */
persistHazard();persistMeta();
hazardGrid=null;hazardMeta=null;gridByHazard={};clearHazCache();
restore();
assert(hazardGrid&&hazardGrid.rows.length===rows.length,"grid restored from storage");
assert(hazardMeta&&hazardMeta.data.sources.length===2,"sidecar restored from storage");
assert(!!gridByHazard.tc&&!!gridByHazard.heat,"providers rebuilt on restore");

/* ---------------- Phase 4: partial scenario coverage flagged ---------------- */
const partialRows=rows.concat([{lat:25.0,lon:-80.0,scenario:"present",hazard:"cflood",v10:0.2,v25:0.5,v50:0.9,v100:1.4,v250:2.1,v500:2.6}]);
loadHazardMeta(JSON.stringify(goodMeta),"hazard_grid_meta.json");
loadHazardCsv(csvOf(partialRows),"hazard_grid.csv");
renderHazProv();
assert(htext.textContent.indexOf("4/4")>=0,"cflood now live: badge reads 4/4");
assert(note.textContent.indexOf("Partial scenario coverage")>=0&&note.textContent.indexOf("coastal flood")>=0,
  "present-only cflood is flagged as partial, not hidden");

/* ---------------- interim branch ---------------- */
hazardGrid=null;hazardMeta=null;gridByHazard={};clearHazCache();
renderHazProv();
assert(!badge.classList.contains("authoritative")&&htext.textContent==="Interim model",
  "no grid -> interim badge restored");
assert(prov.innerHTML.indexOf("all on the interim model")>=0,"interim panel shows gray chips line");

/* ---------------- Phase 5: results pack intake, render, persistence -------- */
const goodPack={pack_version:1,kind:"results_pack",
  generated_utc:"2026-07-02T06:00:00+00:00",
  script:"refresh_impacts.py v1 (Phase 5 results pack, step 1)",
  sites:{count:3,file:"sites.csv",total_value_usd:260000000},
  scenarios:{present:{portfolio:{direct_aal_usd:2500000,
      by_peril_aal_usd:{tc:1600000,cflood:700000,rflood:200000},
      ep_usd:{"10":900000,"25":2500000,"50":5500000,"100":11000000,"250":21000000,"500":30000000}},
    per_site:[]},
   ssp585_2080:{portfolio:{direct_aal_usd:4400000,
      by_peril_aal_usd:{tc:2700000,cflood:1400000,rflood:300000},
      ep_usd:{"10":1500000,"25":4100000,"50":8600000,"100":17000000,"250":31000000,"500":43000000}},
    per_site:[]}},
  adaptation:{},
  capital_plan:{scenario:"ssp585_2080",discount_rate:0.03,horizon_years:25,
    projects:[{site:"Reef Bay",measure:"Wind hardening (roofs & openings)",measure_key:"wind",
               averted_direct_aal_usd:400000,cost_usd:1200000,bcr:5.804},
              {site:"Dune Point",measure:"Dry floodproofing & utility elevation",measure_key:"flood",
               averted_direct_aal_usd:90000,cost_usd:480000,bcr:3.265}]},
  uncertainty:{present:{acute_aal_usd:{p5:1900000,p50:2500000,p95:3400000,central:2500000},
    loss_1in100_usd:{p5:8000000,p50:11000000,p95:15000000,central:11000000},drivers:[]}}};

loadResultsPack("{broken","p.json");
assert(_lastToast.indexOf("parse")>=0&&resultsPack===null,"broken pack JSON rejected, state untouched");
loadResultsPack(JSON.stringify({kind:"results_pack",pack_version:2,scenarios:{}}),"p.json");
assert(_lastToast.indexOf("does not look like")>=0&&resultsPack===null,"wrong pack version rejected");
loadResultsPack(JSON.stringify(goodPack),"results_pack.json");
assert(resultsPack&&resultsPack.data.kind==="results_pack","valid pack accepted and stored");

routeHazJson(JSON.stringify(goodMeta),"hazard_grid_meta.json");
assert(hazardMeta&&hazardMeta.data.combined===true,"dispatcher: sidecar JSON still routes to meta");
resultsPack=null;
routeHazJson(JSON.stringify(goodPack),"results_pack.json");
assert(resultsPack&&resultsPack.data.pack_version===1,"dispatcher: pack JSON routes to the pack loader");

scenario="present";
sites=[{id:1,name:"T",brand:"B",latitude:25.0,longitude:-80.0,asset_value_usd:100000000}];
renderResultsPack();
const panel=document.getElementById("packPanel");
assert(panel.innerHTML.indexOf("CLIMADA results pack")>=0,"pack panel renders");
assert(panel.innerHTML.indexOf("$2.50M")>=0,"pack direct AAL shown");
assert(panel.innerHTML.indexOf("$11.00M")>=0,"pack 1-in-100 loss shown");
assert(panel.innerHTML.indexOf("live model:")>=0,"live-model comparison shown beside pack figures");
assert(panel.innerHTML.indexOf("p5..p95")>=0,"uncertainty band shown");
assert(panel.innerHTML.indexOf("results_pack.json")>=0,"pack provenance carries the file name");

scenario="ssp245_2050";           // pack lacks this key: falls back, visibly
renderResultsPack();
assert(panel.innerHTML.indexOf("pack has no ssp245_2050")>=0,
  "missing pack scenario falls back to present and says so");
scenario="ssp585_2080";
renderResultsPack();
assert(panel.innerHTML.indexOf("$4.40M")>=0,"pack scenario rows resolve per key");

/* ---------------- v1.9: event-set layer benchmark + capital plan ---------- */
scenario="present";
const pls=packLayerStats("present");
assert(pls&&pls.transferred>0&&pls.premium===pls.transferred*adapt.load,
  "packLayerStats: layer integral on the pack curve, premium = transferred x load");
renderResultsPack();
assert(panel.innerHTML.indexOf("Layer benchmark")>=0&&panel.innerHTML.indexOf("technical premium")>=0,
  "pack panel carries the technical-premium layer benchmark");
assert(panel.innerHTML.indexOf("Top capital projects")>=0&&panel.innerHTML.indexOf("Reef Bay")>=0
  &&panel.innerHTML.indexOf("BCR 5.804")>=0,"pack panel ranks the capital plan");
assert(panel.innerHTML.indexOf("ssp585_2080 appraisal")>=0,
  "capital plan states its appraisal scenario");

persistPack();
resultsPack=null;
restore();
assert(resultsPack&&resultsPack.data.scenarios.ssp585_2080,"pack restored from storage");

resultsPack=null;
renderResultsPack();
assert(panel.innerHTML==="","no pack -> empty panel");

console.log("\\nALL FRONTEND FUNCTIONAL TESTS PASSED");
"""


def main(html_path: str) -> int:
    html = Path(html_path).read_text(encoding="utf-8")
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    if not blocks:
        print("FAIL: no inline script block found")
        return 1
    js = max(blocks, key=len)
    i = js.index("function restore(")
    depth, j = 0, js.index("{", i)
    for k in range(j, len(js)):
        if js[k] == "{":
            depth += 1
        elif js[k] == "}":
            depth -= 1
            if depth == 0:
                break
    harness = STUBS + js[:k + 1] + TESTS
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(harness)
        tmp = f.name
    r = subprocess.run(["node", tmp], capture_output=True, text=True)
    print(r.stdout, end="")
    if r.returncode:
        print(r.stderr)
    return r.returncode


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python test_frontend.py <app.html>")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
