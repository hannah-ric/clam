/* ============================================================
   Data intake
   ============================================================ */
function addSites(arr){
  arr.forEach(a=>sites.push(Object.assign({id:nextId++},a)));
  persist();render();
}
function loadSample(){ sites=[]; nextId=1; clearHazCache();
  ui.portfolioSource="sample";
  addSites(SAMPLE.map(s=>Object.assign({name:s[0],brand:s[1],latitude:s[2],longitude:s[3],asset_value_usd:s[4]},s[5]||{})));
  toast("Sample portfolio loaded (illustrative values)");
}
/* quote-aware CSV line splitter: handles "quoted, fields" and "" escapes */
function splitCsvLine(line){
  const out=[];let cur="",q=false;
  for(let i=0;i<line.length;i++){const ch=line[i];
    if(q){ if(ch==='"'){ if(line[i+1]==='"'){cur+='"';i++;} else q=false; } else cur+=ch; }
    else { if(ch==='"')q=true; else if(ch===",")  {out.push(cur);cur="";} else cur+=ch; }
  }
  out.push(cur);return out;
}
function parseCsv(text){
  text=(text||"").replace(/^\uFEFF/,"");                       // strip Excel BOM
  const lines=text.split(/\r?\n/).filter(l=>l.trim().length);
  if(!lines.length)return {head:[],out:[]};
  const head=splitCsvLine(lines[0]).map(h=>h.trim().toLowerCase());
  const idx=n=>head.indexOf(n);
  const out=[];
  for(let i=1;i<lines.length;i++){
    const c=splitCsvLine(lines[i]).map(x=>x.trim());
    out.push({get:n=>{const j=idx(n);return j>=0?c[j]:undefined;}});
  }
  return {head,out};
}
function truthy(v){ v=String(v==null?"":v).trim().toLowerCase(); return v==="1"||v==="true"||v==="yes"||v==="y"; }
function loadSiteCsv(text){
  const {head,out}=parseCsv(text);
  const missing=["name","latitude","longitude","asset_value_usd"].filter(k=>head.indexOf(k)<0);
  if(missing.length){
    toast("CSV is missing required column"+(missing.length>1?"s":"")+": "+missing.join(", ")+".");return;
  }
  const hasCountry=head.indexOf("country")>=0, hasRev=head.indexOf("annual_revenue_usd")>=0;
  const hasConstr=head.indexOf("construction")>=0, hasYear=head.indexOf("year_built")>=0, hasDef=head.indexOf("defended")>=0;
  const arr=[];let skipped=0;
  out.forEach(row=>{
    const lat=toNum(row.get("latitude")),lon=toNum(row.get("longitude")),val=toNum(row.get("asset_value_usd"));
    if(!isFinite(lat)||!isFinite(lon)||!isFinite(val)||lat< -90||lat>90||lon< -180||lon>180||val<0){skipped++;return;}
    const rec={name:String(row.get("name")||"Site").slice(0,120),brand:String(row.get("brand")||"").slice(0,80),
              latitude:lat,longitude:lon,asset_value_usd:val};
    if(hasCountry){const c=String(row.get("country")||"").slice(0,60);if(c)rec.country=c;}
    if(hasRev){const rv=toNum(row.get("annual_revenue_usd"));if(isFinite(rv)&&rv>=0)rec.annual_revenue_usd=rv;}
    if(hasConstr){const cs=String(row.get("construction")||"").trim().toLowerCase();if(CONSTR_FACTOR[cs]!=null)rec.construction=cs;}
    if(hasYear){const yb=toNum(row.get("year_built"));if(isFinite(yb)&&yb>1800&&yb<2100)rec.year_built=Math.round(yb);}
    if(hasDef){const dv=row.get("defended");if(dv!==undefined&&String(dv).trim()!=="")rec.defended=truthy(dv);}
    /* profile v2 columns, all optional (absent = today's behavior) */
    const rt2=String(row.get("roof_type")||"").trim().toLowerCase();if(ROOF_TYPE_FACTOR[rt2]!=null)rec.roof_type=rt2;
    const op2=String(row.get("opening_protection")||"").trim().toLowerCase();if(OPENING_FACTOR[op2]!=null)rec.opening_protection=op2;
    const ry2=toNum(row.get("roof_year"));if(isFinite(ry2)&&ry2>1800&&ry2<2100)rec.roof_year=Math.round(ry2);
    const ffe2=toNum(row.get("first_floor_elev_m"));if(isFinite(ffe2)&&ffe2>=0)rec.first_floor_elev_m=ffe2;
    const ee2=row.get("equipment_elevated");if(ee2!==undefined&&String(ee2).trim()!=="")rec.equipment_elevated=truthy(ee2);
    const wu2=String(row.get("wui_class")||"").trim().toLowerCase();if(FIRE_WUI_PBURN[wu2]!=null||wu2==="none")rec.wui_class=wu2;
    const ds2=toNum(row.get("defensible_space_m"));if(isFinite(ds2)&&ds2>=0)rec.defensible_space_m=ds2;
    const at2=String(row.get("archetype")||"").trim().toLowerCase();if(ARCHETYPES[at2]!=null)rec.archetype=at2;
    /* Task 4: site + cell ground elevation (m above MSL; negative allowed,
       e.g. below-sea-level ground). Both present -> depth at the structure. */
    const ge2=toNum(row.get("ground_elev_m"));if(isFinite(ge2)&&ge2>-500&&ge2<9000)rec.ground_elev_m=ge2;
    const ce2=toNum(row.get("cell_ground_elev_m"));if(isFinite(ce2)&&ce2>-500&&ce2<9000)rec.cell_ground_elev_m=ce2;
    const ra2=row.get("roof_class_a");if(ra2!==undefined&&String(ra2).trim()!=="")rec.roof_class_a=truthy(ra2);
    /* named-insured aggregation: who is insured (named_insured), which physical
       site they sit on (site_id groups them into one map marker), and the
       campus display name (site_name). All optional free text. */
    const ni2=String(row.get("named_insured")||"").trim();if(ni2)rec.named_insured=ni2.slice(0,80);
    const sid2=String(row.get("site_id")||"").trim();if(sid2)rec.site_id=sid2.slice(0,80);
    const snm2=String(row.get("site_name")||"").trim();if(snm2)rec.site_name=snm2.slice(0,120);
    /* TCOR fields (schema v3 subset, from the SOV; all optional): the
       hurricane-deductible-sharing unit, tenure, the BI exposure ceiling,
       the actual per-site premium, and site risk-control spend. The full
       SOV importer (Task 8) supersedes hand-keyed columns. */
    const cc3=String(row.get("campus_code")||"").trim();if(cc3)rec.campus_code=cc3.slice(0,40);
    const cn3=String(row.get("campus_name")||"").trim();if(cn3)rec.campus_name=cn3.slice(0,120);
    const ol3=String(row.get("owned_or_leased")||"").trim().toLowerCase();if(ol3==="owned"||ol3==="leased")rec.owned_or_leased=ol3;
    const be3=toNum(row.get("bi_ee_usd"));if(isFinite(be3)&&be3>=0)rec.bi_ee_usd=be3;
    const pa3=toNum(row.get("premium_annual_usd"));if(isFinite(pa3)&&pa3>=0)rec.premium_annual_usd=pa3;
    const ms3=toNum(row.get("mitigation_annual_usd"));if(isFinite(ms3)&&ms3>=0)rec.mitigation_annual_usd=ms3;
    arr.push(rec);
  });
  if(!arr.length){toast("No valid rows found. Check that latitude (-90..90), longitude (-180..180), and value are numbers.");return;}
  sites=[];nextId=1;selectedId=null;clearHazCache();ui.portfolioSource="upload";addSites(arr);
  toast(arr.length+" site"+(arr.length>1?"s":"")+" loaded"+(skipped?", "+skipped+" row"+(skipped>1?"s":"")+" skipped (invalid coordinates or value)":""));
}
/* SVP review: the in-app Add/Edit form's coercion, mirroring loadSiteCsv's
   per-field guards exactly so a typed site is validated the same way an uploaded
   one is. Blank or invalid optional fields are omitted, so an empty advanced
   section reproduces today's six-field behaviour. Returns null when the required
   location or value is invalid. Pure; defined before restore() so it is testable. */
