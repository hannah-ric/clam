function render(){
  hideInfo();
  const hasData=sites.length>0;
  document.getElementById("emptyState").style.display=hasData?"none":"block";
  document.getElementById("overviewBody").style.display=hasData?"block":"none";
  document.getElementById("sumEmpty").style.display=hasData?"none":"block";
  document.getElementById("summaryBody").style.display=hasData?"block":"none";
  const scored=scoreHazard(sites,activeHazard,scenario);
  drawMarkers(scored);
  if(hasData){ renderOverview(scored); }
  renderDecision();
  renderSummary();
  renderRiskMatrix();
  renderQuadrant();
  renderTolerance();
  renderScrub();
  renderSites();
  renderAdaptation();
  renderScenarios();
  renderFinance();
  renderBacktest();
  renderHazProv();
  renderResultsPack();
  renderExecHome();
}
/* Task 6: the ranked decision view (the Summary tab's landing artifact).
   Sortable by any column; a row click opens the scorecard, which carries the
   why-these-numbers trace. Physical units lead; the qualitative bands stay
   on the ratings surfaces. */
let decisionSort={key:"ead",dir:-1};
function renderDecision(){
  const host=document.getElementById("decisionHost"); if(!host)return;
  if(!sites.length){host.innerHTML="";const p=document.getElementById("decisionPanel");if(p)p.style.display="none";return;}
  const p=document.getElementById("decisionPanel");if(p)p.style.display="block";
  const rows=decisionRows(sites,scenario,tolAf());
  /* act-by (v2.3.0): the tolerance-crossing horizon, shared with the
     executive plan so the two surfaces state the same deadline */
  rows.forEach(r=>{const s=sites.find(x=>x.id===r.id);const u=execUrgency(s);
    r.actBy=u.label;r.actByOrd=u.when==="now"?0:(u.horizon||9999);});
  const k=decisionSort.key,d=decisionSort.dir;
  rows.sort((a,b)=>{const va=a[k],vb=b[k];
    return (typeof va==="string"||typeof vb==="string")
      ?d*String(va||"").localeCompare(String(vb||""))
      :d*((va||0)-(vb||0));});
  const perilName=k=>k==="heat"?"Extreme heat":HAZARD_LABEL[k]||k;
  const th=(label,key,num)=>'<th'+(num?' class="num"':'')+' data-dsort="'+key+'" style="cursor:pointer" title="click to rank by '+label+'">'+label+(decisionSort.key===key?(decisionSort.dir<0?" ↓":" ↑"):"")+'</th>';
  let h='<table class="tbl"><thead><tr>'+
    th("Site","name")+th("Dominant peril","dom")+
    th("1-in-100 damage","dmg100",1)+th("EAD $/yr","ead",1)+
    th("Flood depth @100 (m)","depth100",1)+th("Downtime @100 (days)","downtime100",1)+
    th("Top measure","measure")+th("BCR","bcr",1)+
    th("Act by","actByOrd",1)+
    th("Basis","trustModeled",1)+'</tr></thead><tbody>';
  rows.forEach(r=>{
    h+='<tr class="rowclick" data-focus="'+r.id+'"><td>'+esc(r.name)+'</td>'+
      '<td>'+esc(perilName(r.dom))+'</td>'+
      '<td class="num mono">'+fmt$(r.dmg100)+'</td>'+
      '<td class="num mono">'+fmt$(r.ead)+'</td>'+
      '<td class="num mono">'+(r.depth100>0?r.depth100.toFixed(2):"\u2014")+'</td>'+
      '<td class="num mono">'+(r.downtime100>0?Math.round(r.downtime100):"\u2014")+'</td>'+
      '<td>'+(r.measure?esc(r.measure):'<span class="hint">none in scope</span>')+'</td>'+
      '<td class="num mono" style="color:'+(r.bcr>=1?"#2E8B6F":"#B23A32")+'">'+(r.measure?r.bcr.toFixed(2)+"x":"\u2014")+'</td>'+
      '<td class="num"><span class="whenchip '+(r.actByOrd===0?"now":(r.actByOrd===9999?"monitor":"soon"))+'">'+esc(r.actBy)+'</span></td>'+
      '<td class="num"><span class="pill mini" data-trust="'+(r.trustModeled===r.trustTotal?"modeled":"degraded")+'" style="background:'+(r.trustModeled===r.trustTotal?"var(--r-low)":"var(--r-min)")+'" title="'+r.trustModeled+' of '+r.trustTotal+' perils modeled at this site (see the trust strip on the scorecard)">'+r.trustModeled+'/'+r.trustTotal+'</span></td></tr>';
  });
  h+='</tbody></table>';
  host.innerHTML=h;
  host.querySelectorAll("th[data-dsort]").forEach(el=>el.onclick=()=>{
    const key=el.dataset.dsort;
    if(decisionSort.key===key)decisionSort.dir*=-1;
    else decisionSort={key,dir:(key==="name"||key==="dom"||key==="measure")?1:-1};
    renderDecision();
  });
  host.querySelectorAll("tr[data-focus]").forEach(tr=>tr.onclick=()=>openScorecard(+tr.dataset.focus));
}
function renderSummary(){
  const host=document.getElementById("sumKpis"); if(!host)return;
  if(!sites.length){return;}
  const f=finPortfolio(sites,scenario);
  const agg=aggregatePortfolio(sites,scenario);
  const pathway=currentPathway();
  const futureSc=(scenario!=="present")?scenario:(pathway+"_2050");
  const pf=finPortfolio(sites,"present"), ff=finPortfolio(sites,futureSc);
  const premium=ff.totalAal-pf.totalAal, premiumPct=pf.totalAal?premium/pf.totalAal*100:0;
  const futLabel=SCEN_LABEL[futureSc]||futureSc, curLabel=SCEN_LABEL[scenario]||scenario;
  document.getElementById("sumSub").innerHTML="Every peril and every cost type in one view, at "+esc(curLabel)+". "+(hazardGrid?"Using the loaded CLIMADA grid.":"Interim screening model.");
  const db=document.getElementById("dataBanner");
  if(db){
    if(hazardGrid){
      const live=perilAuthority().filter(a=>a.live).length;
      db.style.borderLeftColor="#2E8B6F";
      db.innerHTML="<b>Running on your loaded climate data</b> ("+live+" of "+HAZARDS.length+" perils authoritative). These figures are disclosure-grade for those perils; any peril still on the built-in estimate is labelled where it appears.";
    }else{
      db.style.borderLeftColor="#E0A43B";
      db.innerHTML="<b>You are exploring with built-in estimates.</b> Good for a first look, not for disclosure. To sharpen every number, load your climate data on the Method and data tab (or ask your analytics team for the CLIMADA grid).";
    }
  }
  const card=(l,v,foot,info)=>'<div class="card"><div class="l">'+l+(info?infoBtn(info):"")+'</div><div class="v" style="font-size:22px">'+v+'</div><div class="foot">'+foot+'</div></div>';
  const u=uncRange(sites,scenario);
  host.innerHTML=
    card("Insured value",fmt$(f.value),sites.length+" site"+(sites.length>1?"s":""),"")+
    card("Expected annual cost",fmt$(f.totalAal)+"/yr",f.aalPctValue.toFixed(2)+"% of value \u00b7 range "+fmt$(u.low)+" to "+fmt$(u.high),"totalAal")+
    (f.jointTail
      ?card("1-in-100 Value at Risk",fmt$(f.jointTail.var100),(f.value?f.jointTail.var100/f.value*100:0).toFixed(1)+"% of value · "+TAIL_JOINT_LABEL+" · live blend incl. BI: "+fmt$(f.var100),"var100")
      :card("1-in-100 Value at Risk",fmt$(f.var100),(f.value?f.var100/f.value*100:0).toFixed(1)+"% of value · "+TAIL_BOUND_LABEL,"var100"))+
    card("Climate premium","+"+fmt$(premium)+"/yr","by "+esc(futLabel)+", "+(premiumPct>=0?"+":"")+premiumPct.toFixed(0)+"% vs today","premium");
  const perilName={tc:"Tropical cyclone wind",cflood:"Coastal flood",rflood:"Riverine flood",heat:"Extreme heat",wfire:"Wildfire",prain:"TC rainfall"};
  const perilArr=Object.keys(agg.byPeril).map(k=>[k,agg.byPeril[k]]).sort((a,b)=>b[1]-a[1]);
  const dom=perilArr[0], domShare=agg.total?dom[1]/agg.total*100:0;
  const highSevere=(agg.bands.High||0)+(agg.bands.Severe||0);
  document.getElementById("sumReadout").innerHTML=
    "At "+esc(curLabel)+", the portfolio's expected annual climate cost is <b>"+fmt$(f.totalAal)+"</b> ("+f.aalPctValue.toFixed(2)+"% of value, "+f.aalPctRev.toFixed(1)+"% of revenue). A 1-in-100 year would cost about <b>"+fmt$(f.jointTail?f.jointTail.var100:f.var100)+"</b> ("+(f.value?(f.jointTail?f.jointTail.var100:f.var100)/f.value*100:0).toFixed(0)+"% of value; "+(f.jointTail?"joint event tail":"blend approximation, not the joint tail")+"). "+
    "<b>"+perilName[dom[0]]+"</b> is the largest driver at "+domShare.toFixed(0)+"% of the annual cost. "+
    "By "+esc(futLabel)+", warming lifts the annual cost to <b>"+fmt$(ff.totalAal)+"</b> ("+(premiumPct>=0?"+":"")+premiumPct.toFixed(0)+"%) and the 1-in-100 to <b>"+fmt$(ff.jointTail?ff.jointTail.var100:ff.var100)+"</b>. "+
    (highSevere?("<b>"+highSevere+"</b> of "+sites.length+" sites sit in High or Severe combined physical risk."):("No sites sit in High or Severe combined physical risk at this scenario."));
  document.getElementById("sumByPeril").innerHTML=barsSvg(perilArr.map(([k,v])=>({label:perilName[k],ead:v})),"ead","label","#0F3A4B");
  document.getElementById("sumByType").innerHTML=barsSvg([
    {label:"Physical damage",ead:agg.byType.direct},
    {label:"Business interruption",ead:agg.byType.bi},
    {label:"Extreme heat",ead:agg.byType.heat},
  ].sort((a,b)=>b.ead-a.ead),"ead","label","#12586F");
  const traj=[["Present","present"],[PATHWAY_LABEL[pathway]+" 2050",pathway+"_2050"],[PATHWAY_LABEL[pathway]+" 2080",pathway+"_2080"]];
  document.getElementById("sumTraj").innerHTML=barsSvg(traj.map(([lab,sc])=>({label:lab,ead:finPortfolio(sites,sc).totalAal})),"ead","label","#2C7DA0");
  const order=["Minimal","Low","Moderate","High","Severe"];
  const tot=order.reduce((a,b)=>a+(agg.bands[b]||0),0)||1;
  let bar='<div style="display:flex;height:26px;border-radius:6px;overflow:hidden;border:1px solid var(--line)">';
  order.forEach(b=>{const n=agg.bands[b]||0;if(n)bar+='<div title="'+b+': '+n+'" style="width:'+(n/tot*100)+'%;background:'+BAND_COLOR[b]+'"></div>';});
  bar+='</div><div class="hint" style="margin-top:8px;display:flex;flex-wrap:wrap;gap:12px">'+order.map(b=>'<span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:'+BAND_COLOR[b]+';margin-right:5px;vertical-align:middle"></span>'+b+' '+(agg.bands[b]||0)+'</span>').join("")+'</div>';
  document.getElementById("sumBands").innerHTML=bar;
  const top=agg.perSite.slice().sort((a,b)=>b.total-a.total).slice(0,6);
  document.getElementById("sumTopSites").innerHTML=barsSvg(top.map(r=>({label:r.name,ead:r.total})),"ead","label","#B23A32");
  const brands=Object.keys(agg.byBrand).map(b=>({label:b,ead:agg.byBrand[b]})).sort((a,b)=>b.ead-a.ead);
  document.getElementById("sumByBrand").innerHTML=barsSvg(brands,"ead","label","#0F3A4B");
  /* named-insured breakout: who carries the exposure across the portfolio. Only
     shown when the portfolio actually carries a named_insured field, so a
     portfolio without it is unchanged. */
  const insPanel=document.getElementById("sumInsuredPanel");
  if(insPanel){
    if(hasNamedInsured(sites)){
      insPanel.style.display="";
      const ins=insuredRollup(sites,scenario);
      document.getElementById("sumByInsured").innerHTML=
        barsSvg(ins.map(r=>({label:r.insured,ead:r.ead})),"ead","label","#6E5AA6");
    }else{ insPanel.style.display="none"; }
  }
  /* caveats only for the perils actually still on the interim model, so the
     note stops warning about proxies a loaded grid has already replaced */
  const caveats=[];
  if(!gridByHazard.cflood)caveats.push("coastal-flood depth is keyed to open-coast proximity, so sheltered below-sea-level locations can be understated");
  if(!gridByHazard.heat)caveats.push("the heat overlay is indicative");
  document.getElementById("sumNote").innerHTML=(hazardGrid?"Figures use the loaded CLIMADA grid where available. ":"Figures use the interim screening model and are for exploration, not disclosure. ")+
    (caveats.length?caveats.join(", and ").replace(/^./,c=>c.toUpperCase())+"; a CLIMADA grid sharpens "+(caveats.length>1?"both":"this")+". ":"")+
    "Financial assumptions are set on the Financial impact tab.";
}
/* SVP review: the portfolio risk matrix (a heatmap of every row against every
   peril at the current scenario, coloured by risk band). matrixRows is pure over
   hzSite / bandOf / heatBand; renderRiskMatrix only paints it. No computed figure
   changes, so the parity surface is untouched. The View and Show selects are the
   "change views" lens: regroup the rows, or switch what each cell reports. */
/* roll the portfolio up by an arbitrary key (brand or named insured) into
   matrix rows. Kept identical to the original brand branch so that view's
   output is byte-for-byte unchanged; the named-insured view reuses it. */
