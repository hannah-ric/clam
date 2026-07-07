/* ============================================================
   Executive home (v2.3.0): the one-minute view.
   A full-bleed map, Google-Maps-style, with floating panels: the
   headline annual climate cost, three decision tiles (tail, tolerance
   position, largest driver), a cost trajectory, the peril mix, and the
   ranked top priorities with their best value actions. A timeline pill
   walks the whole app through Present to 2080; a colour bar switches
   what the markers encode.

   Pure display layer over the shared engine: every figure here is read
   from functions the analyst workspace already runs (finPortfolio,
   aggregatePortfolio, decisionRows, toleranceFlags, scorePhysTotal),
   so the executive view can never disagree with the specialist tabs.
   Drill-downs land on surfaces that already existed: the site
   scorecard (with its why-these-numbers trace), the analyst tabs, and
   the consolidated Export menu in the top bar.
   ============================================================ */
const EXEC_PATHWAY_NAME={ssp126:"low emissions",ssp245:"middle path",ssp585:"high emissions"};
const EXEC_PERIL_SHORT={tc:"Wind",cflood:"Coastal flood",rflood:"River flood",heat:"Heat",wfire:"Wildfire",prain:"TC rain"};

function execModeOn(){ return !!(ui&&ui.execMode); }
function applyExecMode(){
  document.body.classList.toggle("execmode",execModeOn());
  const be=document.getElementById("modeExec"),ba=document.getElementById("modeAnalyst");
  if(be&&be.setAttribute)be.setAttribute("aria-pressed",execModeOn()?"true":"false");
  if(ba&&ba.setAttribute)ba.setAttribute("aria-pressed",execModeOn()?"false":"true");
  // the map keeps its centre when the layout swaps between hero and inset
  if(typeof map!=="undefined"&&map&&mapOk)setTimeout(()=>{try{map.invalidateSize();}catch(e){}},80);
}
function setExecMode(on){ ui.execMode=!!on; persist(); applyExecMode(); render(); }
function closeExportMenu(){
  const em=document.getElementById("exportMenu"),emb=document.getElementById("exportMenuBtn");
  if(em&&em.classList)em.classList.remove("open");
  if(emb&&emb.setAttribute)emb.setAttribute("aria-expanded","false");
}

/* zoom the hero map to one site; honours prefers-reduced-motion */
function execFlyTo(id){
  const s=sites.find(x=>x.id===id); if(!s||!mapOk)return;
  const z=Math.max((map.getZoom&&map.getZoom())||4,11);
  let reduce=false;
  try{reduce=window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches;}catch(e){}
  try{ if(reduce)map.setView([s.latitude,s.longitude],z); else map.flyTo([s.latitude,s.longitude],z,{duration:1.1}); }catch(e){}
}

/* exec timeline controls: thin wrappers over the shared scrubber so the
   top-bar selects, the Summary-tab scrubber, and this pill can never drift */
function execScrubTo(i){ stopScrub(); scrubTo(i); }
function execSetPathway(v){
  stopScrub();
  const ps=document.getElementById("pathSel"); if(ps)ps.value=v;
  if(scenario!=="present"){
    const hor=scenario.split("_")[1]||"2050";
    scenario=v+"_"+hor;
  }
  persist(); if(scenHook)scenHook(); render();
}
function execSetMapColor(m){
  ui.views.mapColor=m;
  const sel=document.getElementById("mapColorSel"); if(sel)sel.value=m;
  persist(); render();
}
function execSetHazard(v){
  activeHazard=v;
  const sel=document.getElementById("hazSel"); if(sel)sel.value=v;
  persist(); render();
}

/* the ranked priorities: the portfolio's all-in cost concentration, joined
   with the decision view's dominant peril, best measure, and model basis */
