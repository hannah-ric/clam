const LS_STATE="rtv_state_v1", LS_HAZ="rtv_hazard_v1", LS_META="rtv_hazmeta_v1", LS_PACK="rtv_respack_v1";
/* Power BI export contract (Phase C): the column ORDER is frozen. The three
   legacy perils sit mid-row where they always were; later perils append at
   the tail, never reorder. A test asserts these two lists partition ACUTE. */
const EXPORT_ACUTE_LEGACY=["tc","cflood","rflood"];
const EXPORT_ACUTE_APPENDED=["prain","wfire"];
function persist(){ try{ localStorage.setItem(LS_STATE,JSON.stringify({sites,scenario,activeHazard,finAssume,adapt,backtest,nextId})); }catch(e){} }
function persistHazard(){ try{ localStorage.setItem(LS_HAZ,JSON.stringify(hazardGrid)); }catch(e){ /* grid too large to cache: fine, keeps working in-session */ } }
function persistMeta(){ try{ localStorage.setItem(LS_META,JSON.stringify(hazardMeta)); }catch(e){} }
function persistPack(){ try{ localStorage.setItem(LS_PACK,JSON.stringify(resultsPack)); }catch(e){} }
function restore(){
  try{
    const s=JSON.parse(localStorage.getItem(LS_STATE)||"null");
    if(s&&Array.isArray(s.sites)&&s.sites.length){
      sites=s.sites;
      scenario=SCEN_LABEL[s.scenario]?s.scenario:"present";     // drop legacy RCP keys
      if(HAZARD_BY[s.activeHazard])activeHazard=s.activeHazard;
      if(s.finAssume&&typeof s.finAssume==="object")finAssume=Object.assign({},finAssume,s.finAssume);
      if(s.adapt&&typeof s.adapt==="object"){
        const mDef=adapt.m;
        adapt=Object.assign({},adapt,s.adapt);
        adapt.m={};Object.keys(mDef).forEach(k=>adapt.m[k]=Object.assign({},mDef[k],(s.adapt.m||{})[k]||{}));
      }
      if(s.backtest&&Array.isArray(s.backtest.rows)&&s.backtest.rows.length)backtest=s.backtest;
      nextId=s.nextId||(sites.length+1);
    }
    const h=JSON.parse(localStorage.getItem(LS_HAZ)||"null");
    if(h&&h.rows&&h.rows.length){ hazardGrid=h; buildGridsFromRows(h.rows); }
    const hm=JSON.parse(localStorage.getItem(LS_META)||"null");
    if(hm&&hm.data)hazardMeta=hm;
    const rpk=JSON.parse(localStorage.getItem(LS_PACK)||"null");
    if(rpk&&rpk.data)resultsPack=rpk;
  }catch(e){}
}

/* ---- geocode (external; degrades quietly if blocked) ---- */
let geoTimer=null;
function geocode(q){
  fetch("https://nominatim.openstreetmap.org/search?format=json&limit=6&q="+encodeURIComponent(q),{headers:{"Accept-Language":"en"}})
    .then(r=>r.json()).then(list=>{
      const box=document.getElementById("geoResults");
      if(!Array.isArray(list)||!list.length){box.innerHTML='<div class="r"><small>No matches</small></div>';box.classList.add("open");return;}
      box.innerHTML=list.map(p=>'<div class="r" data-lat="'+esc(p.lat)+'" data-lon="'+esc(p.lon)+'">'+esc(p.display_name.split(",")[0])+' <small>'+esc(p.display_name.split(",").slice(1,3).join(","))+'</small></div>').join("");
      box.classList.add("open");
      box.querySelectorAll(".r[data-lat]").forEach(el=>el.onclick=()=>{openAdd(+el.dataset.lat,+el.dataset.lon,document.getElementById("geo").value.split(",")[0]);box.classList.remove("open");document.getElementById("geo").value="";});
    }).catch(()=>toast("Search is unavailable on this network. Add sites by CSV or map click."));
}