const FORM_OPTIONAL_FIELDS=["annual_revenue_usd","construction","year_built","defended",
  "roof_type","roof_year","opening_protection","first_floor_elev_m","equipment_elevated",
  "wui_class","defensible_space_m","archetype","ground_elev_m","cell_ground_elev_m",
  "named_insured","site_id","site_name"];
function siteRecordFromFields(raw){
  raw=raw||{};
  const lat=toNum(raw.latitude),lon=toNum(raw.longitude),val=toNum(raw.asset_value_usd);
  if(!isFinite(lat)||!isFinite(lon)||!isFinite(val)||lat< -90||lat>90||lon< -180||lon>180||val<0)return null;
  const rec={name:String(raw.name||"Site").slice(0,120),brand:String(raw.brand||"").slice(0,80),
             latitude:lat,longitude:lon,asset_value_usd:val};
  const rv=toNum(raw.annual_revenue_usd); if(isFinite(rv)&&rv>=0)rec.annual_revenue_usd=rv;
  const cs=String(raw.construction||"").trim().toLowerCase(); if(CONSTR_FACTOR[cs]!=null)rec.construction=cs;
  const yb=toNum(raw.year_built); if(isFinite(yb)&&yb>1800&&yb<2100)rec.year_built=Math.round(yb);
  if(raw.defended!==undefined&&String(raw.defended).trim()!=="")rec.defended=truthy(raw.defended);
  const rt=String(raw.roof_type||"").trim().toLowerCase(); if(ROOF_TYPE_FACTOR[rt]!=null)rec.roof_type=rt;
  const ry=toNum(raw.roof_year); if(isFinite(ry)&&ry>1800&&ry<2100)rec.roof_year=Math.round(ry);
  const op=String(raw.opening_protection||"").trim().toLowerCase(); if(OPENING_FACTOR[op]!=null)rec.opening_protection=op;
  const ffe=toNum(raw.first_floor_elev_m); if(isFinite(ffe)&&ffe>=0)rec.first_floor_elev_m=ffe;
  if(raw.equipment_elevated!==undefined&&String(raw.equipment_elevated).trim()!=="")rec.equipment_elevated=truthy(raw.equipment_elevated);
  const wu=String(raw.wui_class||"").trim().toLowerCase(); if(FIRE_WUI_PBURN[wu]!=null||wu==="none")rec.wui_class=wu;
  const ds=toNum(raw.defensible_space_m); if(isFinite(ds)&&ds>=0)rec.defensible_space_m=ds;
  const at=String(raw.archetype||"").trim().toLowerCase(); if(ARCHETYPES[at]!=null)rec.archetype=at;
  const ge=toNum(raw.ground_elev_m); if(isFinite(ge)&&ge>-500&&ge<9000)rec.ground_elev_m=ge;
  const ce=toNum(raw.cell_ground_elev_m); if(isFinite(ce)&&ce>-500&&ce<9000)rec.cell_ground_elev_m=ce;
  const ni=String(raw.named_insured||"").trim(); if(ni)rec.named_insured=ni.slice(0,80);
  const sid=String(raw.site_id||"").trim(); if(sid)rec.site_id=sid.slice(0,80);
  const snm=String(raw.site_name||"").trim(); if(snm)rec.site_name=snm.slice(0,120);
  return rec;
}
function buildGridsFromRows(rows){
  gridByHazard={};
  const byHaz={};
  rows.forEach(r=>{const h=r.hazard||"tc";(byHaz[h]||(byHaz[h]=[])).push(r);});
  /* Phase 3: heat rows are kept (v10=days>32C, v25=days>35C, v50=CDD);
     heatIndicators reads them grid-first. */
  Object.keys(byHaz).forEach(h=>{ gridByHazard[h]=makeGridProvider(byHaz[h]); });
  const tcGrid=gridByHazard.tc;
  _baseProvider = tcGrid
    ? (la,lo,sc)=>{const r=tcGrid(la,lo,sc);return (r.meta&&r.meta.outside)?interimVector(la,lo,sc):r;}
    : ((la,lo,sc)=>interimVector(la,lo,sc));
}
function loadBacktestCsv(text){
  const {head,out}=parseCsv(text);
  if(head.indexOf("name")<0||head.indexOf("observed_annual_loss_usd")<0){
    toast("Backtest CSV needs columns: name, observed_annual_loss_usd.");return;
  }
  const rows=[];
  out.forEach(row=>{
    const nm=String(row.get("name")||"").trim(), obs=toNum(row.get("observed_annual_loss_usd"));
    if(nm&&isFinite(obs)&&obs>=0)rows.push({name:nm,observed:obs});
  });
  if(!rows.length){toast("No valid backtest rows found.");return;}
  backtest={rows,loaded:new Date().toISOString().slice(0,16).replace("T"," ")};
  persist();renderBacktest();
  toast("Observed losses loaded ("+rows.length+" rows)");
}
/* parse one hazard CSV to normalized rows; null means the required columns are
   missing (the caller shows the schema hint). An empty array means the file
   parsed but held no usable rows. */