function matrixGroupRows(keyOf){
  const by={};
  sites.forEach(s=>{const b=keyOf(s);const g=by[b]||(by[b]={name:b,value:0,parts:{},comb:0,days:0,n:0});
    g.value+=s.asset_value_usd; g.n++;
    ACUTE.forEach(hz=>{const r=hzSite(s,hz,scenario);g.parts[hz]=(g.parts[hz]||0)+r.ead;g.comb+=r.ead;});
    const d=heatIndicators(s.latitude,s.longitude,scenario).daysOver32; if(d>g.days)g.days=d;});
  return Object.keys(by).map(b=>{const g=by[b];const row={label:g.name+" ("+g.n+")",value:g.value,cells:{},combined:null};
    ACUTE.forEach(hz=>{const ead=g.parts[hz]||0,pct=g.value?ead/g.value*100:0;row.cells[hz]={ead,eadPct:pct,band:bandOf(pct)};});
    row.cells.heat={ead:0,eadPct:0,band:heatBand(g.days),days:g.days,isHeat:true};
    const cpct=g.value?g.comb/g.value*100:0; row.combined={ead:g.comb,eadPct:cpct,band:bandOf(cpct)};
    return row;
  }).sort((a,b)=>b.combined.ead-a.combined.ead);
}
function matrixRows(group){
  if(group==="brand")return matrixGroupRows(s=>s.brand||"Unbranded");
  if(group==="insured")return matrixGroupRows(insuredOf);
  return sites.map(s=>{const row={label:s.name,id:s.id,value:s.asset_value_usd,cells:{},combined:null};let comb=0;
    ACUTE.forEach(hz=>{const r=hzSite(s,hz,scenario);row.cells[hz]={ead:r.ead,eadPct:r.eadPct,band:r.band};comb+=r.ead;});
    const hr=hzSite(s,"heat",scenario); row.cells.heat={ead:0,eadPct:0,band:hr.band,days:hr.indicators?hr.indicators.daysOver32:0,isHeat:true};
    const cpct=s.asset_value_usd?comb/s.asset_value_usd*100:0; row.combined={ead:comb,eadPct:cpct,band:bandOf(cpct)};
    return row;
  }).sort((a,b)=>b.combined.ead-a.combined.ead);
}
function renderRiskMatrix(){
  const host=document.getElementById("riskMatrix"); if(!host)return;
  if(!sites.length){host.innerHTML="";return;}
  const group=["brand","insured"].indexOf(ui.views.matrixGroup)>=0?ui.views.matrixGroup:"site";
  const metric=["pct","usd","band"].indexOf(ui.views.matrixMetric)>=0?ui.views.matrixMetric:"pct";
  const gsel=document.getElementById("mtxGroup"); if(gsel)gsel.value=group;
  const msel=document.getElementById("mtxMetric"); if(msel)msel.value=metric;
  const cols=HAZARDS.slice();
  const rows=matrixRows(group);
  const groupLabel=group==="brand"?"Brand":(group==="insured"?"Named insured":"Site");
  const cellText=c=>{ if(c.isHeat)return ""; if(c.ead<=0&&c.eadPct<=0)return "0";
    if(metric==="usd")return fmt$(c.ead); if(metric==="band")return c.band; return c.eadPct.toFixed(2); };
  const cellTitle=(label,hzLabel,c)=>c.isHeat
    ? esc(label)+" · "+hzLabel+": "+c.band+" ("+c.days+" days over 32C)"
    : esc(label)+" · "+hzLabel+": "+c.band+" · "+fmt$(c.ead)+"/yr · "+c.eadPct.toFixed(2)+"% of value";
  let h='<table class="mtx"><thead><tr><th class="rowh">'+groupLabel+'</th>';
  cols.forEach(H=>h+='<th title="'+esc(H.label)+'">'+H.short+'</th>');
  h+='<th title="Combined physical risk across all perils">All</th></tr></thead><tbody>';
  rows.forEach(r=>{
    const click=(group==="site")?' class="rowclick" data-focus="'+r.id+'"':'';
    h+='<tr'+click+'><td class="rowh" title="'+esc(r.label)+'">'+esc(r.label)+'</td>';
    cols.forEach(H=>{const c=r.cells[H.key];const zero=(!c.isHeat&&c.ead<=0&&c.eadPct<=0);
      h+='<td class="cell'+(zero?' zero':'')+'" style="background:'+BAND_COLOR[c.band]+'" title="'+cellTitle(r.label,H.label,c)+'">'+cellText(c)+'</td>';});
    const cc=r.combined;
    h+='<td class="cell comb" style="background:'+BAND_COLOR[cc.band]+'" title="'+esc(r.label)+' · combined: '+cc.band+' · '+fmt$(cc.ead)+'/yr · '+cc.eadPct.toFixed(2)+'%">'+
      (metric==="usd"?fmt$(cc.ead):(metric==="band"?cc.band:cc.eadPct.toFixed(2)))+'</td></tr>';
  });
  h+='</tbody></table>';
  const bands=["Minimal","Low","Moderate","High","Severe"];
  h+='<div class="mtxlegend"><span>Cell colour is the risk band:</span>'+
    bands.map(b=>'<span><i style="background:'+BAND_COLOR[b]+'"></i>'+b+'</span>').join("")+
    '<span style="color:var(--muted)">Columns: W wind, F coastal, R river, H heat, B wildfire, P rainfall, All combined</span></div>';
  host.innerHTML=h;
  if(group==="site")host.querySelectorAll("tr[data-focus]").forEach(tr=>tr.onclick=()=>openScorecard(+tr.dataset.focus));
}
/* SVP review: the risk-vs-value quadrant. Plots each site by value and by cost
   share, coloured by combined band, over scorePhysTotal (parity-pinned). Display
   only: it moves no number. */
function renderQuadrant(){
  const host=document.getElementById("riskValue"); if(!host)return;
  if(!sites.length){host.innerHTML="";return;}
  const pts=scorePhysTotal(sites,scenario).rows.map(r=>({id:r.id,name:r.name,value:r.asset_value_usd,ead:r.ead,eadPct:r.eadPct,band:r.band}));
  host.innerHTML=quadrantSvg(pts);
}
/* why a damage peril reads zero everywhere, phrased as the user's next step.
   Mirrors explainPeril's source logic at portfolio level: only the two perils
   that can be honestly data-less (wildfire without a grid or wui_class,
   rainfall without a grid) ever produce a note; a computed zero returns null. */
function perilZeroNote(hz){
  if(gridByHazard[hz])return null;
  if(hz==="wfire"){
    const profiled=sites.some(s=>FIRE_WUI_PBURN[String(s.wui_class||"").toLowerCase()]!=null);
    return profiled?null:
      "No wildfire grid is loaded and no site profile carries a <span class=\"mono\">wui_class</span>, so wildfire honestly scores zero rather than guessing. "+
      "Run the pipeline with <span class=\"mono\">--fire</span> (or <span class=\"mono\">--all</span>) and load the merged grid on the Method tab, or add <span class=\"mono\">wui_class</span> (interface / intermix) to exposed sites in the site CSV.";
  }
  if(hz==="prain")return "TC rainfall has no interim model by design, so it stays zero until a rainfall grid is loaded. "+
    "Run the pipeline with <span class=\"mono\">--rain</span> (or <span class=\"mono\">--all</span>) and load the merged grid on the Method tab.";
  return null;
}
/* Wave 1 R1: the tolerance panel. Reads the appraisal sliders for the
   breakeven screen (defaults when unset) so the lane routing matches the
   Adaptation tab's own appraisal. Render-only: every figure comes from
   toleranceFlags over the parity-pinned finPortfolio. */
function tolAf(){
  const hv=document.getElementById("horizon").value, dv=document.getElementById("disc").value;
  return annuity(hv===""?APPRAISAL_DEFAULTS.horizonYears:+hv,
                 (dv===""?APPRAISAL_DEFAULTS.discountPct:+dv)/100);
}
function renderTolerance(){
  const host=document.getElementById("tolBody"); if(!host)return;
  const panel=document.getElementById("tolPanel");
  if(!sites.length){ if(panel)panel.style.display="none"; return; }
  if(panel)panel.style.display="block";
  const t=toleranceFlags(sites,scenario,tolAf());
  const fld=(key,label,val,step,unit)=>'<div class="field" style="margin-bottom:4px"><label>'+label+'</label>'+
    '<input type="number" data-tol="'+key+'" min="0" step="'+step+'" value="'+val+'" style="width:100%"> <span class="hint">'+unit+'</span></div>';
  const line=(lab,val,lim,breach)=>'<span class="k">'+lab+'</span><span class="v mono">'+val+' vs '+lim+
    ' <b style="color:'+(breach?"#B23A32":"#2E8B6F")+'">'+(breach?"ABOVE tolerance":"within tolerance")+'</b></span>';
  let h='<div class="grid2" style="grid-template-columns:1fr 1fr 1fr;gap:10px">'+
    fld("siteAalBps","Site threshold",tolerance.siteAalBps,5,"bps (hundredths of a percent) of site value, expected annual cost")+
    fld("portAalPct","Portfolio threshold",tolerance.portAalPct,0.1,"% of insured value, expected annual cost")+
    fld("varPctValue","Tail threshold",tolerance.varPctValue,1,"% of value, 1-in-100 loss")+
    '</div><div class="kv" style="margin-top:8px">'+
    line("Portfolio expected cost",t.portPct.toFixed(2)+"%",tolerance.portAalPct+"%",t.portBreach)+
    line("1-in-100 Value at Risk ("+t.tailBasis+")",t.varPct.toFixed(1)+"%",tolerance.varPctValue+"%",t.varBreach)+
    '<span class="k">Sites above threshold</span><span class="v mono">'+t.siteBreaches.length+' of '+sites.length+'</span>'+
    '</div>';
  if(t.siteBreaches.length){
    h+='<table class="tbl" style="margin-top:8px"><thead><tr><th>Site</th><th class="num">Cost $/yr</th><th class="num">bps of value</th><th>Best in-scope measure</th><th class="num">BCR</th><th>Lane</th></tr></thead><tbody>'+
      t.siteBreaches.map(b=>'<tr class="rowclick" data-focus="'+b.id+'"><td>'+esc(b.name)+'</td><td class="num mono">'+fmt$(b.aal)+'</td>'+
        '<td class="num mono">'+b.bps.toFixed(0)+'</td><td>'+(b.bestMeasure?esc(b.bestMeasure):'<span class="hint">none in scope</span>')+'</td>'+
        '<td class="num mono" style="color:'+(b.bestBcr>=1?"#2E8B6F":"#B23A32")+'">'+b.bestBcr.toFixed(2)+'x</td>'+
        '<td>'+(b.lane==="capex"?"Harden (capex)":"Transfer or accept")+'</td></tr>').join("")+'</tbody></table>';
  }
  const acts=[];
  const capex=t.siteBreaches.filter(b=>b.lane==="capex"),xfer=t.siteBreaches.filter(b=>b.lane==="transfer");
  if(capex.length)acts.push("<b>Harden first:</b> "+capex.map(b=>esc(b.name)).join(", ")+" (a measure clears breakeven at each; the action queue on the Adaptation tab ranks the projects).");
  if(xfer.length)acts.push("<b>Review transfer or accept:</b> "+xfer.map(b=>esc(b.name)).join(", ")+" (no measure clears breakeven at current settings; the risk-layering panel prices the transfer).");
  if(t.varBreach)acts.push("<b>Tail above tolerance:</b> review the insurance attachment and limit against the retention table on the Adaptation tab.");
  if(t.portBreach)acts.push("<b>Portfolio expected cost above tolerance:</b> fund the action queue and carry the plan into the disclosure table and the board brief.");
  h+='<div class="note" style="margin-top:10px">'+(t.anyBreach
    ?acts.join("<br>")
    :"Within tolerance at "+esc(SCEN_LABEL[scenario]||scenario)+". These thresholds, and this statement, are the documented screening basis; they are editable above and travel with your saved session.")+'</div>';
  host.innerHTML=h;
  host.querySelectorAll("input[data-tol]").forEach(inp=>inp.onchange=()=>{
    const v=+inp.value;
    if(isFinite(v)&&v>=0){tolerance[inp.dataset.tol]=v;persist();render();}
  });
  host.querySelectorAll("tr[data-focus]").forEach(tr=>tr.onclick=()=>openScorecard(+tr.dataset.focus));
  // one-line position statement on the executive read-out
  const ro=document.getElementById("sumReadout");
  if(ro&&ro.innerHTML)ro.innerHTML+=" "+(t.anyBreach
    ?'Against the stated risk tolerance, <b>'+(t.siteBreaches.length?t.siteBreaches.length+" site"+(t.siteBreaches.length>1?"s":""):"")+
      (t.siteBreaches.length&&(t.portBreach||t.varBreach)?" and ":"")+
      ((t.portBreach||t.varBreach)?"the portfolio":"")+'</b> sit above threshold; see Position vs tolerance below.'
    :"The portfolio sits within its stated risk tolerance at this scenario.");
}
function renderOverview(scored){
  const hz=activeHazard, heat=hz==="heat", hazName=HAZARD_LABEL[hz];
  const src=hazardGrid?"CLIMADA hazard grid":"interim hazard model";
  document.getElementById("ovSub").textContent=hazName+" \u00b7 "+SCEN_LABEL[scenario]+" \u00b7 "+src+" \u00b7 "+sites.length+" sites";
  const highSev=scored.rows.filter(r=>r.band==="High"||r.band==="Severe").length;
  let cards;
  if(heat){
    const avg=k=>scored.rows.reduce((a,r)=>a+(r.indicators?r.indicators[k]:0),0)/(scored.rows.length||1);
    cards=[
      ["Total insured value",fmt$(scored.tiv),sites.length+" sites","tiv"],
      ["Avg days over 32\u00b0C",Math.round(avg("daysOver32"))+"/yr","portfolio mean, dry-bulb","heat"],
      ["Avg days over 35\u00b0C",Math.round(avg("daysOver35"))+"/yr","dry-bulb \u00b7 feels-like &gt;35\u00b0C: "+Math.round(avg("daysHi35"))+"/yr","heat"],
      ["High or Severe sites",String(highSev),"of "+sites.length,"bands"],
    ];
  }else{
    cards=[
      ["Total insured value",fmt$(scored.tiv),sites.length+" sites","tiv"],
      ["Expected annual damage",fmt$(scored.ead)+"/yr",scored.eadPct.toFixed(2)+"% of value","ead"],
      ["1-in-100 portfolio loss",fmt$(scored.rpLoss[100]),"sum across sites at equal RP: an upper bound, not the joint tail","rp100"],
      ["High or Severe sites",String(highSev),"of "+sites.length,"bands"],
    ];
  }
  document.getElementById("kpiCards").innerHTML=cards.map(c=>
    '<div class="card"><div class="l">'+c[0]+(c[3]?infoBtn(c[3]):"")+'</div><div class="v">'+c[1]+'</div><div class="foot">'+c[2]+'</div></div>').join("");

  // left panel: EP curve for damage perils, indicator bars for heat
  if(heat){
    document.getElementById("epTitle").innerHTML="Heat indicators by site"+infoBtn("heat");
    document.getElementById("epHint").textContent="Days per year above 32\u00b0C, "+SCEN_LABEL[scenario].toLowerCase()+".";
    const items=scored.rows.slice().sort((a,b)=>(b.indicators.daysOver32)-(a.indicators.daysOver32))
      .map(r=>({label:r.name,v:r.indicators.daysOver32}));
    document.getElementById("epCurve").innerHTML=countBarsSvg(items,"v","label","#C06B2E"," d");
  }else{
    document.getElementById("epTitle").innerHTML="Loss exceedance"+infoBtn("epcurve");
    document.getElementById("epHint").textContent="Portfolio "+hazName.toLowerCase()+" loss by return period, "+SCEN_LABEL[scenario].toLowerCase()+" (site losses summed at equal RP: an upper bound; the results pack carries the joint event tail).";
    /* an all-zero curve is a data-availability story, not a chart: say why and
       what to do, instead of drawing an empty axis */
    const zero=scored.ead===0&&RPS.every(rp=>!(scored.rpLoss[rp]>0));
    const why=zero?perilZeroNote(hz):null;
    document.getElementById("epCurve").innerHTML=why
      ?'<div class="note" style="margin-top:8px"><b>No modeled '+hazName.toLowerCase()+' loss.</b> '+why+'</div>'
      :epCurveSvg(scored.rpLoss);
  }

  // right panel: EAD by brand, or avg hot-days by brand for heat
  if(heat){
    document.getElementById("brandTitle").innerHTML="Days over 32\u00b0C by brand"+infoBtn("brand");
    document.getElementById("brandHint").textContent="Portfolio-average exposure by brand.";
    const bm={};scored.rows.forEach(r=>{const k=r.brand||"Unbranded";(bm[k]||(bm[k]={label:k,sum:0,n:0}));bm[k].sum+=r.indicators.daysOver32;bm[k].n++;});
    const items=Object.values(bm).map(x=>({label:x.label,v:Math.round(x.sum/x.n)})).sort((a,b)=>b.v-a.v);
    document.getElementById("brandBars").innerHTML=countBarsSvg(items,"v","label","#C06B2E"," d");
  }else{
    document.getElementById("brandTitle").innerHTML="Expected annual damage by brand"+infoBtn("brand");
    document.getElementById("brandHint").textContent="Where "+hazName.toLowerCase()+" loss concentrates across the portfolio.";
    const br=brandRollup(scored.rows.map(r=>Object.assign({},r,{eadUsd:r.ead})));
    document.getElementById("brandBars").innerHTML=barsSvg(br,"ead","brand","#12586F");
  }

  // risk drivers: portfolio EAD split across perils (always all perils)
  const rd=riskDrivers(sites,scenario);
  const items=ACUTE.map(hz=>({label:HAZARD_LABEL[hz],ead:rd.byHazard[hz]||0}))
    .sort((a,b)=>b.ead-a.ead);
  const heatDays=Math.round(sites.reduce((a,s)=>a+heatIndicators(s.latitude,s.longitude,scenario).daysOver32,0)/(sites.length||1));
  document.getElementById("riskDrivers").innerHTML=
    barsSvg(items,"ead","label","#12586F")+
    '<div class="hint" style="margin-top:6px">Extreme heat is tracked as indicators (portfolio average '+heatDays+' days over 32\u00b0C) and is dollarised as heat revenue at risk on the Financial impact tab.</div>';

  // narrative
  const top=scored.rows.slice().sort((a,b)=>(b.ead||0)-(a.ead||0));
  const dom=items[0];
  const domName=dom.label.toLowerCase();
  const domShare=rd.total>0?(dom.ead/rd.total*100):0;
  const fut=scorePhysTotal(sites,"ssp585_2080").ead, now=scorePhysTotal(sites,"present").ead;
  const growth=now>0?((fut/now-1)*100):0;
  if(heat){
    document.getElementById("narrative").innerHTML=
      "Across "+sites.length+" sites worth <b>"+fmt$(scored.tiv)+"</b>, extreme-heat exposure at "+SCEN_LABEL[scenario].toLowerCase()+" averages <b>"+heatDays+" days per year over 32\u00b0C</b>. "+
      (highSev>0?"<b>"+highSev+"</b> site"+(highSev>1?"s rate":" rates")+" High or Severe for heat. ":"")+
      "Across all modeled perils, <b>"+domName+"</b> is the largest driver of physical expected annual damage; the combined figure rises about <b>"+growth.toFixed(0)+"%</b> from present to SSP5-8.5 late-century.";
  }else{
    const whyZero=(scored.ead===0)?perilZeroNote(hz):null;
    document.getElementById("narrative").innerHTML=whyZero
      ?("Across "+sites.length+" sites worth <b>"+fmt$(scored.tiv)+"</b>, "+hazName.toLowerCase()+" shows <b>no modeled loss</b> at "+SCEN_LABEL[scenario].toLowerCase()+". "+whyZero)
      :("Across "+sites.length+" sites worth <b>"+fmt$(scored.tiv)+"</b>, modeled "+hazName.toLowerCase()+" risk runs to <b>"+fmt$(scored.ead)+" per year</b> ("+scored.eadPct.toFixed(2)+"% of value) at "+SCEN_LABEL[scenario].toLowerCase()+(top[0]?", led by <b>"+esc(top[0].name)+"</b>":"")+". "+
      "Across all modeled perils, <b>"+domName+"</b> is the single largest driver of physical expected annual damage ("+domShare.toFixed(0)+"% of it). "+
      (highSev>0?"<b>"+highSev+"</b> site"+(highSev>1?"s sit":" sits")+" in the High or Severe band for this peril. ":"All sites fall below the High band for this peril. ")+
      "Combined physical expected annual damage rises about <b>"+growth.toFixed(0)+"%</b> from present to SSP5-8.5 late-century.");
  }
}
function renderSites(){
  const heat=activeHazard==="heat";
  const scored=scoreHazard(sites,activeHazard,scenario);
  // attach all-peril ratings, a sortable severity for heat, and the per-site
  // 1-in-100 loss for this peril (Task 5: RP losses beside the EAD)
  scored.rows.forEach(r=>{ r.ratings=siteRatings(r,scenario);
    r.sev=heat?(r.indicators?r.indicators.daysOver32:0):r.ead;
    const c100=(r.curve||[]).find(x=>x.rp===100);
    r.rp100=heat?0:(c100?c100.loss:0); });
  const key=(heat&&(sortKey==="ead"||sortKey==="eadPct"))?"sev":sortKey;
  const rows=scored.rows.slice().sort((a,b)=>{
    let va=a[key],vb=b[key];if(typeof va==="string"){return sortDir*va.localeCompare(vb);}return sortDir*((va||0)-(vb||0));
  });
  const ratingCell=r=>'<div class="ratecell">'+HAZARDS.map(h=>
    '<span class="pill mini '+r.ratings[h.key]+'" title="'+h.label+': '+r.ratings[h.key]+'">'+h.short+'</span>').join("")+'</div>';
  const tolIds=new Set(sites.length?toleranceFlags(sites,scenario,tolAf()).siteBreaches.map(b=>b.id):[]);
  document.getElementById("siteBody").innerHTML=rows.map(r=>
    '<tr class="rowclick '+(r.id===selectedId?"sel":"")+'" data-id="'+r.id+'">'+
    '<td>'+(tolIds.has(r.id)?'<span class="tolbreach" title="Expected annual cost above the site tolerance ('+tolerance.siteAalBps+' bps of value); see Position vs tolerance on the Summary tab"></span>':'')+esc(r.name)+'</td><td>'+esc(r.brand||"")+'</td>'+
    '<td class="num mono">'+fmt$(r.asset_value_usd)+'</td>'+
    '<td class="num mono">'+(heat?"&mdash;":fmt$(r.ead))+'</td>'+
    '<td class="num mono">'+(heat?(r.indicators.daysOver32+" d"):r.eadPct.toFixed(2)+'%')+'</td>'+
    '<td class="num mono">'+(heat?"&mdash;":fmt$(r.rp100))+'</td>'+
    '<td>'+ratingCell(r)+'</td></tr>').join("")
    || '<tr><td colspan="7" style="color:var(--muted);padding:18px">No sites yet. Add one, load the sample, or search a place.</td></tr>';
  document.querySelectorAll("#siteBody tr.rowclick").forEach(tr=>tr.onclick=()=>{selectedId=+tr.dataset.id;renderSites();});
  if(selectedId!=null){renderDetail(rows.find(r=>r.id===selectedId));}
}
/* the named-insured breakout for one physical site: every named insured that
   shares it, with value, expected annual damage, % of value, and share of the
   site total, so the reader sees who is impacted and to what degree. Empty for
   a single-record site (nothing to break out). The selected record's row is
   highlighted. */
