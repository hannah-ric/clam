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
assert(htext.textContent.indexOf("3/6")>=0,"badge counts live perils (tc, rflood, heat = 3/6)");
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
assert(htext.textContent.indexOf("4/6")>=0,"cflood now live: badge reads 4/6");
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
    plan_years:3,budget_annual_usd:1500000,
    projects:[{site:"Reef Bay",measure:"Re-roof to rated metal system",measure_key:"reroof",
               averted_direct_aal_usd:400000,cost_usd:1200000,bcr:5.804,
               annuity_years:25,year:1},
              {site:"Dune Point",measure:"Dry floodproofing (barriers & sealing)",measure_key:"floodproof",
               averted_direct_aal_usd:90000,cost_usd:408000,bcr:3.265,
               annuity_years:25,year:2,renovation_synergy:true},
              {site:"River Bend",measure:"Roof-to-wall connection retrofit",measure_key:"tiedown",
               averted_direct_aal_usd:20000,cost_usd:300000,bcr:1.161,
               annuity_years:25,year:null,deferred:true}]},
  measures_catalog:{modeled:{},identified:[
    {key:"defensible",name:"Defensible space (wildfire)",sites_in_scope:2},
    {key:"backup_power",name:"Backup power (full-site generation)",sites_in_scope:3}]},
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

/* ---------------- v1.11: phased catalog plan + identified measures ---------- */
assert(panel.innerHTML.indexOf("Y1 · Reef Bay")>=0,"plan rows carry the phase year");
assert(panel.innerHTML.indexOf("deferred · River Bend")>=0,"deferred projects say so");
assert(panel.innerHTML.indexOf("refurbishment-phased")>=0,"renovation synergy is marked");
assert(panel.innerHTML.indexOf("$1.50M/yr budget")>=0,"the annual budget is stated");
assert(panel.innerHTML.indexOf("Identified, not yet priced")>=0
  &&panel.innerHTML.indexOf("Defensible space (wildfire)")>=0
  &&panel.innerHTML.indexOf("(2 sites)")>=0,
  "identified-but-unpriced measures stay visible with their site counts");

/* ---------------- v1.10: profile v2 parity with the pipeline ---------------- */
let v=vulnOf({construction:"masonry",year_built:1980,roof_type:"metal",roof_year:2020,opening_protection:"impact"});
assert(Math.abs(v.windMult-0.85*0.9*0.85)<1e-12,"vulnOf v2: roof detail supersedes year-built (pipeline parity)");
v=vulnOf({construction:"frame",year_built:2015,roof_type:"shingle",roof_year:2000,opening_protection:"none"});
assert(v.windMult===1.6,"vulnOf v2: clipped at 1.6 (1.3x1.1x1.2x1.05)");
v=vulnOf({construction:"masonry",roof_type:"tile"});
assert(Math.abs(v.windMult-0.95)<1e-12,"vulnOf v2: single field present, others neutral");
v=vulnOf({construction:"frame",year_built:1980});
assert(Math.abs(v.windMult-1.3*1.15)<1e-12&&v.floodCap===0.75,"vulnOf v2: no v2 fields -> exact legacy factors, cap 0.75");
v=vulnOf({defended:true,first_floor_elev_m:1.2});
assert(v.fbBonus===1.2,"vulnOf v2: measured first floor supersedes the defended proxy");
assert(vulnOf({first_floor_elev_m:9.0}).fbBonus===3.0,"vulnOf v2: first-floor sanity cap 3 m");
assert(vulnOf({equipment_elevated:true}).floodCap===0.5,"vulnOf v2: elevated equipment caps flood MDD at 0.5");
assert(Math.abs(floodMdd(6.0,1.1)-0.75)<1e-12&&floodMdd(6.0,1.1,0.5)===0.5,
  "floodMdd: cap parameter binds in deep water, default unchanged");

/* ---------------- v1.12: six perils, migration safety first ---------------- */
gridByHazard={};clearHazCache();
const plain={id:9,name:"Plain",latitude:29.5,longitude:-98.5,asset_value_usd:50000000};
assert(hzSite(plain,"wfire","present").ead===0,
  "MIGRATION SAFETY: wildfire scores zero without a grid or wui_class");
assert(hzSite(plain,"prain","present").ead===0,
  "MIGRATION SAFETY: rainfall scores zero without a grid (no interim model)");
