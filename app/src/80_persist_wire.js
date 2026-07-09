const LS_STATE="rtv_state_v1", LS_HAZ="rtv_hazard_v1", LS_META="rtv_hazmeta_v1", LS_PACK="rtv_respack_v1";
const LS_LOSSRUN="rtv_lossrun_v1", LS_TCOR="rtv_tcor_v1";
/* Power BI export contract (Phase C): the column ORDER is frozen. The three
   legacy perils sit mid-row where they always were; later perils append at
   the tail, never reorder. A test asserts these two lists partition ACUTE. */
const EXPORT_ACUTE_LEGACY=["tc","cflood","rflood"];
const EXPORT_ACUTE_APPENDED=["prain","wfire"];
function persist(){ try{ localStorage.setItem(LS_STATE,JSON.stringify({sites,scenario,activeHazard,finAssume,adapt,backtest,nextId,tolerance,ui})); }catch(e){} }
function persistHazard(){ try{ localStorage.setItem(LS_HAZ,JSON.stringify(hazardGrid)); }catch(e){ /* grid too large to cache: fine, keeps working in-session */ } }
function persistMeta(){ try{ localStorage.setItem(LS_META,JSON.stringify(hazardMeta)); }catch(e){} }
function persistPack(){ try{ localStorage.setItem(LS_PACK,JSON.stringify(resultsPack)); }catch(e){} }
function persistLossRun(){ try{ localStorage.setItem(LS_LOSSRUN,JSON.stringify(lossRun)); }catch(e){ /* a very large loss run may exceed quota: keeps working in-session */ } }
function persistTcorProgram(){ try{ localStorage.setItem(LS_TCOR,JSON.stringify(tcorProgram)); }catch(e){} }
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
      if(s.tolerance&&typeof s.tolerance==="object")tolerance=Object.assign({},tolerance,s.tolerance);
      if(s.ui&&typeof s.ui==="object"){
        ui=Object.assign({},ui,s.ui);
        ui.views=Object.assign({},ui.views,s.ui.views||{});
        if(!ui.views.scrubPathway)ui.views.scrubPathway="ssp245";
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
    const lr=JSON.parse(localStorage.getItem(LS_LOSSRUN)||"null");
    if(lr&&Array.isArray(lr.claims)&&lr.claims.length)lossRun=lr;
    const tp=JSON.parse(localStorage.getItem(LS_TCOR)||"null");
    if(tp&&typeof tp==="object"){
      tcorProgram=Object.assign({},tcorProgram,tp);
      /* nested blocks merge over defaults so a new field ships with its
         documented default even against an older saved program */
      ["deductibles","perilClass","bi","premium","indirect"].forEach(k=>{
        if(tp[k]&&typeof tp[k]==="object")tcorProgram[k]=Object.assign({},tcorProgram[k],tp[k]);
      });
    }
  }catch(e){}
}

/* ---- geocode (external; degrades quietly if blocked). geocodeInto is shared by
   the top-bar search and the in-form search so both use one code path. ---- */
let geoTimer=null, mGeoTimer=null;
function geocodeInto(q,box,onPick){
  fetch("https://nominatim.openstreetmap.org/search?format=json&limit=6&q="+encodeURIComponent(q),{headers:{"Accept-Language":"en"}})
    .then(r=>r.json()).then(list=>{
      if(!Array.isArray(list)||!list.length){box.innerHTML='<div class="r"><small>No matches</small></div>';box.classList.add("open");return;}
      box.innerHTML=list.map(p=>'<div class="r" data-lat="'+esc(p.lat)+'" data-lon="'+esc(p.lon)+'" data-name="'+esc(p.display_name.split(",")[0])+'">'+esc(p.display_name.split(",")[0])+' <small>'+esc(p.display_name.split(",").slice(1,3).join(","))+'</small></div>').join("");
      box.classList.add("open");
      box.querySelectorAll(".r[data-lat]").forEach(el=>el.onclick=()=>{onPick(+el.dataset.lat,+el.dataset.lon,el.dataset.name);box.classList.remove("open");});
    }).catch(()=>toast("Search is unavailable on this network. Add sites by CSV or map click."));
}
function geocode(q){ geocodeInto(q,document.getElementById("geoResults"),(lat,lon,name)=>{document.getElementById("geo").value="";openForm("add",{latitude:lat,longitude:lon,name:name});}); }