function namedInsuredDetail(record){
  const key=siteGroupKey(record);
  const members=sites.filter(x=>siteGroupKey(x)===key);
  if(members.length<2)return "";
  const gr=scoreGroup(siteGroups(members)[0],scenario);
  const rows=gr.byInsured.map(r=>
    '<tr'+(insuredOf(record)===r.insured?' style="background:#F2F5F3"':'')+'><td>'+esc(r.insured)+(r.n>1?' <span class="hint">('+r.n+' rec)</span>':'')+'</td>'+
    '<td class="num mono">'+fmt$(r.value)+'</td><td class="num mono">'+fmt$(r.ead)+'</td>'+
    '<td class="num mono">'+r.eadPct.toFixed(2)+'%</td><td class="num mono">'+r.share.toFixed(0)+'%</td>'+
    '<td><span class="pill mini '+r.band+'" title="'+r.band+'">'+r.band+'</span></td></tr>').join("");
  return '<div class="panel" style="margin-top:12px;border-left:3px solid var(--primary)">'+
    '<h3 style="margin:0 0 2px">Named insured at this site'+infoBtn("namedInsured")+'</h3>'+
    '<div class="hint" style="margin-bottom:6px">'+esc(gr.name)+' aggregates '+gr.members.length+' named-insured records into one site worth '+fmt$(gr.value)+', with '+fmt$(gr.ead)+'/yr combined expected damage ('+gr.band+'). Who is impacted, and to what degree:</div>'+
    '<table class="tbl"><thead><tr><th>Named insured</th><th class="num">Value</th><th class="num">EAD $/yr</th><th class="num">% value</th><th class="num">Share</th><th>Band</th></tr></thead><tbody>'+rows+'</tbody></table></div>';
}
/* the per-site trust strip: which perils THIS site's numbers are actually
   modeled on (green = the grid reached it within snap and coverage), and
   which are degraded (interim screening or honest zero). A site can never
   read green here on a peril whose grid did not serve it a value. */
function siteTrustStrip(site){
  const t=siteTrustSummary(site,scenario);
  const bits=HAZARDS.map(h=>{const x=t.byHz[h.key];const on=x.state==="modeled";
    return '<span class="pill mini" data-trust="'+(on?"modeled":"degraded")+'" style="background:'+(on?"var(--r-low)":"var(--r-min)")+(on?'':';opacity:0.8')+'" title="'+esc(h.label+": "+(on?"modeled at this site (grid"+(x.distKm!=null?", "+Math.round(x.distKm)+" km to cell":"")+")"+(x.note?"; "+x.note:""):"degraded: "+(x.detail||x.basis)))+'">'+h.short+'</span>';}).join("");
  return '<div class="ratecell" style="margin:2px 0 10px">'+bits+notModeledChips()+
    '<span class="hint" style="margin-left:8px">model basis at this site: '+t.modeled+' of '+t.total+' perils modeled'+(t.modeled<t.total?', the rest degraded (hover a chip for why)':'')+'; dashed chips are perils this tool does not model at all</span></div>';
}
function renderDetail(r){
  if(!r){document.getElementById("detailBody").style.display="none";document.getElementById("detailHint").style.display="block";return;}
  document.getElementById("detailHint").style.display="none";
  const body=document.getElementById("detailBody");body.style.display="block";
  const hz=activeHazard, heat=hz==="heat", H=HAZARD_BY[hz];
  const ratings=r.ratings||siteRatings(r,scenario);
  const ratingStrip='<div class="ratecell" style="margin:2px 0 12px">'+HAZARDS.map(h=>
    '<span class="pill mini '+ratings[h.key]+'" title="'+h.label+': '+ratings[h.key]+'">'+h.short+'</span>').join("")+
    '<span class="hint" style="margin-left:8px">W wind &middot; F coastal &middot; R riverine &middot; H heat &middot; B wildfire &middot; P rainfall</span></div>';
  const nowS=hzSite(r,hz,"present"), lateS=hzSite(r,hz,"ssp585_2080");

  let mid, table;
  if(heat){
    const ind=r.indicators||heatIndicators(r.latitude,r.longitude,scenario);
    mid='<div class="cards" style="grid-template-columns:1fr 1fr;margin-bottom:14px">'+
      '<div class="card"><div class="l">Heat rating '+SCEN_LABEL[scenario]+'</div><div class="v" style="font-size:20px">'+r.band+'</div><div class="foot">'+ind.daysOver32+' days &gt;32&deg;C</div></div>'+
      '<div class="card"><div class="l">Value</div><div class="v" style="font-size:20px">'+fmt$(r.asset_value_usd)+'</div><div class="foot">days &gt;32&deg;C, present to 2080: '+nowS.indicators.daysOver32+' &rarr; '+lateS.indicators.daysOver32+infoBtn("scenShift")+'</div></div>'+
    '</div>';
    table='<table class="tbl"><thead><tr><th>Indicator</th><th class="num">Value / yr</th></tr></thead><tbody>'+
      '<tr><td>Days over 32&deg;C (dry-bulb)</td><td class="num mono">'+ind.daysOver32+'</td></tr>'+
      '<tr><td>Days over 35&deg;C (dry-bulb)</td><td class="num mono">'+ind.daysOver35+'</td></tr>'+
      '<tr><td>Humid-heat days (feels-like &gt;35&deg;C)'+infoBtn("heat")+'</td><td class="num mono">'+ind.daysHi35+'</td></tr>'+
      '<tr><td>Cooling degree-days</td><td class="num mono">'+ind.cdd+'</td></tr>'+
      '<tr><td>Effective warm-season index (dry-bulb)</td><td class="num mono">'+ind.effT+' &deg;C</td></tr>'+
      '<tr><td>Feels-like at that index (heat index, RH '+Math.round(ind.rhWarm*100)+'%)</td><td class="num mono">'+ind.hiT+' &deg;C</td></tr></tbody></table>';
  }else{
    const rpRows=RPS.map(rp=>{const c=r.curve.find(x=>x.rp===rp);return '<tr><td class="mono">1 in '+rp+'</td><td class="num mono">'+c.v.toFixed(hz==="tc"?0:2)+' '+H.unit+'</td><td class="num mono">'+fmt$(c.loss)+'</td></tr>';}).join("");
    mid='<div class="cards" style="grid-template-columns:1fr 1fr;margin-bottom:14px">'+
      '<div class="card"><div class="l">EAD '+SCEN_LABEL[scenario]+'</div><div class="v" style="font-size:20px">'+fmt$(r.ead)+'</div><div class="foot">'+r.eadPct.toFixed(2)+'% · '+r.band+'</div></div>'+
      '<div class="card"><div class="l">Value</div><div class="v" style="font-size:20px">'+fmt$(r.asset_value_usd)+'</div><div class="foot">present to 2080: '+fmt$(nowS.ead)+' &rarr; '+fmt$(lateS.ead)+'/yr'+infoBtn("scenShift")+'</div></div>'+
    '</div>';
    table='<table class="tbl"><thead><tr><th>Return period</th><th class="num">Intensity</th><th class="num">Loss</th></tr></thead><tbody>'+rpRows+'</tbody></table>';
  }
  body.innerHTML=
    '<div style="font-family:Fraunces,serif;font-size:17px;color:var(--primary);margin-bottom:2px">'+esc(r.name)+'</div>'+
    '<div class="hint" style="margin-bottom:6px">'+esc(r.brand||"")+(insuredOf(r)!=="Unspecified"?' · '+esc(insuredOf(r)):'')+' · '+r.latitude.toFixed(3)+', '+r.longitude.toFixed(3)+' · '+H.label+infoBtn(hz)+(r.hazardMeta&&r.hazardMeta.outside?' · <span style="color:var(--r-high)">outside hazard grid</span>':'')+'</div>'+
    ratingStrip+siteTrustStrip(r)+mid+table+namedInsuredDetail(r)+
    '<div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">'+
      '<button class="lightbtn primary" id="openCard">Full scorecard</button>'+
      '<button class="lightbtn" id="editVal">Edit site</button>'+
      '<button class="lightbtn" id="delSite" style="color:var(--r-sev)">Remove</button>'+
    '</div>';
  document.getElementById("openCard").onclick=()=>openScorecard(r.id);
  document.getElementById("editVal").onclick=()=>{const s=sites.find(x=>x.id===r.id);if(s)openForm("edit",s);};
  document.getElementById("delSite").onclick=()=>{sites=sites.filter(x=>x.id!==r.id);selectedId=null;persist();render();};
}