/* ---- add modal ---- */
function openAdd(lat,lon,name){
  document.getElementById("mLat").value=lat.toFixed(4);
  document.getElementById("mLon").value=lon.toFixed(4);
  document.getElementById("mName").value=name||"";
  document.getElementById("mBrand").value="";
  document.getElementById("mVal").value=30000000;
  document.getElementById("addModal").classList.add("open");
}
function closeAdd(){document.getElementById("addModal").classList.remove("open");}

/* ---- export ---- */
function exportCsv(){
  if(!sites.length){toast("Load a portfolio first.");return;}
  const src=hazardGrid?"climada_grid":"interim_model";
  const cols=["site_id","name","brand","latitude","longitude","asset_value_usd","annual_revenue_usd","construction","year_built","defended","scenario","hazard_source"]
    .concat(EXPORT_ACUTE_LEGACY.map(hz=>"ead_"+hz+"_usd"))
    .concat(["ead_physical_total_usd","ead_physical_pct"])
    .concat(EXPORT_ACUTE_LEGACY.map(hz=>"rating_"+hz)).concat(["rating_heat"])
    .concat(["heat_days_over_32","heat_days_over_35","heat_cdd",
    "direct_damage_aal_usd","business_interruption_aal_usd","heat_revenue_at_risk_usd","total_climate_aal_usd","total_aal_pct_revenue"])
    .concat(RPS.map(rp=>"loss_rp"+rp+"_physical_usd"))
    .concat(EXPORT_ACUTE_APPENDED.map(hz=>"ead_"+hz+"_usd"))
    .concat(EXPORT_ACUTE_APPENDED.map(hz=>"rating_"+hz))
    .concat(["grid_perils"]);
  const gridPerils=perilAuthority().filter(a=>a.live).length+"/"+HAZARDS.length;
  const g=(cur,rp)=>{const c=(cur||[]).find(x=>x.rp===rp);return c?c.loss:0;};
  let csv=cols.join(",")+"\n";
  sites.forEach(s=>{
    const hzr={};for(const hz of ACUTE.concat(["heat"]))hzr[hz]=hzSite(s,hz,scenario);
    const ht=hzr.heat;
    const physEad=ACUTE.reduce((a,hz)=>a+hzr[hz].ead,0), physPct=s.asset_value_usd?physEad/s.asset_value_usd*100:0;
    const fin=finSite(s,scenario);
    const rpLoss=RPS.map(rp=>ACUTE.reduce((a,hz)=>a+g(hzr[hz].curve,rp),0).toFixed(0));
    const row=[s.id,csvCell(s.name),csvCell(s.brand||""),s.latitude,s.longitude,s.asset_value_usd,fin.revenue.toFixed(0),
      s.construction||"",s.year_built||"",s.defended?"true":"",scenario,src]
      .concat(EXPORT_ACUTE_LEGACY.map(hz=>hzr[hz].ead.toFixed(0)))
      .concat([physEad.toFixed(0),physPct.toFixed(3)])
      .concat(EXPORT_ACUTE_LEGACY.map(hz=>hzr[hz].band)).concat([ht.band])
      .concat([ht.indicators.daysOver32,ht.indicators.daysOver35,ht.indicators.cdd,
      fin.directEad.toFixed(0),fin.biEad.toFixed(0),fin.heatCost.toFixed(0),fin.totalAal.toFixed(0),
      (fin.revenue?fin.totalAal/fin.revenue*100:0).toFixed(3)]).concat(rpLoss)
      .concat(EXPORT_ACUTE_APPENDED.map(hz=>hzr[hz].ead.toFixed(0)))
      .concat(EXPORT_ACUTE_APPENDED.map(hz=>hzr[hz].band))
      .concat([gridPerils]);
    csv+=row.join(",")+"\n";
  });
  const blob=new Blob(["\uFEFF"+csv],{type:"text/csv;charset=utf-8"});const a=document.createElement("a");
  a.href=URL.createObjectURL(blob);a.download="rtv_portfolio_multihazard_"+scenario+".csv";a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  toast("Exported "+sites.length+" rows (multi-hazard Power BI schema)");
}
function downloadTemplate(){
  // Required: name, latitude, longitude, asset_value_usd. Optional: brand, country.
  const csv=
    "name,brand,latitude,longitude,asset_value_usd,country,annual_revenue_usd,construction,year_built,defended,roof_type,roof_year,opening_protection,first_floor_elev_m,equipment_elevated,wui_class,defensible_space_m,roof_class_a\n"+
    "Example Beachfront Resort,Club Wyndham,27.9500,-82.4600,40000000,USA,14000000,masonry,2002,false,metal,2018,impact,1.2,true,,,\n"+
    "Example Inland Resort,WorldMark,29.4241,-98.4936,22000000,USA,,frame,2005,,shingle,2005,none,,,intermix,10,false\n"+
    "Example Island Resort,Margaritaville,18.3797,-65.8083,51000000,USA,18000000,engineered,2011,true,,,,,,,,\n";
  const blob=new Blob(["\uFEFF"+csv],{type:"text/csv;charset=utf-8"});const a=document.createElement("a");
  a.href=URL.createObjectURL(blob);a.download="rtv_site_template.csv";a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  toast("Template downloaded (rtv_site_template.csv)");
}