/* ---- add / edit site form (SVP review) ---- */
let _editId=null,_formReturn=null;
function openForm(mode,site){
  const g=id=>document.getElementById(id), s=site||{};
  const bl=g("brandList"); if(bl){const bs=[];sites.forEach(x=>{const b=x.brand;if(b&&bs.indexOf(b)<0)bs.push(b);});bl.innerHTML=bs.sort().map(b=>'<option value="'+esc(b)+'"></option>').join("");}
  const set=(id,v)=>{g(id).value=(v==null||(typeof v==="number"&&!isFinite(v)))?"":v;};
  g("formTitle").textContent=(mode==="edit")?"Edit site":"Add a site";
  g("mAdd").textContent=(mode==="edit")?"Save changes":"Add site";
  set("mName",s.name); g("mBrand").value=s.brand||"";
  set("mLat",(s.latitude!=null&&isFinite(+s.latitude))?(+s.latitude).toFixed(4):"");
  set("mLon",(s.longitude!=null&&isFinite(+s.longitude))?(+s.longitude).toFixed(4):"");
  set("mVal",s.asset_value_usd); set("mRev",s.annual_revenue_usd);
  g("mConstr").value=s.construction||""; set("mYear",s.year_built);
  g("mDefended").checked=!!s.defended;
  g("mRoofType").value=s.roof_type||""; set("mRoofYear",s.roof_year);
  g("mOpening").value=s.opening_protection||""; set("mFfe",s.first_floor_elev_m);
  g("mEquipElev").checked=!!s.equipment_elevated;
  g("mWui").value=s.wui_class||""; set("mDefSpace",s.defensible_space_m);
  g("mArch").value=s.archetype||"";
  set("mGround",s.ground_elev_m); set("mCellGround",s.cell_ground_elev_m);
  g("mNamedInsured").value=s.named_insured||""; g("mSiteId").value=s.site_id||""; g("mSiteName").value=s.site_name||"";
  g("mGeo").value=""; g("mGeoResults").classList.remove("open");
  /* v3.1 UX: sections open themselves when they carry data (editing), and
     stay collapsed on a fresh add so the four required fields lead. Any
     stale validation state from a previous visit is cleared. */
  const more=g("mMoreWrap"),adv=g("mAdvWrap");
  if(more)more.open=!!(s.brand||s.named_insured||s.site_id||s.site_name||s.annual_revenue_usd!=null||s.construction||s.year_built||s.defended);
  if(adv)adv.open=!!(s.roof_type||s.roof_year||s.opening_protection||s.first_floor_elev_m!=null||s.equipment_elevated||s.wui_class||s.defensible_space_m!=null||s.archetype||s.ground_elev_m!=null||s.cell_ground_elev_m!=null);
  clearFormErrors();
  _editId=(mode==="edit"&&s.id!=null)?s.id:null;
  try{_formReturn=document.activeElement;}catch(e){_formReturn=null;}
  g("addModal").classList.add("open");
  const nm=g("mName"); if(nm&&nm.focus)try{nm.focus();}catch(e){}
}
function openAdd(lat,lon,name){ openForm("add",{latitude:lat,longitude:lon,name:name}); }   // back-compat shim (map click)
function closeAdd(){
  document.getElementById("addModal").classList.remove("open");_editId=null;
  if(_formReturn&&_formReturn.focus)try{_formReturn.focus();}catch(e){}
  _formReturn=null;
}
/* v3.1 UX: inline validation for the form's required fields. Each invalid
   field is outlined and named in one message beside the buttons; the state
   clears as the user types. The engine-level guard (siteRecordFromFields)
   stays the source of truth and is unchanged. */
