
/* ============================================================
   RtV risk engine (validated; mirrors CLIMADA emanuel_usa)
   ============================================================ */
const V_THRESH=25.7, V_HALF=74.7;
const RPS=[10,25,50,100,250,500];
// Scenario keys are "present" or "<pathway>_<horizon>" on the CMIP6 SSP-RCP
// framework. Warming (deg C above present) and sea-level rise (m) are
// screening-grade central estimates consistent with IPCC AR6 ranges.
const PATHWAYS=["ssp126","ssp245","ssp585"];
const HORIZONS=[2030,2050,2080];
const PATHWAY_LABEL={present:"Present day",ssp126:"SSP1-2.6",ssp245:"SSP2-4.5",ssp585:"SSP5-8.5"};
const WARMING={present:0,
  ssp126_2030:0.6,ssp126_2050:1.0,ssp126_2080:1.3,
  ssp245_2030:0.7,ssp245_2050:1.4,ssp245_2080:2.3,
  ssp585_2030:0.8,ssp585_2050:2.0,ssp585_2080:3.6};
const SLR={present:0,
  ssp126_2030:0.09,ssp126_2050:0.19,ssp126_2080:0.34,
  ssp245_2030:0.10,ssp245_2050:0.22,ssp245_2080:0.44,
  ssp585_2030:0.11,ssp585_2050:0.27,ssp585_2080:0.62};
function warming(sc){return WARMING[sc]||0;}
function slrOf(sc){return SLR[sc]||0;}
const SCEN_KEYS=["present"].concat([].concat(...HORIZONS.map(h=>PATHWAYS.map(p=>p+"_"+h))));
const SCEN_LABEL=(()=>{const o={present:"Present day"};
  for(const p of PATHWAYS)for(const h of HORIZONS)o[p+"_"+h]=PATHWAY_LABEL[p]+" \u00b7 "+h;return o;})();
// Wind intensity uplift for the interim TC field: ~2% per deg C of warming.
const SCEN_UPLIFT=(()=>{const o={};for(const k of SCEN_KEYS)o[k]=1+0.02*warming(k);return o;})();

function emanuelMdd(v){const vt=Math.max((v-V_THRESH)/(V_HALF-V_THRESH),0);const c=vt*vt*vt;return c/(1+c);}
function haversine(a,b,c,d){const R=6371,r=Math.PI/180;const dLat=(c-a)*r,dLon=(d-b)*r;
  const x=Math.sin(dLat/2)**2+Math.cos(a*r)*Math.cos(c*r)*Math.sin(dLon/2)**2;return 2*R*Math.asin(Math.sqrt(x));}

