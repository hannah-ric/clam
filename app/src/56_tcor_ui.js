/* ============================================================
   v3 command surface (front-end overhaul, Surfaces 1 + 2).

   SURFACE 1 (renderCommand): the default screen. Portfolio TCOR for
   the selected scenario/horizon with its five-component split as one
   compact stacked bar, expected-year vs bad-year side by side, a
   portfolio confidence indicator, the climate map, and the ranked
   decision list, under ONE global scenario control and a
   renewal/capital framing toggle.

   SURFACE 2 (renderSiteView): the site view, organized entirely by
   TCOR. The signature visual is the animated waterfall: gross modeled
   loss, minus the transferred portion that goes to the insurer,
   leaving retained property, plus retained BI, plus allocated premium,
   arriving at TCOR. Every segment is hoverable to its derivation.

   READ-ONLY over the TCOR engine (22_tcor.js): every figure comes
   from tcorPortfolio / tcorSite / simulateRetainedYears /
   lossrunCalibration / the adaptation appraisal, or is plain
   arithmetic on their outputs. Nothing here re-derives or alters the
   financial science; where a needed output does not exist yet (the
   full BI bad-year module, the TCOR-aware premium credit), the
   surface says so instead of inventing it.
   ============================================================ */

/* The five TCOR components: one fixed palette, one fixed order, used
   identically everywhere the components appear (validated categorical
   set; see the token block in the shell head). The frequency layer is
   the engine's own attritional band (events at 1-in-10 or more
   frequent), carved OUT of retained property so the five parts still
   sum exactly to the engine's TCOR total. */
const TCOR_COMPONENTS=[
  {key:"prop", label:"Retained property", color:"var(--c-prop)", hint:"catastrophe-band retained damage after deductibles (frequent band shown separately)"},
  {key:"bi",   label:"Retained BI",       color:"var(--c-bi)",   hint:"waiting periods on every event plus losses beyond the BI limit or indemnity period"},
  {key:"prem", label:"Premium",           color:"var(--c-prem)", hint:"allocated insurance premium: actual where on file, technical benchmark elsewhere"},
  {key:"freq", label:"Frequency layer",   color:"var(--c-freq)", hint:"the attritional band: small events at 1-in-10 or more frequent tripping deductibles across the portfolio"},
  {key:"admin",label:"Admin & risk control", color:"var(--c-admin)", hint:"program admin and annualized risk-control spend, allocated by TIV"},
];
const TCOR_COMP_BY={};TCOR_COMPONENTS.forEach(c=>TCOR_COMP_BY[c.key]=c);

/* the engine's own frequent-band integral for ONE site: the same
   ladders, deductibles, and 1-in-10 cutoff retainedPropertyCalc uses
   for its portfolio attritional layer (22_tcor.js), restricted to one
   site so the five components can be shown per site. Summed across
   sites this reproduces ctx.prop.attritional.frequentBandRetained by
   construction; a test pins that. */
const CMD_F_ATTR=0.1;   /* mirrors F_ATTR in retainedPropertyCalc */
function siteFrequentBand(s,sc,join){
  let a=0;
  ["flood","general"].forEach(cls=>{
    TCOR_CLASS_PERILS[cls].forEach(hz=>{
      const lad=siteLadderFor(s,hz,sc,join);
      a+=ladderIntegral(lad.rps,lad.losses,
        L=>Math.min(L,tcorProgram.deductibles[cls].amountUsd),CMD_F_ATTR);
    });
  });
  return a;
}

/* per-site five-part split from a tcorSite row: plain arithmetic on
   the engine's outputs (freq is carved out of retained property;
   admin and risk-control spend share the fifth slot). */
function tcorComponentsOf(r,freqBand){
  const prop=r.components.retainedProperty.value;
  const freq=Math.min(Math.max(freqBand||0,0),prop);
  return {prop:prop-freq,freq,
    bi:r.components.retainedBI.value,
    prem:r.components.premium.value,
    admin:r.components.admin.value+r.components.mitigation.value};
}

/* per-field provenance for the exports: SOV (a fact on file),
   calibrated (modeled AND grounded by the loaded loss run within the
   0.5x-2x band), modeled (event/pack math), estimated (interim model
   or defaults). Never overstates: anything standing on a fallback or
   default reads estimated. */
function provenanceOf(basis,calibrated){
  const b=String(basis||"").toLowerCase();
  if(/actual|on file/.test(b))return "sov";
  if(/interim|default|approximation|fallback|pending/.test(b))return "estimated";
  if(/event|pack/.test(b))return calibrated?"calibrated":"modeled";
  return "estimated";
}
/* is a peril class grounded by the loss run (actuals exist and the
   model sits within the 0.5x-2x band)? read from lossrunCalibration. */
function calibrationStateOf(calib,cls){
  if(!calib)return null;
  const row=(calib.perClass||[]).find(p=>p.cls===cls);
  if(!row||row.ratio==null)return null;
  return {ratio:row.ratio,within:!(row.bias),note:row.note};
}

/* ------------------------------------------------------------
   Command context: one computation per paint, shared by the band,
   the list, the map, the site view, and the exports. Memoized on a
   cheap state key so scenario scrubbing and re-renders stay quick.
   ------------------------------------------------------------ */
let _cmd={key:null};
function cmdStateKey(){
  let v=0;
  sites.forEach(s=>{v+=(+s.asset_value_usd||0)+(+s.premium_annual_usd||0)+(+s.annual_revenue_usd||0);});
  return [scenario,sites.length,typeof nextId==="undefined"?0:nextId,v.toFixed(0),
    hazardGrid?hazardGrid.meta.loaded:"-",
    resultsPack?resultsPack.loaded:"-",
    lossRun?lossRun.loaded:"-",
    JSON.stringify(tcorProgram.deductibles),
    tcorProgram.bi.limitUsd||"",tcorProgram.premium.programAnnualUsd||"",
    tcorProgram.adminAnnualUsd,tcorProgram.mitigationAnnualUsd,
    finAssume.revRatio,finAssume.gopMargin,finAssume.reopenMonths,
    typeof adapt!=="undefined"?JSON.stringify(adapt.m):""].join("|");
}
function cmdCtx(){
  if(!sites.length)return null;
  const key=cmdStateKey();
  if(_cmd.key===key)return _cmd;
  const tp=tcorPortfolio(sites,scenario);
  const join=packJoin(sites,scenario);
  const af=typeof tolAf==="function"?tolAf():annuity(APPRAISAL_DEFAULTS.horizonYears,APPRAISAL_DEFAULTS.discountPct/100);
  const calib=lossRun?lossrunCalibration(sites):null;
  const rows=tp.rows.map(r=>{
    const s=sites.find(x=>x.id===r.id);
    const comp=tcorComponentsOf(r,s?siteFrequentBand(s,scenario,join):0);
    let domComp="prop",dv=-Infinity;
    TCOR_COMPONENTS.forEach(c=>{if(comp[c.key]>dv){dv=comp[c.key];domComp=c.key;}});
    /* top climate driver: the peril with the largest modeled gross EAD
       at this site (hazard engine outputs, unchanged) */
    let driver="tc",de=-Infinity;
    if(s)ACUTE.forEach(hz=>{const e=hzSite(s,hz,scenario).ead;if(e>de){de=e;driver=hz;}});
    const best=s?bestMeasureFor(s,scenario,af):null;
    const prem=tp.ctx.prem.perSite[r.id]||{};
    return {id:r.id,name:r.name,brand:s?s.brand:"",comp,domComp,
      total:r.total,retained:comp.prop+comp.freq+comp.bi,
      driver,driverEad:Math.max(de,0),
      opp:best?{name:best.name,averted:best.averted,cost:best.cost,bcr:best.bcr,
        payback:(best.averted>0&&best.cost>0)?best.cost/best.averted:null}:null,
      premTechnical:prem.technical||0,premActual:prem.actual,
      premAllocated:prem.allocated||0,premBasis:prem.basis||"",
      estimate:r.quality.estimate,missing:r.quality.missing,
      tiv:s?(+s.asset_value_usd||0):0,
      lat:s?+s.latitude:0,lon:s?+s.longitude:0,site:s,row:r};
  }).sort((a,b)=>b.total-a.total);
  const completeTcor=rows.reduce((a,r)=>a+(r.estimate?0:r.total),0);
  const sim=simulateRetainedYears(sites,scenario);
  const fixed=tp.components.retainedBI+tp.components.premium
    +tp.components.mitigation+tp.components.admin;
  _cmd={key,tp,rows,join,af,calib,sim,
    portComp:{
      prop:Math.max(tp.components.retainedProperty-tp.attritional.frequentBandRetained,0),
      freq:Math.min(tp.attritional.frequentBandRetained,tp.components.retainedProperty),
      bi:tp.components.retainedBI,prem:tp.components.premium,
      admin:tp.components.mitigation+tp.components.admin},
    confidence:tp.total>0?completeTcor/tp.total:0,
    nComplete:rows.filter(r=>!r.estimate).length,
    /* bad-year TCOR: retained property at the 99th percentile of the
       engine's seeded year simulation; BI, premium, and fixed costs at
       expected level (the BI bad-year module is pending, and the
       surface says so). */
    badYear:sim.p99+fixed,
    expectedYear:tp.total};
  return _cmd;
}
function cmdInvalidate(){_cmd={key:null};}

