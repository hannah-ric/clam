/* ============================================================
   Adaptation intelligence (Phase A)
   Measures are appraised against the FULL climate cost (direct damage +
   business interruption + heat). Each measure declares a mechanism: a
   modifier on one part of the risk chain. Modifiers compose, so the
   combined portfolio of measures never double-counts averted loss.
   ============================================================ */
let adapt={growth:2.0,attach:25,exhaust:250,load:1.5,quote:0,budget:0,
  m:{wind:{on:true,strength:65,cost:1.0},
     flood:{on:true,fb:0.5,cost:0.6},
     buffer:{on:false,red:0.3,cost:0.4},
     ops:{on:true,fast:30,cost:300},
     cool:{on:false,red:40,cost:0.5},
     fire:{on:false,red:40,cost:0.6}}};

// scope predicates: which sites a measure can act on (and be costed on)
function siteAcuteParts(s,sc){return {cf:hzSite(s,"cflood",sc).ead,rf:hzSite(s,"rflood",sc).ead};}
function isFloodExposed(s,sc){const p=siteAcuteParts(s,sc);return p.cf+p.rf>100;}
function isCoastalExposed(s,sc){return hzSite(s,"cflood",sc).ead>100;}
function isHeatExposed(s,sc){return heatIndicators(s.latitude,s.longitude,sc).daysOver35>HEAT_COMFORT_DAYS;}
function isFireExposed(s,sc){return fireBurnPct(s,sc).pct>0;}

const MEASURES=[
  {key:"wind",name:"Wind hardening (roofs & openings)",info:"mWind",target:"Wind damage + its BI",
   sliders:[{p:"strength",label:"Residual wind damage",min:40,max:100,step:5,fmt:v=>v+"%"},
            {p:"cost",label:"Cost, % of site value",min:0.2,max:3,step:0.1,fmt:v=>(+v).toFixed(1)+"%"}],
   mods:st=>({tcDmgMult:st.strength/100}),
   inScope:()=>true,
   siteCost:(s,st)=>s.asset_value_usd*st.cost/100},
  {key:"flood",name:"Dry floodproofing & utility elevation",info:"mFlood",target:"Flood damage + its BI",
   sliders:[{p:"fb",label:"Added freeboard",min:0.2,max:1.5,step:0.1,fmt:v=>(+v).toFixed(1)+" m"},
            {p:"cost",label:"Cost, % of site value",min:0.1,max:2,step:0.1,fmt:v=>(+v).toFixed(1)+"%"}],
   mods:st=>({fbBonus:st.fb}),
   inScope:isFloodExposed,
   siteCost:(s,st)=>s.asset_value_usd*st.cost/100},
  {key:"buffer",name:"Coastal buffer (dune & mangrove)",info:"mBuffer",target:"Coastal-flood depth",
   sliders:[{p:"red",label:"Surge depth reduction",min:0.1,max:0.8,step:0.1,fmt:v=>(+v).toFixed(1)+" m"},
            {p:"cost",label:"Cost, % of site value",min:0.1,max:1.5,step:0.1,fmt:v=>(+v).toFixed(1)+"%"}],
   mods:st=>({cfDepthRed:st.red}),
   inScope:isCoastalExposed,
   siteCost:(s,st)=>s.asset_value_usd*st.cost/100},
  {key:"ops",name:"Resilient operations (backup power, rapid reopen)",info:"mOps",target:"Business interruption",
   sliders:[{p:"fast",label:"Reopen time reduction",min:10,max:50,step:5,fmt:v=>v+"%"},
            {p:"cost",label:"Cost per site",min:100,max:1000,step:50,fmt:v=>"$"+v+"k"}],
   mods:st=>({reopenMult:1-st.fast/100}),
   inScope:()=>true,
   siteCost:(s,st)=>st.cost*1000},
  {key:"cool",name:"Cooling & shading retrofit",info:"mCool",target:"Heat revenue at risk",
   sliders:[{p:"red",label:"Heat-loss reduction",min:10,max:60,step:5,fmt:v=>v+"%"},
            {p:"cost",label:"Cost, % of site value",min:0.1,max:1.5,step:0.1,fmt:v=>(+v).toFixed(1)+"%"}],
   mods:st=>({heatMult:1-st.red/100}),
   inScope:isHeatExposed,
   siteCost:(s,st)=>s.asset_value_usd*st.cost/100},
  {key:"fire",name:"Wildfire hardening (defensible space & Class A roof)",info:"mFire",target:"Wildfire damage + its BI",
   sliders:[{p:"red",label:"Burn-loss reduction",min:20,max:70,step:5,fmt:v=>v+"%"},
            {p:"cost",label:"Cost, % of site value",min:0.1,max:1.5,step:0.1,fmt:v=>(+v).toFixed(1)+"%"}],
   mods:st=>({fireMult:1-st.red/100}),
   inScope:isFireExposed,
   siteCost:(s,st)=>s.asset_value_usd*st.cost/100},
];
function measureCost(m,sitesArr,sc){
  const st=adapt.m[m.key];
  return sitesArr.reduce((a,s)=>a+(m.inScope(s,sc)?m.siteCost(s,st):0),0);
}
/* finSite with mechanism modifiers. With no mods this reproduces finSite
   exactly (validated), so base and adapted figures share one formula. */