function parseHazardRows(text){
  const {head,out}=parseCsv(text);
  if(["lat","lon","scenario"].some(k=>head.indexOf(k)<0))return null;
  const hasHaz=head.indexOf("hazard")>=0;
  const rows=[];
  out.forEach(row=>{
    const lat=toNum(row.get("lat")),lon=toNum(row.get("lon")),sc=row.get("scenario");
    if(!isFinite(lat)||!isFinite(lon)||!sc)return;
    const hazard=hasHaz?(String(row.get("hazard")||"tc").trim()||"tc"):"tc";
    const r={lat,lon,scenario:String(sc).trim(),hazard};
    RPS.forEach(rp=>{const v=toNum(row.get("v"+rp));r["v"+rp]=isFinite(v)?v:0;});
    rows.push(r);
  });
  return rows;
}
/* build the live grid and its provenance summary from already-parsed rows,
   shared by the single-file and multi-file loaders */
function installHazardRows(rows,name){
  const scens=new Set(),hazSet=new Set(),perHaz={};
  rows.forEach(r=>{scens.add(r.scenario);hazSet.add(r.hazard);
    const ph=perHaz[r.hazard]||(perHaz[r.hazard]={cells:0,scen:{}});ph.cells++;ph.scen[r.scenario]=1;});
  buildGridsFromRows(rows);
  const perHazOut={};Object.keys(perHaz).forEach(k=>perHazOut[k]={cells:perHaz[k].cells,scenarios:Object.keys(perHaz[k].scen)});
  hazardGrid={rows,meta:{name:name||"hazard_grid.csv",cells:rows.length,scenarios:[...scens],hazards:[...hazSet],perHaz:perHazOut,loaded:new Date().toISOString().slice(0,16).replace("T"," ")}};
  clearHazCache();persistHazard();
  toast("CLIMADA hazard grid active ("+rows.length+" cells, "+hazSet.size+" peril"+(hazSet.size>1?"s":"")+")");
  render();
}
function loadHazardCsv(text,name){
  const rows=parseHazardRows(text);
  if(rows===null){toast("Hazard grid needs columns: lat, lon, scenario, v10..v500 (optional: hazard).");return;}
  if(!rows.length){toast("Could not read hazard grid. Expect lat, lon, scenario, v10..v500.");return;}
  installHazardRows(rows,name);
}
/* Several hazard CSVs dropped at once (e.g. hazard_grid.csv + heat_grid.csv):
   MERGE them the way the pipeline's merge_grids.py does, later files winning on
   (lat, lon, scenario, hazard). Without this the loader replaces the whole grid
   per file, so the last file silently wipes every peril the others carried. */