const FORM_REQUIRED=["mName","mLat","mLon","mVal"];
function clearFormErrors(){
  const g=id=>document.getElementById(id);
  FORM_REQUIRED.forEach(id=>{const el=g(id);if(el&&el.classList)el.classList.remove("invalid");});
  const eb=g("mErr"); if(eb){eb.style.display="none";eb.textContent="";}
}
function validateForm(){
  const g=id=>document.getElementById(id);
  const errs=[];
  const mark=(id,bad)=>{const el=g(id);if(el&&el.classList){if(bad)el.classList.add("invalid");else el.classList.remove("invalid");}
    if(el&&el.setAttribute)el.setAttribute("aria-invalid",bad?"true":"false");};
  const name=String(g("mName").value||"").trim(); mark("mName",!name); if(!name)errs.push("a site name");
  const lat=parseFloat(g("mLat").value); const latBad=!isFinite(lat)||lat<-90||lat>90; mark("mLat",latBad); if(latBad)errs.push("a latitude between -90 and 90");
  const lon=parseFloat(g("mLon").value); const lonBad=!isFinite(lon)||lon<-180||lon>180; mark("mLon",lonBad); if(lonBad)errs.push("a longitude between -180 and 180");
  const val=parseFloat(g("mVal").value); const valBad=!isFinite(val)||val<0; mark("mVal",valBad); if(valBad)errs.push("a non-negative asset value");
  const eb=g("mErr");
  if(eb){
    if(errs.length){eb.textContent="Still needed: "+errs.join(", ")+".";eb.style.display="";}
    else{eb.style.display="none";eb.textContent="";}
  }
  return !errs.length;
}
function submitForm(){
  const g=id=>document.getElementById(id);
  if(!validateForm())return;
  const raw={name:g("mName").value,brand:g("mBrand").value,latitude:g("mLat").value,longitude:g("mLon").value,
    asset_value_usd:g("mVal").value,annual_revenue_usd:g("mRev").value,construction:g("mConstr").value,
    year_built:g("mYear").value,defended:g("mDefended").checked,roof_type:g("mRoofType").value,
    roof_year:g("mRoofYear").value,opening_protection:g("mOpening").value,first_floor_elev_m:g("mFfe").value,
    equipment_elevated:g("mEquipElev").checked,wui_class:g("mWui").value,defensible_space_m:g("mDefSpace").value,
    archetype:g("mArch").value,
    ground_elev_m:g("mGround").value,cell_ground_elev_m:g("mCellGround").value,
    named_insured:g("mNamedInsured").value,site_id:g("mSiteId").value,site_name:g("mSiteName").value};
  const rec=siteRecordFromFields(raw);
  if(!rec){toast("Enter a valid location (latitude -90..90, longitude -180..180) and a non-negative asset value.");return;}
  if(_editId!=null){
    const s=sites.find(x=>x.id===_editId);
    if(s){FORM_OPTIONAL_FIELDS.forEach(k=>delete s[k]);Object.assign(s,rec);clearHazCache();persist();render();toast("Site updated");}
  }else{
    if(!ui.portfolioSource)ui.portfolioSource="manual";
    clearHazCache();addSites([rec]);toast("Site added");
  }
  closeAdd();
}

/* ---- first-run orientation (SVP review) ---- */
function closeOnboard(seen){ document.getElementById("onboardModal").classList.remove("open"); if(seen){ui.onboarded=true;persist();} }
function openOnboard(){
  const b=document.getElementById("obStart"); if(!b)return;
  if(sites.length){ b.textContent="Got it"; b.onclick=()=>closeOnboard(true); }
  else { b.textContent="Load the sample and explore"; b.onclick=()=>{closeOnboard(true);loadSample();}; }
  document.getElementById("onboardModal").classList.add("open");
}
function maybeOnboard(){ if(!ui.onboarded)openOnboard(); }

/* ---- executive / simple view (SVP review): hides the specialist panels via a
   body class, exactly like body.printbrief. Never touches a number, and never
   hides the trust surface (hazard source, provenance, drop zones, badge). ---- */
function applySimpleView(){
  document.body.classList.toggle("execview", !!ui.simpleView);
}

/* ---- v2.4.0 display options: theme, density, detail level, Summary panels.
   Pure presentation over persisted ui keys; never touches a computed figure.
   Charts read CSS variables, so a theme change needs no re-render. Every
   function guards for the node test stubs and is only invoked from wire()
   or a user action. ---- */
function applyTheme(){
  try{
    const de=document.documentElement; if(!de||!de.setAttribute)return;
    let t=ui.theme||"auto";
    if(t==="auto")t=(typeof window!=="undefined"&&window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches)?"dark":"light";
    if(t==="dark")de.setAttribute("data-theme","dark"); else de.removeAttribute("data-theme");
  }catch(e){}
}
function applyDensity(){
  try{ document.body.classList.toggle("compact",(ui.density||"comfortable")==="compact"); }catch(e){}
}
/* v3.1 UX: display controls live in their own small modal (opened from the
   Portfolio menu), so the menu itself stays a short list of actions. */