function execPriorities(n){
  const af=tolAf();
  const f=finPortfolio(sites,scenario);
  const dr={};decisionRows(sites,scenario,af).forEach(r=>{dr[r.id]=r;});
  const bands={};scorePhysTotal(sites,scenario).rows.forEach(r=>{bands[r.id]=r.band;});
  const tf=toleranceFlags(sites,scenario,af);
  const breach={};tf.siteBreaches.forEach(b=>{breach[b.id]=true;});
  const rows=f.rows.slice().sort((a,b)=>b.totalAal-a.totalAal).slice(0,n).map(r=>{
    const d=dr[r.id]||{};
    return {id:r.id,name:r.name,brand:r.brand,cost:r.totalAal,dom:d.dom||"tc",
      measure:d.measure||null,bcr:d.bcr||0,trustModeled:d.trustModeled||0,
      trustTotal:d.trustTotal||HAZARDS.length,band:bands[r.id]||"Minimal",breach:!!breach[r.id]};
  });
  return {rows,tf,f};
}

/* cost trajectory sparkline: Present to 2080 under the current pathway.
   Single series, so no legend; the endpoints carry the only direct labels
   and every step keeps a hover title. Baseline is zero (honest area). */
function execSparkSvg(steps,vals,curIdx){
  const W=374,H=98,padL=10,padR=10,padT=16,padB=24;
  const maxV=Math.max(1,Math.max.apply(null,vals));
  const X=i=>padL+22+(i/(Math.max(1,steps.length-1)))*(W-padL-padR-44);
  const Y=v=>H-padB-(v/maxV)*(H-padB-padT);
  let area="M"+X(0)+" "+(H-padB)+" ";
  vals.forEach((v,i)=>{area+="L"+X(i)+" "+Y(v)+" ";});
  area+="L"+X(vals.length-1)+" "+(H-padB)+" Z";
  let line="";vals.forEach((v,i)=>{line+=(i?"L":"M")+X(i)+" "+Y(v)+" ";});
  let s='<svg viewBox="0 0 '+W+' '+H+'" width="100%" height="'+H+'" preserveAspectRatio="xMidYMid meet" role="img" '+
    'aria-label="Expected annual cost from '+esc(steps[0].label)+' to '+esc(steps[steps.length-1].label)+': '+
    fmt$(vals[0])+' rising to '+fmt$(vals[vals.length-1])+'">';
  s+='<path d="'+area+'" fill="rgba(15,58,75,.09)"/>';
  s+='<path d="'+line+'" fill="none" stroke="#0F3A4B" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>';
  vals.forEach((v,i)=>{
    const cur=i===curIdx;
    s+='<circle cx="'+X(i)+'" cy="'+Y(v)+'" r="'+(cur?5:4)+'" fill="'+(cur?"#1E7FA6":"#0F3A4B")+'" stroke="#fff" stroke-width="2">'+
       '<title>'+esc(steps[i].label)+': '+fmt$(v)+'/yr</title></circle>';
    s+='<text x="'+X(i)+'" y="'+(H-8)+'" text-anchor="middle" font-size="10" fill="'+(cur?"#15202B":"#7A8893")+'"'+(cur?' font-weight="600"':'')+'>'+esc(steps[i].label)+'</text>';
  });
  // direct labels on the two endpoints only; the titles carry the rest
  s+='<text x="'+X(0)+'" y="'+(Y(vals[0])-9)+'" text-anchor="start" font-size="10.5" fill="#43535F" class="mono">'+fmt$(vals[0])+'</text>';
  s+='<text x="'+X(vals.length-1)+'" y="'+(Y(vals[vals.length-1])-9)+'" text-anchor="end" font-size="10.5" fill="#15202B" font-weight="600" class="mono">'+fmt$(vals[vals.length-1])+'</text>';
  s+='</svg>';
  return s;
}

/* peril mix: one part-to-whole bar (2px surface gaps between segments) plus
   a legend naming every segment, so identity never rides on colour alone */