function loadHazardCsvMulti(files){
  const merged=new Map();const used=[];let bad=0;
  files.forEach(f=>{
    const rows=parseHazardRows(f.text);
    if(rows===null){bad++;return;}
    used.push(f.name||"");
    rows.forEach(r=>merged.set(r.lat+"|"+r.lon+"|"+r.scenario+"|"+r.hazard,r));
  });
  const rows=[...merged.values()];
  if(!rows.length){toast(bad?"None of the dropped files look like a hazard grid (need lat, lon, scenario, v10..v500).":"Could not read the hazard grids.");return;}
  const name=used.length>1?used[0]+" + "+(used.length-1)+" more (merged)":used[0];
  installHazardRows(rows,name);
}
function loadHazardMeta(text,name){
  let data=null;
  try{ data=JSON.parse(text); }catch(e){ toast("Could not parse the provenance JSON."); return; }
  if(!data||typeof data!=="object"||!(data.layers||data.sources||data.generated_utc)){
    toast("That JSON does not look like a hazard_grid_meta file."); return;
  }
  hazardMeta={data,name:name||"hazard_grid_meta.json",loaded:new Date().toISOString().slice(0,16).replace("T"," ")};
  persistMeta();
  const n=metaSources(data).length;
  toast("Provenance attached ("+n+" pipeline record"+(n>1?"s":"")+")");
  render();
}
function loadResultsPack(text,name){
  let data=null;
  try{ data=JSON.parse(text); }catch(e){ toast("Could not parse the results pack JSON."); return; }
  if(!data||data.kind!=="results_pack"||data.pack_version!==1||!data.scenarios){
    toast("That JSON does not look like a results_pack file."); return;
  }
  resultsPack={data,name:name||"results_pack.json",loaded:new Date().toISOString().slice(0,16).replace("T"," ")};
  persistPack();
  toast("Results pack attached ("+Object.keys(data.scenarios).length+" scenario"+(Object.keys(data.scenarios).length>1?"s":"")+")");
  render();
}
/* one JSON drop zone, two JSON artifacts: sniff the pack marker, else treat
   the file as the provenance sidecar (whose own shape check still applies) */