function closeDisplayMenu(){
  const m=document.getElementById("displayModal");
  if(m&&m.classList)m.classList.remove("open");
}
function closePortfolioMenu(){
  const m=document.getElementById("portfolioMenu"),b=document.getElementById("portfolioBtn");
  if(m&&m.classList)m.classList.remove("open");
  if(b&&b.setAttribute)b.setAttribute("aria-expanded","false");
}
function syncDisplayMenu(){
  const m=document.getElementById("displayModal"); if(!m||!m.querySelectorAll)return;
  m.querySelectorAll("[data-set-theme]").forEach(b=>b.setAttribute("aria-pressed",(ui.theme||"auto")===b.dataset.setTheme?"true":"false"));
  m.querySelectorAll("[data-set-density]").forEach(b=>b.setAttribute("aria-pressed",(ui.density||"comfortable")===b.dataset.setDensity?"true":"false"));
  const det=ui.simpleView?"essentials":"full";
  m.querySelectorAll("[data-set-detail]").forEach(b=>b.setAttribute("aria-pressed",det===b.dataset.setDetail?"true":"false"));
  const host=document.getElementById("dmPanels");
  if(host){
    host.innerHTML=SUMMARY_PANELS.map(x=>'<label><input type="checkbox" data-panel-key="'+x.key+'"'+
      (((ui.panels||{})[x.key]===false)?'':' checked')+'> '+esc(x.label)+'</label>').join("");
    host.querySelectorAll("input[data-panel-key]").forEach(cb=>cb.onchange=()=>{
      if(!ui.panels)ui.panels={};
      ui.panels[cb.dataset.panelKey]=cb.checked?true:false;
      persist();applyPanelPrefs();
    });
  }
}

/* ---- export ---- */
function exportCsv(){
  if(!sites.length){toast("Load a portfolio first.");return;}
  /* hazard_source is resolved PER SITE: "climada_grid" only when every peril's
     grid actually reached that site; a site outside some peril's coverage is
     labeled degraded with its modeled count, so a row can never claim grid
     backing it did not receive. Column set unchanged (frozen contract). */
  const src=s=>{if(!hazardGrid)return "interim_model";
    const t=siteTrustSummary(s,scenario);
    return t.modeled===t.total?"climada_grid":"climada_grid_degraded_"+t.modeled+"of"+t.total;};
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
      s.construction||"",s.year_built||"",s.defended?"true":"",scenario,src(s)]
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
/* Wave 1 R2/R3: new artifacts get NEW files. The Power BI export above is a
   frozen contract and never changes; these two exports carry the decision
   layer's outputs on their own schemas, documented on the Method tab. */