/* ---- tabs ---- */
function switchTab(name){
  document.querySelectorAll("nav.tabs button").forEach(b=>b.setAttribute("aria-selected",b.dataset.tab===name));
  document.querySelectorAll(".tabpane").forEach(p=>p.classList.toggle("active",p.id==="tab-"+name));
  if(name==="sites"&&map){setTimeout(()=>map.invalidateSize(),50);}
}

/* ============================================================
   Wire up
   ============================================================ */
function wire(){
  restore();
  initMap();
  wireInfo();
  document.querySelectorAll("nav.tabs button").forEach(b=>b.onclick=()=>switchTab(b.dataset.tab));
  // hazard + scenario controls
  const hazSel=document.getElementById("hazSel"),pathSel=document.getElementById("pathSel"),horSel=document.getElementById("horSel");
  function syncScenControls(){
    const parts=scenario==="present"?["present","2050"]:scenario.split("_");
    hazSel.value=activeHazard;
    pathSel.value=parts[0];
    horSel.value=parts[0]==="present"?horSel.value||"2050":parts[1];
    horSel.disabled=(pathSel.value==="present");
  }
  function composeScenario(){
    stopScrub();
    scenario=(pathSel.value==="present")?"present":(pathSel.value+"_"+horSel.value);
    horSel.disabled=(pathSel.value==="present");
    persist();render();
  }
  syncScenControls();
  scenHook=syncScenControls;   // lets the scenario scrubber keep the top bar in sync
  hazSel.onchange=e=>{activeHazard=e.target.value;persist();render();};
  pathSel.onchange=composeScenario;
  horSel.onchange=composeScenario;
  document.getElementById("sampleBtn").onclick=loadSample;
  document.getElementById("sampleBtn2").onclick=loadSample;
  document.getElementById("sampleBtn3").onclick=loadSample;
  document.getElementById("sampleBtn4").onclick=loadSample;
  document.getElementById("exportBtn").onclick=exportCsv;
  document.getElementById("briefBtn").onclick=openBrief;
  window.addEventListener("afterprint",()=>{document.body.classList.remove("printbrief");});
  document.getElementById("scrubPlay").onclick=playScrub;
  document.getElementById("brandSel").onchange=e=>{brandFilter=e.target.value;render();};
  document.getElementById("tmplBtn").onclick=downloadTemplate;
  document.getElementById("addSiteBtn").onclick=()=>openAdd(27.95,-82.46,"");
  // sort
  document.querySelectorAll("#siteTbl th[data-sort]").forEach(th=>th.onclick=e=>{
    if(e.target.closest(".info"))return;
    const k=th.dataset.sort;if(sortKey===k)sortDir*=-1;else{sortKey=k;sortDir=(k==="name"||k==="brand"||k==="band")?1:-1;}renderSites();
  });
  // geocode
  const geo=document.getElementById("geo");
  geo.oninput=()=>{clearTimeout(geoTimer);const q=geo.value.trim();if(q.length<3){document.getElementById("geoResults").classList.remove("open");return;}geoTimer=setTimeout(()=>geocode(q),400);};
  document.addEventListener("click",e=>{if(!e.target.closest(".searchwrap"))document.getElementById("geoResults").classList.remove("open");});
  // modal
  document.getElementById("mCancel").onclick=closeAdd;
  document.getElementById("addModal").addEventListener("click",e=>{if(e.target.id==="addModal")closeAdd();});
  document.getElementById("focusClose").onclick=closeScorecard;
  document.getElementById("focusBg").addEventListener("click",e=>{if(e.target.id==="focusBg")closeScorecard();});
  document.addEventListener("keydown",e=>{if(e.key==="Escape"){closeAdd();closeScorecard();}});
  document.getElementById("mAdd").onclick=()=>{
    const lat=toNum(document.getElementById("mLat").value),lon=toNum(document.getElementById("mLon").value),val=toNum(document.getElementById("mVal").value);
    if(!isFinite(lat)||!isFinite(lon)||!isFinite(val)||lat< -90||lat>90||lon< -180||lon>180||val<0){toast("Enter valid latitude (-90..90), longitude (-180..180), and a non-negative value.");return;}
    addSites([{name:(document.getElementById("mName").value||"New site").slice(0,120),brand:(document.getElementById("mBrand").value||"").slice(0,80),latitude:lat,longitude:lon,asset_value_usd:val}]);
    closeAdd();toast("Site added");
  };
  // adaptation controls (measure sliders are wired dynamically in renderAdaptation)
  document.getElementById("growth").value=adapt.growth;
  document.getElementById("load").value=adapt.load;
  document.getElementById("attachSel").value=adapt.attach;
  document.getElementById("exhaustSel").value=adapt.exhaust;
  ["horizon","disc","growth","load"].forEach(id=>document.getElementById(id).oninput=renderAdaptation);
  document.getElementById("attachSel").onchange=renderAdaptation;
  document.getElementById("exhaustSel").onchange=renderAdaptation;
  // finance assumption sliders
  const finInit={revRatio:Math.round(finAssume.revRatio*100),gop:Math.round(finAssume.gopMargin*100),reopen:finAssume.reopenMonths,heatDrop:Math.round(finAssume.heatDrop*100),corr:Math.round(finAssume.corr*100)};
  Object.keys(finInit).forEach(id=>{const el=document.getElementById(id);if(el){el.value=finInit[id];el.oninput=syncFinAssume;}});
  syncFinAssume();
  // hazard drop: grid CSV(s) + JSON sidecar(s), loaded as one batch so multiple
  // CSVs merge instead of the last one silently replacing the rest
  const hd=document.getElementById("hazDrop"),hf=document.getElementById("hazFile");
  hd.onclick=()=>hf.click();
  hf.onchange=()=>{ routeHazFiles(hf.files); hf.value=""; };
  dropZoneMulti(hd,routeHazFiles);
  // site drop
  const sd=document.getElementById("siteDrop"),sf=document.getElementById("siteFile");
  sd.onclick=()=>sf.click();sf.onchange=()=>{if(sf.files[0])readFile(sf.files[0],loadSiteCsv);};
  dropZone(sd,f=>readFile(f,loadSiteCsv));
  // backtest drop
  const bd=document.getElementById("btDrop"),bf=document.getElementById("btFile");
  bd.onclick=()=>bf.click();bf.onchange=()=>{if(bf.files[0])readFile(bf.files[0],loadBacktestCsv);};
  dropZone(bd,f=>readFile(f,loadBacktestCsv));
  render();
}
function dropZone(el,cb){
  el.addEventListener("dragover",e=>{e.preventDefault();el.classList.add("over");});
  el.addEventListener("dragleave",()=>el.classList.remove("over"));
  el.addEventListener("drop",e=>{e.preventDefault();el.classList.remove("over");for(const f of e.dataTransfer.files)cb(f);});
}
/* like dropZone but hands the whole FileList to the callback in one call, so a
   multi-file drop is loaded as a batch (see routeHazFiles) */
function dropZoneMulti(el,cb){
  el.addEventListener("dragover",e=>{e.preventDefault();el.classList.add("over");});
  el.addEventListener("dragleave",()=>el.classList.remove("over"));
  el.addEventListener("drop",e=>{e.preventDefault();el.classList.remove("over");cb(e.dataTransfer.files);});
}
window.addEventListener("DOMContentLoaded",wire);