/* ---- scenario / horizon: THE global control ---- */
function cmdSetScenario(sc){
  if(typeof stopScrub==="function")stopScrub();
  scenario=sc;
  if(sc!=="present"&&ui)ui.futureSc=sc;
  if(typeof persist==="function")persist();
  if(typeof scenHook==="function"&&scenHook)scenHook();
  render();
}
function cmdSetLens(l){
  if(!ui)return;
  ui.lens=(l==="renewal")?"renewal":"capital";
  if(ui.lens==="renewal"){ if(scenario!=="present")ui.futureSc=scenario; cmdSetScenario("present"); }
  else cmdSetScenario(ui.futureSc||"ssp245_2050");
}
function cmdScenParts(){
  if(scenario==="present")return {pathway:(ui&&ui.futureSc?ui.futureSc.split("_")[0]:"ssp245"),horizon:"present"};
  const p=scenario.split("_");return {pathway:p[0],horizon:p[1]};
}

/* ---- derivation popover: every figure one hover from how it was built ---- */
let _derivePop=null,_deriveEl=null;
function ensureDerive(){
  if(_derivePop)return _derivePop;
  _derivePop=document.createElement("div");
  _derivePop.className="derive";
  document.body.appendChild(_derivePop);
  return _derivePop;
}
function showDerive(el,html){
  const pop=ensureDerive();
  pop.innerHTML=html;pop.classList.add("open");_deriveEl=el;
  const r=el.getBoundingClientRect?el.getBoundingClientRect():{left:20,bottom:20,top:20};
  const vw=document.documentElement.clientWidth||1200;
  let left=(r.left||0)+window.scrollX, top=(r.bottom||0)+window.scrollY+8;
  const pw=pop.offsetWidth||320,ph=pop.offsetHeight||120;
  left=Math.max(8,Math.min(left,window.scrollX+vw-pw-10));
  const vh=document.documentElement.clientHeight||800;
  if((r.bottom||0)+ph+12>vh)top=(r.top||0)+window.scrollY-ph-8;
  pop.style.left=left+"px";pop.style.top=top+"px";
}
function hideDerive(){ if(_derivePop)_derivePop.classList.remove("open"); _deriveEl=null; }
/* wire hover+focus derivations on any [data-derive] element inside host */
function wireDerive(host,contentOf){
  if(!host||!host.querySelectorAll)return;
  host.querySelectorAll("[data-derive]").forEach(el=>{
    const show=()=>{const h=contentOf(el.dataset.derive,el);if(h)showDerive(el,h);};
    el.addEventListener("mouseenter",show);
    el.addEventListener("mouseleave",hideDerive);
    el.addEventListener("focus",show);
    el.addEventListener("blur",hideDerive);
  });
}
function deriveHtml(title,rows,basis){
  return '<h5>'+esc(title)+'</h5><div class="kv">'+
    rows.map(x=>'<span class="k">'+esc(x[0])+'</span><span class="v mono">'+x[1]+'</span>').join("")+
    '</div>'+(basis?'<div class="basis">'+esc(basis)+'</div>':"");
}

/* portfolio-level derivation content per component key */
function portDeriveHtml(key,c){
  const tp=c.tp,pc=c.portComp;
  if(key==="prop"){
    const cl=tp.ctx.prop.classes;
    return deriveHtml("Retained property (catastrophe band)",[
      ["Hurricane retained",fmt$(cl.hurricane.annualRetained)+"/yr"],
      ["Flood retained",fmt$(cl.flood.annualRetained)+"/yr"],
      ["General retained",fmt$(cl.general.annualRetained)+"/yr"],
      ["Frequency band shown separately","-"+fmt$(pc.freq)+"/yr"],
      ["Hurricane deductible",fmt$(cl.hurricane.dedUsd)+" "+cl.hurricane.dedBasis]],
      "Basis: "+cl.hurricane.basis+". One shared per-occurrence hurricane deductible per campus per event; flood and general are per-location ladders.");
  }
  if(key==="bi"){
    const bi=tp.ctx.bi;
    return deriveHtml("Retained business interruption",[
      ["Waiting-period share",fmt$(bi.waiting)+"/yr"],
      ["Beyond limit / indemnity",fmt$(bi.overage)+"/yr"],
      ["Gross BI (before terms)",fmt$(bi.gross)+"/yr"],
      ["Transferred to insurer",fmt$(bi.transferred)+"/yr"]],
      bi.basis);
  }
  if(key==="prem"){
    const pr=tp.ctx.prem;
    return deriveHtml("Allocated premium",[
      ["Allocated total",fmt$(pr.allocatedTotal)+"/yr"],
      ["Technical benchmark",fmt$(pr.technicalTotal)+"/yr"],
      ["Actual on file",pr.nActual+" site"+(pr.nActual===1?"":"s")+" · "+fmt$(pr.actualTotal)+"/yr"],
      ["Loading factor",pr.load+"x"]],
      pr.allocBasis);
  }
  if(key==="freq"){
    const at=tp.attritional;
    return deriveHtml("Frequency layer (attritional band)",[
      ["Retained, frequent band",fmt$(at.frequentBandRetained)+"/yr"],
      ["Deductible hits",at.frequentHitsPerYear.toFixed(1)+"/yr"],
      ["Hurricane occurrences",at.hurricaneOccurrencesPerYear.toFixed(2)+"/yr"]],
      at.note);
  }
  if(key==="admin"){
    return deriveHtml("Admin & risk control",[
      ["Program admin",fmt$(tp.components.admin)+"/yr"],
      ["Risk-control spend",fmt$(tp.components.mitigation)+"/yr"]],
      "Allocated across sites by TIV; site-level spend on file wins where present.");
  }
  return null;
}

/* ---- the compact stacked component bar ---- */
function compBarHtml(comp,total,idPrefix){
  const t=total||1;
  let bar='<div class="compbar" role="img" aria-label="'+
    esc(TCOR_COMPONENTS.map(c=>c.label+" "+(comp[c.key]/t*100).toFixed(0)+"%").join(", "))+'">';
  TCOR_COMPONENTS.forEach(c=>{
    const v=Math.max(comp[c.key],0);
    bar+='<div data-derive="'+idPrefix+c.key+'" tabindex="0" style="flex-grow:'+(v/t).toFixed(5)+
      ';background:'+c.color+'" title="'+esc(c.label+": "+fmt$(v)+"/yr ("+(v/t*100).toFixed(0)+"%)")+'"></div>';
  });
  bar+='</div><div class="complegend">';
  TCOR_COMPONENTS.forEach(c=>{
    bar+='<button type="button" class="ci" data-derive="'+idPrefix+c.key+'" title="'+esc(c.hint)+'">'+
      '<i style="background:'+c.color+'"></i>'+esc(c.label)+
      ' <span class="cv">'+fmt$(Math.max(comp[c.key],0))+'</span></button>';
  });
  bar+='</div>';
  return bar;
}

/* ============================================================
   SURFACE 1: the command view
   ============================================================ */