function renderAdaptation(){
  const host=document.getElementById("measuresHost"); if(!host)return;
  if(!sites.length){
    host.innerHTML='<p class="hint">Load a portfolio to appraise measures.</p>';
    ["costCurve","waterfallChart","layerChart","layerStats","recBody","portfolioSummary",
     "sweepHost","queueRoll","queueBody","queuePack","queueMore"].forEach(id=>document.getElementById(id).innerHTML="");
    return;
  }
  // read shared settings
  const horizon=+document.getElementById("horizon").value;
  const disc=+document.getElementById("disc").value/100;
  adapt.growth=+document.getElementById("growth").value;
  adapt.load=+document.getElementById("load").value;
  adapt.attach=+document.getElementById("attachSel").value;
  adapt.exhaust=+document.getElementById("exhaustSel").value;
  adapt.quote=+document.getElementById("quoteIn").value||0;
  adapt.budget=+document.getElementById("budgetIn").value||0;
  if(adapt.exhaust<=adapt.attach){adapt.exhaust=RPS.find(rp=>rp>adapt.attach)||500;document.getElementById("exhaustSel").value=adapt.exhaust;}
  document.getElementById("horizonVal").textContent=horizon;
  document.getElementById("discVal").textContent=(disc*100).toFixed(1)+"%";
  document.getElementById("growthVal").textContent=adapt.growth.toFixed(1)+"%";
  document.getElementById("loadVal").textContent=adapt.load.toFixed(1)+"x";
  const af=annuity(horizon,disc);
  const base=adaptedTotal(sites,scenario,{});

  // per-measure appraisal at the selected scenario
  const appraised=MEASURES.map(m=>{
    const st=adapt.m[m.key];
    const averted=base.totalAal-adaptedTotal(sites,scenario,m.mods(st)).totalAal;
    const cost=measureCost(m,sites,scenario);
    const scopeN=sites.filter(s=>m.inScope(s,scenario)).length;
    return {m,st,averted,cost,benefit:averted*af,bcr:cost>0?averted*af/cost:0,scopeN};
  });

  // measure cards with enable checkbox and sliders
  host.innerHTML=appraised.map(a=>{
    const sliders=a.m.sliders.map(sl=>{
      const v=a.st[sl.p];
      return '<div class="field" style="margin-bottom:8px"><label>'+sl.label+' <span class="mono" id="mv_'+a.m.key+'_'+sl.p+'">'+sl.fmt(v)+'</span></label>'+
        '<input type="range" data-mkey="'+a.m.key+'" data-mp="'+sl.p+'" min="'+sl.min+'" max="'+sl.max+'" step="'+sl.step+'" value="'+v+'"></div>';
    }).join("");
    return '<div class="measure" style="'+(a.st.on?"":"opacity:.62")+'">'+
      '<div class="mh"><span class="nm"><label style="display:flex;align-items:center;gap:8px;cursor:pointer"><input type="checkbox" data-mtoggle="'+a.m.key+'" '+(a.st.on?"checked":"")+'> '+esc(a.m.name)+infoBtn(a.m.info)+'</label></span>'+
      '<span class="bcr" style="color:'+(a.bcr>=1?"#2E8B6F":"#B23A32")+'">BCR '+a.bcr.toFixed(2)+'x</span></div>'+
      '<div class="hint" style="margin:0 0 8px">Targets: '+a.m.target+' · applies to '+a.scopeN+' of '+sites.length+' sites</div>'+
      sliders+
      '<div class="stat"><span>Cost <b>'+fmt$(a.cost)+'</b></span><span>Averted <b>'+fmt$(a.averted)+'/yr</b></span><span>Benefit ('+horizon+'y) <b>'+fmt$(a.benefit)+'</b></span></div></div>';
  }).join("");
  // wire dynamic inputs
  host.querySelectorAll("input[type=range][data-mkey]").forEach(inp=>inp.oninput=()=>{
    adapt.m[inp.dataset.mkey][inp.dataset.mp]=+inp.value;persist();renderAdaptation();
  });
  host.querySelectorAll("input[type=checkbox][data-mtoggle]").forEach(cb=>cb.onchange=()=>{
    adapt.m[cb.dataset.mtoggle].on=cb.checked;persist();renderAdaptation();
  });

  // enabled portfolio (combined mods, so overlaps never double-count)
  const enabled=appraised.filter(a=>a.st.on);
  const combAverted=base.totalAal-adaptedTotal(sites,scenario,enabledMods()).totalAal;
  const combCost=enabled.reduce((s,a)=>s+a.cost,0);
  const combBcr=combCost>0?combAverted*af/combCost:0;
  document.getElementById("portfolioSummary").innerHTML=enabled.length?
    "<b>Selected portfolio ("+enabled.length+" measure"+(enabled.length>1?"s":"")+"):</b> averts <b>"+fmt$(combAverted)+"/yr</b> of "+fmt$(base.totalAal)+" ("+(base.totalAal?combAverted/base.totalAal*100:0).toFixed(0)+"%) for "+fmt$(combCost)+" upfront. Portfolio BCR <b>"+combBcr.toFixed(2)+"x</b>. Combined benefit is computed jointly, so overlapping measures are never double-counted.":
    "No measures selected. Check measures in the library to build the adaptation portfolio.";

  // adaptation cost curve
  document.getElementById("costCurve").innerHTML=costCurveSvg(appraised);
  // waterfall
  const futureSc=(scenario!=="present")?scenario:(currentPathway()+"_2050");
  const wf=waterfallData(sites,futureSc);
  document.getElementById("wfHint").textContent="Present to "+(SCEN_LABEL[futureSc]||futureSc)+", exposure growth "+adapt.growth.toFixed(1)+"%/yr over "+wf.years+" years, minus the selected measure portfolio.";
  document.getElementById("waterfallChart").innerHTML=waterfallSvg(wf);
  // risk layering: the canonical joint curve prices the layer when a pack
  // is loaded; without one the live blend stands, explicitly labeled (Task 5)
  const f=finPortfolio(sites,scenario);
  const tailCurve=f.jointTail?f.jointTail.byRp:f.varByRp;
  const tailBase=f.jointTail?f.jointTail.aal:f.acuteAal;
  const ls=layerStatsCalc(tailCurve,tailBase);
  document.getElementById("layerStats").innerHTML=
    '<span class="k">Priced on</span><span class="v">'+(f.jointTail?TAIL_JOINT_LABEL:TAIL_BOUND_LABEL)+'</span>'+
    '<span class="k">Attachment (1-in-'+adapt.attach+')</span><span class="v mono">'+fmt$(ls.A)+'</span>'+
    '<span class="k">Limit</span><span class="v mono">'+fmt$(ls.limit)+'</span>'+
    '<span class="k">Transferred</span><span class="v mono">'+fmt$(ls.transferred)+'/yr ('+(ls.frac*100).toFixed(0)+'% of '+(f.jointTail?'direct AAL':'acute')+')</span>'+
    '<span class="k">Retained</span><span class="v mono">'+fmt$(ls.retained)+'/yr</span>'+
    '<span class="k">Indicative premium</span><span class="v mono">'+fmt$(ls.premium)+'/yr</span>'+
    '<span class="k">Cost of certainty</span><span class="v mono">'+fmt$(ls.premium-ls.transferred)+'/yr</span>'+
    (function(){if(!f.jointTail)return '';const bs=layerStatsCalc(f.varByRp,f.acuteAal);
      return '<span class="k">Live blend (for reference)</span><span class="v mono">'+fmt$(bs.transferred)+'/yr to layer \u00b7 premium '+fmt$(bs.premium)+'/yr <small>'+TAIL_BOUND_LABEL+'</small></span>';})()+
    (function(){ // Wave 1 R2: quoted premium vs the modeled benchmark
      if(!(adapt.quote>0))return '';
      const gapM=quoteGapPct(adapt.quote,ls.premium);
      const wd=g=>Math.abs(g)<=15?"broadly in line with":(g>0?g.toFixed(0)+"% above":Math.abs(g).toFixed(0)+"% below");
      const hint=gapM==null?"No modeled premium to compare at this layer.":
        gapM>15?"Grounds to negotiate, or to raise the attachment (see the retention table below).":
        gapM<-15?"Below the technical benchmark: attractive if terms and exclusions are equivalent.":
        "Within the range a benchmark can resolve.";
      return '<span class="k">Broker quote'+infoBtn("quote")+'</span><span class="v mono">'+fmt$(adapt.quote)+'/yr'+
        (gapM!=null?': '+wd(gapM)+' the '+(f.jointTail?'joint-tail':'blend')+' technical premium':'')+
        '. <small>'+hint+' The '+adapt.load.toFixed(1)+'x loading assumption is yours to set.</small></span>';
    })();
  document.getElementById("layerChart").innerHTML=layerSvg(tailCurve,ls);
  document.getElementById("sweepHost").innerHTML=sweepTable(tailCurve,tailBase);
  // per-site recommendations: best measure by site BCR (shared helper)
  const rec=sites.map(s=>({site:s.name,id:s.id,
    aal:adaptedFinSite(s,scenario,{}).totalAal,
    best:bestMeasureFor(s,scenario,af)}))
    .sort((a,b)=>(b.best?b.best.bcr:0)-(a.best?a.best.bcr:0));
  document.getElementById("recBody").innerHTML=rec.map(r=>
    '<tr class="rowclick" data-focus="'+r.id+'"><td>'+esc(r.site)+'</td><td class="num mono">'+fmt$(r.aal)+'</td>'+
    (r.best?'<td>'+esc(r.best.name)+'</td><td class="num mono">'+fmt$(r.best.averted)+'</td><td class="num mono">'+fmt$(r.best.cost)+'</td><td class="num mono" style="color:'+(r.best.bcr>=1?"#2E8B6F":"#B23A32")+'">'+r.best.bcr.toFixed(2)+'x</td>':'<td colspan="4" class="hint">No in-scope measure</td>')+'</tr>').join("");
  document.querySelectorAll("#recBody tr[data-focus]").forEach(tr=>tr.onclick=()=>openScorecard(+tr.dataset.focus));

  // Wave 1 R3: the action queue with its funding cutline
  const q=actionQueue(sites,scenario,af,adapt.budget);
  const unf=q.items.filter(i=>!i.funded&&i.bcr>=1);
  document.getElementById("queueRoll").innerHTML=q.items.length?
    "<b>Program:</b> "+q.roll.n+" funded project"+(q.roll.n===1?"":"s")+", cost "+fmt$(q.roll.cost)+
    (adapt.budget>0?" of the "+fmt$(adapt.budget)+" budget":"")+
    ", jointly averting <b>"+fmt$(q.roll.averted)+"/yr</b> (program BCR "+q.roll.bcr.toFixed(2)+
    "x; the roll-up is computed jointly per site, so overlapping measures never double-count)."+
    (unf.length?" <b>"+unf.length+"</b> project"+(unf.length===1?"":"s")+" above breakeven sit"+(unf.length===1?"s":"")+
      " unfunded ("+fmt$(unf.reduce((a,i)=>a+i.cost,0))+"): deferred by the budget, not dropped.":"")+
    " Nothing below breakeven is ever funded.":
    "No in-scope measures for this portfolio at current settings.";
  const QSHOW=12;
  document.getElementById("queueBody").innerHTML=q.items.slice(0,QSHOW).map((it,i)=>
    '<tr class="rowclick" data-focus="'+it.id+'"><td class="mono">'+(i+1)+'</td><td>'+esc(it.site)+'</td><td>'+esc(it.measure)+'</td>'+
    '<td class="num mono">'+fmt$(it.averted)+'</td><td class="num mono">'+fmt$(it.cost)+'</td>'+
    '<td class="num mono" style="color:'+(it.bcr>=1?"#2E8B6F":"#B23A32")+'">'+it.bcr.toFixed(2)+'x</td>'+
    '<td style="color:'+(it.funded?"#2E8B6F":"#7A8893")+';font-weight:600">'+(it.funded?"funded":"unfunded")+'</td></tr>').join("");
  document.getElementById("queueMore").textContent=q.items.length>QSHOW?
    ("Top "+QSHOW+" of "+q.items.length+" pairs shown; the export carries the full list."):"";
  const pkq=resultsPack&&resultsPack.data;
  document.getElementById("queuePack").innerHTML=(pkq&&pkq.capital_plan&&pkq.capital_plan.projects&&pkq.capital_plan.projects.length)?
    '<div class="note" style="margin-top:10px"><b>Canonical plan (CLIMADA results pack):</b><br>'+
    pkq.capital_plan.projects.slice(0,5).map(cp=>(cp.year!=null?"Y"+esc(cp.year):"deferred")+" · "+esc(cp.site)+" · "+esc(cp.measure)+" · BCR "+esc(cp.bcr)).join("<br>")+
    '<br><small>Event-set appraisal at '+esc(pkq.capital_plan.scenario||"")+
    (pkq.capital_plan.budget_annual_usd?', '+fmt$(pkq.capital_plan.budget_annual_usd)+'/yr budget':'')+
    '. This is the authoritative ranking; the interactive queue above is the live estimate. Both go into the export.</small></div>':"";
  document.querySelectorAll("#queueBody tr[data-focus]").forEach(tr=>tr.onclick=()=>openScorecard(+tr.dataset.focus));
}
/* Wave 1 R2: the retention table. Every candidate attachment priced on the
   same curve, exhaustion and loading held fixed. */