function exportBrokerPack(){
  if(!sites.length){toast("Load a portfolio first.");return;}
  const csv=brokerPackCsv();
  const blob=new Blob(["\uFEFF"+csv],{type:"text/csv;charset=utf-8"});const a=document.createElement("a");
  a.href=URL.createObjectURL(blob);a.download="rtv_broker_evidence_"+new Date().toISOString().slice(0,10)+".csv";a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  toast("Broker evidence pack exported ("+sites.length+" sites)");
}
function exportActionList(){
  if(!sites.length){toast("Load a portfolio first.");return;}
  const hv=document.getElementById("horizon").value, dv=document.getElementById("disc").value;
  const csv=actionListCsv(scenario,hv===""?APPRAISAL_DEFAULTS.horizonYears:+hv,
                          dv===""?APPRAISAL_DEFAULTS.discountPct:+dv);
  const blob=new Blob(["\uFEFF"+csv],{type:"text/csv;charset=utf-8"});const a=document.createElement("a");
  a.href=URL.createObjectURL(blob);a.download="rtv_action_list_"+scenario+"_"+new Date().toISOString().slice(0,10)+".csv";a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  toast("Action list exported (live model"+(resultsPack?" + canonical pack plan":"")+")");
}
function downloadTemplate(){
  // Required: name, latitude, longitude, asset_value_usd. Optional: brand, country.
  // The first two rows share a site_id (CAMPUS-BEACH), so they aggregate into a
  // single site on the map with an HOA / operating-company named-insured breakout.
  const csv=
    "name,brand,latitude,longitude,asset_value_usd,country,annual_revenue_usd,construction,year_built,defended,roof_type,roof_year,opening_protection,first_floor_elev_m,equipment_elevated,wui_class,defensible_space_m,roof_class_a,archetype,ground_elev_m,cell_ground_elev_m,named_insured,site_id,site_name\n"+
    "Example Beachfront Resort,Coastal Collection,27.9500,-82.4600,40000000,USA,14000000,masonry,2002,false,metal,2018,impact,1.2,true,,,,beachfront_lowrise,2.6,1.6,HOA,CAMPUS-BEACH,Example Beachfront Resort\n"+
    "Example Beachfront Resort,Coastal Collection,27.9500,-82.4600,12000000,USA,,masonry,2002,false,metal,2018,impact,1.2,true,,,,tower_concrete,2.6,1.6,Operating company,CAMPUS-BEACH,Example Beachfront Resort\n"+
    "Example Inland Resort,Heritage Stays,29.4241,-98.4936,22000000,USA,,frame,2005,,shingle,2005,none,,,intermix,10,false,lowrise_timber,,,,,\n"+
    "Example Island Resort,Island Collection,18.3797,-65.8083,51000000,USA,18000000,engineered,2011,true,,,,,,,,,,,,,,\n";
  const blob=new Blob(["\uFEFF"+csv],{type:"text/csv;charset=utf-8"});const a=document.createElement("a");
  a.href=URL.createObjectURL(blob);a.download="rtv_site_template.csv";a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  toast("Template downloaded (rtv_site_template.csv)");
}

/* ---- tabs ---- */
function switchTab(name){
  activeTab=name;
  document.querySelectorAll("nav.tabs button").forEach(b=>{
    const on=b.dataset.tab===name;
    b.setAttribute("aria-selected",on);
    b.tabIndex=on?0:-1;              // roving tabindex; arrow keys move between tabs
  });
  document.querySelectorAll(".tabpane").forEach(p=>p.classList.toggle("active",p.id==="tab-"+name));
  if(name==="sites"&&map){setTimeout(()=>map.invalidateSize(),50);}
  if(typeof updateLegend==="function")updateLegend();
}

/* ============================================================
   Wire up
   ============================================================ */