function execMixHtml(byPeril,total){
  const items=Object.keys(byPeril).map(k=>({k,v:byPeril[k]})).filter(i=>i.v>0).sort((a,b)=>b.v-a.v);
  if(!items.length)return '<div class="execnote">No annual cost at this scenario.</div>';
  const tot=items.reduce((a,i)=>a+i.v,0)||1;
  let h='<div style="display:flex;gap:2px;height:14px;border-radius:7px;overflow:hidden" role="img" aria-label="'+
    esc(items.map(i=>EXEC_PERIL_SHORT[i.k]+" "+(i.v/tot*100).toFixed(0)+"%").join(", "))+'">';
  items.forEach(i=>{
    h+='<div style="flex:'+(i.v/tot).toFixed(4)+' 1 0%;background:'+HAZARD_BY[i.k].color+'" title="'+
      esc(HAZARD_LABEL[i.k])+': '+fmt$(i.v)+'/yr ('+(i.v/tot*100).toFixed(0)+'%)"></div>';
  });
  h+='</div><div style="display:grid;grid-template-columns:1fr 1fr;gap:3px 12px;margin-top:7px;font-size:11.5px;color:var(--ink-2)">';
  items.forEach(i=>{
    const pct=i.v/tot*100;
    h+='<span><span class="perildot" style="background:'+HAZARD_BY[i.k].color+'"></span>'+
      esc(EXEC_PERIL_SHORT[i.k])+' <span class="mono">'+(pct<0.5?"&lt;1":pct.toFixed(0))+'% · '+fmt$(i.v)+'</span></span>';
  });
  h+='</div>';
  return h;
}