const wui={id:10,name:"Ridge",latitude:34.0,longitude:-116.5,asset_value_usd:50000000,wui_class:"intermix"};
const wf0=hzSite(wui,"wfire","present");
assert(Math.abs(wf0.ead-50000000*(0.6/100)*FIRE_MDD)<1e-6,
  "wildfire interim: WUI class drives burn probability (0.6%/yr intermix)");
const wf85=hzSite(wui,"wfire","ssp585_2080");
assert(Math.abs(wf85.ead-wf0.ead*(1+FIRE_WARMING_UPLIFT*3.6))<1e-3,
  "wildfire interim scales with warming per scenario");
const hard1={...wui,roof_class_a:true,defensible_space_m:40};
assert(Math.abs(hzSite(hard1,"wfire","present").ead-wf0.ead*0.6*0.7)<1e-6,
  "wildfire profile fields (Class A roof, defensible space) cut the loss");

const sixRows=[];
for(const sc of SCEN_KEYS){
  sixRows.push({lat:34.0,lon:-116.5,scenario:sc,hazard:"wfire",
    v10:+(1.2*(1+FIRE_WARMING_UPLIFT*(WARMING[sc]||0))).toFixed(3),v25:0,v50:0,v100:0,v250:0,v500:0});
  sixRows.push({lat:29.5,lon:-98.5,scenario:sc,hazard:"prain",
    v10:200,v25:350,v50:550,v100:800,v250:1200,v500:1600});
}
buildGridsFromRows(sixRows);
const wfg=hzSite(wui,"wfire","present");
assert(wfg.fireSource==="grid"&&Math.abs(wfg.burnPct-1.2)<1e-9,
  "wildfire grid supersedes the WUI interim (grid-first)");
const prg=hzSite(plain,"prain","present");
assert(prg.ead>0,"rainfall grid lights the peril up");
const d100=Math.max(0,800-PRAIN_DRAIN_MM)/1000*PRAIN_POND_COEFF;
assert(Math.abs(prg.vec[100]-d100)<1e-12,
  "rainfall converts mm to ponding depth via the documented drainage constants");
assert(prg.curve.find(c=>c.rp===100).loss===0&&prg.curve.find(c=>c.rp===500).loss>0,
  "drainage freeboard keeps moderate rain dry; only extreme rain ponds deep enough");
assert(ACUTE.length===5&&ACUTE.indexOf("prain")>=0&&ACUTE.indexOf("wfire")>=0,
  "both new perils are acute (they carry business interruption)");
assert(HAZARDS.length===6&&siteRatings(wui,"present").wfire,
  "six perils registered; site ratings cover wildfire");

const fireBase=adaptedFinSite(wui,"present",{});
const fireAdapted=adaptedFinSite(wui,"present",{fireMult:0.5});
assert(fireAdapted.directEad<fireBase.directEad,
  "the wildfire-hardening measure averts loss through adaptedFinSite");
assert(Math.abs(adaptedFinSite(wui,"present",{}).totalAal-fireBase.totalAal)<1e-9,
  "adaptedFinSite with no mods stays self-consistent across six perils");
gridByHazard={};clearHazCache();

/* ---------------- v1.13: six-peril coherence ---------------- */
assert(INFO.wfire&&INFO.wfire.b.indexOf("burn probability")>=0
  &&INFO.wfire.b.indexOf("Honest limit")>=0,
  "wildfire INFO popover exists and states the fire-tail limit");
assert(INFO.prain&&INFO.prain.b.indexOf("no interim model")>=0,
  "rainfall INFO popover exists and states the no-interim design");
loadSiteCsv("name,latitude,longitude,asset_value_usd,wui_class,defensible_space_m,roof_class_a\\n"+
            "Ridge,34.0,-116.5,50000000,intermix,10,true","sites.csv");
assert(sites.length===1&&sites[0].wui_class==="intermix"
  &&sites[0].defensible_space_m===10&&sites[0].roof_class_a===true,
  "site CSV ingests the wildfire profile fields");
gridByHazard={};clearHazCache();
assert(hzSite(sites[0],"wfire","present").ead>0,
  "an ingested WUI site reaches the wildfire interim model end to end");
goodPack.scenarios.present.portfolio.by_peril_aal_usd.prain=120000;
goodPack.scenarios.present.portfolio.by_peril_aal_usd.wfire=80000;
resultsPack=null;
loadResultsPack(JSON.stringify(goodPack),"results_pack.json");
scenario="present";
renderResultsPack();
assert(panel.innerHTML.indexOf("prain")>=0&&panel.innerHTML.indexOf("wfire")>=0,
  "pack by-peril row shows every peril the pack carries");