function adaptedFinSite(s,sc,mods){
  mods=mods||{};
  const vuln=vulnOf(s);
  const exp=mods.expMult==null?1:mods.expMult;             // exposure uncertainty: scales value and revenue
  const haz=mods.hazMult==null?1:mods.hazMult;             // hazard-intensity uncertainty: scales wind speed and flood depth
  const dmgK=mods.dmgScale==null?1:mods.dmgScale;          // damage-curve steepness uncertainty
  const a=assumeFor(s);
  const value=s.asset_value_usd*exp;
  const revenue=siteRevenue(s)*exp*(mods.revMult==null?1:mods.revMult);
  const gop=revenue*a.gopMargin;
  const reopenShare=(a.reopenMonths*(mods.reopenMult==null?1:mods.reopenMult))/12;
  const scaleVec=v=>{if(haz===1)return v;const nv={};RPS.forEach(rp=>nv[rp]=(v[rp]||0)*haz);return nv;};
  let directEad=0,biEad=0;
  const w=siteEad(scaleVec(provider()(s.latitude,s.longitude,sc).vec),value,
    {dmgMult:vuln.windMult*(mods.tcDmgMult==null?1:mods.tcDmgMult)*dmgK,vHalf:vuln.vHalf});
  directEad+=w.eadUsd; biEad+=gop*reopenShare*w.eadFrac;
  const relief=siteRelief(s);
  let cvec=scaleVec(reliefVec(hzVector("cflood",s.latitude,s.longitude,sc),relief));
  if(mods.cfDepthRed){const nv={};RPS.forEach(rp=>nv[rp]=Math.max(0,(cvec[rp]||0)-mods.cfDepthRed));cvec=nv;}
  const cf=floodEad(cvec,value,Math.max(FB_COAST+vuln.fbBonus,0)+(mods.fbBonus||0),dmgK,vuln.floodCap);
  directEad+=cf.eadUsd; biEad+=gop*reopenShare*cf.eadFrac;
  const rf=floodEad(scaleVec(reliefVec(hzVector("rflood",s.latitude,s.longitude,sc),relief)),value,Math.max(fbRiver()+vuln.fbBonus,0)+(mods.fbBonus||0),dmgK,vuln.floodCap);
  directEad+=rf.eadUsd; biEad+=gop*reopenShare*rf.eadFrac;
  const pv=floodEad(prainToDepth(scaleVec(hzVector("prain",s.latitude,s.longitude,sc))),value,Math.max(PRAIN_FB+vuln.fbBonus,0)+(mods.fbBonus||0),dmgK,vuln.floodCap);
  directEad+=pv.eadUsd; biEad+=gop*reopenShare*pv.eadFrac;
  const fb2=fireBurnPct(s,sc);
  const fFrac=Math.min((fb2.pct/100)*haz,1)*fb2.cond*fireVulnMult(s)*dmgK*(mods.fireMult==null?1:mods.fireMult);
  directEad+=fFrac*value; biEad+=gop*reopenShare*fFrac;
  const ind=heatIndicators(s.latitude,s.longitude,sc);
  const excess=Math.max(0,ind.daysOver35-HEAT_COMFORT_DAYS);
  const heatCost=(gop/365)*excess*a.heatDrop*(mods.heatMult==null?1:mods.heatMult);
  return {directEad,biEad,heatCost,totalAal:directEad+biEad+heatCost};
}
function adaptedTotal(sitesArr,sc,mods){
  let d=0,b=0,h=0;
  sitesArr.forEach(s=>{const r=adaptedFinSite(s,sc,mods);d+=r.directEad;b+=r.biEad;h+=r.heatCost;});
  return {directEad:d,biEad:b,heatCost:h,totalAal:d+b+h};
}
// merge the modifiers of all enabled measures (fields are disjoint by design)
function enabledMods(){
  const out={};
  MEASURES.forEach(m=>{if(adapt.m[m.key].on)Object.assign(out,m.mods(adapt.m[m.key]));});
  return out;
}
function annuity(years,rate){let a=0;for(let t=1;t<=years;t++)a+=1/Math.pow(1+rate,t);return a;}
/* CLIMADA-style waterfall: risk today, plus exposure growth, plus climate
   change, minus the enabled measure portfolio, equals residual. AAL is
   linear in value and revenue, so growth scales it by (1+g)^years. */