function renderCommand(){
  const band=document.getElementById("cmdBand");
  if(!band)return;
  const empty=document.getElementById("cmdEmpty"),body=document.getElementById("cmdBody");
  const has=sites.length>0;
  if(empty)empty.style.display=has?"none":"flex";
  if(body)body.style.display=has?"flex":"none";
  band.style.display=has?"flex":"none";
  if(!has){band.innerHTML="";return;}
  const c=cmdCtx(); if(!c)return;
  const tp=c.tp;
  const lens=(ui&&ui.lens)==="renewal"?"renewal":"capital";
  const parts=cmdScenParts();
  const tiv=sites.reduce((a,s)=>a+(+s.asset_value_usd||0),0);
  const conf=Math.round(c.confidence*100);

  /* headline */
  let h='<div class="cmd-headline cmd-col">'+
    '<div class="cmd-kicker">Total cost of risk'+infoBtn("cmdTcor")+
      (tp.estimate?' <span class="estflag" data-derive="quality" tabindex="0">estimate</span>':'')+
      ' <span style="font-weight:500;letter-spacing:0;text-transform:none">'+esc(scenLabelPlain(scenario))+'</span></div>'+
    '<div class="cmd-hero" data-derive="total" tabindex="0">'+fmt$(tp.total)+'<span class="unit">/yr</span></div>'+
    '<div class="cmd-sub">'+(tiv?(tp.total/tiv*100).toFixed(2):"0.00")+'% of '+fmt$(tiv)+' insured value · '+
      sites.length+' site'+(sites.length>1?"s":"")+
      ' · gross modeled loss '+fmt$(tp.waterfall.gross)+'/yr, '+
      (tp.waterfall.gross>0?Math.round((tp.waterfall.transferredProperty+tp.waterfall.transferredBI)/tp.waterfall.gross*100):0)+'% transferred</div>'+
    compBarHtml(c.portComp,tp.total,"pc_")+
    '</div>';

  /* expected vs bad year + confidence */
  h+='<div class="cmd-col"><div class="col-l">Expected vs bad year'+infoBtn("cmdBadYear")+'</div>'+
    '<div class="cmd-eb">'+
    '<div class="eb"><div class="l">Expected year</div><div class="v">'+fmt$(c.expectedYear)+'</div>'+
      '<div class="f">mean annual TCOR</div></div>'+
    '<div class="eb bad" data-derive="badyear" tabindex="0"><div class="l">Bad year (1-in-100)</div><div class="v">'+fmt$(c.badYear)+'</div>'+
      '<div class="f">retained property at the 99th percentile simulated year; BI and premium at expected level</div></div>'+
    '</div>'+
    '<div class="col-l" style="margin-top:8px">Confidence'+infoBtn("cmdConfidence")+'</div>'+
    '<div data-derive="confidence" tabindex="0"><div class="confbar"><i style="width:'+conf+'%"></i></div>'+
    '<div class="cmd-sub" style="margin-top:3px">'+conf+'% of TCOR backed by complete data · '+
      c.nComplete+' of '+sites.length+' sites complete</div></div></div>';

  /* controls: the ONE scenario control + framing + export */
  const hor=[["present","Now"],["2030","2030"],["2050","2050"],["2080","2080"]];
  const pw=[["ssp126","SSP1-2.6"],["ssp245","SSP2-4.5"],["ssp585","SSP5-8.5"]];
  h+='<div class="cmd-controls">'+
    '<div class="cmd-ctlrow"><span class="seg-l">Horizon</span><div class="segbtns" role="group" aria-label="Time horizon">'+
      hor.map(([k,l])=>'<button type="button" data-cmdhor="'+k+'" aria-pressed="'+((parts.horizon===k)||(k==="present"&&scenario==="present")?"true":"false")+'">'+l+'</button>').join("")+
    '</div></div>'+
    '<div class="cmd-ctlrow"><span class="seg-l">Pathway</span><div class="segbtns" role="group" aria-label="Emissions pathway">'+
      pw.map(([k,l])=>'<button type="button" data-cmdpw="'+k+'"'+(scenario==="present"?" disabled":"")+' aria-pressed="'+(parts.pathway===k&&scenario!=="present"?"true":"false")+'" title="'+esc(PATHWAY_LABEL[k])+'">'+l+'</button>').join("")+
    '</div></div>'+
    '<div class="cmd-ctlrow"><span class="seg-l">Framing</span><div class="segbtns" role="group" aria-label="Decision framing">'+
      '<button type="button" data-cmdlens="renewal" aria-pressed="'+(lens==="renewal"?"true":"false")+'" title="Present day, 1 to 3 years: premium and retention lead">Renewal</button>'+
      '<button type="button" data-cmdlens="capital" aria-pressed="'+(lens==="capital"?"true":"false")+'" title="Multi-decade: adaptation leads">Capital</button>'+
    '</div>'+infoBtn("cmdLens")+'</div>'+
    '<div class="cmd-ctlrow"><div class="exportwrap"><button type="button" class="lightbtn" id="cmdExportBtn" aria-haspopup="true" aria-expanded="false">Export this view &#9662;</button>'+
      '<div class="exportmenu" id="cmdExportMenu" role="menu" aria-label="Command view exports" style="right:0;top:38px">'+
      '<button class="mi" role="menuitem" id="cmdExpTcor"><b>Portfolio TCOR by site (CSV)</b><small>Five components per site with per-field provenance, scoped to this scenario</small></button>'+
      '<button class="mi" role="menuitem" id="cmdExpList"><b>Ranked decision list (CSV)</b><small>Exactly the list beside the map: totals, drivers, opportunities, confidence</small></button>'+
      '<button class="mi" role="menuitem" id="cmdExpComp"><b>Component breakdown (CSV)</b><small>Portfolio five-part split, expected vs bad year, confidence</small></button>'+
      '</div></div></div>';
  band.innerHTML=h;

  /* wire the band */
  band.querySelectorAll("[data-cmdhor]").forEach(b=>b.onclick=()=>{
    const k=b.dataset.cmdhor;
    if(ui)ui.lens=(k==="present")?"renewal":"capital";
    cmdSetScenario(k==="present"?"present":(parts.pathway+"_"+k));
  });
  band.querySelectorAll("[data-cmdpw]").forEach(b=>b.onclick=()=>{
    if(scenario==="present")return;
    cmdSetScenario(b.dataset.cmdpw+"_"+parts.horizon);
  });
  band.querySelectorAll("[data-cmdlens]").forEach(b=>b.onclick=()=>cmdSetLens(b.dataset.cmdlens));
  const xb=document.getElementById("cmdExportBtn"),xm=document.getElementById("cmdExportMenu");
  if(xb&&xm){
    xb.onclick=e=>{e.stopPropagation();const open=!xm.classList.contains("open");
      xm.classList.toggle("open",open);xb.setAttribute("aria-expanded",open?"true":"false");};
    xm.addEventListener("click",e=>e.stopPropagation());
    const w=(id,fn)=>{const el=document.getElementById(id);if(el)el.onclick=()=>{xm.classList.remove("open");fn();};};
    w("cmdExpTcor",exportTcorPortfolioCsv);
    w("cmdExpList",exportDecisionListCsv);
    w("cmdExpComp",exportComponentBreakdownCsv);
  }
  wireDerive(band,key=>{
    if(key.indexOf("pc_")===0)return portDeriveHtml(key.slice(3),c);
    if(key==="total")return deriveHtml("Portfolio TCOR",[
      ["Retained property",fmt$(tp.components.retainedProperty)+"/yr"],
      ["Retained BI",fmt$(tp.components.retainedBI)+"/yr"],
      ["Premium",fmt$(tp.components.premium)+"/yr"],
      ["Risk control + admin",fmt$(tp.components.mitigation+tp.components.admin)+"/yr"],
      ["Indirect (flagged, excluded)",fmt$(tp.indirect.value)+"/yr"]],
      "Event-level for hurricane (shared per-occurrence deductible per campus), per-location ladders for flood and general. "+(tp.basisFlags[0]||""));
    if(key==="badyear")return deriveHtml("Bad year (1-in-100)",[
      ["Retained property, p99 year",fmt$(c.sim.p99)],
      ["Median year",fmt$(c.sim.median)],
      ["p90 year",fmt$(c.sim.p90)],
      ["BI + premium + fixed",fmt$(c.badYear-c.sim.p99)+" (expected level)"]],
      c.sim.years+"-year seeded simulation, "+c.sim.basis+". The BI bad-year module is pending; until it lands, BI rides at expected level and this figure is labeled an estimate.");
    if(key==="confidence"||key==="quality"){
      const miss={};c.rows.forEach(r=>r.missing.forEach(m=>miss[m]=(miss[m]||0)+1));
      const top=Object.keys(miss).sort((a,b)=>miss[b]-miss[a]).slice(0,4);
      return deriveHtml("Confidence",[["Complete-data share",conf+"% of TCOR"],
        ["Complete sites",c.nComplete+" of "+sites.length]].concat(top.map(m=>["Missing at "+miss[m]+" site"+(miss[m]>1?"s":""),esc(m)])),
        "A site is complete when no component stands on a default or interim fallback; every gap is listed on its site view.");
    }
    return null;
  });

  renderCmdList(c,lens);
  renderCmdMap(c);
}

/* ---- the ranked decision list ---- */
let cmdSort={key:"total",dir:-1};
function renderCmdList(c,lens){
  const head=document.getElementById("cmdListHead"),scroll=document.getElementById("cmdListScroll");
  if(!head||!scroll)return;
  head.innerHTML='<h2>Sites by cost</h2><span class="hint">'+
    (lens==="renewal"?"renewal framing: premium and retention lead":"capital framing: adaptation leads")+
    ' · click a row for the site view</span>';
  const rows=c.rows.slice();
  const k=cmdSort.key,d=cmdSort.dir;
  rows.sort((a,b)=>{
    const va=k==="opp"?(a.opp?a.opp.payback||1e9:1e9):(k==="prem"?a.premAllocated:a[k]);
    const vb=k==="opp"?(b.opp?b.opp.payback||1e9:1e9):(k==="prem"?b.premAllocated:b[k]);
    return (typeof va==="string")?d*String(va).localeCompare(String(vb)):d*((va||0)-(vb||0));
  });
  const maxT=Math.max.apply(null,rows.map(r=>r.total))||1;
  const th=(lab,key,num)=>'<th'+(num?' class="num"':'')+' data-csort="'+key+'">'+lab+
    (cmdSort.key===key?(cmdSort.dir<0?" ↓":" ↑"):"")+'</th>';
  let h='<table class="cmdtbl"><thead><tr>'+
    th("Site","name")+
    th("TCOR / yr","total",1)+
    th("Dominant cost","domComp")+
    th("Climate driver","driverEad")+
    (lens==="renewal"
      ?th("Premium","prem",1)+th("Retained","retained",1)
      :th("Top opportunity","opp"))+
    th("Conf.","estimate",1)+'</tr></thead><tbody>';
  rows.forEach(r=>{
    const dc=TCOR_COMP_BY[r.domComp];
    const hzc=HAZARD_BY[r.driver]||{color:"#7A8893",label:r.driver};
    const retained=r.comp.prop+r.comp.freq+r.comp.bi;
    const gap=(r.premActual!=null&&r.premTechnical>0)?(r.premActual/r.premTechnical-1)*100:null;
    h+='<tr class="rowclick'+(r.id===selectedId?" sel":"")+'" data-sv="'+r.id+'" tabindex="0" role="button" aria-label="Open '+esc(r.name)+'">'+
      '<td><div style="font-weight:600;color:var(--ink)">'+esc(r.name)+'</div>'+
        '<div style="font-size:10.5px;color:var(--muted)">'+esc(r.brand||"")+'</div></td>'+
      '<td class="num"><span class="mono" style="font-weight:600">'+fmt$(r.total)+'</span><br>'+
        '<span class="tcorbar" style="width:'+Math.max(r.total/maxT*72,2).toFixed(0)+'px"></span></td>'+
      '<td><span class="compchip"><i style="background:'+dc.color+'"></i>'+esc(dc.label)+'</span></td>'+
      '<td><span class="drivechip"><span class="perildot" style="background:'+hzc.color+'"></span>'+esc(hzc.label)+'</span></td>'+
      (lens==="renewal"
        ?('<td class="num mono">'+fmt$(r.premAllocated)+(gap!=null?'<br><span style="font-size:10px;color:'+(gap>0?"var(--div-hi)":"var(--div-lo)")+'" title="actual vs technical benchmark">'+(gap>0?"+":"")+gap.toFixed(0)+'% vs tech.</span>':'<br><span style="font-size:10px;color:var(--muted)">technical</span>')+'</td>'+
         '<td class="num mono">'+fmt$(retained)+'</td>')
        :('<td>'+(r.opp?('<div style="font-size:11.5px">'+esc(r.opp.name.split("(")[0].trim())+'</div>'+
           '<div style="font-size:10.5px;color:'+(r.opp.bcr>=1?"var(--good)":"var(--muted)")+'">'+
           (r.opp.payback!=null?(r.opp.payback<1?"pays back <1 yr":"pays back "+r.opp.payback.toFixed(1)+" yr"):"not priced")+'</div>'):'<span class="hint">none in scope</span>')+'</td>'))+
      '<td class="num"><span class="confmark'+(r.estimate?" est":"")+'" title="'+
        esc(r.estimate?("estimate: "+(r.missing.slice(0,3).join("; ")||"interim basis")):"complete data")+'">'+
        (r.estimate?"est":"ok")+'</span></td></tr>';
  });
  h+='</tbody></table>';
  scroll.innerHTML=h;
  scroll.querySelectorAll("th[data-csort]").forEach(el=>el.onclick=()=>{
    const key=el.dataset.csort;
    if(cmdSort.key===key)cmdSort.dir*=-1;
    else cmdSort={key,dir:(key==="name"||key==="domComp")?1:-1};
    renderCmdList(cmdCtx(),(ui&&ui.lens)==="renewal"?"renewal":"capital");
  });
  scroll.querySelectorAll("[data-sv]").forEach(tr=>{
    const open=()=>{selectedId=+tr.dataset.sv;openSiteView(+tr.dataset.sv);};
    tr.onclick=open;
    tr.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();open();}});
  });
}