const ANCHORS=[
  [25.8,-80.2,62,7.5],[24.5,-81.8,64,7.7],[30.0,-90.1,58,7.2],[29.3,-94.8,56,7.0],
  [18.4,-66.1,62,7.6],[18.3,-64.9,62,7.6],[27.0,-82.6,60,7.4],[26.1,-80.1,61,7.5],
  [32.8,-79.9,52,6.9],[33.7,-78.9,50,6.8],[35.2,-75.5,54,7.0],[34.2,-77.9,51,6.8],[30.3,-81.4,48,6.7],
  [36.8,-76.0,44,6.4],[40.7,-74.0,40,6.0],[41.7,-70.3,42,6.2],
  [21.3,-157.8,42,5.8],[19.7,-155.1,46,6.1],[22.1,-159.4,44,6.0],
  [28.5,-81.4,41,6.0],[29.4,-98.5,30,5.2],[33.7,-84.4,26,4.8],[30.3,-97.7,27,5.0],
  [33.8,-116.5,15,3.6],[36.2,-115.1,14,3.4],[39.7,-105.0,12,3.2],[34.0,-118.2,14,3.4],[37.8,-122.4,13,3.3],
];
const IDW_SCALE=380;
function interimVector(lat,lon,scenario){
  let wSum=0,v100=0,b=0;
  for(const [alat,alon,av,ab] of ANCHORS){const d=haversine(lat,lon,alat,alon);const w=Math.exp(-((d/IDW_SCALE)**2));wSum+=w;v100+=w*av;b+=w*ab;}
  if(wSum<1e-6){v100=13;b=3.2;}else{v100/=wSum;b/=wSum;}
  v100*=(SCEN_UPLIFT[scenario]||1);
  const a=v100-b*Math.log(100);const vec={};
  for(const rp of RPS)vec[rp]=Math.max(a+b*Math.log(rp),0);
  return {vec,meta:{v100,b,source:"interim"}};
}
function makeGridProvider(rows){
  const byScen={};for(const row of rows){(byScen[row.scenario]||(byScen[row.scenario]=[])).push(row);}
  return function(lat,lon,scenario,maxKm){maxKm=maxKm||200;
    const list=byScen[scenario]||byScen.present||[];let best=null,bestD=Infinity;
    for(const row of list){const d=haversine(lat,lon,row.lat,row.lon);if(d<bestD){bestD=d;best=row;}}
    if(!best||bestD>maxKm){const z={};for(const rp of RPS)z[rp]=0;return {vec:z,meta:{source:"grid",outside:true,dist:bestD}};}
    const vec={};for(const rp of RPS)vec[rp]=Math.max(+best["v"+rp]||0,0);
    return {vec,meta:{source:"grid",dist:bestD}};
  };
}
function siteEad(vec,value,opts){
  opts=opts||{};const windRed=opts.windRed||0;const dmgMult=opts.dmgMult==null?1:opts.dmgMult;
  const pts=RPS.map(rp=>{const v=Math.max((vec[rp]||0)-windRed,0);return {rp,v,f:1/rp,frac:Math.min(emanuelMdd(v)*dmgMult,1)};});
  if(opts.transfer){for(const p of pts){if(p.rp>=opts.transfer.attachRp&&p.rp<=opts.transfer.exhaustRp)p.frac=0;}}
  const s=pts.slice().sort((x,y)=>y.f-x.f);let eadFrac=0;
  for(let i=0;i<s.length-1;i++)eadFrac+=0.5*(s[i].frac+s[i+1].frac)*(s[i].f-s[i+1].f);
  eadFrac+=s[s.length-1].frac*s[s.length-1].f;
  const curve=pts.map(p=>({rp:p.rp,v:p.v,loss:p.frac*value}));
  return {eadUsd:eadFrac*value,eadFrac,curve};
}
function bandOf(pct){if(pct>=1.5)return"Severe";if(pct>=0.75)return"High";if(pct>=0.25)return"Moderate";if(pct>0.001)return"Low";return"Minimal";}
function brandRollup(rows){
  const m={};for(const r of rows){const k=r.brand||"Unbranded";(m[k]||(m[k]={brand:k,tiv:0,ead:0,n:0}));m[k].tiv+=r.asset_value_usd;m[k].ead+=r.eadUsd;m[k].n++;}
  return Object.values(m).map(x=>Object.assign({},x,{eadPct:x.tiv?x.ead/x.tiv*100:0})).sort((a,b)=>b.ead-a.ead);
}

/* ============================================================
   Multi-hazard interim layer
   Adds coastal flood, riverine flood, and extreme heat alongside the
   wind model. Every proxy here is screening-grade and clearly labelled;
   an extended CLIMADA grid (with a `hazard` column) supersedes any peril
   per-hazard, exactly as the wind grid already supersedes the wind field.
   ============================================================ */
const HAZARDS=[
  {key:"tc",     label:"Tropical cyclone", short:"W", color:"#12586F", type:"damage",    unit:"m/s"},
  {key:"cflood", label:"Coastal flood",    short:"F", color:"#2C7DA0", type:"damage",    unit:"m"},
  {key:"rflood", label:"Riverine flood",   short:"R", color:"#6A8CAF", type:"damage",    unit:"m"},
  {key:"heat",   label:"Extreme heat",     short:"H", color:"#C06B2E", type:"indicator", unit:"days"},
  {key:"wfire",  label:"Wildfire",         short:"B", color:"#A6432E", type:"damage",    unit:"%/yr"},
  {key:"prain",  label:"TC rainfall",      short:"P", color:"#4E7B8C", type:"damage",    unit:"m ponding"},
];
const HAZARD_LABEL={};HAZARDS.forEach(h=>HAZARD_LABEL[h.key]=h.label);
const HAZARD_BY={};HAZARDS.forEach(h=>HAZARD_BY[h.key]=h);