function sweepTable(varByRp,acuteAal){
  const rows=retentionSweep(varByRp,acuteAal,adapt.exhaust,adapt.load);
  if(!rows.length)return "";
  return '<h3 style="margin-top:14px">Retention: the attachment trade'+infoBtn("retention")+'</h3>'+
    '<table class="tbl"><thead><tr><th>Attachment</th><th class="num">Retained below</th><th class="num">Transferred</th><th class="num">Premium</th><th class="num">Cost of certainty</th><th class="num">Tail beyond limit</th></tr></thead><tbody>'+
    rows.map(r=>'<tr'+(r.attach===adapt.attach?' style="background:#F2F5F3;font-weight:600"':'')+'>'+
      '<td class="mono">1-in-'+r.attach+(r.attach===adapt.attach?" (current)":"")+'</td>'+
      '<td class="num mono">'+fmt$(r.below)+'/yr</td><td class="num mono">'+fmt$(r.layer)+'/yr</td>'+
      '<td class="num mono">'+fmt$(r.premium)+'/yr</td><td class="num mono">'+fmt$(r.certainty)+'/yr</td>'+
      '<td class="num mono">'+fmt$(r.above)+'/yr</td></tr>').join("")+'</tbody></table>'+
    '<div class="hint" style="margin-top:6px">Same exhaustion (1-in-'+adapt.exhaust+') and loading ('+adapt.load.toFixed(1)+
    'x) on every row; only the attachment moves. Retained below is the working layer a higher retention or a captive would fund. The three slices always add up to the acute expected annual loss.</div>';
}
/* ECA-style adaptation cost curve: width = averted AAL, height = BCR */
function costCurveSvg(appraised){
  const items=appraised.slice().sort((a,b)=>b.bcr-a.bcr);
  const W=460,H=230,padL=44,padB=54,padT=12;
  const totAvert=Math.max(items.reduce((s,a)=>s+a.averted,0),1);
  const maxBcr=Math.max(1.5,Math.min(Math.max.apply(null,items.map(a=>a.bcr)),8));
  const X=v=>padL+(v/totAvert)*(W-padL-14);
  const Y=b=>padT+(1-Math.min(b,maxBcr)/maxBcr)*(H-padT-padB);
  const colors=["#0F3A4B","#12586F","#2C7DA0","#6A8CAF","#7FD0C4"];
  let s=svgEl(W,H),x=0,legend="";
  [0.25,0.5,0.75,1].forEach(t=>{const y=Y(t*maxBcr);
    s+='<line x1="'+padL+'" y1="'+y+'" x2="'+(W-14)+'" y2="'+y+'" stroke="#EEF0EC"/>';
    s+='<text x="'+(padL-6)+'" y="'+(y+3)+'" text-anchor="end" font-size="10" fill="#7A8893">'+(t*maxBcr).toFixed(1)+'x</text>';});
  items.forEach((a,i)=>{
    const w=(a.averted/totAvert)*(W-padL-14);
    const y=Y(a.bcr), h=(H-padB)-y;
    s+='<rect x="'+X(x)+'" y="'+y+'" width="'+Math.max(w-2,1)+'" height="'+Math.max(h,1)+'" rx="2" fill="'+colors[i%colors.length]+'" opacity="'+(a.st.on?0.95:0.35)+'"><title>'+esc(a.m.name)+': BCR '+a.bcr.toFixed(2)+'x, averts '+fmt$(a.averted)+'/yr</title></rect>';
    legend+='<span style="margin-right:12px;white-space:nowrap"><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:'+colors[i%colors.length]+';margin-right:5px;vertical-align:middle;opacity:'+(a.st.on?1:0.4)+'"></span>'+esc(a.m.name.split("(")[0].trim())+' '+a.bcr.toFixed(1)+'x</span>';
    x+=a.averted;
  });
  const y1=Y(1);
  s+='<line x1="'+padL+'" y1="'+y1+'" x2="'+(W-14)+'" y2="'+y1+'" stroke="#B23A32" stroke-width="1.5" stroke-dasharray="5 4"/>';
  s+='<text x="'+(W-16)+'" y="'+(y1-5)+'" text-anchor="end" font-size="10" fill="#B23A32">breakeven 1.0x</text>';
  s+='<text x="'+((padL+W-14)/2)+'" y="'+(H-padB+16)+'" text-anchor="middle" font-size="10" fill="#43535F">Averted expected annual cost (bar width, total '+fmt$(totAvert)+'/yr)</text>';
  s+="</svg>";
  return s+'<div class="hint" style="margin-top:6px;display:flex;flex-wrap:wrap;row-gap:4px">'+legend+'</div>';
}
/* CLIMADA-style waterfall bridge */
function waterfallSvg(wf){
  const W=460,H=240,padL=48,padB=40,padT=14;
  const cols=[
    {lab:"Today",v:wf.today,base:0,color:"#0F3A4B",solid:true},
    {lab:"+ Growth",v:wf.growthInc,base:wf.today,color:"#7A8893"},
    {lab:"+ Climate",v:wf.climateInc,base:wf.today+wf.growthInc,color:"#D9772F"},
    {lab:"Future",v:wf.future,base:0,color:"#12586F",solid:true},
    {lab:"- Adaptation",v:-wf.averted,base:wf.future,color:"#2E8B6F"},
    {lab:"Residual",v:wf.residual,base:0,color:"#2C7DA0",solid:true},
  ];
  const ymax=Math.max(wf.future,1)*1.12;
  const Y=v=>padT+(1-v/ymax)*(H-padT-padB);
  const bw=(W-padL-16)/cols.length;
  let s=svgEl(W,H);
  [0.25,0.5,0.75,1].forEach(t=>{const y=Y(t*ymax);
    s+='<line x1="'+padL+'" y1="'+y+'" x2="'+(W-14)+'" y2="'+y+'" stroke="#EEF0EC"/>';
    s+='<text x="'+(padL-6)+'" y="'+(y+3)+'" text-anchor="end" font-size="10" fill="#7A8893">'+fmt$(t*ymax)+'</text>';});
  cols.forEach((c,i)=>{
    const x=padL+i*bw+6, w=bw-12;
    const top=c.solid?Y(c.v):Y(Math.max(c.base,c.base+c.v));
    const bot=c.solid?Y(0):Y(Math.min(c.base,c.base+c.v));
    s+='<rect x="'+x+'" y="'+top+'" width="'+w+'" height="'+Math.max(bot-top,1.5)+'" rx="2" fill="'+c.color+'"><title>'+c.lab+': '+fmt$(Math.abs(c.v))+'</title></rect>';
    if(!c.solid){ // connector from previous level
      const lev=Y(c.base);
      s+='<line x1="'+(x-6)+'" y1="'+lev+'" x2="'+x+'" y2="'+lev+'" stroke="#C4CCC7" stroke-width="1"/>';
    }
    s+='<text x="'+(x+w/2)+'" y="'+(top-4)+'" text-anchor="middle" font-size="9.5" class="mono" fill="#15202B">'+fmt$(Math.abs(c.v))+'</text>';
    s+='<text x="'+(x+w/2)+'" y="'+(H-padB+14)+'" text-anchor="middle" font-size="9.5" fill="#43535F">'+c.lab+'</text>';
  });
  s+='<text x="'+((padL+W-14)/2)+'" y="'+(H-6)+'" text-anchor="middle" font-size="10" fill="#7A8893">Expected annual climate cost, $/yr</text>';
  s+="</svg>";return s;
}
/* loss-exceedance curve with retain / transfer / tail shading */
function layerSvg(varByRp,ls){
  const W=460,H=230,padL=54,padB=34,padT=12;
  const xs=RPS.map(rp=>Math.log(rp));
  const xmin=xs[0],xmax=xs[xs.length-1];
  const ymax=Math.max(varByRp[500]||1,1)*1.06;
  const X=rp=>padL+(Math.log(rp)-xmin)/(xmax-xmin)*(W-padL-14);
  const Y=v=>padT+(1-v/ymax)*(H-padT-padB);
  let s=svgEl(W,H);
  // layer bands (horizontal, in loss space)
  s+='<rect x="'+padL+'" y="'+Y(ls.A)+'" width="'+(W-padL-14)+'" height="'+Math.max(Y(0)-Y(ls.A),0)+'" fill="#8AA0AC" opacity="0.13"/>';
  s+='<rect x="'+padL+'" y="'+Y(ls.E)+'" width="'+(W-padL-14)+'" height="'+Math.max(Y(ls.A)-Y(ls.E),0)+'" fill="#7FD0C4" opacity="0.28"/>';
  s+='<rect x="'+padL+'" y="'+padT+'" width="'+(W-padL-14)+'" height="'+Math.max(Y(ls.E)-padT,0)+'" fill="#B23A32" opacity="0.10"/>';
  [ [ls.A,"attach "+fmt$(ls.A),"#43535F"], [ls.E,"exhaust "+fmt$(ls.E),"#43535F"] ].forEach(([v,lab,col])=>{
    s+='<line x1="'+padL+'" y1="'+Y(v)+'" x2="'+(W-14)+'" y2="'+Y(v)+'" stroke="'+col+'" stroke-width="1" stroke-dasharray="4 4"/>';
    s+='<text x="'+(W-16)+'" y="'+(Y(v)-4)+'" text-anchor="end" font-size="9.5" fill="'+col+'">'+lab+'</text>';});
  // EP curve
  let path="";RPS.forEach((rp,i)=>{path+=(i?"L":"M")+X(rp)+" "+Y(varByRp[rp]||0)+" ";});
  s+='<path d="'+path+'" fill="none" stroke="#0F3A4B" stroke-width="2.5"/>';
  RPS.forEach(rp=>{s+='<circle cx="'+X(rp)+'" cy="'+Y(varByRp[rp]||0)+'" r="3" fill="#12586F"/>';
    s+='<text x="'+X(rp)+'" y="'+(H-padB+14)+'" text-anchor="middle" font-size="10" fill="#7A8893">'+rp+'</text>';});
  [0.5,1].forEach(t=>{const y=Y(t*ymax);s+='<text x="'+(padL-6)+'" y="'+(y+3)+'" text-anchor="end" font-size="10" fill="#7A8893">'+fmt$(t*ymax)+'</text>';});
  s+='<text x="'+((padL+W-14)/2)+'" y="'+(H-4)+'" text-anchor="middle" font-size="10" fill="#43535F">Return period (years) &middot; grey retained &middot; teal transferred &middot; red tail beyond limit</text>';
  s+="</svg>";return s;
}
function renderScenarios(){
  if(!sites.length){document.getElementById("scenCards").innerHTML="";document.getElementById("scenBars").innerHTML="";document.getElementById("bandMig").innerHTML="";return;}
  const hz=+(document.getElementById("horSel").value||2050);
  const keys=["present","ssp126_"+hz,"ssp245_"+hz,"ssp585_"+hz];
  const runs=keys.map(sc=>({sc,r:scorePhysTotal(sites,sc)}));
  const present=runs[0].r.ead;
  document.getElementById("scenCards").innerHTML=runs.map(x=>
    '<div class="card"><div class="l">'+SCEN_LABEL[x.sc]+'</div><div class="v" style="font-size:21px">'+fmt$(x.r.ead)+'</div>'+
    '<div class="foot">'+x.r.eadPct.toFixed(2)+'% of value'+(x.sc!=="present"&&present>0?' · +'+((x.r.ead/present-1)*100).toFixed(0)+'% vs present':'')+'</div></div>').join("");
  document.getElementById("scenBars").innerHTML=barsSvg(runs.map(x=>({label:SCEN_LABEL[x.sc],ead:x.r.ead})),"ead","label","#0F3A4B");
  // band migration on combined physical risk
  const bands=["Severe","High","Moderate","Low","Minimal"];
  let s='<table class="tbl"><thead><tr><th>Horizon</th>'+bands.map(b=>'<th class="num">'+b+'</th>').join("")+'</tr></thead><tbody>';
  runs.forEach(x=>{const counts={};bands.forEach(b=>counts[b]=0);x.r.rows.forEach(r=>counts[r.band]++);
    s+='<tr><td>'+SCEN_LABEL[x.sc]+'</td>'+bands.map(b=>'<td class="num mono">'+(counts[b]||"·")+'</td>').join("")+'</tr>';});
  s+="</tbody></table>";document.getElementById("bandMig").innerHTML=s;
}
function currentPathway(){const p=document.getElementById("pathSel");return (p&&p.value&&p.value!=="present")?p.value:"ssp245";}
function syncFinAssume(){
  const g=id=>document.getElementById(id);
  finAssume.revRatio=+g("revRatio").value/100;
  finAssume.gopMargin=+g("gop").value/100;
  finAssume.reopenMonths=+g("reopen").value;
  finAssume.heatDrop=+g("heatDrop").value/100;
  finAssume.corr=+g("corr").value/100;
  g("revRatioVal").textContent=g("revRatio").value+"%";
  g("gopVal").textContent=g("gop").value+"%";
  g("reopenVal").textContent=g("reopen").value;
  g("heatDropVal").textContent=g("heatDrop").value+"%";
  g("corrVal").textContent=(+g("corr").value/100).toFixed(2);
  persist();renderFinance();
}
/* SVP review: optional per-brand overrides of the three site-level assumptions
   (revenue ratio, operating margin, reopen months). Blank uses the global default;
   a set value writes into finAssume.brandOverrides[brand], which assumeFor consumes.
   State + display only, never a bespoke number. */