/* ---- the command map (interim SVG plot).
   This panel is the placeholder for Surface 3: the genuine WebGL
   geospatial map (MapLibre, offline basemap, real hazard surfaces)
   replaces it in the next build step. Until then: an honest
   projection of the portfolio, sites sized by TCOR and coloured by
   dominant component, so the command view is already decision-ready. */
function renderCmdMap(c){
  const el=document.getElementById("cmdMap");
  if(!el)return;
  const lg=document.getElementById("cmdMapLegend"),note=document.getElementById("cmdMapNote");
  const rows=c.rows.filter(r=>isFinite(r.lat)&&isFinite(r.lon));
  if(!rows.length){el.innerHTML="";return;}
  let la0=Infinity,la1=-Infinity,lo0=Infinity,lo1=-Infinity;
  rows.forEach(r=>{la0=Math.min(la0,r.lat);la1=Math.max(la1,r.lat);lo0=Math.min(lo0,r.lon);lo1=Math.max(lo1,r.lon);});
  const padLa=Math.max((la1-la0)*0.18,2),padLo=Math.max((lo1-lo0)*0.10,2);
  la0-=padLa;la1+=padLa;lo0-=padLo;lo1+=padLo;
  const W=920,H=560;
  const kx=W/(lo1-lo0),ky=H/(la1-la0);
  const X=lon=>(lon-lo0)*kx, Y=lat=>H-(lat-la0)*ky;
  const maxT=Math.max.apply(null,rows.map(r=>r.total))||1;
  let s='<svg viewBox="0 0 '+W+' '+H+'" width="100%" height="100%" preserveAspectRatio="xMidYMid meet" style="display:block">';
  /* graticule in whole degrees, recessive */
  const stepLo=(lo1-lo0)>40?10:5, stepLa=(la1-la0)>20?10:5;
  for(let lo=Math.ceil(lo0/stepLo)*stepLo;lo<lo1;lo+=stepLo)
    s+='<line x1="'+X(lo).toFixed(1)+'" y1="0" x2="'+X(lo).toFixed(1)+'" y2="'+H+'" style="stroke:var(--line-2)" stroke-width="1"/>'+
       '<text x="'+(X(lo)+3).toFixed(1)+'" y="'+(H-6)+'" font-size="9" class="mono" style="fill:var(--muted)">'+lo+'&#176;</text>';
  for(let la=Math.ceil(la0/stepLa)*stepLa;la<la1;la+=stepLa)
    s+='<line x1="0" y1="'+Y(la).toFixed(1)+'" x2="'+W+'" y2="'+Y(la).toFixed(1)+'" style="stroke:var(--line-2)" stroke-width="1"/>'+
       '<text x="4" y="'+(Y(la)-3).toFixed(1)+'" font-size="9" class="mono" style="fill:var(--muted)">'+la+'&#176;</text>';
  rows.slice().sort((a,b)=>b.total-a.total).forEach(r=>{
    const rad=5+16*Math.sqrt(r.total/maxT);
    const dc=TCOR_COMP_BY[r.domComp];
    s+='<circle cx="'+X(r.lon).toFixed(1)+'" cy="'+Y(r.lat).toFixed(1)+'" r="'+rad.toFixed(1)+'"'+
      ' fill="'+dc.color+'" fill-opacity="0.82" stroke="var(--surface)" stroke-width="2"'+
      (r.id===selectedId?' style="filter:drop-shadow(0 0 4px var(--focus))"':'')+
      ' class="rowclick" data-svmap="'+r.id+'" tabindex="0" role="button" aria-label="'+esc(r.name+", TCOR "+fmt$(r.total)+" per year")+'">'+
      '<title>'+esc(r.name+" · TCOR "+fmt$(r.total)+"/yr · dominant: "+dc.label+(r.estimate?" · estimate":""))+'</title></circle>';
  });
  s+='</svg>';
  el.innerHTML=s;
  el.querySelectorAll("[data-svmap]").forEach(ci=>{
    const open=()=>{selectedId=+ci.dataset.svmap;openSiteView(+ci.dataset.svmap);};
    ci.addEventListener("click",open);
    ci.addEventListener("keydown",e=>{if(e.key==="Enter"){open();}});
  });
  if(lg){
    /* compact key: only the components that are actually dominant somewhere */
    const present={};rows.forEach(r2=>present[r2.domComp]=true);
    lg.innerHTML='<div class="lh">Sites · area = TCOR · colour = dominant part</div>'+
      TCOR_COMPONENTS.filter(cc=>present[cc.key]).map(cc=>'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:10px;white-space:nowrap"><i style="display:inline-block;width:9px;height:9px;border-radius:2px;background:'+cc.color+'"></i>'+esc(cc.label)+'</span>').join("");
  }
  if(note)note.textContent="Interim plot: sites sized by TCOR, coloured by dominant component. The WebGL climate map with real hazard surfaces and pathway animation replaces this panel in the next build step.";
}

/* ============================================================
   SURFACE 2: the site view with the animated TCOR waterfall
   ============================================================ */
let _svId=null;
function openSiteView(id){
  _svId=id;
  renderSiteView();
  const el=document.getElementById("siteView");
  if(el&&el.classList)el.classList.add("open");
  if(typeof renderCommand==="function")try{renderCommand();}catch(e){}
  const back=document.getElementById("svBack");
  if(back&&back.focus)try{back.focus();}catch(e){}
}
function closeSiteView(){
  _svId=null;
  const el=document.getElementById("siteView");
  if(el&&el.classList)el.classList.remove("open");
}