assert(panel.innerHTML.indexOf("await")<0,
  "the stale wildfire caveat is gone from the pack panel");

assert(JSON.stringify(EXPORT_ACUTE_LEGACY.concat(EXPORT_ACUTE_APPENDED).slice().sort())
  ===JSON.stringify(ACUTE.slice().sort()),
  "the frozen export column lists partition ACUTE exactly (Power BI contract)");

persistPack();
resultsPack=null;
restore();
assert(resultsPack&&resultsPack.data.scenarios.ssp585_2080,"pack restored from storage");

resultsPack=null;
renderResultsPack();
assert(panel.innerHTML==="","no pack -> empty panel");

/* ---------------- v2.1.0: C2 experience layer ---------------- */
/* scenario scrubber: pure scenario walking, top bar kept in sync */
const st=scrubSteps();
assert(st.length===4&&st[0].sc==="present"&&st[1].sc==="ssp245_2030"&&st[3].sc==="ssp245_2080",
  "scrubSteps walks Present to 2080 under the default pathway");
document.getElementById("pathSel").value="ssp585";
assert(scrubSteps()[2].sc==="ssp585_2050","the scrubber follows the top-bar pathway");
scenario="ssp585_2050";
assert(scrubIndex()===2,"scrubIndex finds the current scenario on the timeline");
let hooked=false; scenHook=()=>{hooked=true;};
scrubTo(0);
assert(scenario==="present"&&hooked,"scrubTo pins the scenario and resyncs the top bar");

/* score tracing: the trace can never diverge from the math it explains */
const traceProfiles=[
  {construction:"masonry",year_built:1980,roof_type:"metal",roof_year:2020,opening_protection:"impact"},
  {construction:"frame",year_built:2015,roof_type:"shingle",roof_year:2000,opening_protection:"none"},
  {construction:"engineered",year_built:2012},{construction:"frame",year_built:1980},{}];
assert(traceProfiles.every(p=>Math.abs(
    windFactorTrail(p).reduce((a,f)=>a*f.mult,1)-vulnOf(p).windMult)<1e-9),
  "the wind factor trail reproduces vulnOf exactly, clip entry included");
clearHazCache();
const exT=explainPeril({latitude:25.02,longitude:-80.02,asset_value_usd:1e8,
  construction:"frame",roof_type:"shingle",roof_year:2000,opening_protection:"none"},"tc","present");
assert(exT.source.kind==="grid"&&exT.source.dataset==="hazard_grid.csv"&&exT.source.distKm<10,
  "tc trace names the grid dataset and the nearest-cell distance");
assert(exT.factors.length>0&&Math.abs(exT.windMult-1.6)<1e-9,
  "tc trace lists the profile factors and the combined multiplier");
const exC=explainPeril({latitude:25.05,longitude:-80.05,asset_value_usd:1e8},"cflood","present");
assert(exC.source.kind==="grid"&&exC.source.distKm<10&&exC.factors[0].add===FB_COAST,
  "coastal trace reports the grid cell and the freeboard baseline");
const exP=explainPeril(plain,"prain","present");
assert(exP.source.kind==="none"&&exP.source.detail.indexOf("no interim model")>=0,
  "rainfall trace states the honest zero (no interim model)");
const exW=explainPeril(plain,"wfire","present");
assert(exW.source.kind==="none"&&exW.source.detail.indexOf("wui_class")>=0,
  "wildfire trace explains its zero (no grid, no wui_class)");
const exWui=explainPeril(wui,"wfire","present");
assert(exWui.source.kind==="interim"&&exWui.source.detail.indexOf("intermix")>=0,
  "wildfire interim trace names the WUI class");
scenario="present";
const traceHtml=traceSection(wui);
assert(traceHtml.indexOf("Why these numbers")>=0&&traceHtml.indexOf("scores zero")>=0
  &&traceHtml.indexOf("interim model")>=0,
  "the scorecard trace section renders a source line for every peril");
assert(INFO.trace&&INFO.scrub&&INFO.brief,"the C2 surfaces carry INFO popovers");