function waterfallData(sitesArr,futureSc){
  const yearMatch=String(futureSc).match(/_(\d{4})$/);
  const years=Math.max((yearMatch?+yearMatch[1]:2050)-2026,1);
  const g=Math.pow(1+adapt.growth/100,years);
  const today=adaptedTotal(sitesArr,"present",{}).totalAal;
  const futBase=adaptedTotal(sitesArr,futureSc,{}).totalAal;
  const futAdapted=adaptedTotal(sitesArr,futureSc,enabledMods()).totalAal;
  const growthInc=today*(g-1);
  const climateInc=g*(futBase-today);
  const future=g*futBase;                 // = today+growthInc+climateInc exactly
  const averted=g*(futBase-futAdapted);
  return {today,growthInc,climateInc,future,averted,residual:future-averted,years,g};
}
/* Risk layering on the diversified acute loss curve. The transferred share
   of the curve integral is applied to acute AAL so retained + transferred
   always reconcile. */
function layerStatsCalc(varByRp,acuteAal){
  const A=varByRp[adapt.attach]||0, E=varByRp[adapt.exhaust]||0;
  const integ=tr=>{
    const pts=RPS.map(rp=>({f:1/rp,L:tr(varByRp[rp]||0)})).sort((a,b)=>b.f-a.f);
    let s2=0;for(let i=0;i<pts.length-1;i++)s2+=0.5*(pts[i].L+pts[i+1].L)*(pts[i].f-pts[i+1].f);
    return s2+pts[pts.length-1].L*pts[pts.length-1].f;
  };
  const tot=integ(L=>L)||1;
  const lay=integ(L=>Math.min(Math.max(L-A,0),Math.max(E-A,0)));
  const frac=Math.min(lay/tot,1);
  const transferred=acuteAal*frac;
  return {A,E,limit:Math.max(E-A,0),transferred,retained:acuteAal-transferred,premium:transferred*adapt.load,frac};
}

/* ============================================================
   Wave 1 decision layer (business-ready roadmap R1-R3).
   Everything here is ADDITIVE: pure functions over the same math the
   parity suite pins. finPortfolio, adaptedFinSite, and layerStatsCalc
   are called, never modified, so no existing number can change.
   ============================================================ */

/* R1: screen the portfolio against the operator's tolerance thresholds and
   route every breach to a decision lane: capex when a measure at that site
   clears breakeven, risk transfer or acceptance when none does. af is the
   annuity factor used for the breakeven screen. */
function toleranceFlags(sitesArr,sc,af){
  const f=finPortfolio(sitesArr,sc);
  const portPct=f.value?f.totalAal/f.value*100:0;
  /* Task 5: the tail breach reads the CANONICAL tail (the pack's joint
     event curve) when one is loaded; else the live blend, labeled */
  const varRef=f.jointTail?f.jointTail.var100:f.var100;
  const varPct=f.value?varRef/f.value*100:0;
  const tailBasis=f.jointTail?"joint event tail (results pack)":"live blend approximation";
  const siteBreaches=[];
  f.rows.forEach(r=>{
    const bps=r.value?r.totalAal/r.value*1e4:0;
    if(bps<=tolerance.siteAalBps)return;
    const s=sitesArr.find(x=>x.id===r.id);
    let best=null;
    if(s){
      const sBase=adaptedFinSite(s,sc,{}).totalAal;
      MEASURES.forEach(m=>{
        if(!m.inScope(s,sc))return;
        const st=adapt.m[m.key];
        const averted=sBase-adaptedFinSite(s,sc,m.mods(st)).totalAal;
        const cost=m.siteCost(s,st);
        const bcr=cost>0?averted*af/cost:0;
        if(!best||bcr>best.bcr)best={name:m.name,bcr};
      });
    }
    siteBreaches.push({id:r.id,name:r.name,aal:r.totalAal,bps,
      bestBcr:best?best.bcr:0,bestMeasure:best?best.name:null,
      lane:(best&&best.bcr>=1)?"capex":"transfer"});
  });
  siteBreaches.sort((a,b)=>b.bps-a.bps);
  const portBreach=portPct>tolerance.portAalPct, varBreach=varPct>tolerance.varPctValue;
  return {portPct,varPct,tailBasis,portBreach,varBreach,siteBreaches,
    anyBreach:portBreach||varBreach||siteBreaches.length>0};
}