/* the per-site waterfall figures: pure arithmetic on engine outputs */
function siteWaterfall(c,id){
  const perSite=c.tp.ctx.prop.perSite[id];
  const grossProp=TCOR_CLASSES.reduce((a,cl)=>a+perSite[cl].gross,0);
  const retProp=TCOR_CLASSES.reduce((a,cl)=>a+perSite[cl].retained,0);
  const b=c.tp.ctx.bi.perSite[id];
  const r=c.rows.find(x=>x.id===id);
  const admin=r?r.comp.admin:0, prem=r?r.premAllocated:0;
  return {grossProp,transferred:grossProp-retProp,retProp,
    freq:r?r.comp.freq:0,propCat:r?r.comp.prop:retProp,
    biRetained:b?b.retained:0,biGross:b?b.gross:0,
    prem,admin,tcor:r?r.total:retProp+(b?b.retained:0)+prem+admin};
}
function svWaterfallHtml(w){
  /* columns of the bridge; lvl = running level BEFORE the step */
  const cols=[
    {key:"gross",lab:"Gross modeled loss",v:w.grossProp,solid:true,color:"var(--chart-neutral)"},
    {key:"xfer",lab:"Transferred to insurer",v:-w.transferred,lvl:w.grossProp,color:"var(--seq-2)",down:true},
    {key:"retp",lab:"Retained property",v:w.retProp,solid:true,color:"var(--c-prop)",stack:[
      {v:w.propCat,color:"var(--c-prop)"},{v:w.freq,color:"var(--c-freq)"}]},
    {key:"bi",lab:"+ Retained BI",v:w.biRetained,lvl:w.retProp,color:"var(--c-bi)"},
    {key:"prem",lab:"+ Premium",v:w.prem,lvl:w.retProp+w.biRetained,color:"var(--c-prem)"},
    {key:"admin",lab:"+ Admin & risk control",v:w.admin,lvl:w.retProp+w.biRetained+w.prem,color:"var(--c-admin)"},
    {key:"tcor",lab:"TCOR",v:w.tcor,solid:true,color:"var(--c-prop)",stack:[
      {v:w.propCat,color:"var(--c-prop)"},{v:w.freq,color:"var(--c-freq)"},
      {v:w.biRetained,color:"var(--c-bi)"},{v:w.prem,color:"var(--c-prem)"},
      {v:w.admin,color:"var(--c-admin)"}]},
  ];
  const ymax=Math.max(w.grossProp,w.tcor,1)*1.08;
  const n=cols.length,cw=100/n;
  const plotH=252;                   /* px inside the 300px box (24px labels) */
  const pxOf=v=>Math.max(v,0)/ymax*plotH;
  let h='<div class="wf" id="svWf">';
  /* recessive hairline gridlines; the columns carry their own value
     labels, so the grid stays unlabeled */
  [0.25,0.5,0.75,1].forEach(t=>{
    h+='<div class="wf-grid" style="bottom:'+(24+t*plotH/1.08).toFixed(1)+'px"></div>';
  });
  cols.forEach((col,i)=>{
    const x0=(i*cw+1.2).toFixed(2)+"%",x1=(cw-2.4).toFixed(2)+"%";
    const top=col.solid?pxOf(col.v):pxOf(Math.max(col.lvl,col.lvl+col.v));
    const bot=col.solid?0:pxOf(Math.min(col.lvl,col.lvl+col.v));
    const hgt=Math.max(top-bot,1.5);
    h+='<div class="wf-col" style="left:'+x0+';width:'+x1+'">';
    if(col.stack){
      let acc=0;
      col.stack.forEach((seg,si)=>{
        const sb=pxOf(acc),sh=Math.max(pxOf(acc+Math.max(seg.v,0))-sb-(si<col.stack.length-1?2:0),0);
        h+='<div class="wf-seg" data-wf="'+col.key+(col.stack.length>1?"_"+si:"")+'" data-derive="'+col.key+(col.stack.length>1?"_"+si:"")+'" tabindex="0" data-fin-bottom="'+sb.toFixed(1)+'" data-fin-h="'+sh.toFixed(1)+'"'+
          ' style="bottom:0;height:0;background:'+seg.color+'"></div>';
        acc+=Math.max(seg.v,0);
      });
    }else{
      h+='<div class="wf-seg'+(col.down?" down":"")+'" data-wf="'+col.key+'" data-derive="'+col.key+'" tabindex="0" data-fin-bottom="'+bot.toFixed(1)+'" data-fin-h="'+hgt.toFixed(1)+'"'+
        ' style="bottom:0;height:0;background:'+col.color+(col.down?';opacity:.9':'')+'"></div>';
    }
    h+='<div class="wf-val" data-fin-valbottom="'+(top+6).toFixed(1)+'" style="bottom:0;opacity:0;transition:bottom .7s cubic-bezier(.25,.8,.3,1),opacity .5s">'+
      (col.solid?fmt$(col.v):((col.v<0?"−":"+")+fmt$(Math.abs(col.v))))+'</div>';
    h+='</div>';
    h+='<div class="wf-lab" style="left:'+(i*cw).toFixed(2)+'%;width:'+cw.toFixed(2)+'%;position:absolute">'+esc(col.lab)+'</div>';
    if(i<n-1){
      const lev=col.solid?pxOf(col.v):pxOf(col.lvl+col.v);
      h+='<div class="wf-conn" data-fin-connbottom="'+lev.toFixed(1)+'" style="left:'+((i+1)*cw-1.2).toFixed(2)+'%;width:'+(2.4).toFixed(2)+'%;bottom:0"></div>';
    }
  });
  h+='</div>';
  return h;
}
/* run the load / scenario-change animation: segments grow from the
   baseline into place (CSS transitions carry the motion) */
function svAnimateWaterfall(){
  const wf=document.getElementById("svWf");
  if(!wf||!wf.querySelectorAll)return;
  const go=()=>{
    wf.querySelectorAll(".wf-seg").forEach(seg=>{
      seg.style.bottom=(24+ +seg.dataset.finBottom)+"px";
      seg.style.height=seg.dataset.finH+"px";
    });
    wf.querySelectorAll(".wf-val").forEach(v=>{
      v.style.bottom=(24+ +v.dataset.finValbottom)+"px";v.style.opacity="1";
    });
    wf.querySelectorAll(".wf-conn").forEach(cn=>{
      cn.style.bottom=(24+ +cn.dataset.finConnbottom)+"px";
    });
  };
  if(typeof requestAnimationFrame==="function")requestAnimationFrame(()=>requestAnimationFrame(go));
  else go();
}

/* derivation content for a waterfall segment */
function svWfDerive(key,c,r,w){
  const cl=c.tp.ctx.prop.classes;
  const perSite=c.tp.ctx.prop.perSite[r.id];
  if(key==="gross")return deriveHtml("Gross modeled property loss",[
    ["Hurricane (wind + surge)",fmt$(perSite.hurricane.gross)+"/yr"],
    ["Flood (river + rainfall)",fmt$(perSite.flood.gross)+"/yr"],
    ["General (wildfire etc.)",fmt$(perSite.general.gross)+"/yr"]],
    "Expected annual loss from the climate event sets and ladders before any insurance. Basis: "+cl.hurricane.basis+".");
  if(key==="xfer")return deriveHtml("Transferred to the insurer",[
    ["Above deductibles",fmt$(w.transferred)+"/yr"],
    ["Share of gross",w.grossProp>0?Math.round(w.transferred/w.grossProp*100)+"%":"0%"]],
    "What the program pays: gross loss beyond the retained deductible layer. Hurricane retains one shared per-occurrence deductible per campus per event.");
  if(key==="retp"||key==="retp_0")return deriveHtml("Retained property (catastrophe band)",[
    ["Hurricane retained",fmt$(perSite.hurricane.retained)+"/yr"],
    ["Flood retained",fmt$(perSite.flood.retained)+"/yr"],
    ["General retained",fmt$(perSite.general.retained)+"/yr"],
    ["Hurricane deductible",fmt$(cl.hurricane.dedUsd)+" "+cl.hurricane.dedBasis]],
    r.row.components.retainedProperty.basis==="event"
      ?"Event-level from the results pack's per-event table."
      :"Basis: "+r.row.components.retainedProperty.basis+".");
  if(key==="retp_1")return deriveHtml("Frequency layer at this site",[
    ["Frequent-band retained",fmt$(w.freq)+"/yr"]],
    "Events at 1-in-10 or more frequent tripping the flood and general per-location deductibles; the same integral as the engine's portfolio attritional layer, shown per site.");
  if(key==="bi")return deriveHtml("Retained business interruption",[
    ["Waiting-period share",fmt$(r.row.components.retainedBI.waiting)+"/yr"],
    ["Beyond limit / indemnity",fmt$(r.row.components.retainedBI.overage)+"/yr"],
    ["Gross BI before terms",fmt$(w.biGross)+"/yr"]],
    r.row.components.retainedBI.basis);
  if(key==="prem")return deriveHtml("Allocated premium",[
    ["Allocated",fmt$(r.premAllocated)+"/yr"],
    ["Technical benchmark",fmt$(r.premTechnical)+"/yr"],
    ["Actual on file",r.premActual!=null?fmt$(r.premActual)+"/yr":"none"]],
    r.premBasis);
  if(key==="admin")return deriveHtml("Admin & risk control",[
    ["This site's share",fmt$(w.admin)+"/yr"]],
    "Program admin and risk-control spend allocated by TIV; site spend on file wins.");
  if(key.indexOf("tcor")===0)return deriveHtml("TCOR: what TNL pays",[
    ["Retained property",fmt$(w.retProp)+"/yr"],
    ["Retained BI",fmt$(w.biRetained)+"/yr"],
    ["Premium",fmt$(w.prem)+"/yr"],
    ["Admin & risk control",fmt$(w.admin)+"/yr"],
    ["Total",fmt$(w.tcor)+"/yr"]],
    "Most of the gross number is transferred; what TNL pays is BI plus premium plus the retained slivers. Indirect costs (rebooking, reputation) are a flagged estimate and never inside this total.");
  return null;
}