/* board brief: print-ready portfolio one-pager from the same functions */
const bh=briefHtml();
assert(bh.indexOf("Portfolio climate risk brief")>=0&&bh.indexOf("Expected annual cost")>=0
  &&bh.indexOf("CLIMADA hazard grid")>=0&&bh.indexOf("not audited disclosure")>=0,
  "the board brief carries headline figures and states its data basis");
assert(bh.indexOf("Most exposed sites")>=0&&bh.indexOf("Ridge")>=0,
  "the brief names the most exposed sites");
sites=[];
openBrief();
assert(briefHtml()===""&&_lastToast.indexOf("Load sites")>=0,
  "an empty portfolio cannot print a brief, and the app says why");

/* map brand filter: options track the portfolio, stale picks reset */
brandFilter="";_lastBrandKey="";
syncBrandFilter([{brand:"A"},{brand:"B"},{}]);
assert(document.getElementById("brandSel").innerHTML.indexOf("All brands")>=0
  &&document.getElementById("brandSel").innerHTML.indexOf("Unbranded")>=0,
  "the brand filter offers every brand plus Unbranded");
brandFilter="Gone";_lastBrandKey="";
syncBrandFilter([{brand:"A"}]);
assert(brandFilter==="","a vanished brand resets the map filter instead of blanking the map");

/* ---------------- Wave 1: the decision layer (v2.2.0) ---------------- */
/* tolerance, lanes, retention sweep, quote gap, action queue, artifacts.
   All additive: the parity suite already proved no pinned number moved. */
gridByHazard={};clearHazCache();resultsPack=null;hazardGrid=null;
scenario="present";
sites=[
 {id:1,name:"Reef",brand:"A",latitude:25.01,longitude:-80.01,asset_value_usd:80e6,
  construction:"frame",year_built:1988},
 {id:2,name:"Plains",brand:"B",latitude:39.0,longitude:-97.0,asset_value_usd:60e6,
  construction:"engineered",year_built:2015,defended:true},
];
const afW=annuity(20,0.02);
const fW=finPortfolio(sites,"present");
const bpsArr=fW.rows.map(r=>r.value?r.totalAal/r.value*1e4:0);
const hiBps=Math.max.apply(null,bpsArr), loBps=Math.min.apply(null,bpsArr);
const hiName=fW.rows[bpsArr.indexOf(hiBps)].name;
assert(hiBps>loBps,"decision fixture has a risk spread between sites");
tolerance.siteAalBps=(hiBps+loBps)/2;
tolerance.portAalPct=0.0001;      // force a portfolio breach
tolerance.varPctValue=1e9;        // never a tail breach
const tf=toleranceFlags(sites,"present",afW);
assert(tf.siteBreaches.length===1&&tf.siteBreaches[0].name===hiName,
  "only the site above the threshold breaches, and it is the risky one");
assert(tf.portBreach===true&&tf.varBreach===false,
  "portfolio breach and tail non-breach both detected");
assert((tf.siteBreaches[0].bestBcr>=1)===(tf.siteBreaches[0].lane==="capex"),
  "the decision lane follows the breakeven screen exactly");
assert(tf.anyBreach===true,"anyBreach aggregates the three screens");

/* tolerance persistence: round trip, and legacy state keeps defaults */
tolerance.siteAalBps=123;persist();
tolerance={siteAalBps:75,portAalPct:1.0,varPctValue:10};
restore();
assert(tolerance.siteAalBps===123&&tolerance.varPctValue===1e9,
  "tolerance thresholds persist and restore");
const stW=JSON.parse(localStorage.getItem("rtv_state_v1"));
delete stW.tolerance;localStorage.setItem("rtv_state_v1",JSON.stringify(stW));
tolerance={siteAalBps:75,portAalPct:1.0,varPctValue:10};
restore();
assert(tolerance.siteAalBps===75&&tolerance.portAalPct===1.0,
  "legacy saved state without tolerance keeps the defaults (backward safe)");
hazardGrid=null;gridByHazard={};clearHazCache();   // restore() re-loaded the Phase 4 grid; back to interim

/* tolerance panel renders the breach and hides without sites */
tolerance={siteAalBps:(hiBps+loBps)/2,portAalPct:1.0,varPctValue:10};
document.getElementById("sumReadout").innerHTML="Base readout.";
renderTolerance();
const tolB=document.getElementById("tolBody");
assert(tolB.innerHTML.indexOf(hiName)>=0&&tolB.innerHTML.indexOf("tolerance")>=0,
  "the tolerance panel names the breaching site");