/* R2: the acute loss curve split into retained-below, transferred layer,
   and tail beyond the limit, at an EXPLICIT attachment and exhaustion.
   Same trapezoid integral as layerStatsCalc (untouched: parity-pinned);
   the three slices always reconcile to the acute AAL. */
function layerSlices(varByRp,acuteAal,attach,exhaust,load){
  const A=varByRp[attach]||0,E=varByRp[exhaust]||0;
  const integ=tr=>{
    const pts=RPS.map(rp=>({f:1/rp,L:tr(varByRp[rp]||0)})).sort((a,b)=>b.f-a.f);
    let s2=0;for(let i=0;i<pts.length-1;i++)s2+=0.5*(pts[i].L+pts[i+1].L)*(pts[i].f-pts[i+1].f);
    return s2+pts[pts.length-1].L*pts[pts.length-1].f;
  };
  const tot=integ(L=>L)||1;
  const below=acuteAal*Math.min(integ(L=>Math.min(L,A))/tot,1);
  const layer=acuteAal*Math.min(integ(L=>Math.min(Math.max(L-A,0),Math.max(E-A,0)))/tot,1);
  const above=Math.max(acuteAal-below-layer,0);
  return {attach,exhaust,A,E,below,layer,above,premium:layer*load,certainty:layer*load-layer};
}
/* R2: the same layer economics at every candidate attachment below the
   exhaustion point, so "raise the attachment" is a readable trade instead
   of a guess. below is the working layer a higher retention or a captive
   would fund. */
function retentionSweep(varByRp,acuteAal,exhaust,load){
  return RPS.filter(rp=>rp<exhaust).map(rp=>layerSlices(varByRp,acuteAal,rp,exhaust,load));
}
/* R2: a broker quote against the modeled technical premium, as a signed
   percent gap. null when either side is missing: no verdict without data. */
function quoteGapPct(quote,premium){
  if(!(quote>0)||!(premium>0))return null;
  return (quote/premium-1)*100;
}

/* R3: the portfolio action queue. Every in-scope (site, measure) pair is
   appraised individually and ranked by BCR, then a funding cutline is
   drawn: with a budget, fill greedily from the top (never fund below
   breakeven, never drop what does not fit: it stays listed as unfunded,
   the pipeline's defer-not-delete discipline); with no budget the cutline
   is breakeven. The roll-up recomputes the funded set JOINTLY per site
   (merged measure modifiers), so overlapping measures at one site are
   never double-counted in the program figure. */
function actionQueue(sitesArr,sc,af,budget){
  const items=[];
  sitesArr.forEach(s=>{
    const sBase=adaptedFinSite(s,sc,{}).totalAal;
    MEASURES.forEach(m=>{
      if(!m.inScope(s,sc))return;
      const st=adapt.m[m.key];
      const averted=sBase-adaptedFinSite(s,sc,m.mods(st)).totalAal;
      const cost=m.siteCost(s,st);
      items.push({id:s.id,site:s.name,measure:m.name,key:m.key,target:m.target,
        averted,cost,bcr:cost>0?averted*af/cost:0});
    });
  });
  items.sort((a,b)=>b.bcr-a.bcr);
  let spent=0;
  items.forEach(it=>{
    if(it.bcr<1){it.funded=false;return;}
    if(budget>0&&spent+it.cost>budget){it.funded=false;return;}
    it.funded=true;spent+=it.cost;
  });
  const funded=items.filter(i=>i.funded);
  const bySite={};
  funded.forEach(i=>{(bySite[i.id]||(bySite[i.id]=[])).push(i.key);});
  let jointAverted=0;
  Object.keys(bySite).forEach(id=>{
    const s=sitesArr.find(x=>x.id===+id); if(!s)return;
    const mods={};
    bySite[id].forEach(k=>{const m=MEASURES.find(x=>x.key===k);Object.assign(mods,m.mods(adapt.m[k]));});
    jointAverted+=adaptedFinSite(s,sc,{}).totalAal-adaptedFinSite(s,sc,mods).totalAal;
  });
  const cost=funded.reduce((a,i)=>a+i.cost,0);
  return {items,spent,budget,
    roll:{n:funded.length,cost,averted:jointAverted,bcr:cost>0?jointAverted*af/cost:0}};
}

