/* ============================================================
   Data intake
   ============================================================ */
function addSites(arr){
  arr.forEach(a=>sites.push(Object.assign({id:nextId++},a)));
  persist();render();
}
function loadSample(){ sites=[]; nextId=1; clearHazCache();
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
function truthy(v){ v=String(v==null?"":v).trim().toLowerCase(); return v==="1"||v==="true"||v==="yes"||v==="y"||v==="coastal"; }
function loadSiteCsv(text){
  const {head,out}=parseCsv(text);
  const missing=["name","latitude","longitude","asset_value_usd"].filter(k=>head.indexOf(k)<0);
  if(missing.length){
    toast("CSV is missing required column"+(missing.length>1?"s":"")+": "+missing.join(", ")+".");return;
  }
  const hasCoastal=head.indexOf("coastal")>=0, hasCountry=head.indexOf("country")>=0, hasRev=head.indexOf("annual_revenue_usd")>=0;
  const hasConstr=head.indexOf("construction")>=0, hasYear=head.indexOf("year_built")>=0, hasDef=head.indexOf("defended")>=0;
  const arr=[];let skipped=0;
  out.forEach(row=>{
    const lat=toNum(row.get("latitude")),lon=toNum(row.get("longitude")),val=toNum(row.get("asset_value_usd"));
    if(!isFinite(lat)||!isFinite(lon)||!isFinite(val)||lat< -90||lat>90||lon< -180||lon>180||val<0){skipped++;return;}
    const rec={name:String(row.get("name")||"Site").slice(0,120),brand:String(row.get("brand")||"").slice(0,80),
              latitude:lat,longitude:lon,asset_value_usd:val};
    if(hasCountry){const c=String(row.get("country")||"").slice(0,60);if(c)rec.country=c;}
    if(hasCoastal){const cv=row.get("coastal");if(cv!==undefined&&String(cv).trim()!=="")rec.coastal=truthy(cv);}
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
    const ra2=row.get("roof_class_a");if(ra2!==undefined&&String(ra2).trim()!=="")rec.roof_class_a=truthy(ra2);
    arr.push(rec);
  });
  if(!arr.length){toast("No valid rows found. Check that latitude (-90..90), longitude (-180..180), and value are numbers.");return;}
  sites=[];nextId=1;selectedId=null;clearHazCache();addSites(arr);
  toast(arr.length+" site"+(arr.length>1?"s":"")+" loaded"+(skipped?", "+skipped+" row"+(skipped>1?"s":"")+" skipped (invalid coordinates or value)":""));
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
function loadHazardCsv(text,name){
  const {head,out}=parseCsv(text);
  if(["lat","lon","scenario"].some(k=>head.indexOf(k)<0)){
    toast("Hazard grid needs columns: lat, lon, scenario, v10..v500 (optional: hazard).");return;
  }
  const hasHaz=head.indexOf("hazard")>=0;
  const rows=[];const scens=new Set();const hazSet=new Set();const perHaz={};
  out.forEach(row=>{
    const lat=toNum(row.get("lat")),lon=toNum(row.get("lon")),sc=row.get("scenario");
    if(!isFinite(lat)||!isFinite(lon)||!sc)return;
    const hazard=hasHaz?(String(row.get("hazard")||"tc").trim()||"tc"):"tc";
    const r={lat,lon,scenario:String(sc).trim(),hazard};
    RPS.forEach(rp=>{const v=toNum(row.get("v"+rp));r["v"+rp]=isFinite(v)?v:0;});
    rows.push(r);scens.add(r.scenario);hazSet.add(hazard);
    const ph=perHaz[hazard]||(perHaz[hazard]={cells:0,scen:{}});ph.cells++;ph.scen[r.scenario]=1;
  });
  if(!rows.length){toast("Could not read hazard grid. Expect lat, lon, scenario, v10..v500.");return;}
  buildGridsFromRows(rows);
  const perHazOut={};Object.keys(perHaz).forEach(k=>perHazOut[k]={cells:perHaz[k].cells,scenarios:Object.keys(perHaz[k].scen)});
  hazardGrid={rows,meta:{name:name||"hazard_grid.csv",cells:rows.length,scenarios:[...scens],hazards:[...hazSet],perHaz:perHazOut,loaded:new Date().toISOString().slice(0,16).replace("T"," ")}};
  clearHazCache();persistHazard();
  toast("CLIMADA hazard grid active ("+rows.length+" cells, "+hazSet.size+" peril"+(hazSet.size>1?"s":"")+")");
  render();
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

/* ---- persistence (guarded; safe if storage is unavailable or full) ---- */