function wire(){
  restore();
  ensurePanelDefaults();
  initMap();
  wireInfo();
  const tabBtns=Array.from(document.querySelectorAll("nav.tabs button"));
  tabBtns.forEach((b,i)=>{
    b.onclick=()=>switchTab(b.dataset.tab);
    // arrow keys walk the tablist (WAI-ARIA tabs pattern); Home/End jump
    b.addEventListener("keydown",e=>{
      let j=null;
      if(e.key==="ArrowRight")j=(i+1)%tabBtns.length;
      else if(e.key==="ArrowLeft")j=(i-1+tabBtns.length)%tabBtns.length;
      else if(e.key==="Home")j=0;
      else if(e.key==="End")j=tabBtns.length-1;
      if(j!=null){e.preventDefault();switchTab(tabBtns[j].dataset.tab);tabBtns[j].focus();}
    });
  });
  // hazard + scenario controls
  const hazSel=document.getElementById("hazSel"),pathSel=document.getElementById("pathSel"),horSel=document.getElementById("horSel");
  const horSeg=document.getElementById("horSeg");
  function syncScenControls(){
    const parts=scenario==="present"?["present","2050"]:scenario.split("_");
    hazSel.value=activeHazard;
    pathSel.value=parts[0];
    horSel.value=parts[0]==="present"?horSel.value||"2050":parts[1];
    horSel.disabled=(pathSel.value==="present");
    // the horizon only applies to future pathways; hide it on Present day
    if(horSeg)horSeg.style.display=(pathSel.value==="present")?"none":"";
  }
  function composeScenario(){
    stopScrub();
    scenario=(pathSel.value==="present")?"present":(pathSel.value+"_"+(horSel.value||"2050"));
    horSel.disabled=(pathSel.value==="present");
    if(horSeg)horSeg.style.display=(pathSel.value==="present")?"none":"";
    persist();render();
  }
  syncScenControls();
  scenHook=syncScenControls;   // lets the scenario scrubber keep the top bar in sync
  hazSel.onchange=e=>{activeHazard=e.target.value;persist();render();};
  pathSel.onchange=composeScenario;
  horSel.onchange=composeScenario;
  document.getElementById("sampleBtn").onclick=loadSample;
  document.getElementById("exportBtn").onclick=exportCsv;
  /* v3: the board brief is the TCOR one-pager; the pre-TCOR analytical
     brief stays available as the legacy item (nothing deleted) */
  document.getElementById("briefBtn").onclick=(typeof openTcorBrief==="function")?openTcorBrief:openBrief;
  const blb=document.getElementById("briefLegacyBtn");
  if(blb)blb.onclick=openBrief;
  window.addEventListener("afterprint",()=>{document.body.classList.remove("printbrief");});
  const dcb=document.getElementById("decisionCompactBtn");
  if(dcb)dcb.onclick=()=>{ui.decisionCompact=!decisionCompactOn();persist();renderDecision();};
  window.addEventListener("resize",()=>{if(typeof syncDecisionScroll==="function")syncDecisionScroll();});
  // brand filter persists like every other view preference
  brandFilter=(ui.views&&ui.views.brand)||"";
  document.getElementById("brandSel").onchange=e=>{brandFilter=e.target.value;ui.views.brand=brandFilter;persist();render();};
  // SVP review: risk-matrix view lenses (regroup / re-measure; matrix only)
  const mtxG=document.getElementById("mtxGroup"),mtxM=document.getElementById("mtxMetric");
  if(mtxG)mtxG.onchange=e=>{ui.views.matrixGroup=e.target.value;persist();renderRiskMatrix();};
  if(mtxM)mtxM.onchange=e=>{ui.views.matrixMetric=e.target.value;persist();renderRiskMatrix();};
  const mcSel=document.getElementById("mapColorSel");
  if(mcSel){mcSel.value=["peril","combined","dominant"].indexOf(ui.views.mapColor)>=0?ui.views.mapColor:"peril";
    mcSel.onchange=e=>{ui.views.mapColor=e.target.value;persist();render();};}
  document.getElementById("tmplBtn").onclick=downloadTemplate;
  document.getElementById("addSiteBtn").onclick=()=>openForm("add",{});
  // sort
  document.querySelectorAll("#siteTbl th[data-sort]").forEach(th=>th.onclick=e=>{
    if(e.target.closest(".info"))return;
    const k=th.dataset.sort;if(sortKey===k)sortDir*=-1;else{sortKey=k;sortDir=(k==="name"||k==="brand"||k==="band")?1:-1;}renderSites();
  });
  // geocode
  const geo=document.getElementById("geo");
  geo.oninput=()=>{clearTimeout(geoTimer);const q=geo.value.trim();if(q.length<3){document.getElementById("geoResults").classList.remove("open");return;}geoTimer=setTimeout(()=>geocode(q),400);};
  document.addEventListener("click",e=>{if(!e.target.closest(".searchwrap")){document.getElementById("geoResults").classList.remove("open");document.getElementById("mGeoResults").classList.remove("open");}});
  // in-form place search (fills the coordinate fields; keeps its own results box)
  const mGeo=document.getElementById("mGeo");
  if(mGeo)mGeo.oninput=()=>{clearTimeout(mGeoTimer);const q=mGeo.value.trim();if(q.length<3){document.getElementById("mGeoResults").classList.remove("open");return;}
    mGeoTimer=setTimeout(()=>geocodeInto(q,document.getElementById("mGeoResults"),(lat,lon,name)=>{
      document.getElementById("mLat").value=lat.toFixed(4);document.getElementById("mLon").value=lon.toFixed(4);
      if(!document.getElementById("mName").value)document.getElementById("mName").value=name||"";mGeo.value="";}),400);};
  // modal
  document.getElementById("mCancel").onclick=closeAdd;
  document.getElementById("addModal").addEventListener("click",e=>{if(e.target.id==="addModal")closeAdd();});
  document.getElementById("mAdd").onclick=submitForm;
  // required fields clear their invalid outline as soon as the user types
  FORM_REQUIRED.forEach(id=>{const el=document.getElementById(id);
    if(el)el.addEventListener("input",()=>{if(el.classList)el.classList.remove("invalid");if(el.setAttribute)el.setAttribute("aria-invalid","false");});});
  document.getElementById("focusClose").onclick=closeScorecard;
  const fe=document.getElementById("focusEdit");
  if(fe)fe.onclick=()=>{const s=sites.find(x=>x.id===_scorecardId);if(s){closeScorecard();openForm("edit",s);}};
  document.getElementById("focusBg").addEventListener("click",e=>{if(e.target.id==="focusBg")closeScorecard();});
  document.addEventListener("keydown",e=>{if(e.key==="Escape"){closeAdd();closeScorecard();closeOnboard(true);closeExportMenu();closeDisplayMenu();closePortfolioMenu();
    if(typeof closeSiteView==="function")closeSiteView();
    ["cmdExportMenu","svExportMenu"].forEach(id=>{const m=document.getElementById(id);if(m&&m.classList)m.classList.remove("open");});}});
  // keep Tab inside whichever modal is open (simple focus trap)
  document.addEventListener("keydown",e=>{
    if(e.key!=="Tab")return;
    const open=document.querySelector(".modal-bg.open"); if(!open)return;
    const f=Array.from(open.querySelectorAll('button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])'))
      .filter(el=>!el.disabled&&el.offsetParent!==null);
    if(!f.length)return;
    const first=f[0],last=f[f.length-1];
    if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
    else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
  });
  // display options: theme, density, detail level, Summary panels
  applySimpleView();applyTheme();applyDensity();syncDisplayMenu();
  const pBtn=document.getElementById("portfolioBtn"),pMenu=document.getElementById("portfolioMenu");
  if(pBtn&&pMenu){
    pBtn.onclick=e=>{e.stopPropagation();closeExportMenu();
      const open=!pMenu.classList.contains("open");
      pMenu.classList.toggle("open",open);pBtn.setAttribute("aria-expanded",open?"true":"false");};
    pMenu.addEventListener("click",e=>e.stopPropagation());
    pMenu.querySelectorAll(".mi").forEach(b=>b.addEventListener("click",closePortfolioMenu));
  }
  const dModal=document.getElementById("displayModal");
  if(dModal){
    dModal.querySelectorAll("[data-set-theme]").forEach(b=>b.onclick=()=>{ui.theme=b.dataset.setTheme;persist();applyTheme();syncDisplayMenu();});
    dModal.querySelectorAll("[data-set-density]").forEach(b=>b.onclick=()=>{ui.density=b.dataset.setDensity;persist();applyDensity();syncDisplayMenu();});
    dModal.querySelectorAll("[data-set-detail]").forEach(b=>b.onclick=()=>{ui.simpleView=(b.dataset.setDetail==="essentials");persist();applySimpleView();syncDisplayMenu();});
    dModal.addEventListener("click",e=>{if(e.target.id==="displayModal")closeDisplayMenu();});
    const dClose=document.getElementById("displayClose");
    if(dClose)dClose.onclick=closeDisplayMenu;
  }
  const dsBtn=document.getElementById("displaySettingsBtn");
  if(dsBtn)dsBtn.onclick=()=>{closePortfolioMenu();syncDisplayMenu();if(dModal&&dModal.classList)dModal.classList.add("open");};
  const pMethod=document.getElementById("portfolioMethodBtn");
  if(pMethod)pMethod.onclick=()=>{setAdvancedMode(true);switchTab("method");};
  const pTmpl=document.getElementById("portfolioTmplBtn");
  if(pTmpl)pTmpl.onclick=downloadTemplate;
  const pGuide=document.getElementById("portfolioGuideBtn");
  if(pGuide)pGuide.onclick=()=>{closePortfolioMenu();openOnboard();};
  try{ if(window.matchMedia)window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change",()=>{if((ui.theme||"auto")==="auto")applyTheme();}); }catch(e){}
  const advBtn=document.getElementById("advancedBtn");
  if(advBtn)advBtn.onclick=()=>setAdvancedMode(!(ui&&ui.advanced));
  const cmdSample=document.getElementById("cmdSampleBtn");
  if(cmdSample)cmdSample.onclick=loadSample;
  const cmdAdv=document.getElementById("cmdAdvancedBtn");
  if(cmdAdv)cmdAdv.onclick=()=>setAdvancedMode(true);
  const emBtn=document.getElementById("exportMenuBtn"),emBox=document.getElementById("exportMenu");
  emBtn.onclick=e=>{e.stopPropagation();closeDisplayMenu();closePortfolioMenu();const open=!emBox.classList.contains("open");
    emBox.classList.toggle("open",open);emBtn.setAttribute("aria-expanded",open?"true":"false");};
  document.addEventListener("click",e=>{if(!e.target.closest(".exportwrap")){closeExportMenu();closeDisplayMenu();closePortfolioMenu();
    ["cmdExportMenu","svExportMenu"].forEach(id=>{const m=document.getElementById(id);if(m&&m.classList)m.classList.remove("open");});}});
  emBox.querySelectorAll(".mi").forEach(b=>b.addEventListener("click",closeExportMenu));
  document.getElementById("menuBrokerBtn").onclick=exportBrokerPack;
  document.getElementById("menuActionBtn").onclick=exportActionList;
  applyAdvancedMode();
  // first-run orientation
  document.getElementById("obGlossary").onclick=()=>{closeOnboard(true);setAdvancedMode(true);switchTab("method");};
  document.getElementById("onboardModal").addEventListener("click",e=>{if(e.target.id==="onboardModal")closeOnboard(true);});
  // adaptation controls (measure sliders are wired dynamically in renderAdaptation)
  document.getElementById("growth").value=adapt.growth;
  document.getElementById("load").value=adapt.load;
  document.getElementById("attachSel").value=adapt.attach;
  document.getElementById("exhaustSel").value=adapt.exhaust;
  ["horizon","disc","growth","load"].forEach(id=>document.getElementById(id).oninput=renderAdaptation);
  document.getElementById("attachSel").onchange=renderAdaptation;
  document.getElementById("exhaustSel").onchange=renderAdaptation;
  // Wave 1 decision layer: quote, budget, and the two new export artifacts
  document.getElementById("quoteIn").value=adapt.quote||"";
  document.getElementById("budgetIn").value=adapt.budget||"";
  document.getElementById("quoteIn").oninput=()=>{persist();renderAdaptation();};
  document.getElementById("budgetIn").oninput=()=>{persist();renderAdaptation();};
  document.getElementById("brokerBtn").onclick=exportBrokerPack;
  document.getElementById("actionBtn").onclick=exportActionList;
  // finance assumption sliders
  const finInit={revRatio:Math.round(finAssume.revRatio*100),gop:Math.round(finAssume.gopMargin*100),reopen:finAssume.reopenMonths,heatDrop:Math.round(finAssume.heatDrop*100),corr:Math.round(finAssume.corr*100)};
  Object.keys(finInit).forEach(id=>{const el=document.getElementById(id);if(el){el.value=finInit[id];el.oninput=syncFinAssume;}});
  syncFinAssume();
  // hazard drop: grid CSV(s) + JSON sidecar(s), loaded as one batch so multiple
  // CSVs merge instead of the last one silently replacing the rest.
  // v3.1 UX: step 2 is gated until step 1 (a portfolio) is loaded, so new
  // users cannot mis-sequence the walkthrough; the loaders are untouched.
  const hd=document.getElementById("hazDrop"),hf=document.getElementById("hazFile");
  const hazGateBlocked=()=>{
    if(sites.length)return false;
    toast("Load your sites first (step 1). Use the sample portfolio or drop your site CSV, then load climate data.");
    return true;
  };
  hd.onclick=()=>{ if(hazGateBlocked())return; hf.click(); };
  hf.onchange=()=>{ routeHazFiles(hf.files); hf.value=""; };
  dropZoneMulti(hd,files=>{ if(hazGateBlocked())return; routeHazFiles(files); });
  const msb=document.getElementById("methodSampleBtn");
  if(msb)msb.onclick=loadSample;
  // site drop
  const sd=document.getElementById("siteDrop"),sf=document.getElementById("siteFile");
  sd.onclick=()=>sf.click();sf.onchange=()=>{if(sf.files[0])readFile(sf.files[0],loadSiteCsv);};
  dropZone(sd,f=>readFile(f,loadSiteCsv));
  // backtest drop
  const bd=document.getElementById("btDrop"),bf=document.getElementById("btFile");
  bd.onclick=()=>bf.click();bf.onchange=()=>{if(bf.files[0])readFile(bf.files[0],loadBacktestCsv);};
  dropZone(bd,f=>readFile(f,loadBacktestCsv));
  render();
  maybeOnboard();
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