/* R2: the broker evidence pack. Renewal pricing keys off submission data
   quality: documented secondary modifiers (roof, openings, floor height,
   defenses) change the insurer's modeled loss, not just the negotiation.
   One row per site: the verified attributes plus this model's present-day
   direct-damage view, with its source stated honestly. */
function brokerPackCsv(){
  /* per-site source honesty: the old portfolio-wide "climada_grid" label let
     a site outside a peril's coverage claim grid backing in front of a
     broker. hazardSourceOf states, per peril, what actually fed this row. */
  const cols=["name","brand","latitude","longitude","asset_value_usd","annual_revenue_usd",
    "construction","year_built","roof_type","roof_year","opening_protection",
    "first_floor_elev_m","equipment_elevated","defended","wui_class",
    "defensible_space_m","roof_class_a",
    "modeled_direct_ead_usd_present","modeled_top_peril_present",
    "modeled_loss_rp100_usd_present","hazard_source"];
  let csv=cols.join(",")+"\n";
  sites.forEach(s=>{
    let ead=0,top=null,rp100=0;
    ACUTE.forEach(hz=>{
      const r=hzSite(s,hz,"present");ead+=r.ead;
      const c=r.curve.find(x=>x.rp===100);rp100+=c?c.loss:0;
      if(!top||r.ead>top.ead)top={hz,ead:r.ead};
    });
    csv+=[csvCell(s.name),csvCell(s.brand||""),s.latitude,s.longitude,s.asset_value_usd,
      s.annual_revenue_usd!=null?s.annual_revenue_usd:"",
      s.construction||"",s.year_built||"",s.roof_type||"",s.roof_year||"",
      s.opening_protection||"",
      s.first_floor_elev_m!=null?s.first_floor_elev_m:"",
      s.equipment_elevated?"true":"",s.defended?"true":"",
      s.wui_class||"",s.defensible_space_m!=null?s.defensible_space_m:"",
      s.roof_class_a?"true":"",
      ead.toFixed(0),top?top.hz:"",rp100.toFixed(0),
      hazardSourceOf(s,"present")].join(",")+"\n";
  });
  return csv;
}

/* R3: the action-list artifact for a capital committee. Live-model rows are
   the interactive appraisal at current settings; when a results pack is
   loaded, its capital-plan rows are included and labeled canonical (full
   event sets, refurbishment phasing). The owner column is deliberately
   blank: assigning it is the committee's decision, not the model's. */
function actionListCsv(sc,horizon,discPct){
  const af=annuity(horizon,discPct/100);
  const q=actionQueue(sites,sc,af,adapt.budget||0);
  const cols=["source","rank","site","measure","targets","averted_usd_per_yr","cost_usd","bcr",
    "status","renovation_synergy","scenario","appraisal_horizon_years","discount_rate_pct","owner"];
  let csv=cols.join(",")+"\n";
  q.items.forEach((it,i)=>{
    csv+=["live_model",i+1,csvCell(it.site),csvCell(it.measure),csvCell(it.target),
      it.averted.toFixed(0),it.cost.toFixed(0),it.bcr.toFixed(2),
      it.funded?"funded":"unfunded","",sc,horizon,discPct.toFixed(1),""].join(",")+"\n";
  });
  const pk=resultsPack&&resultsPack.data;
  if(pk&&pk.capital_plan&&pk.capital_plan.projects){
    pk.capital_plan.projects.forEach((cp,i)=>{
      csv+=["climada_pack",i+1,csvCell(cp.site),csvCell(cp.measure),csvCell(cp.peril||""),
        (+cp.averted_direct_aal_usd||0).toFixed(0),(+cp.cost_usd||0).toFixed(0),(+cp.bcr||0).toFixed(2),
        cp.year!=null?("year_"+cp.year):"deferred",cp.renovation_synergy?"true":"",
        csvCell(pk.capital_plan.scenario||""),pk.capital_plan.horizon_years!=null?pk.capital_plan.horizon_years:"",
        pk.capital_plan.discount_rate!=null?(pk.capital_plan.discount_rate*100).toFixed(1):"",""].join(",")+"\n";
    });
  }
  return csv;
}

/* ============================================================
   Uncertainty & sensitivity (Phase B)
   A screening-grade take on CLIMADA's unsequa: perturb the most uncertain
   inputs one at a time over plausible ranges, then combine the deltas by
   root-sum-square (independence assumed) into a low/central/high band.
   The per-factor deltas are the sensitivity tornado.
   ============================================================ */