function renderSiteView(){
  const host=document.getElementById("siteView");
  if(!host||_svId==null)return;
  const c=cmdCtx(); if(!c){host.innerHTML="";return;}
  const r=c.rows.find(x=>x.id===_svId);
  const s=sites.find(x=>x.id===_svId);
  if(!r||!s){host.innerHTML="";return;}
  const w=siteWaterfall(c,r.id);
  const campus=String(s.campus_name||s.campus_code||"").trim();
  const tenure=s.owned_or_leased?s.owned_or_leased:"tenure not on file";
  const biee=+s.bi_ee_usd>0?fmt$(+s.bi_ee_usd)+" BI & EE":"no BI & EE on file";

  /* climate drivers: per-peril modeled gross EAD at this site, plus
     the modeled events that hit it when an event table is loaded */
  const drivers=ACUTE.map(hz=>({hz,label:HAZARD_LABEL[hz],color:HAZARD_BY[hz].color,
    ead:hzSite(s,hz,scenario).ead})).sort((a,b)=>b.ead-a.ead);
  const dmax=Math.max.apply(null,drivers.map(d=>d.ead))||1;
  let events=[];
  if(c.join&&c.join.idxOf&&resultsPack&&resultsPack.data&&resultsPack.data.event_sets){
    const evScen=resultsPack.data.event_sets.scenarios&&resultsPack.data.event_sets.scenarios[scenario];
    if(evScen){
      const myIdx={};c.join.map.forEach((ms,i)=>{if(ms&&ms.id===s.id)myIdx[i]=true;});
      evScen.forEach(part=>{
        const wgt=+part.weight||0;
        (part.events||[]).forEach(e=>{
          let mine=0,tot=0,nSites=0;
          (e.sites||[]).forEach(p=>{tot+=(+p[1]||0);nSites++;if(myIdx[p[0]])mine+=(+p[1]||0);});
          if(mine>0)events.push({id:e.id,freq:+e.freq||0,mine,tot,nSites,w:wgt});
        });
      });
      events.sort((a,b)=>b.w*b.freq*b.mine-a.w*a.freq*a.mine);
      events=events.slice(0,6);
    }
  }

  /* calibration: this site's actual claims vs modeled retained */
  const agg=lossRun?lossrunAggregates(sites):null;
  const actual=agg&&agg.bySite[s.id]?agg.bySite[s.id]:null;
  const nYears=agg?agg.years.n:0;

  /* opportunities: the adaptation engine's own appraisal */
  const sBase=adaptedFinSite(s,scenario,{}).totalAal;
  const opps=MEASURES.filter(m=>m.inScope(s,scenario)).map(m=>{
    const st=adapt.m[m.key];
    const averted=sBase-adaptedFinSite(s,scenario,m.mods(st)).totalAal;
    const cost=m.siteCost(s,st);
    return {name:m.name,target:m.target,averted,cost,
      bcr:cost>0?averted*c.af/cost:0,
      payback:(averted>0&&cost>0)?cost/averted:null};
  }).sort((a,b)=>b.bcr-a.bcr);

  const comps=r.row.components;
  const bt=biTermsOf(s);
  const compCard=(title,color,rows2,basis,prov)=>
    '<div class="panel" style="margin-bottom:0"><h3><span style="display:inline-block;width:10px;height:10px;border-radius:3px;background:'+color+';margin-right:7px"></span>'+esc(title)+
    (prov==="estimated"?' <span class="estflag">estimate</span>':'')+'</h3>'+
    '<div class="kv" style="margin-top:8px">'+rows2.map(x=>'<span class="k">'+esc(x[0])+'</span><span class="v mono">'+x[1]+'</span>').join("")+'</div>'+
    (basis?'<div class="sv-note" style="margin-top:8px">'+esc(basis)+'</div>':'')+'</div>';

  const calibProp=calibrationStateOf(c.calib,"hurricane");
  let h='<div class="sv-wrap">'+
    '<div class="sv-top">'+
      '<button type="button" class="sv-back" id="svBack">&#8592; Portfolio</button>'+
      '<div><div class="sv-name">'+esc(s.name)+'</div>'+
      '<div class="sv-meta">'+esc(s.brand||"")+(campus?' · campus '+esc(campus):' · no campus code (own deductible-sharing unit, flagged)')+
        ' · '+esc(tenure)+' · TIV '+fmt$(+s.asset_value_usd||0)+' · '+esc(biee)+
        ' · '+esc(scenLabelPlain(scenario))+'</div></div>'+
      '<div class="sv-tcor"><div class="l">TCOR'+(r.estimate?' · estimate':'')+'</div><div class="v">'+fmt$(r.total)+'<span style="font-size:15px;color:var(--ink-2)">/yr</span></div>'+
      '<div style="margin-top:6px;display:flex;gap:8px;justify-content:flex-end">'+
        '<div class="exportwrap"><button type="button" class="lightbtn" id="svExportBtn" aria-haspopup="true" aria-expanded="false">Export site &#9662;</button>'+
        '<div class="exportmenu" id="svExportMenu" role="menu" style="right:0;top:38px">'+
        '<button class="mi" role="menuitem" id="svExpCsv"><b>TCOR breakdown (CSV)</b><small>Waterfall, components, drivers, opportunities, provenance</small></button>'+
        '<button class="mi" role="menuitem" id="svExpJson"><b>Full site detail (JSON)</b><small>Everything on this view, machine-readable</small></button>'+
        '</div></div></div></div>'+
    '</div>'+
    '<div class="panel" style="margin-bottom:16px"><h3>From gross loss to TCOR'+infoBtn("wfTeach")+'</h3>'+
    '<div class="hint">Hover any bar for its derivation. '+
      (w.grossProp>0?('The insurer takes '+Math.round(w.transferred/Math.max(w.grossProp,1)*100)+'% of the gross modeled property loss; what TNL pays is BI, premium, and the retained slivers.'):'')+'</div>'+
    svWaterfallHtml(w)+'</div>'+
    '<div class="sv-grid">'+
    compCard("Retained property","var(--c-prop)",[
      ["Hurricane retained",fmt$(c.tp.ctx.prop.perSite[r.id].hurricane.retained)+"/yr"],
      ["Flood retained",fmt$(c.tp.ctx.prop.perSite[r.id].flood.retained)+"/yr"],
      ["General retained",fmt$(c.tp.ctx.prop.perSite[r.id].general.retained)+"/yr"],
      ["Frequency layer (within)",fmt$(r.comp.freq)+"/yr"],
      ["Hurricane deductible",fmt$(tcorProgram.deductibles.hurricane.amountUsd)+" per occurrence, shared per campus"]],
      "Basis: "+comps.retainedProperty.basis+(calibProp&&calibProp.ratio!=null?" · loss-run ratio (modeled/actual) "+calibProp.ratio.toFixed(2)+"x":""),
      provenanceOf(comps.retainedProperty.basis)) +
    compCard("Retained business interruption","var(--c-bi)",[
      ["Waiting period ("+bt.waitingDays+" days, every event)",fmt$(comps.retainedBI.waiting)+"/yr"],
      ["Beyond limit / indemnity",fmt$(comps.retainedBI.overage)+"/yr"],
      ["BI limit",bt.limitUsd!=null?fmt$(bt.limitUsd)+" ("+bt.limitBasis+")":bt.limitBasis],
      ["Indemnity period",bt.indemnityDays+" days"]],
      comps.retainedBI.basis+" Downtime days and seasonality weighting arrive with the full BI module; until then the linear damage-to-downtime chain stands, labeled.",
      "estimated") +
    compCard("Premium: technical vs actual","var(--c-prem)",[
      ["Allocated",fmt$(r.premAllocated)+"/yr"],
      ["Technical benchmark",fmt$(r.premTechnical)+"/yr"],
      ["Actual on file",r.premActual!=null?fmt$(r.premActual)+"/yr":"none"],
      ["Gap (actual vs technical)",(r.premActual!=null&&r.premTechnical>0)?(((r.premActual/r.premTechnical-1)*100).toFixed(0)+"%"):"n/a"]],
      r.premBasis,
      provenanceOf(r.premBasis)) +
    compCard("Frequency layer & admin","var(--c-freq)",[
      ["Frequent-band retained (site)",fmt$(r.comp.freq)+"/yr"],
      ["Portfolio deductible hits",c.tp.attritional.frequentHitsPerYear.toFixed(1)+"/yr"],
      ["Admin & risk control (site share)",fmt$(r.comp.admin)+"/yr"]],
      c.tp.attritional.note) +
    '<div class="panel" style="margin-bottom:0"><h3>Climate drivers</h3>'+
      '<div class="hint">Modeled gross expected annual damage by peril at this site; the map shows these as hazard surfaces when this site is focused (next build step).</div>'+
      drivers.map(d=>'<div style="display:flex;align-items:center;gap:8px;margin:5px 0">'+
        '<span style="width:118px;font-size:11.5px;color:var(--ink-2);flex:none">'+esc(d.label)+'</span>'+
        '<span style="flex:1;height:10px;border-radius:4px;background:var(--line-2);overflow:hidden"><i style="display:block;height:100%;width:'+(d.ead/dmax*100).toFixed(1)+'%;background:'+d.color+'"></i></span>'+
        '<span class="mono" style="font-size:11px;width:64px;text-align:right;flex:none">'+fmt$(d.ead)+'</span></div>').join("")+
      (events.length?('<div style="margin-top:10px;font-weight:600;font-size:12px;color:var(--heading)">Modeled events hitting this site</div>'+
        '<table class="tbl" style="margin-top:4px"><thead><tr><th>Event</th><th class="num">Frequency</th><th class="num">Loss here</th><th class="num">Sites hit</th></tr></thead><tbody>'+
        events.map(e=>'<tr><td class="mono">'+esc(String(e.id))+'</td><td class="num mono">1-in-'+Math.round(1/Math.max(e.freq,1e-6))+'</td>'+
          '<td class="num mono">'+fmt$(e.mine)+'</td><td class="num mono">'+e.nSites+'</td></tr>').join("")+
        '</tbody></table><div class="sv-note" style="margin-top:5px">Multi-site events share ONE hurricane deductible per campus: the accumulation the map will draw.</div>')
        :'<div class="sv-note" style="margin-top:10px">Load a results pack (Advanced &#8594; Method &amp; data) to see the modeled events behind these figures.</div>')+
    '</div>'+
    '<div class="panel" style="margin-bottom:0"><h3>Expected year vs bad year</h3>'+
      '<div class="kv" style="margin-top:6px">'+
      '<span class="k">Expected year (this site)</span><span class="v mono">'+fmt$(r.total)+' TCOR</span>'+
      '<span class="k">Site loss at 1-in-100</span><span class="v mono">'+fmt$((function(){const lad=siteLadderFor(s,"tc_joint",scenario,c.join);const i=lad.rps.indexOf(100);return i>=0?lad.losses[i]:0;})())+' gross (wind + surge)</span>'+
      '<span class="k">Portfolio bad year (p99)</span><span class="v mono">'+fmt$(c.sim.p99)+' retained property</span>'+
      '</div>'+
      '<div class="sv-note" style="margin-top:8px">A 1-in-100 season can blow through the shared hurricane retention and the BI limit at once: the waiting period bites on every event, and downtime beyond the indemnity period stays with TNL. The seeded year simulation carries the retained-property side; the BI bad-year module is pending and this narrative says so.</div></div>'+
    '<div class="panel" style="margin-bottom:0"><h3>Calibration vs actual losses</h3>'+
      (lossRun?(
        '<div class="kv" style="margin-top:6px">'+
        '<span class="k">Actual incurred at this site</span><span class="v mono">'+(actual?fmt$(actual.total)+" over "+nYears+" yr ("+fmt$(actual.total/Math.max(nYears,1))+"/yr)":"no matched claims")+'</span>'+
        '<span class="k">Modeled retained (property)</span><span class="v mono">'+fmt$(comps.retainedProperty.value)+"/yr</span>"+
        (actual?('<span class="k">By class</span><span class="v mono">'+Object.keys(actual.byClass).map(k2=>k2+" "+fmt$(actual.byClass[k2])).join(" · ")+'</span>'):'')+
        '</div>'+
        ((c.calib&&c.calib.disagreements.length)?'<div class="note" style="margin-top:8px;border-left-color:var(--bad)"><b>Model vs actuals disagree:</b> '+esc(c.calib.disagreements.join(" "))+'</div>':'<div class="sv-note" style="margin-top:8px">Portfolio calibration within band; single-site scatter is expected. '+esc(c.calib?c.calib.tail.note:"")+'</div>')+
        ((c.calib&&c.calib.development.flagged)?'<div class="sv-note" style="margin-top:5px;color:var(--warn-ink)">Development risk: '+esc(c.calib.development.note)+'</div>':'')
      ):'<div class="sv-note" style="margin-top:6px">No loss run loaded. Drop the claims report on Advanced &#8594; Method &amp; data to anchor these figures to actual losses; disagreement is shown honestly when it exists.</div>')+
    '</div>'+
    '<div class="panel" style="margin-bottom:0"><h3>Opportunities'+infoBtn("svOpp")+'</h3>'+
      (opps.length?('<table class="tbl" style="margin-top:4px"><thead><tr><th>Measure</th><th class="num">Averted / yr</th><th class="num">Cost</th><th class="num">Payback</th><th class="num">Benefit-cost</th></tr></thead><tbody>'+
        opps.map(o=>'<tr><td>'+esc(o.name)+'<div style="font-size:10.5px;color:var(--muted)">'+esc(o.target)+'</div></td>'+
          '<td class="num mono">'+fmt$(o.averted)+'</td><td class="num mono">'+fmt$(o.cost)+'</td>'+
          '<td class="num mono">'+(o.payback!=null?(o.payback<1?"<1 yr":o.payback.toFixed(1)+" yr"):"\u2014")+'</td>'+
          '<td class="num mono" style="color:'+(o.bcr>=1?"var(--good)":"var(--bad)")+'">'+o.bcr.toFixed(2)+'x</td></tr>').join("")+
        '</tbody></table>'):'<div class="sv-note" style="margin-top:6px">No in-scope measures for this site at current settings.</div>')+
      '<div class="sv-note" style="margin-top:8px">Appraised on averted expected annual climate cost (the adaptation engine’s own figures; planning-grade costs). The split of certain retained saving vs negotiated premium saving, and the TCOR benefit-cost ratio with and without the premium credit, arrive with the TCOR-aware payoff module; until then this table states the engine’s appraisal and nothing more.</div></div>'+
    '</div></div>';
  host.innerHTML=h;

  const back=document.getElementById("svBack");
  if(back)back.onclick=()=>{closeSiteView();renderCommand();};
  const xb=document.getElementById("svExportBtn"),xm=document.getElementById("svExportMenu");
  if(xb&&xm){
    xb.onclick=e=>{e.stopPropagation();const open=!xm.classList.contains("open");
      xm.classList.toggle("open",open);xb.setAttribute("aria-expanded",open?"true":"false");};
    const w2=(id,fn)=>{const el2=document.getElementById(id);if(el2)el2.onclick=()=>{xm.classList.remove("open");fn();};};
    w2("svExpCsv",()=>exportSiteTcorCsv(r.id));
    w2("svExpJson",()=>exportSiteTcorJson(r.id));
  }
  wireDerive(host,key=>svWfDerive(key,c,r,w));
  svAnimateWaterfall();
}