function routeHazJson(text,name){
  let peek=null; try{ peek=JSON.parse(text); }catch(e){}
  if(peek&&peek.kind==="results_pack") loadResultsPack(text,name);
  else loadHazardMeta(text,name);
}
function readFile(file,cb){
  const r=new FileReader();
  r.onload=()=>{ try{ cb(r.result); }catch(e){ toast("Could not read that file."); } };
  r.onerror=()=>toast("Could not read that file.");
  r.readAsText(file);
}
/* read a whole FileList to [{name,text},...] then hand off once, so a batch of
   files (CSV grids + JSON sidecars) is loaded together instead of racing */
function readFiles(files,done){
  const arr=Array.from(files||[]);let left=arr.length;const out=[];
  if(!left){done([]);return;}
  arr.forEach((f,i)=>{const r=new FileReader();
    r.onload=()=>{out[i]={name:f.name||"",text:r.result};if(--left===0)done(out.filter(Boolean));};
    r.onerror=()=>{if(--left===0)done(out.filter(Boolean));};
    r.readAsText(f);});
}
/* the hazard drop zone accepts the grid CSV(s) and the JSON sidecar(s) in one
   go: JSON files route to the provenance/results-pack handlers; a single CSV
   loads as before; multiple CSVs merge (later wins) instead of overwriting.
   A production grid takes a second or two of synchronous parsing, so say so
   first and yield a frame to let the toast paint before the parse blocks. */
function routeHazFiles(files){
  const n=(files&&files.length)||0; if(!n)return;
  toast("Reading "+n+" file"+(n>1?"s":"")+"...");
  readFiles(files,list=>{
    setTimeout(()=>{
      const jsons=[],csvs=[];
      list.forEach(o=>{ if(/\.json$/i.test(o.name)||/^\s*[[{]/.test(o.text)) jsons.push(o); else csvs.push(o); });
      /* a loss run announces itself by its claim columns: route it to the
         calibration loader instead of the hazard-grid parser */
      const grids=[];
      csvs.forEach(o=>{
        const h=(o.text.split(/\r?\n/,1)[0]||"").toLowerCase();
        if(/claim/.test(h)&&/(incurred|coverage)/.test(h)) loadLossRun(o.text,o.name);
        else grids.push(o);
      });
      if(grids.length===1) loadHazardCsv(grids[0].text,grids[0].name);
      else if(grids.length>1) loadHazardCsvMulti(grids);
      jsons.forEach(o=>routeHazJson(o.text,o.name));
    },40);
  });
}

/* ---- persistence (guarded; safe if storage is unavailable or full) ---- */