// Coast-proximity proxy: distance to the nearest anchor on a coastline the
// portfolio actually touches. Interim only; replaced by a coastal-flood grid.
const COAST_ANCHORS=[
  [29.3,-94.8],[29.0,-90.1],[27.8,-82.7],[25.8,-80.1],[29.9,-81.3],
  [32.8,-79.9],[33.7,-78.9],[36.8,-76.0],[18.4,-66.1],[18.3,-64.9],
  [18.0,-63.1],[21.3,-157.9],[19.7,-156.0],[22.1,-159.3],[33.7,-118.2],
  [37.8,-122.5],[32.7,-117.2],
];
function coastKm(la,lo){let b=Infinity;for(const [a,o] of COAST_ANCHORS){const d=haversine(la,lo,a,o);if(d<b)b=d;}return b;}
function continentality(la,lo){return Math.min(coastKm(la,lo),400)/400;}
// flood stage-damage: no damage until water clears the finished-floor
// elevation / defenses (freeboard), then concave and capped. Different
// freeboard for coastal vs river-adjacent structures.
const FB_COAST=1.1, FB_RIVER=0.6;
/* Phase 2: if the loaded rflood grid already embeds flood protection
   (FLOPROS-style ISIMIP sets), the interim riverine freeboard must not
   double-count it. Flip to true ONLY after confirming the served dataset's
   protection assumption (see hazard_grid_meta.json and the runbook). */
const RFLOOD_GRID_INCLUDES_PROTECTION=false;
function fbRiver(){return (gridByHazard.rflood&&RFLOOD_GRID_INCLUDES_PROTECTION)?0:FB_RIVER;}
function floodMdd(d,fb,cap){const e=d-(fb||0);return e<=0?0:Math.min(cap==null?0.75:cap,1-Math.exp(-0.6*e));}

function coastalFloodVector(la,lo,sc){
  const near=Math.exp(-coastKm(la,lo)/40);
  const surge=(interimVector(la,lo,"present").vec[100])/74.7;
  const base100=1.8*near*(0.5+0.5*surge);
  const rise=slrOf(sc)*near;                                   // SLR lifts the curve
  const shape={10:0.35,25:0.55,50:0.78,100:1.0,250:1.25,500:1.45};
  const vec={};for(const rp of RPS)vec[rp]=Math.max(0,base100*shape[rp]+rise);return vec;
}
function riverineFloodVector(la,lo,sc){
  const inland=continentality(la,lo);
  const base100=0.8*(0.3+0.7*inland);
  const uplift=1+0.05*warming(sc);
  const shape={10:0.30,25:0.55,50:0.80,100:1.0,250:1.30,500:1.55};
  const vec={};for(const rp of RPS)vec[rp]=base100*shape[rp]*uplift;return vec;
}
function heatIndicators(la,lo,sc){
  /* Phase 3: prefer the data-driven heat grid (observed daily climatology
     shifted by AR6-consistent warming; see refresh_heat.py), encoded as
     v10=days over 32C, v25=days over 35C, v50=cooling degree days. The
     latitude formula remains the fallback when no heat rows are loaded or
     a site sits outside grid coverage, so behaviour never degrades to zero. */
  const g=gridByHazard.heat;
  if(g){const r=g(la,lo,sc);
    if(!(r.meta&&r.meta.outside)){
      const d32=Math.round(r.vec[10]||0),d35=Math.round(r.vec[25]||0),cdd=Math.round(r.vec[50]||0);
      const p=Math.min(Math.max(d35,0.5),199.5)/200;
      const effT=+(35+1.6*Math.log(p/(1-p))).toFixed(1);
      return {effT,daysOver32:d32,daysOver35:d35,cdd,source:"grid"};
    }}
  const baseT=34-0.35*(Math.abs(la)-18)+6*continentality(la,lo);
  const T=baseT+warming(sc);
  const daysOver=thr=>Math.round(200/(1+Math.exp(-(T-thr)/1.6)));
  return {effT:+T.toFixed(1),daysOver32:daysOver(32),daysOver35:daysOver(35),cdd:Math.round(Math.max(0,T-18)*210)};
}
// flood EAD, same frequency integration as siteEad (f descending, tail closed)
function floodEad(vec,value,fb,dmgScale,cap){
  const k=dmgScale==null?1:dmgScale;
  const pts=RPS.map(rp=>{const d=Math.max(vec[rp]||0,0);return {rp,v:d,f:1/rp,frac:Math.min(floodMdd(d,fb,cap)*k,1)};});
  const s=pts.slice().sort((x,y)=>y.f-x.f);let ef=0;
  for(let i=0;i<s.length-1;i++)ef+=0.5*(s[i].frac+s[i+1].frac)*(s[i].f-s[i+1].f);
  ef+=s[s.length-1].frac*s[s.length-1].f;
  return {eadUsd:ef*value,eadFrac:ef,curve:pts.map(p=>({rp:p.rp,v:p.v,loss:p.frac*value}))};
}
function heatBand(days32){const t=[10,45,100,160],n=["Minimal","Low","Moderate","High","Severe"];let i=0;while(i<t.length&&days32>t[i])i++;return n[i];}