/* ============================================================
   Exports: the data behind every view, scoped to the scenario,
   with per-field provenance. New files on new schemas; the frozen
   Power BI export is untouched.
   ============================================================ */
function dlFile(name,text,mime){
  const blob=new Blob(["\uFEFF"+text],{type:(mime||"text/csv")+";charset=utf-8"});
  const a=document.createElement("a");
  a.href=URL.createObjectURL(blob);a.download=name;a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href),1000);
}
function exportTcorPortfolioCsv(){
  if(!sites.length){toast("Load a portfolio first.");return;}
  const c=cmdCtx();
  const calibProp=calibrationStateOf(c.calib,"hurricane");
  const cols=["site_id","name","brand","campus_code","owned_or_leased","latitude","longitude",
    "tiv_usd","bi_ee_usd","scenario","scenario_label",
    "tcor_total_usd","retained_property_usd","retained_property_cat_usd","frequency_layer_usd",
    "retained_bi_usd","bi_waiting_usd","bi_overage_usd","premium_allocated_usd",
    "premium_technical_usd","premium_actual_usd","admin_risk_control_usd",
    "indirect_flagged_excluded_usd","confidence","missing_fields",
    "prov_retained_property","prov_retained_bi","prov_premium",
    "calibration_ratio_property","hazard_source"];
  let csv=cols.join(",")+"\n";
  c.rows.forEach(r=>{
    const s=r.site,comp=r.row.components;
    csv+=[s&&s.site_id?csvCell(s.site_id):r.id,csvCell(r.name),csvCell(r.brand||""),
      csvCell(s?(s.campus_code||""):""),s?(s.owned_or_leased||""):"",r.lat,r.lon,
      r.tiv,(s&&+s.bi_ee_usd>0)?+s.bi_ee_usd:"",scenario,csvCell(scenLabelPlain(scenario)),
      r.total.toFixed(0),
      (r.comp.prop+r.comp.freq).toFixed(0),r.comp.prop.toFixed(0),r.comp.freq.toFixed(0),
      r.comp.bi.toFixed(0),comp.retainedBI.waiting.toFixed(0),comp.retainedBI.overage.toFixed(0),
      r.premAllocated.toFixed(0),r.premTechnical.toFixed(0),
      r.premActual!=null?r.premActual.toFixed(0):"",
      r.comp.admin.toFixed(0),
      r.row.indirect.value.toFixed(0),
      r.estimate?"estimate":"complete",csvCell(r.missing.join("; ")),
      provenanceOf(comp.retainedProperty.basis,calibProp&&calibProp.within),
      provenanceOf(comp.retainedBI.basis),
      provenanceOf(r.premBasis),
      (calibProp&&calibProp.ratio!=null)?calibProp.ratio.toFixed(3):"",
      s?hazardSourceOf(s,scenario):""].join(",")+"\n";
  });
  dlFile("clam_tcor_portfolio_"+scenario+".csv",csv);
  toast("Portfolio TCOR exported ("+c.rows.length+" sites, "+scenario+")");
}
function exportDecisionListCsv(){
  if(!sites.length){toast("Load a portfolio first.");return;}
  const c=cmdCtx();
  const cols=["rank","name","brand","scenario","tcor_total_usd","dominant_component",
    "top_climate_driver","driver_gross_ead_usd","top_opportunity","opportunity_averted_usd_per_yr",
    "opportunity_cost_usd","opportunity_payback_years","premium_allocated_usd","confidence","hazard_source"];
  let csv=cols.join(",")+"\n";
  c.rows.forEach((r,i)=>{
    csv+=[i+1,csvCell(r.name),csvCell(r.brand||""),scenario,r.total.toFixed(0),
      TCOR_COMP_BY[r.domComp].label.toLowerCase().replace(/[^a-z]+/g,"_"),
      r.driver,r.driverEad.toFixed(0),
      r.opp?csvCell(r.opp.name):"",r.opp?r.opp.averted.toFixed(0):"",
      r.opp?r.opp.cost.toFixed(0):"",
      (r.opp&&r.opp.payback!=null)?r.opp.payback.toFixed(2):"",
      r.premAllocated.toFixed(0),
      r.estimate?"estimate":"complete",
      r.site?hazardSourceOf(r.site,scenario):""].join(",")+"\n";
  });
  dlFile("clam_decision_list_"+scenario+".csv",csv);
  toast("Decision list exported ("+c.rows.length+" rows, "+scenario+")");
}
function exportComponentBreakdownCsv(){
  if(!sites.length){toast("Load a portfolio first.");return;}
  const c=cmdCtx();
  let csv="metric,component,value_usd_per_yr,scenario,basis\n";
  const add=(m,k,v,b)=>{csv+=[m,k,(+v).toFixed(0),scenario,csvCell(b||"")].join(",")+"\n";};
  TCOR_COMPONENTS.forEach(cc=>add("tcor_component",cc.key,c.portComp[cc.key],cc.label));
  add("tcor_total","total",c.tp.total,"five components above");
  add("expected_year","total",c.expectedYear,"mean annual TCOR");
  add("bad_year_p99","total",c.badYear,"retained property at p99 simulated year; BI and fixed at expected level");
  add("gross_modeled_loss","gross",c.tp.waterfall.gross,"property + BI before insurance");
  add("transferred","transfer",c.tp.waterfall.transferredProperty+c.tp.waterfall.transferredBI,"to the insurer");
  add("indirect_flagged","indirect",c.tp.indirect.value,"flagged estimate, excluded from TCOR");
  csv+=["confidence_pct","confidence",(c.confidence*100).toFixed(1),scenario,"share of TCOR backed by complete data"].join(",")+"\n";
  dlFile("clam_tcor_components_"+scenario+".csv",csv);
  toast("Component breakdown exported ("+scenario+")");
}
function exportSiteTcorCsv(id){
  const c=cmdCtx(); const r=c&&c.rows.find(x=>x.id===id);
  if(!r){toast("Open a site first.");return;}
  const w=siteWaterfall(c,id);
  let csv="section,field,value,unit,basis\n";
  const row=(sec,f,v,u,b)=>{csv+=[sec,csvCell(f),typeof v==="number"?v.toFixed(0):csvCell(v),u||"",csvCell(b||"")].join(",")+"\n";};
  row("site","name",r.name,"","");row("site","scenario",scenario,"",scenLabelPlain(scenario));
  row("waterfall","gross_modeled_loss",w.grossProp,"usd_per_yr","before insurance");
  row("waterfall","transferred",w.transferred,"usd_per_yr","to the insurer");
  row("waterfall","retained_property",w.retProp,"usd_per_yr",r.row.components.retainedProperty.basis);
  row("waterfall","frequency_layer",w.freq,"usd_per_yr","frequent band within retained property");
  row("waterfall","retained_bi",w.biRetained,"usd_per_yr",r.row.components.retainedBI.basis);
  row("waterfall","premium",w.prem,"usd_per_yr",r.premBasis);
  row("waterfall","admin_risk_control",w.admin,"usd_per_yr","allocated by TIV");
  row("waterfall","tcor_total",w.tcor,"usd_per_yr",r.estimate?"estimate":"complete");
  ACUTE.forEach(hz=>{const s=sites.find(x=>x.id===id);
    row("driver",HAZARD_LABEL[hz],hzSite(s,hz,scenario).ead,"usd_per_yr_gross_ead","hazard engine");});
  const s2=sites.find(x=>x.id===id);
  const sBase=adaptedFinSite(s2,scenario,{}).totalAal;
  MEASURES.filter(m=>m.inScope(s2,scenario)).forEach(m=>{
    const st=adapt.m[m.key];
    const averted=sBase-adaptedFinSite(s2,scenario,m.mods(st)).totalAal;
    const cost=m.siteCost(s2,st);
    row("opportunity",m.name,averted,"usd_per_yr_averted","cost "+cost.toFixed(0)+", bcr "+(cost>0?(averted*c.af/cost).toFixed(2):"0"));
  });
  r.missing.forEach(m=>row("quality","missing",m,"",""));
  dlFile("clam_site_tcor_"+String(r.name).replace(/[^a-z0-9]+/gi,"_").toLowerCase()+"_"+scenario+".csv",csv);
  toast("Site TCOR exported: "+r.name);
}
function exportSiteTcorJson(id){
  const c=cmdCtx(); const r=c&&c.rows.find(x=>x.id===id);
  if(!r){toast("Open a site first.");return;}
  const s=sites.find(x=>x.id===id);
  const out={name:r.name,scenario,scenario_label:scenLabelPlain(scenario),
    generated:new Date().toISOString(),
    tcor:r.row,waterfall:siteWaterfall(c,id),
    drivers:ACUTE.map(hz=>({peril:hz,gross_ead_usd:hzSite(s,hz,scenario).ead})),
    calibration:c.calib?{portfolio:c.calib.perClass,disagreements:c.calib.disagreements}:null,
    provenance:{hazard_source:hazardSourceOf(s,scenario),
      confidence:r.estimate?"estimate":"complete",missing:r.missing}};
  dlFile("clam_site_tcor_"+String(r.name).replace(/[^a-z0-9]+/gi,"_").toLowerCase()+"_"+scenario+".json",
    JSON.stringify(out,null,2),"application/json");
  toast("Site detail exported: "+r.name);
}