function renderBrandAssume(){
  const host=document.getElementById("brandAssume"); if(!host)return;
  const brands=[];sites.forEach(s=>{const b=s.brand;if(b&&brands.indexOf(b)<0)brands.push(b);});
  brands.sort();
  if(!brands.length){host.innerHTML="";return;}
  const ov=finAssume.brandOverrides||{};
  const cell=(b,k,val,ph)=>'<td class="num"><input type="number" class="brandov" data-brand="'+esc(b)+'" data-key="'+k+'" min="0" step="1" value="'+val+'" placeholder="'+ph+'" style="width:72px;padding:5px 7px;text-align:right"></td>';
  let h='<div style="font-weight:600;color:var(--primary);margin-bottom:4px">Per-brand overrides'+infoBtn("brandAssume")+'</div>'+
    '<div class="hint" style="margin-bottom:8px">Optional. Blank uses the portfolio defaults above. Set a brand that runs a different revenue mix, margin, or reopening speed, and only its sites recompute.</div>'+
    '<table class="tbl"><thead><tr><th>Brand</th><th class="num">Revenue % of value</th><th class="num">Operating margin %</th><th class="num">Months to reopen</th><th></th></tr></thead><tbody>';
  brands.forEach(b=>{const o=ov[b]||{};
    h+='<tr><td>'+esc(b)+'</td>'+
      cell(b,"revRatio",o.revRatio!=null?Math.round(o.revRatio*100):"",Math.round(finAssume.revRatio*100))+
      cell(b,"gopMargin",o.gopMargin!=null?Math.round(o.gopMargin*100):"",Math.round(finAssume.gopMargin*100))+
      cell(b,"reopenMonths",o.reopenMonths!=null?o.reopenMonths:"",String(finAssume.reopenMonths))+
      '<td class="num">'+(ov[b]?'<button class="lightbtn brandclear" data-brand="'+esc(b)+'" style="padding:3px 9px;font-size:11px">Reset</button>':'')+'</td></tr>';});
  h+='</tbody></table>';
  host.innerHTML=h;
  host.querySelectorAll("input.brandov").forEach(inp=>inp.onchange=()=>{
    const b=inp.dataset.brand,k=inp.dataset.key,raw=String(inp.value).trim();
    const map=finAssume.brandOverrides||(finAssume.brandOverrides={});
    const o=map[b]||(map[b]={});
    if(raw===""){delete o[k];}
    else{let v=+raw;if(!isFinite(v)||v<0){toast("Enter a non-negative number.");renderBrandAssume();return;}
      if(k==="revRatio"||k==="gopMargin")v=v/100;o[k]=v;}
    if(!Object.keys(o).length)delete map[b];
    persist();render();
  });
  host.querySelectorAll("button.brandclear").forEach(btn=>btn.onclick=()=>{
    const map=finAssume.brandOverrides||{};delete map[btn.dataset.brand];persist();render();});
}
function renderFinance(){
  const kpis=document.getElementById("finKpis"); if(!kpis)return;
  if(!sites.length){
    kpis.innerHTML='<div class="card"><div class="l">No portfolio</div><div class="v" style="font-size:18px">&mdash;</div><div class="foot">Load sites to see financial impact</div></div>';
    ["finBreakdown","finAcuteChronic","finDiscBody","finSiteBody","tornado","uncStats","brandAssume"].forEach(id=>document.getElementById(id).innerHTML="");
    document.getElementById("finDiscNote").textContent="";document.getElementById("uncNote").textContent="";return;
  }
  renderBrandAssume();
  const f=finPortfolio(sites,scenario);
  const u=uncRange(sites,scenario);
  const indirect=f.biEad+f.heatCost;
  const card=(l,v,foot,info)=>'<div class="card"><div class="l">'+l+(info?infoBtn(info):"")+'</div><div class="v" style="font-size:22px">'+v+'</div><div class="foot">'+foot+'</div></div>';
  kpis.innerHTML=
    card("Expected annual cost",fmt$(f.totalAal)+"/yr","range "+fmt$(u.low)+" to "+fmt$(u.high)+" \u00b7 "+f.aalPctValue.toFixed(2)+"% of value","totalAal")+
    card("Indirect share",(f.totalAal?indirect/f.totalAal*100:0).toFixed(0)+"%",fmt$(f.biEad)+" BI + "+fmt$(f.heatCost)+" heat","indirect")+
    (f.jointTail
      ?card("1-in-100 Value at Risk",fmt$(f.jointTail.var100),TAIL_JOINT_LABEL+" \u00b7 live blend incl. BI: "+fmt$(f.var100),"var100")+
       card("1-in-250 Value at Risk",fmt$(f.jointTail.var250),TAIL_JOINT_LABEL+" \u00b7 live blend incl. BI: "+fmt$(f.var250),"var250")
      :card("1-in-100 Value at Risk",fmt$(f.var100),"range "+fmt$(f.var100*u.varLoMult)+" to "+fmt$(f.var100*u.varHiMult)+" \u00b7 "+TAIL_BOUND_LABEL,"var100")+
       card("1-in-250 Value at Risk",fmt$(f.var250),(f.value?f.var250/f.value*100:0).toFixed(1)+"% of value \u00b7 "+TAIL_BOUND_LABEL,"var250"));
  document.getElementById("finBreakdown").innerHTML=barsSvg([
    {label:"Direct damage",ead:f.directEad},
    {label:"Business interruption",ead:f.biEad},
    {label:"Heat revenue at risk",ead:f.heatCost},
  ].sort((a,b)=>b.ead-a.ead),"ead","label","#12586F");
  document.getElementById("finAcuteChronic").innerHTML=barsSvg([
    {label:"Acute (damage + BI)",ead:f.acuteAal},
    {label:"Chronic (heat)",ead:f.chronicAal},
  ],"ead","label","#0F3A4B")+
    '<div class="hint" style="margin-top:6px">Acute '+(f.totalAal?f.acuteAal/f.totalAal*100:0).toFixed(0)+'% \u00b7 chronic '+(f.totalAal?f.chronicAal/f.totalAal*100:0).toFixed(0)+'% of expected annual cost.</div>';
  // uncertainty & sensitivity
  document.getElementById("tornado").innerHTML=tornadoSvg(u);
  document.getElementById("uncStats").innerHTML=
    '<span class="k">Central estimate</span><span class="v mono">'+fmt$(u.central)+'/yr</span>'+
    '<span class="k">Plausible low</span><span class="v mono">'+fmt$(u.low)+'/yr</span>'+
    '<span class="k">Plausible high</span><span class="v mono">'+fmt$(u.high)+'/yr</span>'+
    '<span class="k">Largest driver</span><span class="v">'+esc(u.factors[0].label)+'</span>'+
    '<span class="k">1-in-100 VaR band</span><span class="v mono">'+fmt$(f.var100*u.varLoMult)+' to '+fmt$(f.var100*u.varHiMult)+'</span>';
  document.getElementById("uncNote").innerHTML="Deltas are combined by root-sum-square assuming independent inputs, a screening stand-in for CLIMADA's unsequa Monte Carlo. The band widens upward because damage curves are convex. Better data on the top bar buys the most accuracy.";
  const disc=finDisclosure(sites,currentPathway());
  document.getElementById("finDiscBody").innerHTML=disc.map(r=>
    '<tr><td>'+esc(r.label)+'</td><td class="num mono">'+r.acutePct.toFixed(2)+'%</td><td class="num mono">'+r.chronicPct.toFixed(2)+'%</td>'+
    '<td class="num mono">'+r.totalPct.toFixed(2)+'%</td><td class="num mono">'+r.var100Pct.toFixed(1)+'%</td></tr>').join("");
  document.getElementById("finDiscNote").innerHTML=(hazardGrid?"Figures use the loaded CLIMADA grid where available. ":"Figures use the interim model and are for exploration, not disclosure. ")+
    (f.jointTail
      ?"The 1-in-100 column is the results pack's JOINT EVENT TAIL (direct damage), the canonical figure; the live correlation blend (corr "+finAssume.corr.toFixed(2)+", incl. BI) is shown only where labeled. "
      :"Value at Risk here is the live correlation blend (corr "+finAssume.corr.toFixed(2)+"): a co-occurrence approximation, NOT the joint event tail. Load the results pack for the canonical joint figure. ")+
    "Total AAL today: central "+fmt$(u.central)+", plausible range "+fmt$(u.low)+" to "+fmt$(u.high)+".";
  const rows=f.rows.slice().sort((a,b)=>b.totalAal-a.totalAal);
  document.getElementById("finSiteBody").innerHTML=rows.map(r=>
    '<tr class="rowclick" data-focus="'+r.id+'"><td>'+esc(r.name)+'</td><td class="num mono">'+fmt$(r.value)+'</td><td class="num mono">'+fmt$(r.revenue)+'</td>'+
    '<td class="num mono">'+fmt$(r.directEad)+'</td><td class="num mono">'+fmt$(r.biEad)+'</td><td class="num mono">'+fmt$(r.heatCost)+'</td>'+
    '<td class="num mono">'+fmt$(r.totalAal)+'</td><td class="num mono">'+(r.revenue?r.totalAal/r.revenue*100:0).toFixed(1)+'%</td></tr>').join("");
  document.querySelectorAll("#finSiteBody tr[data-focus]").forEach(tr=>tr.onclick=()=>openScorecard(+tr.dataset.focus));
}
/* ============================================================
   Site scorecard (Phase B): the full portfolio-to-asset drill-down.
   One overlay tells a single site's complete story: perils, money,
   trajectory, and its best adaptation actions.
   ============================================================ */
function openScorecard(id){
  const s=sites.find(x=>x.id===id); if(!s)return;
  _scorecardId=id;
  renderScorecard(s);
  document.getElementById("focusBg").classList.add("open");
}
function closeScorecard(){document.getElementById("focusBg").classList.remove("open");}
function renderScorecard(s){
  const fin=finSite(s,scenario);
  const fPort=finPortfolio(sites,scenario);
  const vuln=vulnOf(s);
  const _asm=assumeFor(s);
  const gop=fin.gop, dailyGop=gop/365, maxDown=_asm.reopenMonths/12*365;
  const perils=ACUTE.map(hz=>{
    const r=hzSite(s,hz,scenario);
    return {hz,label:HAZARD_LABEL[hz],band:r.band,cost:r.ead+gop*(_asm.reopenMonths/12)*(r.eadPct/100),curve:r.curve};
  });
  const heatR=hzSite(s,"heat",scenario);
  const phys=perils.reduce((a,p)=>{const c=p.curve.find(x=>x.rp===100);return a+(c?c.loss:0);},0);
  const bi100=perils.reduce((a,p)=>{const c=p.curve.find(x=>x.rp===100);return a+(c?dailyGop*maxDown*(s.asset_value_usd?c.loss/s.asset_value_usd:0):0);},0);
  const physPct=s.asset_value_usd?perils.reduce((a,p)=>a+p.cost,0)/s.asset_value_usd:0;
  const combined=scorePhysTotal([s],scenario).rows[0];
  const costShare=fPort.totalAal?fin.totalAal/fPort.totalAal*100:0;
  const valShare=fPort.value?s.asset_value_usd/fPort.value*100:0;
  const pathway=currentPathway();
  const traj=[["Present","present"],[PATHWAY_LABEL[pathway]+" 2050",pathway+"_2050"],[PATHWAY_LABEL[pathway]+" 2080",pathway+"_2080"]]
    .map(([lab,sc])=>({label:lab,ead:finSite(s,sc).totalAal}));
  const rise2080=traj[0].ead?((traj[2].ead/traj[0].ead-1)*100):0;
  // best measures for this site
  const af=annuity(+document.getElementById("horizon").value,+document.getElementById("disc").value/100);
  const sBase=adaptedFinSite(s,scenario,{}).totalAal;
  const acts=MEASURES.filter(m=>m.inScope(s,scenario)).map(m=>{
    const st=adapt.m[m.key];
    const averted=sBase-adaptedFinSite(s,scenario,m.mods(st)).totalAal;
    const cost=m.siteCost(s,st);
    return {name:m.name,averted,cost,bcr:cost>0?averted*af/cost:0};
  }).sort((a,b)=>b.bcr-a.bcr).slice(0,3);
  const attrs=[];
  if(s.construction)attrs.push(s.construction);
  if(s.year_built)attrs.push("built "+s.year_built);
  if(s.defended)attrs.push("defended");
  attrs.push("wind vulnerability x"+vuln.windMult.toFixed(2));
  document.getElementById("focusHead").innerHTML=
    '<div style="font-family:Fraunces,serif;font-size:21px;color:var(--primary)">'+esc(s.name)+'</div>'+
    '<div class="hint" style="margin:2px 0 0">'+esc(s.brand||"")+(insuredOf(s)!=="Unspecified"?' \u00b7 '+esc(insuredOf(s)):'')+' \u00b7 '+s.latitude.toFixed(3)+', '+s.longitude.toFixed(3)+' \u00b7 '+esc(attrs.join(" \u00b7 "))+' \u00b7 '+SCEN_LABEL[scenario]+'</div>'+
    siteTrustStrip(s);
  const card=(l,v,foot)=>'<div class="card"><div class="l">'+l+'</div><div class="v" style="font-size:19px">'+v+'</div><div class="foot">'+foot+'</div></div>';
  const pills=perils.map(p=>'<span class="pill '+p.band+'" title="'+esc(p.label)+'">'+HAZARD_BY[p.hz].short+'</span>').join(" ")+' <span class="pill '+heatR.band+'" title="Extreme heat">H</span>';
  document.getElementById("focusBody").innerHTML=
    '<div class="cards" style="margin:16px 0 14px">'+
      card("Climate cost",fmt$(fin.totalAal)+"/yr",(fin.revenue?fin.totalAal/fin.revenue*100:0).toFixed(1)+"% of revenue \u00b7 "+(physPct*100).toFixed(2)+"% of value")+
      card("Portfolio share",costShare.toFixed(0)+"%","of climate cost on "+valShare.toFixed(0)+"% of value")+
      card("Combined physical band",combined.band,pills)+
      card("1-in-100 loss",fmt$(phys+bi100),fmt$(phys)+" damage + "+fmt$(bi100)+" BI")+
    '</div>'+
    '<div class="grid2">'+
      '<div class="panel" style="margin-bottom:14px"><h3>Cost by peril</h3><div class="hint">Direct damage plus attributed interruption; heat is its revenue at risk.</div>'+
        barsSvg(perils.map(p=>({label:p.label,ead:p.cost})).concat([{label:"Extreme heat",ead:fin.heatCost}]).sort((a,b)=>b.ead-a.ead),"ead","label","#0F3A4B")+'</div>'+
      '<div class="panel" style="margin-bottom:14px"><h3>Cost by type</h3><div class="hint">The same total split by mechanism.</div>'+
        barsSvg([{label:"Direct damage",ead:fin.directEad},{label:"Business interruption",ead:fin.biEad},{label:"Heat revenue at risk",ead:fin.heatCost}].sort((a,b)=>b.ead-a.ead),"ead","label","#12586F")+'</div>'+
    '</div>'+
    '<div class="grid2">'+
      '<div class="panel" style="margin-bottom:14px"><h3>Trajectory</h3><div class="hint">Climate cost under '+esc(PATHWAY_LABEL[pathway])+'.</div>'+barsSvg(traj,"ead","label","#2C7DA0")+'</div>'+
      '<div class="panel" style="margin-bottom:14px"><h3>Return-period losses</h3><div class="hint">Combined physical damage plus interruption; peril losses added at equal return period (an upper bound, not a joint event figure).</div>'+
        '<table class="tbl"><thead><tr><th>Return period</th><th class="num">Damage</th><th class="num">Interruption</th><th class="num">Total</th></tr></thead><tbody>'+
        RPS.map(rp=>{const d=perils.reduce((a,p)=>{const c=p.curve.find(x=>x.rp===rp);return a+(c?c.loss:0);},0);
          const bi=dailyGop*maxDown*(s.asset_value_usd?d/s.asset_value_usd:0);
          return '<tr><td class="mono">1 in '+rp+'</td><td class="num mono">'+fmt$(d)+'</td><td class="num mono">'+fmt$(bi)+'</td><td class="num mono">'+fmt$(d+bi)+'</td></tr>';}).join("")+
        '</tbody></table></div>'+
    '</div>'+
    '<div class="panel" style="margin-bottom:14px"><h3>Best actions for this site</h3><div class="hint">Top in-scope measures at current library settings.</div>'+
      '<table class="tbl"><thead><tr><th>Measure</th><th class="num">Averted $/yr</th><th class="num">Cost</th><th class="num">BCR</th></tr></thead><tbody>'+
      (acts.length?acts.map(a=>'<tr><td>'+esc(a.name)+'</td><td class="num mono">'+fmt$(a.averted)+'</td><td class="num mono">'+fmt$(a.cost)+'</td><td class="num mono" style="color:'+(a.bcr>=1?"#2E8B6F":"#B23A32")+'">'+a.bcr.toFixed(2)+'x</td></tr>').join(""):'<tr><td colspan="4" class="hint">No in-scope measures</td></tr>')+
      '</tbody></table></div>'+
    namedInsuredDetail(s)+
    traceSection(s)+
    '<div class="panel" style="margin-bottom:4px;border-left:3px solid var(--primary)"><div style="font-size:14px;line-height:1.6">'+scorecardNarrative(s,fin,perils,costShare,valShare,rise2080,acts,pathway)+'</div></div>';
}
function scorecardNarrative(s,fin,perils,costShare,valShare,rise2080,acts,pathway){
  const all=perils.map(p=>({label:p.label,cost:p.cost})).concat([{label:"extreme heat",cost:fin.heatCost}]).sort((a,b)=>b.cost-a.cost);
  const dom=all[0], domShare=fin.totalAal?dom.cost/fin.totalAal*100:0;
  const conc=costShare>valShare*1.5?" It carries well more than its share of portfolio risk: "+costShare.toFixed(0)+"% of climate cost on "+valShare.toFixed(0)+"% of value.":
             (costShare<valShare*0.6?" It is a portfolio diversifier, carrying "+costShare.toFixed(0)+"% of climate cost on "+valShare.toFixed(0)+"% of value.":"");
  const act=acts.length&&acts[0].bcr>=1?" Best value action: "+esc(acts[0].name)+" at "+acts[0].bcr.toFixed(1)+"x.":
            (acts.length?" No measure clears breakeven here at current settings; risk transfer or acceptance may be the right posture.":"");
  return "<b>"+esc(s.name)+"</b> runs an expected climate cost of <b>"+fmt$(fin.totalAal)+" per year</b>, led by <b>"+esc(dom.label.toLowerCase())+"</b> at "+domShare.toFixed(0)+"% of its total."+conc+
    " Under "+esc(PATHWAY_LABEL[pathway])+", its cost rises about <b>"+rise2080.toFixed(0)+"%</b> by 2080."+act;
}
function renderBacktest(){
  const stats=document.getElementById("btStats"); if(!stats)return;
  if(!backtest||!sites.length){
    stats.innerHTML="";document.getElementById("btChart").innerHTML="";
    document.getElementById("btTableWrap").style.display="none";
    document.getElementById("btNote").textContent="No observed losses loaded. When loaded, the scatter compares modeled direct-damage AAL against your history; the 1:1 line is a perfect match. Even a decade of records is a noisy sample of catastrophe risk, so read systematic bias, not single-site scatter.";
    return;
  }
  const byName={};sites.forEach(s=>byName[s.name.trim().toLowerCase()]=s);
  const pairs=[],unmatched=[];
  backtest.rows.forEach(r=>{
    const s=byName[r.name.trim().toLowerCase()];
    if(!s){unmatched.push(r.name);return;}
    const modeled=ACUTE.reduce((a,hz)=>a+hzSite(s,hz,"present").ead,0);   // present-day damage AAL, the claims-like quantity
    pairs.push({name:s.name,modeled,observed:r.observed});
  });
  if(!pairs.length){
    stats.innerHTML='<span class="k">Matched sites</span><span class="v">0 of '+backtest.rows.length+'</span>';
    document.getElementById("btChart").innerHTML="";document.getElementById("btTableWrap").style.display="none";
    document.getElementById("btNote").textContent="No site names matched the loaded portfolio. Names must match exactly (case-insensitive).";
    return;
  }
  const sumM=pairs.reduce((a,p)=>a+p.modeled,0), sumO=pairs.reduce((a,p)=>a+p.observed,0);
  const bias=sumM>0?sumO/sumM:0;
  stats.innerHTML=
    '<span class="k">Matched sites</span><span class="v mono">'+pairs.length+' of '+backtest.rows.length+'</span>'+
    '<span class="k">Modeled damage AAL</span><span class="v mono">'+fmt$(sumM)+'/yr</span>'+
    '<span class="k">Observed losses</span><span class="v mono">'+fmt$(sumO)+'/yr</span>'+
    '<span class="k">Bias (observed / modeled)</span><span class="v mono" style="color:'+(bias>0.5&&bias<2?"#2E8B6F":"#B23A32")+'">'+bias.toFixed(2)+'x</span>';
  document.getElementById("btChart").innerHTML=scatterSvg(pairs);
  document.getElementById("btTableWrap").style.display="block";
  document.getElementById("btBody").innerHTML=pairs.slice().sort((a,b)=>b.observed-a.observed).map(p=>
    '<tr><td>'+esc(p.name)+'</td><td class="num mono">'+fmt$(p.modeled)+'</td><td class="num mono">'+fmt$(p.observed)+'</td>'+
    '<td class="num mono">'+(p.modeled>0?(p.observed/p.modeled).toFixed(2)+"x":"\u2014")+'</td></tr>').join("");
  document.getElementById("btNote").innerHTML="Portfolio bias of <b>"+bias.toFixed(2)+"x</b>"+
    (bias>0.5&&bias<2?" is within the noise a short loss history carries; the model is broadly consistent with experience.":
     bias>=2?" suggests the model understates risk for this portfolio; consider raising hazard intensity or damage steepness within their uncertainty ranges.":
     " suggests the model overstates risk; consider your defenses and construction attributes, or lower damage steepness.")+
    (unmatched.length?" Unmatched names: "+esc(unmatched.slice(0,4).join(", "))+(unmatched.length>4?" +"+(unmatched.length-4)+" more":"")+".":"")+
    " Comparison is against present-day modeled damage AAL; single sites scatter widely by nature.";
}
function scatterSvg(pairs){
  const W=460,H=240,pad=52;
  const maxV=Math.max.apply(null,pairs.map(p=>Math.max(p.modeled,p.observed)))*1.1||1;
  const X=v=>pad+(v/maxV)*(W-pad-16);
  const Y=v=>H-34-(v/maxV)*(H-34-14);
  let s=svgEl(W,H);
  [0.25,0.5,0.75,1].forEach(t=>{const v=t*maxV;
    s+='<line x1="'+pad+'" y1="'+Y(v)+'" x2="'+(W-16)+'" y2="'+Y(v)+'" stroke="#EEF0EC"/>';
    s+='<text x="'+(pad-6)+'" y="'+(Y(v)+3)+'" text-anchor="end" font-size="9.5" fill="#7A8893">'+fmt$(v)+'</text>';
    s+='<text x="'+X(v)+'" y="'+(H-20)+'" text-anchor="middle" font-size="9.5" fill="#7A8893">'+fmt$(v)+'</text>';});
  s+='<line x1="'+X(0)+'" y1="'+Y(0)+'" x2="'+X(maxV)+'" y2="'+Y(maxV)+'" stroke="#B23A32" stroke-width="1.2" stroke-dasharray="5 4"/>';
  s+='<text x="'+(X(maxV)-4)+'" y="'+(Y(maxV)+12)+'" text-anchor="end" font-size="9.5" fill="#B23A32">1:1</text>';
  pairs.forEach(p=>{
    s+='<circle cx="'+X(p.modeled)+'" cy="'+Y(p.observed)+'" r="5" fill="#12586F" opacity="0.85"><title>'+esc(p.name)+': modeled '+fmt$(p.modeled)+', observed '+fmt$(p.observed)+'</title></circle>';});
  s+='<text x="'+((pad+W-16)/2)+'" y="'+(H-4)+'" text-anchor="middle" font-size="10" fill="#43535F">Modeled damage AAL</text>';
  s+='<text x="12" y="'+((H-34+14)/2)+'" text-anchor="middle" font-size="10" fill="#43535F" transform="rotate(-90 12 '+((H-34+14)/2)+')">Observed $/yr</text>';
  s+="</svg>";return s;
}
/* Phase 4: per-peril authority, resolved PER SITE. Which perils are
   grid-fed, with how many cells, whether every app scenario is covered
   (partial coverage means the app silently serves that peril's PRESENT grid
   for missing horizons, which is exactly the failure the v1 deployment
   shipped with: so it is surfaced, not hidden), and - the per-site trust
   increment - how many of the LOADED SITES the grid actually reached. A
   peril chip may only read green when the grid is live, covers every
   scenario, AND reached every site; a Hawaii site outside a CONUS-only
   layer degrades the chip and is counted. Tolerates grids persisted before
   perHaz existed by recomputing from the rows. */