assert(document.getElementById("sumReadout").innerHTML.indexOf("tolerance")>=0,
  "the executive read-out carries a position-vs-tolerance sentence");
const savedSites=sites;
sites=[];renderTolerance();
assert(document.getElementById("tolPanel").style.display==="none",
  "no sites: the tolerance panel hides");
sites=savedSites;

/* retention sweep: slices reconcile and match the parity-pinned integral */
adapt.attach=25;adapt.exhaust=250;adapt.load=1.5;
const slW=layerSlices(fW.varByRp,fW.acuteAal,25,250,1.5);
assert(Math.abs(slW.below+slW.layer+slW.above-fW.acuteAal)<1e-6,
  "layer slices reconcile to the acute AAL");
assert(Math.abs(slW.layer-layerStatsCalc(fW.varByRp,fW.acuteAal).transferred)<1e-6,
  "the sweep's layer slice equals the parity-pinned layerStatsCalc integral");
const swW=retentionSweep(fW.varByRp,fW.acuteAal,250,1.5);
assert(swW.length===RPS.filter(rp=>rp<250).length,
  "the sweep covers every attachment below the exhaust");
for(let i=1;i<swW.length;i++)assert(swW[i].layer<=swW[i-1].layer+1e-9,
  "transferred loss falls as the attachment rises ("+swW[i].attach+")");
assert(quoteGapPct(150,100)===50&&quoteGapPct(50,100)===-50
  &&quoteGapPct(0,100)===null&&quoteGapPct(100,0)===null,
  "quote gap: signed percent, and no verdict without both sides");

/* action queue: ranking, cutline semantics, joint roll-up */
const qW=actionQueue(sites,"present",afW,0);
assert(qW.items.length>0,"the queue lists in-scope site-measure pairs");
for(let i=1;i<qW.items.length;i++)assert(qW.items[i].bcr<=qW.items[i-1].bcr+1e-12,
  "the queue is ranked by BCR");
assert(qW.items.every(it=>it.funded===(it.bcr>=1)),
  "no budget: the cutline is breakeven");
assert(qW.roll.cost===qW.items.filter(i=>i.funded).reduce((a,i)=>a+i.cost,0),
  "the roll-up cost sums the funded set");
assert(qW.roll.averted<=qW.items.filter(i=>i.funded).reduce((a,i)=>a+i.averted,0)+1e-6,
  "the joint program benefit never exceeds the itemized sum (no double-counting)");
if(qW.items[0].bcr>=1){
  const qB=actionQueue(sites,"present",afW,qW.items[0].cost);
  assert(qB.items.length===qW.items.length,"a budget never drops items from the list");
  assert(qB.items[0].funded===true,"greedy fill funds the top of the list first");
  assert(qB.items.filter(i=>i.funded).reduce((a,i)=>a+i.cost,0)<=qW.items[0].cost+1e-9,
    "funding respects the budget");
}

/* the two new artifacts: own schemas, honest sourcing, frozen export untouched */
const bpW=brokerPackCsv();
assert(bpW.indexOf("roof_type")>=0&&bpW.indexOf("opening_protection")>=0
  &&bpW.indexOf("modeled_direct_ead_usd_present")>=0,
  "the broker pack carries secondary modifiers and the modeled view");
assert(bpW.trim().split("\\n").length===sites.length+1,"broker pack: one row per site");
assert(bpW.indexOf("interim_model")>=0,
  "the broker pack states its hazard source honestly (interim here)");
const alW=actionListCsv("present",20,2);
assert(alW.indexOf("live_model")>=0&&alW.split("\\n")[0].indexOf("owner")>=0,
  "the action list carries the source label and a blank owner column");
resultsPack={data:goodPack,name:"results_pack.json",loaded:"x"};
const alP=actionListCsv("present",20,2);
assert(alP.indexOf("climada_pack")>=0&&alP.indexOf("deferred")>=0,
  "pack capital-plan rows join the export, deferral preserved");
resultsPack=null;

/* transparency: every new surface carries an authored explanation */
assert(INFO.tolerance&&INFO.quote&&INFO.retention&&INFO.queue&&INFO.brokerPack,
  "the Wave 1 surfaces all carry INFO popovers");
assert(INFO.tolerance.b.indexOf("materiality")>=0,
  "the tolerance INFO states the materiality basis");
assert(INFO.quote.b.indexOf("not a market price")>=0,
  "the quote INFO is honest about what a technical premium is not");

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