/* Increment 3: wildfire and TC-rainfall perils. MIRRORS the pipeline's
   constants; change both sides. Migration safety: with no wfire grid and no
   wui_class, burn probability is ZERO; rainfall has NO interim model at all
   (a grid is required), so loading nothing reproduces the five-peril math. */
const FIRE_MDD=0.6;                              // conditional damage ratio when a site burns
const FIRE_WUI_PBURN={interface:0.3,intermix:0.6};  // interim annual burn %, by WUI class
const FIRE_WARMING_UPLIFT=0.14;                  // burn-probability uplift per deg C
const PRAIN_DRAIN_MM=150, PRAIN_POND_COEFF=0.4, PRAIN_FB=0.3;  // site drainage screening constants
function fireBurnPct(site,sc){
  const g=gridByHazard.wfire;
  if(g){const r=g(site.latitude,site.longitude,sc);
    if(!(r.meta&&r.meta.outside))return {pct:Math.min(Math.max(+r.vec[10]||0,0),100),source:"grid"};}
  const wui=String(site.wui_class||"").toLowerCase();
  const base=FIRE_WUI_PBURN[wui]||0;
  return {pct:base*(1+FIRE_WARMING_UPLIFT*warming(sc)),source:base?"interim":"none"};
}
function fireVulnMult(site){
  let m=1;
  if(site.roof_class_a)m*=0.6;
  const ds=+site.defensible_space_m;
  if(isFinite(ds)&&ds>=30)m*=0.7;
  return m;
}
function prainToDepth(vec){
  const o={};RPS.forEach(rp=>o[rp]=Math.max(0,((vec&&vec[rp])||0)-PRAIN_DRAIN_MM)/1000*PRAIN_POND_COEFF);
  return o;
}

/* Vulnerability attributes (Phase B): optional per-site construction,
   year_built, and defended flags modify the damage curves with simple,
   documented factors. Absent attributes leave the baseline untouched. */
const CONSTR_FACTOR={frame:1.3,masonry:1.0,engineered:0.75};
/* Profile v2 factor table. MIRRORS refresh_impacts.py; change both sides.
   Roof detail supersedes the year-built proxy (no double counting); absent
   fields are neutral; a site with no v2 fields scores exactly as v1. */
const ROOF_TYPE_FACTOR={shingle:1.1,metal:0.85,tile:0.95,membrane:0.95};
const ROOF_AGE_REF_YEAR=2026;
const OPENING_FACTOR={impact:0.85,partial:0.95,none:1.05};
const FIRST_FLOOR_MAX_M=3.0, EQUIP_ELEV_FLOOD_CAP=0.5, FLOOD_CAP_DEFAULT=0.75;
function vulnOf(site){
  let w=1;
  const c=String(site.construction||"").toLowerCase();
  if(CONSTR_FACTOR[c]!=null)w*=CONSTR_FACTOR[c];
  const rt=String(site.roof_type||"").toLowerCase();
  const op=String(site.opening_protection||"").toLowerCase();
  const ry=+site.roof_year;
  const roofish=ROOF_TYPE_FACTOR[rt]!=null||OPENING_FACTOR[op]!=null||(isFinite(ry)&&ry>1800);
  if(roofish){
    if(ROOF_TYPE_FACTOR[rt]!=null)w*=ROOF_TYPE_FACTOR[rt];
    if(isFinite(ry)&&ry>1800){const age=Math.max(ROOF_AGE_REF_YEAR-ry,0);w*=age<=10?0.9:(age<=20?1.0:1.2);}
    if(OPENING_FACTOR[op]!=null)w*=OPENING_FACTOR[op];
  }else{
    const y=+site.year_built;
    if(isFinite(y)&&y>1800){ if(y<1995)w*=1.15; else if(y>=2010)w*=0.9; }
  }
  const ffe=+site.first_floor_elev_m;
  const fbBonus=(isFinite(ffe)&&ffe>=0)?Math.min(ffe,FIRST_FLOOR_MAX_M):(site.defended?0.5:0);
  return {windMult:Math.min(Math.max(w,0.5),1.6), fbBonus,
          floodCap:site.equipment_elevated?EQUIP_ELEV_FLOOD_CAP:FLOOD_CAP_DEFAULT};
}