function perilAuthority(){
  let ph=(hazardGrid&&hazardGrid.meta&&hazardGrid.meta.perHaz)||null;
  if(!ph&&hazardGrid&&hazardGrid.rows){
    ph={};hazardGrid.rows.forEach(r=>{const h=r.hazard||"tc";
      const e=ph[h]||(ph[h]={cells:0,scenarios:[]});e.cells++;
      if(e.scenarios.indexOf(r.scenario)<0)e.scenarios.push(r.scenario);});
  }
  return HAZARDS.map(h=>{
    const live=!!gridByHazard[h.key], info=ph&&ph[h.key];
    let sitesModeled=0;
    if(live)sites.forEach(s=>{if(siteTrust(s,h.key,scenario).state==="modeled")sitesModeled++;});
    const allSites=!sites.length||sitesModeled===sites.length;
    return {key:h.key,label:h.label,short:h.short,live,
      cells:info?info.cells:0,nScen:info?info.scenarios.length:0,
      sitesModeled,nSites:sites.length,allSites,
      full:(info?info.scenarios.length>=SCEN_KEYS.length:false)&&allSites};
  });
}
function metaSources(m){ return m?((m.sources&&m.sources.length)?m.sources:[m]):[]; }
function metaSourceLine(s){
  const bits=[];
  if(s.script)bits.push(esc(String(s.script).split(" ")[0]));
  if(s.generated_utc)bits.push("run "+esc(String(s.generated_utc).slice(0,10)));
  if(s.climada_version)bits.push("climada "+esc(s.climada_version)+(s.climada_petals_version?" + petals "+esc(s.climada_petals_version):""));
  if(s.nb_synth_tracks)bits.push(esc(s.nb_synth_tracks)+" synth tracks");
  if(s.surge&&s.surge.dem_path)bits.push("DEM "+esc(String(s.surge.dem_path).split(/[\/\\]/).pop()));
  if(s.method)bits.push(esc(s.method));
  if(s.years&&s.years.length)bits.push("climatology "+esc(s.years[0])+"-"+esc(s.years[s.years.length-1]));
  return bits.join(" \u00b7 ");
}
function renderHazProv(){
  const badge=document.getElementById("hazBadge"),text=document.getElementById("hazText");
  const auth=perilAuthority();
  const chip=a=>'<span class="pill mini" title="'+esc(a.label+": "+(a.live?("CLIMADA grid, "+a.cells+" cells, "+a.nScen+"/"+SCEN_KEYS.length+" scenarios"+(a.nSites?", "+a.sitesModeled+"/"+a.nSites+" sites within coverage":"")):"interim model"))+'" style="background:'+(a.live?(a.full?"var(--r-low)":"var(--r-mod)"):"var(--r-min)")+'">'+a.short+'</span>';
  const chips=auth.map(chip).join("");
  /* Parallel swap: the perils this tool does NOT model, stated in gray on the
     same surface that vouches for the ones it does. Same row in both branches:
     absence of a model is a fact about the tool, not about the data loaded. */
  const nmRow='<span class="k">Not modeled</span><span class="v">'+notModeledChips()+
    ' hail, non-TC pluvial flooding, and drought are outside this tool’s scope entirely; no figure here includes them (hover a chip for what to do instead)</span>';
  const md=hazardMeta&&hazardMeta.data;
  if(hazardGrid){
    const nLive=auth.filter(a=>a.live).length;
    const liveL=auth.filter(a=>a.live).map(a=>a.label.toLowerCase());
    const interimL=auth.filter(a=>!a.live).map(a=>a.label.toLowerCase());
    const partial=auth.filter(a=>a.live&&!a.full);
    const uncovered=auth.filter(a=>a.live&&!a.allSites);
    badge.classList.add("authoritative");
    text.textContent="CLIMADA \u00b7 "+nLive+"/"+HAZARDS.length+" perils";
    badge.title=md&&md.generated_utc?("Pipeline run "+String(md.generated_utc).slice(0,10)):"Per-peril detail on the Method tab";
    let kv=
      '<span class="k">Perils</span><span class="v">'+chips+(partial.length?' <small>amber: partial scenario or site coverage; green needs every scenario AND every site inside coverage</small>':'')+'</span>'+
      nmRow+
      (uncovered.length?'<span class="k">Site coverage</span><span class="v">'+uncovered.map(a=>a.label.toLowerCase()+": "+a.sitesModeled+" of "+a.nSites+" sites within coverage").join(" \u00b7 ")+' <small>sites outside a peril\u2019s coverage show degraded on that peril, never a silent zero</small></span>':'')+
      /* Task 4: flood depth basis at a glance */
      ((sites.length&&(gridByHazard.cflood||gridByHazard.rflood))?(function(){
        const n=sites.filter(s=>siteRelief(s)!=null).length;
        return '<span class="k">Flood depth basis</span><span class="v">at the structure for '+n+' of '+sites.length+' sites'+(n<sites.length?'; the rest read the cell average (modeled-coarse, flagged per site)':'')+'</span>';
      })():'')+
      '<span class="k">File</span><span class="v mono">'+esc(hazardGrid.meta.name)+'</span>'+
      '<span class="k">Grid cells</span><span class="v mono">'+hazardGrid.meta.cells+'</span>'+
      '<span class="k">Scenarios</span><span class="v mono">'+hazardGrid.meta.scenarios.length+' keys</span>'+
      '<span class="k">Loaded</span><span class="v mono">'+hazardGrid.meta.loaded+'</span>';
    if(md){
      metaSources(md).forEach((s,i)=>{const line=metaSourceLine(s);
        if(line)kv+='<span class="k">'+(i===0?"Pipeline":"")+'</span><span class="v">'+line+'</span>';});
      const skipped=(md.skipped||[]).length;
      if(skipped)kv+='<span class="k">Skipped</span><span class="v">'+skipped+' layer'+(skipped>1?"s":"")+' in the last run fell back to interim (details in the meta file)</span>';
      kv+='<span class="k">Meta file</span><span class="v mono">'+esc(hazardMeta.name)+' \u00b7 '+hazardMeta.loaded+'</span>';
    }else{
      kv+='<span class="k">Provenance</span><span class="v">Drop <span class="mono">hazard_grid_meta.json</span> here too to attach the run record: date, CLIMADA versions, datasets matched, DEM.</span>';
    }
    document.getElementById("hazProv").innerHTML=kv;
    document.getElementById("hazNote").textContent=
      "CLIMADA hazard is live for "+liveL.join(", ")+"."+
      (interimL.length?" Still on the interim model: "+interimL.join(", ")+".":"")+
      (partial.length?" Partial scenario coverage on "+partial.map(a=>a.label.toLowerCase()).join(", ")+": missing horizons use that peril's present grid.":"")+
      (uncovered.length?" Sites outside coverage on "+uncovered.map(a=>a.label.toLowerCase()+" ("+(a.nSites-a.sitesModeled)+")").join(", ")+": those sites show degraded on that peril.":"")+
      (md&&md.generated_utc?" Pipeline run "+String(md.generated_utc).slice(0,10)+".":"")+
      " Each site snaps to the nearest cell within 200 km; beyond that, the site is degraded to the interim model and marked so.";
  }else{
    badge.classList.remove("authoritative");text.textContent="Interim model";badge.title="";
    document.getElementById("hazProv").innerHTML=
      '<span class="k">Perils</span><span class="v">'+chips+' <small>all on the interim model until a grid is loaded</small></span>'+
      nmRow+
      '<span class="k">Source</span><span class="v">Built-in interim model</span>'+
      '<span class="k">Basis</span><span class="v">Regional wind anchors, coast-distance flood proxies, latitude-and-continentality heat</span>'+
      '<span class="k">Status</span><span class="v">Exploration only, not for disclosure</span>';
  }
}
/* Phase 5: the results pack panel. Shows the pipeline's event-set figures
   for the selected scenario BESIDE the live model's equivalents. The pack is
   direct damage only; business interruption, chronic heat, and insurance
   stay in this app's live model, which is why both columns exist. */
/* layer stats on the PACK's joint exceedance curve: the event-set benchmark
   for the insurance layer the sliders configure. Uses the same integral as
   the live model (layerStatsCalc), so the two rows differ only by curve. */