/* ---- Advanced mode toggle (the classic workspace, one action away) ---- */
function applyAdvancedMode(){
  try{
    document.body.classList.toggle("advmode",!!(ui&&ui.advanced));
    const b=document.getElementById("advancedBtn");
    if(b&&b.setAttribute){b.setAttribute("aria-pressed",(ui&&ui.advanced)?"true":"false");
      b.textContent=(ui&&ui.advanced)?"← Command view":"Advanced";}
    if(ui&&ui.advanced&&typeof map!=="undefined"&&map&&mapOk)setTimeout(()=>{try{map.invalidateSize();}catch(e){}},80);
  }catch(e){}
}
function setAdvancedMode(on){
  if(ui)ui.advanced=!!on;
  if(typeof persist==="function")persist();
  applyAdvancedMode();
  render();
}

/* ---- plain-language explanations for the new surfaces ---- */
Object.assign(INFO,{
  cmdTcor:{t:"Total cost of risk (TCOR)",b:
    "<p>What climate risk actually costs per year, all in: <b>retained property loss</b> (the deductible side of damage, with the hurricane deductible shared per campus per occurrence) + <b>retained business interruption</b> (waiting periods and losses beyond the BI limit) + <b>allocated premium</b> + the <b>frequency layer</b> (small events tripping deductibles across the portfolio) + <b>admin and risk-control spend</b>.</p>"+
    "<p>The stacked bar splits the total into those five parts, in the same colours everywhere they appear. Hover any part for its derivation. Indirect costs (rebooking, reputation) are a flagged estimate and are never inside the total.</p>",
    s:"Engine: event-level retained math for hurricane, per-location ladders for the rest; every figure carries its basis."},
  cmdBadYear:{t:"Expected year vs bad year",b:
    "<p><b>Expected year</b> is the mean annual TCOR: the long-run average bill. <b>Bad year</b> is what a roughly 1-in-100 year looks like: retained property at the 99th percentile of the engine's seeded 1000-year simulation (which replays the modeled hurricane event table with the shared deductible), with BI, premium, and fixed costs at expected level.</p>"+
    "<p>The BI side of a bad year (a season that blows through the BI limit) arrives with the full BI module; until then this figure is a labeled partial view, honest rather than precise.</p>"},
  cmdConfidence:{t:"Portfolio confidence",b:
    "<p>The share of the TCOR total that stands on <b>complete data</b>: sites where no component needed a default or interim fallback (campus code present, revenue on file, BI limit known, actual premium on file, policy terms confirmed).</p>"+
    "<p>Everything else is still shown, but marked <b>est</b> in the list and on its site view, with the exact missing fields named. Estimates are never silently rendered as precise.</p>"},
  cmdLens:{t:"Renewal vs capital framing",b:
    "<p>The same data, framed for the two decisions. <b>Renewal</b> (present day, 1 to 3 years): premium and retention lead; the list shows each site's allocated premium against the technical benchmark and its retained total. <b>Capital</b> (multi-decade): adaptation leads; the list shows each site's best measure and payback at the selected horizon.</p>"+
    "<p>Switching the framing never changes a computed figure, only which columns lead.</p>"},
  wfTeach:{t:"The TCOR waterfall",b:
    "<p>Start at the <b>gross modeled property loss</b>: what the climate event sets say the buildings lose per year before any insurance. Subtract the <b>transferred</b> portion the insurance program pays. What remains is <b>retained property</b> (with the frequent attritional band shown in green). Add <b>retained BI</b>, the <b>allocated premium</b>, and <b>admin</b>, and you arrive at <b>TCOR</b>: what TNL actually pays.</p>"+
    "<p>This one figure is the thesis of the tool: most of the gross number is transferred; the cost that stays is BI plus premium plus a sliver of retained damage. Hover any bar for its exact derivation and basis.</p>"},
  svOpp:{t:"Opportunities",b:
    "<p>The site's in-scope adaptation measures, appraised by the engine: annual loss averted, one-time cost, simple payback, and the benefit-cost ratio at the current appraisal settings (Advanced &#8594; Adaptation).</p>"+
    "<p>Costs are planning-grade defaults from published mitigation studies: firm enough to rank, to be replaced with engineering estimates before committing capital. The TCOR-aware split (certain retained saving vs negotiated premium saving, with and without the premium credit) arrives with the payoff module and is flagged until then.</p>"},
});