// per-hazard vector for a site: grid for that hazard if loaded, else interim
function hzVector(hz,la,lo,sc){
  if(hz==="tc") return provider()(la,lo,sc).vec;
  const g=gridByHazard[hz];
  if(g){ const r=g(la,lo,sc); if(!(r.meta&&r.meta.outside)) return r.vec; }
  /* outside grid coverage (>200 km from any cell): fall back to the interim
     model rather than silently scoring zero (Phase 2) */
  if(hz==="cflood") return coastalFloodVector(la,lo,sc);
  if(hz==="rflood") return riverineFloodVector(la,lo,sc);
  return {};
}
// per-hazard result for a site, in a shape the renderers can consume
function hzSite(site,hz,sc){
  const la=site.latitude,lo=site.longitude,val=site.asset_value_usd;
  const vuln=vulnOf(site);
  if(hz==="heat"){
    const ind=heatIndicators(la,lo,sc);
    return {ead:0,eadPct:0,band:heatBand(ind.daysOver32),curve:[],vec:null,indicators:ind,isHeat:true};
  }
  if(hz==="tc"){
    const {vec,meta}=provider()(la,lo,sc);
    const {eadUsd,eadFrac,curve}=siteEad(vec,val,{dmgMult:vuln.windMult});
    return {ead:eadUsd,eadPct:eadFrac*100,band:bandOf(eadFrac*100),curve,vec,hazardMeta:meta};
  }
  if(hz==="wfire"){
    const b=fireBurnPct(site,sc), fv=fireVulnMult(site);
    const frac=(b.pct/100)*FIRE_MDD*fv;
    const curve=RPS.map(rp=>({rp,v:b.pct,loss:(b.pct>=100/rp)?val*FIRE_MDD*fv:0}));
    return {ead:frac*val,eadPct:frac*100,band:bandOf(frac*100),curve,vec:null,burnPct:b.pct,fireSource:b.source};
  }
  if(hz==="prain"){
    const dvec=prainToDepth(hzVector("prain",la,lo,sc));
    const {eadUsd,eadFrac,curve}=floodEad(dvec,val,PRAIN_FB+vuln.fbBonus,null,vuln.floodCap);
    return {ead:eadUsd,eadPct:eadFrac*100,band:bandOf(eadFrac*100),curve,vec:dvec};
  }
  const vec=hzVector(hz,la,lo,sc);
  const {eadUsd,eadFrac,curve}=floodEad(vec,val,(hz==="cflood"?FB_COAST:fbRiver())+vuln.fbBonus,null,vuln.floodCap);
  return {ead:eadUsd,eadPct:eadFrac*100,band:bandOf(eadFrac*100),curve,vec};
}
function scoreHazard(sites,hz,sc){
  const rows=sites.map(s=>Object.assign({},s,hzSite(s,hz,sc)));
  const tiv=rows.reduce((a,r)=>a+r.asset_value_usd,0);
  const ead=rows.reduce((a,r)=>a+(r.ead||0),0);
  const rpLoss={};for(const rp of RPS)rpLoss[rp]=rows.reduce((a,r)=>{const c=(r.curve||[]).find(x=>x.rp===rp);return a+(c?c.loss:0);},0);
  return {rows,tiv,ead,eadPct:tiv?ead/tiv*100:0,rpLoss,hazardKey:hz};
}
// combined physical risk across all damage perils (wind + both floods)
function scorePhysTotal(sites,sc){
  const rows=sites.map(s=>{
    /* registry-driven (Phase C): every acute peril, exactly once */
    const parts={};let ead=0;
    for(const hz of ACUTE){const r=hzSite(s,hz,sc);parts[hz]=r.ead;ead+=r.ead;}
    const pct=s.asset_value_usd?ead/s.asset_value_usd*100:0;
    return Object.assign({},s,{ead,eadPct:pct,band:bandOf(pct),parts});
  });
  const tiv=rows.reduce((a,r)=>a+r.asset_value_usd,0);
  const ead=rows.reduce((a,r)=>a+r.ead,0);
  return {rows,tiv,ead,eadPct:tiv?ead/tiv*100:0};
}
// portfolio EAD split by peril, for the risk-driver panel
function riskDrivers(sites,sc){
  const t={tc:0,cflood:0,rflood:0,prain:0,wfire:0};
  for(const s of sites)for(const hz of ACUTE)t[hz]+=hzSite(s,hz,sc).ead;
  const total=ACUTE.reduce((a,hz)=>a+t[hz],0),sum=total||1;
  const share={};ACUTE.forEach(hz=>share[hz]=t[hz]/sum);
  return {byHazard:t,total,share};
}
// all four hazard ratings for a site (for the Sites ratings column)
function siteRatings(site,sc){
  const o={};for(const h of HAZARDS)o[h.key]=hzSite(site,h.key,sc).band;return o;}