function packLayerStats(sc){
  const pk=resultsPack&&resultsPack.data;
  if(!pk||!pk.scenarios)return null;
  const s=pk.scenarios[sc]||pk.scenarios.present;
  if(!s)return null;
  const ep={};RPS.forEach(rp=>ep[rp]=+((s.portfolio.ep_usd||{})[String(rp)])||0);
  return layerStatsCalc(ep,+s.portfolio.direct_aal_usd||0);
}
function renderResultsPack(){
  const el=document.getElementById("packPanel"); if(!el)return;
  const pk=resultsPack&&resultsPack.data;
  if(!pk||!pk.scenarios){ el.innerHTML=""; return; }
  const sc=pk.scenarios[scenario]?scenario:"present";
  const s=pk.scenarios[sc]; if(!s){ el.innerHTML=""; return; }
  const p=s.portfolio, ep=p.ep_usd||{};
  const live=sites.length?finPortfolio(sites,sc):null;
  const unc=(pk.uncertainty||{})[sc], band=unc&&unc.acute_aal_usd;
  const scLabel=sc==="present"?"Present day":sc.replace("_"," \u00b7 ");
  const row=(k,pack,liveV)=>'<span class="k">'+k+'</span><span class="v mono">'+pack+
    (liveV!=null?' <small>live model: '+liveV+'</small>':'')+'</span>';
  let h='<div class="drop" style="cursor:default;text-align:left">'+
    '<div class="big">CLIMADA results pack <span style="font-size:11px;color:var(--r-low,#2c7a4b)">event-set figures</span></div>'+
    '<div class="kv" style="margin-top:8px">'+
    row("Scenario",esc(scLabel)+(sc!==scenario?" (pack has no "+esc(scenario)+")":""))+
    row("Direct AAL",fmt$(p.direct_aal_usd||0),
        live?fmt$(live.directEad)+" direct EAD":null)+
    row("1-in-100 loss",fmt$(+ep["100"]||0),
        live?fmt$(live.var100)+" diversified acute (upper-bound blend)":null)+
    row("Loss exceedance",RPS.map(rp=>rp+"y "+fmt$(+ep[String(rp)]||0)).join(" \u00b7 "))+
    row("By peril",Object.keys(p.by_peril_aal_usd||{}).map(z=>z+" "+fmt$(p.by_peril_aal_usd[z]||0)).join(" \u00b7 "))+
    (band?row("Uncertainty",fmt$(band.p5)+" .. "+fmt$(band.p95)+" (p5..p95, AAL)"):"")+
    (pk.calibration?row("Calibration","v_half "+esc(pk.calibration.fitted_v_half)+
        " (model/observed bias "+esc(pk.calibration.portfolio_bias)+")"):"")+
    (function(){const ps=packLayerStats(sc);return (ps&&ps.limit>0)?
      row("Layer benchmark","1-in-"+adapt.attach+" to 1-in-"+adapt.exhaust+": "+
        fmt$(ps.transferred)+"/yr expected to layer \u00b7 technical premium "+
        fmt$(ps.premium)+"/yr at load "+adapt.load):"";})()+
    (pk.capital_plan&&pk.capital_plan.projects&&pk.capital_plan.projects.length?
      row("Top capital projects",pk.capital_plan.projects.slice(0,5).map(cp=>
        (cp.year!=null?"Y"+esc(cp.year)+" \u00b7 ":(("year" in cp)?"deferred \u00b7 ":""))+
        esc(cp.site)+" \u00b7 "+esc(cp.measure)+" \u00b7 BCR "+esc(cp.bcr)+
        " ("+fmt$(cp.averted_direct_aal_usd)+"/yr averted, "+fmt$(cp.cost_usd)+
        (cp.renovation_synergy?", refurbishment-phased":"")+")"
      ).join("<br>")+"<br><small>ranked by canonical benefit-cost ratio, "+
        esc(pk.capital_plan.scenario)+" appraisal"+
        (pk.capital_plan.budget_annual_usd?", "+fmt$(pk.capital_plan.budget_annual_usd)+"/yr budget":"")+
        "</small>"):"")+
    (pk.measures_catalog&&pk.measures_catalog.identified&&pk.measures_catalog.identified.length?
      row("Identified, not yet priced",pk.measures_catalog.identified.map(m=>
        esc(m.name)+" ("+esc(m.sites_in_scope)+" site"+(m.sites_in_scope===1?"":"s")+")"
      ).join("<br>")+"<br><small>continuity measures are appraised in this "+
        "app\u2019s financial model</small>"):"")+
    row("Provenance",esc(String(pk.script||"refresh_impacts.py").split(" ")[0])+
        " \u00b7 run "+esc(String(pk.generated_utc||"").slice(0,10))+
        " \u00b7 "+esc((pk.sites&&pk.sites.count)||"?")+" sites \u00b7 file "+esc(resultsPack.name))+
    '</div>'+
    '<small>Pack figures are DIRECT damage from the full CLIMADA event sets '+
    '(per-event losses summed across sites before the exceedance curve, so the '+
    'portfolio tail is joint, not an upper bound). Business interruption, '+
    'chronic heat, and insurance layering remain in this app\u2019s live model.</small></div>';
  el.innerHTML=h;
}


/* ============================================================
   Phase C2 experience layer: scenario scrubber, score tracing,
   board brief. Render-only: every figure on these surfaces comes
   from the same functions the parity suite pins.
   ============================================================ */
function scrubSteps(){
  const p=currentPathway();
  return [{label:"Present",sc:"present"}].concat(HORIZONS.map(h=>({label:String(h),sc:p+"_"+h})));
}
function scrubIndex(){
  const st=scrubSteps();
  for(let i=0;i<st.length;i++)if(st[i].sc===scenario)return i;
  return scenario==="present"?0:-1;
}
function scrubTo(i){
  const st=scrubSteps()[i]; if(!st)return;
  scenario=st.sc; persist(); if(scenHook)scenHook(); render();
}
function stopScrub(){
  if(scrubTimer){clearInterval(scrubTimer);scrubTimer=null;}
  const b=document.getElementById("scrubPlay"); if(b)b.textContent="Play";
  const eb=document.getElementById("execPlay"); if(eb)eb.textContent="▶ Play";   // exec timeline pill stays in sync
}
function playScrub(){
  if(scrubTimer){stopScrub();return;}
  const b=document.getElementById("scrubPlay"); if(b)b.textContent="Stop";
  /* start the timer before the first step so the exec timeline pill (rebuilt
     by the render inside scrubTo) labels itself Stop from the first frame */
  let i=0;
  scrubTimer=setInterval(()=>{i++;
    if(i>=scrubSteps().length){stopScrub();return;}
    scrubTo(i);
  },1500);
  scrubTo(0);
}
function renderScrub(){
  const host=document.getElementById("scrubSteps"); if(!host)return;
  const idx=scrubIndex(), p=currentPathway();
  const lab=document.getElementById("scrubPath"); if(lab)lab.textContent="under "+(PATHWAY_LABEL[p]||p);
  host.innerHTML=scrubSteps().map((st,i)=>'<button type="button" class="scrubstep'+(i===idx?" cur":"")+'" data-scrub="'+i+'">'+esc(st.label)+'</button>').join("");
  host.querySelectorAll("button[data-scrub]").forEach(bt=>bt.onclick=()=>{stopScrub();scrubTo(+bt.dataset.scrub);});
}

/* ---- score tracing (scorecard) ---- */
function fmtVecLine(ex){
  if(ex.inputs.kind==="indicators"){const d=ex.inputs.indicators||{};
    return d.daysOver32+" days over 32C, "+d.daysOver35+" over 35C (dry-bulb), "+
      (d.daysHi35!=null?d.daysHi35+" humid-heat days (feels-like >35C at screening RH "+Math.round((d.rhWarm||0)*100)+"%), ":"")+
      d.cdd+" cooling degree days";}
  if(ex.inputs.kind==="burn")return (+ex.inputs.burnPct).toFixed(2)+" % annual burn probability";
  const v=ex.inputs.vec||{};
  return RPS.map(rp=>"1-in-"+rp+": "+(+v[rp]||0).toFixed(ex.hz==="tc"?0:2)).join(" \u00b7 ")+" "+ex.unit;
}
function fmtFactor(f){
  if(f.mult!=null)return esc(f.name)+" \u00d7"+f.mult.toFixed(2);
  if(f.add!=null)return esc(f.name)+" +"+f.add.toFixed(1)+" m freeboard";
  if(f.cap!=null)return esc(f.name)+": damage capped at "+Math.round(f.cap*100)+"% of value";
  return esc(f.name);
}
function traceSection(s){
  const rows=ACUTE.concat(["heat"]).map(hz=>{
    const ex=explainPeril(s,hz,scenario);
    const src=ex.source||{};
    const srcTxt=src.kind==="grid"?("CLIMADA grid"+(src.distKm!=null?", cell "+(+src.distKm).toFixed(1)+" km":"")):
                 src.kind==="interim"?"interim model":"no data, scores zero";
    const head=hz==="heat"
      ?((ex.inputs.indicators?ex.inputs.indicators.daysOver32+" days over 32C":"")+" ("+ex.band+")")
      :(fmt$(ex.ead)+"/yr ("+ex.band+")");
    const det=
      '<div class="kv" style="margin-top:6px">'+
      '<span class="k">Source</span><span class="v">'+(src.kind==="grid"
        ?("CLIMADA grid"+(src.dataset?" \u00b7 "+esc(src.dataset):"")+(src.distKm!=null?" \u00b7 nearest cell "+(+src.distKm).toFixed(1)+" km":""))
        :esc(src.detail||srcTxt))+'</span>'+
      '<span class="k">Intensity</span><span class="v mono">'+esc(fmtVecLine(ex))+'</span>'+
      (ex.factors.length?'<span class="k">Profile factors</span><span class="v">'+ex.factors.map(fmtFactor).join("<br>")+
        (ex.windMult!=null?'<br><b>combined wind multiplier \u00d7'+ex.windMult.toFixed(2)+'</b>':'')+'</span>':'')+
      (ex.notes.length?'<span class="k">Model</span><span class="v">'+ex.notes.map(esc).join("<br>")+'</span>':'')+
      '</div>';
    return '<details class="trace"><summary><b>'+esc(ex.label)+'</b> \u00b7 '+esc(srcTxt)+' \u00b7 '+head+'</summary>'+det+'</details>';
  }).join("");
  return '<div class="panel" style="margin-bottom:14px"><h3>Why these numbers '+infoBtn("trace")+'</h3>'+
    '<div class="hint">Every figure traced to its data source, its intensities, and the factors this building applies.</div>'+rows+'</div>';
}

/* ---- board brief (print to PDF, zero dependencies) ---- */
function briefHtml(){
  if(!sites.length)return "";
  const sc=scenario, f=finPortfolio(sites,sc), agg=aggregatePortfolio(sites,sc), u=uncRange(sites,sc);
  const p=currentPathway();
  const futureSc=(sc!=="present")?sc:(p+"_2050");
  const pf=finPortfolio(sites,"present"), ff=finPortfolio(sites,futureSc);
  const perilName={tc:"Tropical cyclone wind",cflood:"Coastal flood",rflood:"Riverine flood",heat:"Extreme heat",wfire:"Wildfire",prain:"TC rainfall"};
  const perils=Object.keys(agg.byPeril).map(k=>[perilName[k]||k,agg.byPeril[k]]).sort((a,b)=>b[1]-a[1]);
  const top=agg.perSite.slice().sort((a,b)=>b.total-a.total).slice(0,6);
  const traj=[["Present","present"],[PATHWAY_LABEL[p]+" 2050",p+"_2050"],[PATHWAY_LABEL[p]+" 2080",p+"_2080"]]
    .map(([lab,k])=>[lab,finPortfolio(sites,k).totalAal]);
  const auth=perilAuthority(); const nLive=auth.filter(a=>a.live).length;
  const pk=resultsPack&&resultsPack.data;
  const dt=new Date().toISOString().slice(0,10);
  const kpi=(l,v,foot)=>'<div class="bk"><div class="bl">'+l+'</div><div class="bv">'+v+'</div><div class="bf">'+foot+'</div></div>';
  const tr2=(a,b)=>'<tr><td>'+a+'</td><td class="num mono">'+b+'</td></tr>';
  return '<div class="briefpage">'+
    '<div class="bhead"><div class="bkicker">Travel + Leisure Co. \u00b7 Resort Portfolio Risk-to-Value</div>'+
    '<h1>Portfolio climate risk brief</h1>'+
    '<div class="bmeta">'+esc(SCEN_LABEL[sc]||sc)+' \u00b7 '+sites.length+' site'+(sites.length>1?"s":"")+' \u00b7 generated '+dt+'</div></div>'+
    '<div class="bkpis">'+
      kpi("Insured value",fmt$(f.value),"")+
      kpi("Expected annual cost",fmt$(f.totalAal)+"/yr",f.aalPctValue.toFixed(2)+"% of value \u00b7 range "+fmt$(u.low)+" to "+fmt$(u.high))+
      kpi("1-in-100 Value at Risk",fmt$(f.jointTail?f.jointTail.var100:f.var100),
          (f.value?(f.jointTail?f.jointTail.var100:f.var100)/f.value*100:0).toFixed(1)+"% of value · "+
          (f.jointTail?"joint event tail (results pack, direct damage)":"blend approximation, not the joint tail"))+
      kpi("Climate premium","+"+fmt$(ff.totalAal-pf.totalAal)+"/yr","by "+esc(SCEN_LABEL[futureSc]||futureSc))+
    '</div>'+
    '<div class="bcols"><div>'+
      '<h2>Cost by peril</h2><table>'+perils.map(x=>tr2(esc(x[0]),fmt$(x[1])+"/yr")).join("")+'</table>'+
      '<h2>Trajectory</h2><table>'+traj.map(x=>tr2(esc(x[0]),fmt$(x[1])+"/yr")).join("")+'</table>'+
    '</div><div>'+
      '<h2>Most exposed sites</h2><table>'+top.map(r=>tr2(esc(r.name),fmt$(r.total)+"/yr")).join("")+'</table>'+
    '</div></div>'+
    (pk&&pk.capital_plan&&pk.capital_plan.projects&&pk.capital_plan.projects.length?
      '<h2>Top capital projects (CLIMADA appraisal)</h2><table>'+pk.capital_plan.projects.slice(0,5).map(cp=>
        '<tr><td>'+esc(cp.site)+' \u00b7 '+esc(cp.measure)+'</td><td class="num mono">BCR '+esc(cp.bcr)+' \u00b7 '+
        fmt$(cp.averted_direct_aal_usd)+'/yr averted \u00b7 '+fmt$(cp.cost_usd)+'</td></tr>').join("")+'</table>':'')+
    '<div class="bprov"><b>Data basis:</b> '+(hazardGrid
      ?("CLIMADA hazard grid ("+esc(hazardGrid.meta.name)+"), "+nLive+" of "+HAZARDS.length+" perils grid-driven; the rest use the interim screening model.")
      :"Built-in interim screening model for every peril; load a CLIMADA grid for disclosure-grade figures.")+
    (pk?" Results pack: "+esc(String(pk.script||"refresh_impacts.py").split(" ")[0])+", run "+esc(String(pk.generated_utc||"").slice(0,10))+".":"")+
    " Assumptions: revenue "+Math.round(finAssume.revRatio*100)+"% of value, GOP margin "+Math.round(finAssume.gopMargin*100)+"%, reopen "+finAssume.reopenMonths+" months at total loss."+
    " Screening and appraisal for internal planning, not audited disclosure.</div>"+
    '</div>';
}
function openBrief(){
  if(!sites.length){toast("Load sites first: the brief reports the portfolio.");return;}
  const h=document.getElementById("briefHost"); if(!h)return;
  h.innerHTML=briefHtml();
  document.body.classList.add("printbrief");
  setTimeout(()=>{try{window.print();}catch(e){}},60);
}