function renderExecHome(){
  const panel=document.getElementById("execPanel"); if(!panel)return;
  if(!execModeOn())return;
  const empty=document.getElementById("execEmpty"),layer=document.getElementById("execLayerbar"),time=document.getElementById("execTimebar");
  const has=sites.length>0;
  if(empty)empty.style.display=has?"none":"flex";
  panel.style.display=has?"flex":"none";
  if(layer)layer.style.display=has?"flex":"none";
  if(time)time.style.display=has?"flex":"none";
  if(!has)return;
  let focusId=null;
  try{focusId=(document.activeElement&&document.activeElement.id)||null;}catch(e){}

  const p=execPriorities(5), f=p.f, tf=p.tf;
  const agg=aggregatePortfolio(sites,scenario);
  const pathway=currentPathway();
  const curLabel=SCEN_LABEL[scenario]||scenario;

  /* headline delta: at Present, the projection to 2050 under the chosen
     pathway; at a future scenario, the change against today */
  let delta,deltaPct,deltaLabel;
  if(scenario==="present"){
    const ff=finPortfolio(sites,pathway+"_2050");
    delta=ff.totalAal-f.totalAal;deltaPct=f.totalAal?delta/f.totalAal*100:0;
    deltaLabel="by 2050, "+(EXEC_PATHWAY_NAME[pathway]||pathway);
  }else{
    const pf=finPortfolio(sites,"present");
    delta=f.totalAal-pf.totalAal;deltaPct=pf.totalAal?delta/pf.totalAal*100:0;
    deltaLabel="vs present day";
  }
  const easing=delta<0;
  const deltaChip='<span class="execdelta'+(easing?" easing":"")+'" title="How the expected annual cost moves with warming">'+
    (easing?"▼ ":"▲ +")+fmt$(Math.abs(delta))+"/yr ("+(easing?"":"+")+deltaPct.toFixed(0)+"%) "+esc(deltaLabel)+'</span>';

  const live=hazardGrid?perilAuthority().filter(a=>a.live).length:0;
  const basis=hazardGrid
    ?'<button type="button" class="execbasis authoritative" id="execBasisBtn" title="Running on your loaded climate data. Click for the full provenance record."><span class="dot"></span>'+live+' of '+HAZARDS.length+' perils on loaded data</button>'
    :'<button type="button" class="execbasis" id="execBasisBtn" title="Built-in screening estimates; good for exploration, not disclosure. Click to load climate data."><span class="dot"></span>Built-in estimates</button>';

  const varRef=f.jointTail?f.jointTail.var100:f.var100;
  const tailBasis=f.jointTail?"joint event tail":"upper-bound blend";
  const nBr=tf.siteBreaches.length;
  const tolTile=nBr
    ?'<div class="exectile alert" title="'+esc(tf.siteBreaches.map(b=>b.name).join(", "))+'"><div class="l">Over tolerance</div><div class="v">'+nBr+' site'+(nBr>1?"s":"")+'</div><div class="f">past your stated line</div></div>'
    :(tf.anyBreach
      ?'<div class="exectile alert"><div class="l">Over tolerance</div><div class="v">Portfolio</div><div class="f">total past your stated line</div></div>'
      :'<div class="exectile"><div class="l">Tolerance</div><div class="v">In position</div><div class="f">no thresholds breached</div></div>');
  const perilArr=Object.keys(agg.byPeril).map(k=>[k,agg.byPeril[k]]).sort((a,b)=>b[1]-a[1]);
  const domK=perilArr[0][0], domShare=agg.total?perilArr[0][1]/agg.total*100:0;

  const steps=scrubSteps(), vals=steps.map(st=>finPortfolio(sites,st.sc).totalAal), curIdx=scrubIndex();

  let h='<div class="exechead">'+
    '<div class="execkicker">Expected annual climate cost'+infoBtn("execHome")+' <span style="flex:1"></span>'+basis+'</div>'+
    '<div class="exechero">'+fmt$(f.totalAal)+'<span class="unit">/yr</span></div>'+
    '<div class="execsub">'+f.aalPctValue.toFixed(2)+'% of '+fmt$(f.value)+' insured value · '+sites.length+' site'+(sites.length>1?"s":"")+' · '+esc(curLabel)+'</div>'+
    deltaChip+
    '</div>';
  h+='<div class="scrollbody">';
  h+='<div class="exectiles">'+
    '<div class="exectile" title="What a 1-in-100 year would cost the whole portfolio ('+esc(tailBasis)+')"><div class="l">1-in-100 year</div><div class="v">'+fmt$(varRef)+'</div><div class="f">'+(f.value?(varRef/f.value*100).toFixed(0):0)+'% of value · '+esc(tailBasis)+'</div></div>'+
    tolTile+
    '<div class="exectile" title="'+esc(HAZARD_LABEL[domK])+' drives '+domShare.toFixed(0)+'% of the expected annual cost"><div class="l">Largest driver</div><div class="v">'+esc(EXEC_PERIL_SHORT[domK]||domK)+'</div><div class="f">'+domShare.toFixed(0)+'% of annual cost</div></div>'+
    '</div>';
  h+='<div class="execsec">How the cost grows · '+esc(PATHWAY_LABEL[pathway]||pathway)+'</div>'+execSparkSvg(steps,vals,curIdx);
  h+='<div class="execsec">Where it comes from</div>'+execMixHtml(agg.byPeril,agg.total);
  h+='<div class="execsec">Top priorities</div>';
  h+='<ol class="prio">';
  p.rows.forEach(r=>{
    const full=r.trustModeled===r.trustTotal;
    h+='<li>'+
      '<button type="button" class="priobtn" data-exfocus="'+(+r.id)+'" aria-label="Open the scorecard for '+esc(r.name)+'">'+
      '<span class="priotop"><span class="nm">'+esc(r.name)+'</span><span class="cost">'+fmt$(r.cost)+'/yr</span></span>'+
      '<span class="priometa">'+
        (r.breach?'<span class="tolbreach" title="Over your stated risk tolerance"></span>':"")+
        '<span title="Dominant peril at this site"><span class="perildot" style="background:'+(HAZARD_BY[r.dom]?HAZARD_BY[r.dom].color:"#7A8893")+'"></span>'+esc(HAZARD_LABEL[r.dom]||r.dom)+'</span>'+
        '<span class="pill mini '+esc(r.band)+'">'+esc(r.band)+'</span>'+
        '<span class="mono" style="font-size:10px;color:'+(full?"var(--ink-2)":"#8A4A1B")+'" title="'+r.trustModeled+' of '+r.trustTotal+' perils modeled at this site; the scorecard trust strip has the detail">'+r.trustModeled+'/'+r.trustTotal+' modeled</span>'+
      '</span>'+
      (r.measure
        ?'<span class="prioact">Best value: <b>'+esc(r.measure)+' · BCR '+r.bcr.toFixed(1)+'x</b></span>'
        :'<span class="prioact">No priced measure in scope; see the adaptation tab</span>')+
      '</button>'+
      '<button type="button" class="priolocate" data-exfly="'+(+r.id)+'" title="Zoom the map to '+esc(r.name)+'" aria-label="Zoom the map to '+esc(r.name)+'">◎</button>'+
      '</li>';
  });
  h+='</ol>';
  if(sites.length>p.rows.length)h+='<div class="execnote">Ranked by all-in annual cost (damage, interruption, heat); the analyst workspace ranks all '+sites.length+' sites with every column.</div>';
  h+='<div class="execnote">'+(hazardGrid
    ?"Running on your loaded CLIMADA data ("+live+" of "+HAZARDS.length+" perils); perils still on the built-in estimate are labelled wherever they appear."
    :"Exploring with built-in screening estimates: good for a first look, not for disclosure. Load your climate data via the analyst workspace's Method &amp; data tab.")+'</div>';
  h+='</div>';
  h+='<div class="execactions">'+
    '<button type="button" class="lightbtn primary" id="execFullBtn">Open full analysis</button>'+
    '<button type="button" class="lightbtn" id="execBriefBtn">Board brief (PDF)</button>'+
    '</div>';
  panel.innerHTML=h;
  panel.querySelectorAll("[data-exfocus]").forEach(b=>b.onclick=()=>openScorecard(+b.dataset.exfocus));
  panel.querySelectorAll("[data-exfly]").forEach(b=>b.onclick=()=>execFlyTo(+b.dataset.exfly));
  const fb=document.getElementById("execFullBtn"); if(fb)fb.onclick=()=>setExecMode(false);
  const bb=document.getElementById("execBriefBtn"); if(bb)bb.onclick=openBrief;
  const eb=document.getElementById("execBasisBtn"); if(eb)eb.onclick=()=>{setExecMode(false);switchTab("method");};

  /* the timeline pill: Present to 2080 plus the emissions outlook */
  if(time){
    let t='<span class="timelabel">Timeline</span>';
    t+=steps.map((st,i)=>'<button type="button" class="timestep'+(i===curIdx?" cur":"")+'" data-exscrub="'+i+'" aria-pressed="'+(i===curIdx?"true":"false")+'">'+esc(st.label)+'</button>').join("");
    t+='<select class="execsel" id="execPathSel" aria-label="Emissions outlook for the future steps" '+
      'title="Which IPCC emissions future the 2030-2080 steps assume: low '+esc(PATHWAY_LABEL.ssp126)+', middle '+esc(PATHWAY_LABEL.ssp245)+', high '+esc(PATHWAY_LABEL.ssp585)+'">'+
      ["ssp126","ssp245","ssp585"].map(k=>'<option value="'+k+'"'+(pathway===k?" selected":"")+'>'+esc(EXEC_PATHWAY_NAME[k].replace(/^./,c=>c.toUpperCase()))+'</option>').join("")+
      '</select>';
    t+='<button type="button" class="timeplay" id="execPlay" title="Walk the portfolio from Present to 2080">'+(scrubTimer?"■ Stop":"▶ Play")+'</button>';
    time.innerHTML=t;
    time.querySelectorAll("[data-exscrub]").forEach(b=>b.onclick=()=>execScrubTo(+b.dataset.exscrub));
    const psel=document.getElementById("execPathSel"); if(psel)psel.onchange=e=>execSetPathway(e.target.value);
    const pl=document.getElementById("execPlay"); if(pl)pl.onclick=playScrub;
  }

  /* the colour bar: what the markers encode */
  if(layer){
    const mode=ui.views.mapColor;
    let l='<span class="timelabel">Colour</span>'+
      [["combined","Combined risk"],["dominant","Dominant peril"],["peril","One peril"]].map(([k,lab])=>
        '<button type="button" class="layerchip" data-exmap="'+k+'" aria-pressed="'+(mode===k?"true":"false")+'">'+lab+'</button>').join("");
    if(mode==="peril"){
      l+='<select class="execsel" id="execHazSel" aria-label="Which peril colours the markers">'+
        HAZARDS.map(hz=>'<option value="'+hz.key+'"'+(activeHazard===hz.key?" selected":"")+'>'+esc(hz.label)+'</option>').join("")+'</select>';
    }
    layer.innerHTML=l;
    layer.querySelectorAll("[data-exmap]").forEach(b=>b.onclick=()=>execSetMapColor(b.dataset.exmap));
    const hsel=document.getElementById("execHazSel"); if(hsel)hsel.onchange=e=>execSetHazard(e.target.value);
  }

  if(focusId){try{const el=document.getElementById(focusId);if(el&&typeof el.focus==="function")el.focus();}catch(e){}}
}