/* ============================================================
   Score tracing (Phase C2)
   explainPeril answers "why is this number what it is": which dataset
   produced the intensity (grid cell and distance, a named interim model,
   or an honest zero), which named factors transformed it, and what came
   out. Introspection only: every output figure is hzSite's own, every
   factor mirrors vulnOf and the peril dispatch, and a test pins the wind
   factor product to vulnOf so the trace can never drift from the math.
   ============================================================ */
function windFactorTrail(site){
  const t=[];
  const c=String(site.construction||"").toLowerCase();
  if(CONSTR_FACTOR[c]!=null)t.push({name:c+" construction",mult:CONSTR_FACTOR[c]});
  const rt=String(site.roof_type||"").toLowerCase();
  const op=String(site.opening_protection||"").toLowerCase();
  const ry=+site.roof_year;
  const roofish=ROOF_TYPE_FACTOR[rt]!=null||OPENING_FACTOR[op]!=null||(isFinite(ry)&&ry>1800);
  if(roofish){
    if(ROOF_TYPE_FACTOR[rt]!=null)t.push({name:rt+" roof",mult:ROOF_TYPE_FACTOR[rt]});
    if(isFinite(ry)&&ry>1800){const age=Math.max(ROOF_AGE_REF_YEAR-ry,0);
      t.push({name:"roof age "+age+" years",mult:age<=10?0.9:(age<=20?1.0:1.2)});}
    if(OPENING_FACTOR[op]!=null)t.push({name:"opening protection: "+op,mult:OPENING_FACTOR[op]});
  }else{
    const y=+site.year_built;
    if(isFinite(y)&&y>1800){
      if(y<1995)t.push({name:"built "+y+" (pre-1995 code era)",mult:1.15});
      else if(y>=2010)t.push({name:"built "+y+" (modern code era)",mult:0.9});
    }
  }
  const raw=t.reduce((a,f)=>a*f.mult,1);
  const clipped=Math.min(Math.max(raw,0.5),1.6);
  if(Math.abs(clipped-raw)>1e-12)t.push({name:"clipped to the 0.5..1.6 range",mult:clipped/raw});
  return t;
}
function fbBonusTrail(site,vuln){
  if(!(vuln.fbBonus>0))return [];
  const ffe=+site.first_floor_elev_m;
  const fromFfe=isFinite(ffe)&&ffe>=0;
  return [{name:fromFfe?("first-floor elevation "+Math.min(ffe,FIRST_FLOOR_MAX_M).toFixed(1)+" m"):"defended site",add:vuln.fbBonus}];
}
function explainPeril(site,hz,sc){
  const la=site.latitude,lo=site.longitude;
  const r=hzSite(site,hz,sc);
  const H=HAZARD_BY[hz]||{label:hz,unit:""};
  const vuln=vulnOf(site);
  const ds=(hazardGrid&&hazardGrid.meta)?hazardGrid.meta.name:null;
  const gmeta=(()=>{const g=gridByHazard[hz];if(!g)return null;const q=g(la,lo,sc);return (q&&q.meta)||null;})();
  const out={hz,label:H.label,unit:H.unit,ead:r.ead||0,eadPct:r.eadPct||0,band:r.band,
             inputs:null,factors:[],notes:[],source:null};
  const gridSrc=()=>({kind:"grid",dataset:ds,distKm:gmeta?gmeta.dist:null});
  if(hz==="heat"){
    out.source=(r.indicators&&r.indicators.source==="grid")?gridSrc()
      :{kind:"interim",detail:"latitude and coast-distance climatology, shifted by scenario warming"};
    out.inputs={kind:"indicators",indicators:r.indicators};
    out.notes.push("chronic peril: banded by days over 32C, costed on the Financial impact tab");
    return out;
  }
  if(hz==="tc"){
    const meta=provider()(la,lo,sc).meta||{};
    out.source=meta.source==="grid"?{kind:"grid",dataset:ds,distKm:meta.dist}
      :{kind:"interim",detail:"regional wind anchors, inverse-distance weighted"};
    out.inputs={kind:"vec",vec:r.vec};
    out.factors=windFactorTrail(site);
    out.windMult=vuln.windMult;
    out.notes.push("Emanuel (2011) cubic damage: threshold "+V_THRESH+" m/s, half damage at "+V_HALF+" m/s");
    return out;
  }
  if(hz==="wfire"){
    const b=fireBurnPct(site,sc);
    if(b.source==="grid")out.source=gridSrc();
    else if(b.source==="interim")out.source={kind:"interim",
      detail:String(site.wui_class||"").toLowerCase()+" WUI class: "+
        (FIRE_WUI_PBURN[String(site.wui_class||"").toLowerCase()]||0)+"%/yr base burn, +"+
        Math.round(FIRE_WARMING_UPLIFT*100)+"% per degree of warming"};
    else out.source={kind:"none",detail:"no wildfire grid loaded and no wui_class on the site profile, so wildfire scores zero"};
    out.inputs={kind:"burn",burnPct:r.burnPct||0};
    out.factors=[{name:"conditional damage when a site burns",mult:FIRE_MDD}];
    if(site.roof_class_a)out.factors.push({name:"Class A fire-rated roof",mult:0.6});
    const dsm=+site.defensible_space_m;
    if(isFinite(dsm)&&dsm>=30)out.factors.push({name:"defensible space "+dsm+" m",mult:0.7});
    return out;
  }
  if(hz==="prain"){
    if(gmeta&&!gmeta.outside)out.source=gridSrc();
    else if(gmeta&&gmeta.outside)out.source={kind:"none",
      detail:"site is "+Math.round(gmeta.dist)+" km from the nearest rainfall cell (beyond 200 km), so rainfall scores zero"};
    else out.source={kind:"none",detail:"TC rainfall has no interim model; it stays zero until a rainfall grid is loaded"};
    out.inputs={kind:"vec",vec:r.vec};
    out.factors=[{name:"drainage transform: first "+PRAIN_DRAIN_MM+" mm absorbed, ponding coefficient "+PRAIN_POND_COEFF}]
      .concat([{name:"site drainage freeboard",add:PRAIN_FB}],fbBonusTrail(site,vuln));
    if(site.equipment_elevated)out.factors.push({name:"equipment elevated",cap:EQUIP_ELEV_FLOOD_CAP});
    out.notes.push("concave stage-damage on ponding depth, capped at "+Math.round((site.equipment_elevated?EQUIP_ELEV_FLOOD_CAP:FLOOD_CAP_DEFAULT)*100)+"% of value");
    return out;
  }
  /* cflood / rflood */
  if(gmeta&&!gmeta.outside)out.source=gridSrc();
  else if(gmeta&&gmeta.outside)out.source={kind:"interim",
    detail:"site is "+Math.round(gmeta.dist)+" km from the nearest grid cell (beyond 200 km); the interim model fills in"};
  else out.source={kind:"interim",detail:hz==="cflood"?"coast-proximity surge screening":"terrain and coast-distance screening"};
  out.inputs={kind:"vec",vec:r.vec};
  out.factors=[{name:hz==="cflood"?"coastal freeboard baseline":"riverine freeboard baseline",add:hz==="cflood"?FB_COAST:fbRiver()}]
    .concat(fbBonusTrail(site,vuln));
  if(site.equipment_elevated)out.factors.push({name:"equipment elevated",cap:EQUIP_ELEV_FLOOD_CAP});
  out.notes.push("concave stage-damage above freeboard, capped at "+Math.round((site.equipment_elevated?EQUIP_ELEV_FLOOD_CAP:FLOOD_CAP_DEFAULT)*100)+"% of value");
  return out;
}

/* ============================================================
   Financial impact layer (Phase 2)
   Turns hazard into money a CFO can read: direct asset damage, business
   interruption, and heat-driven revenue at risk, summed into an expected
   annual cost (AAL) and a tail Value at Risk. Acute perils (wind, coastal
   flood, riverine flood) are event-driven; heat is the chronic peril.
   Every figure is driven by three transparent, adjustable assumptions.
   ============================================================ */
