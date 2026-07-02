/* ============================================================
   Adaptation intelligence (Phase A)
   Measures are appraised against the FULL climate cost (direct damage +
   business interruption + heat). Each measure declares a mechanism: a
   modifier on one part of the risk chain. Modifiers compose, so the
   combined portfolio of measures never double-counts averted loss.
   ============================================================ */
let adapt={growth:2.0,attach:25,exhaust:250,load:1.5,
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
  const value=s.asset_value_usd*exp;
  const revenue=siteRevenue(s)*exp*(mods.revMult==null?1:mods.revMult);
  const gop=revenue*finAssume.gopMargin;
  const reopenShare=(finAssume.reopenMonths*(mods.reopenMult==null?1:mods.reopenMult))/12;
  const scaleVec=v=>{if(haz===1)return v;const nv={};RPS.forEach(rp=>nv[rp]=(v[rp]||0)*haz);return nv;};
  let directEad=0,biEad=0;
  const w=siteEad(scaleVec(provider()(s.latitude,s.longitude,sc).vec),value,
    {dmgMult:vuln.windMult*(mods.tcDmgMult==null?1:mods.tcDmgMult)*dmgK});
  directEad+=w.eadUsd; biEad+=gop*reopenShare*w.eadFrac;
  let cvec=scaleVec(hzVector("cflood",s.latitude,s.longitude,sc));
  if(mods.cfDepthRed){const nv={};RPS.forEach(rp=>nv[rp]=Math.max(0,(cvec[rp]||0)-mods.cfDepthRed));cvec=nv;}
  const cf=floodEad(cvec,value,FB_COAST+vuln.fbBonus+(mods.fbBonus||0),dmgK,vuln.floodCap);
  directEad+=cf.eadUsd; biEad+=gop*reopenShare*cf.eadFrac;
  const rf=floodEad(scaleVec(hzVector("rflood",s.latitude,s.longitude,sc)),value,fbRiver()+vuln.fbBonus+(mods.fbBonus||0),dmgK,vuln.floodCap);
  directEad+=rf.eadUsd; biEad+=gop*reopenShare*rf.eadFrac;
  const pv=floodEad(prainToDepth(scaleVec(hzVector("prain",s.latitude,s.longitude,sc))),value,PRAIN_FB+vuln.fbBonus+(mods.fbBonus||0),dmgK,vuln.floodCap);
  directEad+=pv.eadUsd; biEad+=gop*reopenShare*pv.eadFrac;
  const fb2=fireBurnPct(s,sc);
  const fFrac=Math.min((fb2.pct/100)*haz,1)*FIRE_MDD*fireVulnMult(s)*dmgK*(mods.fireMult==null?1:mods.fireMult);
  directEad+=fFrac*value; biEad+=gop*reopenShare*fFrac;
  const ind=heatIndicators(s.latitude,s.longitude,sc);
  const excess=Math.max(0,ind.daysOver35-HEAT_COMFORT_DAYS);
  const heatCost=(gop/365)*excess*finAssume.heatDrop*(mods.heatMult==null?1:mods.heatMult);
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
   Uncertainty & sensitivity (Phase B)
   A screening-grade take on CLIMADA's unsequa: perturb the most uncertain
   inputs one at a time over plausible ranges, then combine the deltas by
   root-sum-square (independence assumed) into a low/central/high band.
   The per-factor deltas are the sensitivity tornado.
   ============================================================ */
