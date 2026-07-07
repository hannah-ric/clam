
/* ============================================================
   RtV risk engine (validated; mirrors CLIMADA emanuel_usa)
   ============================================================ */
const V_THRESH=25.7, V_HALF=74.7;
const RPS=[10,25,50,100,250,500];
// Scenario keys are "present" or "<pathway>_<horizon>" on the CMIP6 SSP-RCP
// framework. The WARMING and SLR_REGIONS tables are GENERATED into
// 05_assumptions.js from pipeline/assumptions.py (the single sourced
// registry: AR6 central + explicit conservative delta, with units, baseline
// period, and citation per entry), so app and pipeline can never disagree.
const PATHWAYS=["ssp126","ssp245","ssp585"];
const HORIZONS=[2030,2050,2080];
const PATHWAY_LABEL={present:"Present day",ssp126:"SSP1-2.6",ssp245:"SSP2-4.5",ssp585:"SSP5-8.5"};
function warming(sc){return WARMING[sc]||0;}
/* sea-level rise is REGIONAL (Gulf subsidence most of all): with a location,
   the first matching region box's table applies; without one, or outside
   every box, the global-mean table (the legacy single table) applies. */
function slrRegionOf(la,lo){
  for(const [name,la0,la1,lo0,lo1] of SLR_REGION_BOXES)
    if(la>=la0&&la<=la1&&lo>=lo0&&lo<=lo1)return name;
  return "global_mean";
}
function slrOf(sc,la,lo){
  const t=(la!=null&&lo!=null&&SLR_REGIONS[slrRegionOf(la,lo)])||SLR;
  return t[sc]||0;
}
const SCEN_KEYS=["present"].concat([].concat(...HORIZONS.map(h=>PATHWAYS.map(p=>p+"_"+h))));
const SCEN_LABEL=(()=>{const o={present:"Present day"};
  for(const p of PATHWAYS)for(const h of HORIZONS)o[p+"_"+h]=PATHWAY_LABEL[p]+" \u00b7 "+h;return o;})();
// Wind intensity uplift for the interim TC field, per deg C of warming.
const SCEN_UPLIFT=(()=>{const o={};for(const k of SCEN_KEYS)o[k]=1+TC_UPLIFT_PER_C*warming(k);return o;})();

function emanuelMdd(v,vHalf){vHalf=vHalf||V_HALF;const vt=Math.max((v-V_THRESH)/(vHalf-V_THRESH),0);const c=vt*vt*vt;return c/(1+c);}
/* Task 5: the EAD integral used to START at 1-in-10, silently assuming zero
   loss from anything more frequent. subTenPts extends the curve to 1-in-5
   and 1-in-2 by log-linear extrapolation of the intensity/depth vector
   below its most frequent point (slope floored at 0 so the extension can
   never EXCEED the 1-in-10 value, clamped at 0 below). Frequent events then
   enter the integral through the same damage curve, which zeroes them
   naturally below the damage threshold or freeboard: calm sites are
   unchanged, chronically-wet ones stop hiding their frequent losses. */
const SUB10_RPS=[5,2];
function subTenPts(vec){
  const v10=Math.max(vec[10]||0,0), v25=Math.max(vec[25]||0,0);
  const b=Math.max((v25-v10)/(Math.log(25)-Math.log(10)),0);
  return SUB10_RPS.map(rp=>({rp,v:Math.max(v10-b*(Math.log(10)-Math.log(rp)),0)}));
}
/* Task 4: flood/surge depth read AT THE STRUCTURE. Relief = site ground
   minus the hazard cell's mean land ground (both from survey or
   enrich_sites.py). Wet cells shift by the relief; DRY CELLS STAY DRY (a
   low-spot site cannot conjure water the model did not put in the cell).
   Without both fields the cell value stands and the site reads
   MODELED-COARSE on the trust surface. */
const RELIEF_CLAMP_M=10;
function siteRelief(site){
  const g=+site.ground_elev_m, c=+site.cell_ground_elev_m;
  if(!isFinite(g)||!isFinite(c))return null;
  return Math.max(-RELIEF_CLAMP_M,Math.min(g-c,RELIEF_CLAMP_M));
}
function reliefVec(vec,relief){
  if(relief==null)return vec;
  const o={};RPS.forEach(rp=>{const v=vec[rp]||0;o[rp]=v>0?Math.max(v-relief,0):0;});
  return o;
}
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
  /* Nearest-cell lookup is a linear scan, and one render scores every site
     against every peril and scenario many times over, so a realistic grid
     (tens of thousands of cells) turns each render into millions of haversine
     calls and the app appears to freeze. Sites are fixed points, so the set of
     distinct (lat, lon, scenario) queries is tiny: memoise per grid, exactly as
     the tc base provider is cached in provider(). The cache lives on this
     closure, so a new grid (buildGridsFromRows) starts fresh automatically. */
  const _cache=new Map();
  return function(lat,lon,scenario,maxKm){maxKm=maxKm||200;
    const ck=lat.toFixed(5)+","+lon.toFixed(5)+","+scenario+","+maxKm;
    const cached=_cache.get(ck);if(cached!==undefined)return cached;
    const list=byScen[scenario]||byScen.present||[];let best=null,bestD=Infinity;
    for(const row of list){const d=haversine(lat,lon,row.lat,row.lon);if(d<bestD){bestD=d;best=row;}}
    let res;
    if(!best||bestD>maxKm){const z={};for(const rp of RPS)z[rp]=0;res={vec:z,meta:{source:"grid",outside:true,dist:bestD}};}
    else{const vec={};for(const rp of RPS)vec[rp]=Math.max(+best["v"+rp]||0,0);res={vec,meta:{source:"grid",dist:bestD}};}
    _cache.set(ck,res);return res;
  };
}
function siteEad(vec,value,opts){
  opts=opts||{};const windRed=opts.windRed||0;const dmgMult=opts.dmgMult==null?1:opts.dmgMult;
  const pts=subTenPts(vec).concat(RPS.map(rp=>({rp,v:vec[rp]||0})))
    .map(p=>{const v=Math.max(p.v-windRed,0);return {rp:p.rp,v,f:1/p.rp,frac:Math.min(emanuelMdd(v,opts.vHalf)*dmgMult,1)};});
  if(opts.transfer){for(const p of pts){if(p.rp>=opts.transfer.attachRp&&p.rp<=opts.transfer.exhaustRp)p.frac=0;}}
  const s=pts.slice().sort((x,y)=>y.f-x.f);let eadFrac=0;
  for(let i=0;i<s.length-1;i++)eadFrac+=0.5*(s[i].frac+s[i+1].frac)*(s[i].f-s[i+1].f);
  eadFrac+=s[s.length-1].frac*s[s.length-1].f;
  const curve=pts.filter(p=>RPS.indexOf(p.rp)>=0).map(p=>({rp:p.rp,v:p.v,loss:p.frac*value}));
  return {eadUsd:eadFrac*value,eadFrac,curve};
}
function bandOf(pct){if(pct>=1.5)return"Severe";if(pct>=0.75)return"High";if(pct>=0.25)return"Moderate";if(pct>0.001)return"Low";return"Minimal";}
function brandRollup(rows){
  const m={};for(const r of rows){const k=r.brand||"Unbranded";(m[k]||(m[k]={brand:k,tiv:0,ead:0,n:0}));m[k].tiv+=r.asset_value_usd;m[k].ead+=r.eadUsd;m[k].n++;}
  return Object.values(m).map(x=>Object.assign({},x,{eadPct:x.tiv?x.ead/x.tiv*100:0})).sort((a,b)=>b.ead-a.ead);
}

/* ============================================================
   Named-insured aggregation
   A physical site can host several named-insured groups (e.g. an HOA and the
   operating company). Each record is one such group's exposure at a location;
   records sharing a site_id (or, absent that, exact coordinates) are ONE site
   on the map, with a breakout of who is impacted and to what degree. Pure over
   hzSite / bandOf, so it moves no computed per-record figure: every group
   figure is the sum of its members'. A portfolio with no named_insured / site_id
   yields one group per record (today's behaviour, one marker each).
   ============================================================ */
function insuredOf(s){ const v=String(s&&s.named_insured!=null?s.named_insured:"").trim(); return v||"Unspecified"; }
function siteGroupKey(s){
  const sid=String(s&&s.site_id!=null?s.site_id:"").trim();
  if(sid)return "id:"+sid.toLowerCase();
  const la=+s.latitude, lo=+s.longitude;
  return "geo:"+(isFinite(la)?la.toFixed(5):"?")+","+(isFinite(lo)?lo.toFixed(5):"?");
}
/* most common non-empty value of a field across members; ties break by first
   appearance, so the display name and brand of a mixed group are deterministic */
function commonField(members,key){
  const counts=new Map();let best=null,bestN=0;
  members.forEach(s=>{const v=String(s[key]==null?"":s[key]).trim();if(!v)return;
    const n=(counts.get(v)||0)+1;counts.set(v,n);if(n>bestN){bestN=n;best=v;}});
  return best;
}
function siteGroups(rows){
  const m=new Map();
  rows.forEach(s=>{const k=siteGroupKey(s);let g=m.get(k);
    if(!g){g={key:k,members:[]};m.set(k,g);}g.members.push(s);});
  return [...m.values()].map(g=>({
    key:g.key,members:g.members,
    latitude:+g.members[0].latitude,longitude:+g.members[0].longitude,
    name:commonField(g.members,"site_name")||commonField(g.members,"name")||g.members[0].name||"Site",
    brand:commonField(g.members,"brand")||"",
    multi:g.members.length>1}));
}
/* one site group's scored rollup at a scenario: per-peril and combined EAD, the
   combined band, and the named-insured breakout. Members share a location, so
   the hazard is identical; value adds, damage adds, and the band is taken on the
   summed loss ratio (so differing member vulnerabilities are handled correctly). */
function scoreGroup(g,sc){
  const perHaz={};ACUTE.forEach(hz=>perHaz[hz]=0);
  let value=0,ead=0,days=0;
  const ins=new Map();
  g.members.forEach(s=>{
    value+=s.asset_value_usd;
    let sead=0;const sp={};
    ACUTE.forEach(hz=>{const e=hzSite(s,hz,sc).ead;perHaz[hz]+=e;sp[hz]=e;sead+=e;});
    ead+=sead;
    const d=heatIndicators(s.latitude,s.longitude,sc).daysOver32;if(d>days)days=d;
    const key=insuredOf(s);let r=ins.get(key);
    if(!r){r={insured:key,value:0,ead:0,n:0,perHaz:{}};ACUTE.forEach(hz=>r.perHaz[hz]=0);ins.set(key,r);}
    r.value+=s.asset_value_usd;r.ead+=sead;r.n++;ACUTE.forEach(hz=>r.perHaz[hz]+=sp[hz]);
  });
  const pct=value?ead/value*100:0;
  const byInsured=[...ins.values()].map(r=>{const p=r.value?r.ead/r.value*100:0;
    return Object.assign(r,{eadPct:p,band:bandOf(p),share:ead?r.ead/ead*100:0});})
    .sort((a,b)=>b.ead-a.ead);
  return {key:g.key,name:g.name,brand:g.brand,latitude:g.latitude,longitude:g.longitude,
    members:g.members,value,perHaz,ead,eadPct:pct,band:bandOf(pct),heatDays:days,
    byInsured,multi:byInsured.length>1};
}
/* the group analogue of markerFill: combined -> combined band; dominant ->
   leading peril's own colour; peril -> the active peril's band on the group's
   summed loss ratio (heat by hot-days band). */
function groupMarkerFill(gr,mode,activeHz){
  if(mode==="combined")return BAND_COLOR[gr.band];
  if(mode==="dominant"){let best=null,bv=-1;ACUTE.forEach(hz=>{if(gr.perHaz[hz]>bv){bv=gr.perHaz[hz];best=hz;}});return (bv>0&&best)?HAZARD_BY[best].color:BAND_COLOR.Minimal;}
  if(activeHz==="heat")return BAND_COLOR[heatBand(gr.heatDays)];
  const p=gr.value?(gr.perHaz[activeHz]||0)/gr.value*100:0;
  return BAND_COLOR[bandOf(p)];
}
/* portfolio-level acute EAD by named insured (across every site), for the
   summary breakout: who carries the exposure, and to what degree. */
function insuredRollup(rows,sc){
  const m={};
  rows.forEach(s=>{const k=insuredOf(s);const r=m[k]||(m[k]={insured:k,value:0,ead:0,n:0});
    r.value+=s.asset_value_usd;r.n++;for(const hz of ACUTE)r.ead+=hzSite(s,hz,sc).ead;});
  return Object.values(m).map(r=>Object.assign(r,{eadPct:r.value?r.ead/r.value*100:0,
    band:bandOf(r.value?r.ead/r.value*100:0)})).sort((a,b)=>b.ead-a.ead);
}
function hasNamedInsured(rows){ return rows.some(s=>insuredOf(s)!=="Unspecified"); }

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
  const rise=slrOf(sc,la,lo)*near;                     // regional SLR lifts the curve
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
/* Parallel swap: HUMID heat (feels-like) beside dry-bulb. Dry-bulb stays the
   structural and financial view (nothing downstream of daysOver35 moves);
   the heat index is the guest-comfort, cooling-load, and outdoor-labor lens,
   because 33C at 75% coastal humidity is dangerous where 33C dry desert air
   is not. Humidity is a documented SCREENING proxy: warm-season RH decays
   from a coastal 80% toward a 45% interior floor with distance from the
   coast (this portfolio is beach-heavy, so coastal reads humid, Palm
   Springs/San Antonio read dry). The feels-like temperature is the NOAA
   Rothfusz heat-index regression on that RH. */
const HEAT_RH_BASE=0.45, HEAT_RH_COAST=0.35, HEAT_RH_KM=60;
function warmSeasonRh(la,lo){ return Math.min(0.80,HEAT_RH_BASE+HEAT_RH_COAST*Math.exp(-coastKm(la,lo)/HEAT_RH_KM)); }
function heatIndexC(tC,rh){
  const T=tC*9/5+32, R=rh*100;
  let hi=0.5*(T+61+(T-68)*1.2+R*0.094);          // NWS simple form (already T-averaged)
  if(hi>=80)
    hi=-42.379+2.04901523*T+10.14333127*R-0.22475541*T*R-6.83783e-3*T*T
       -5.481717e-2*R*R+1.22874e-3*T*T*R+8.5282e-4*T*R*R-1.99e-6*T*T*R*R;
  return (hi-32)*5/9;
}
/* the dry-bulb temperature at which the heat index crosses `target` at this
   RH: bisection is fine, heatIndexC is monotone in T */
function hiDryBulbFor(target,rh){
  let lo=15,hi=50;
  for(let i=0;i<40;i++){const m=(lo+hi)/2;if(heatIndexC(m,rh)<target)lo=m;else hi=m;}
  return (lo+hi)/2;
}
function heatIndicators(la,lo,sc){
  /* Phase 3: prefer the data-driven heat grid (observed daily climatology
     shifted by AR6-consistent warming; see refresh_heat.py), encoded as
     v10=days over 32C, v25=days over 35C, v50=cooling degree days. The
     latitude formula remains the fallback when no heat rows are loaded or
     a site sits outside grid coverage, so behaviour never degrades to zero. */
  const rh=warmSeasonRh(la,lo);
  /* humid-heat day count: days the FEELS-LIKE temperature exceeds 35C, i.e.
     days dry-bulb exceeds the (lower, humidity-dependent) threshold t* where
     the heat index crosses 35C. Never fewer than the dry-bulb count. */
  const tStar=hiDryBulbFor(35,rh);
  const g=gridByHazard.heat;
  if(g){const r=g(la,lo,sc);
    if(!(r.meta&&r.meta.outside)){
      const d32=Math.round(r.vec[10]||0),d35=Math.round(r.vec[25]||0),cdd=Math.round(r.vec[50]||0);
      const p=Math.min(Math.max(d35,0.5),199.5)/200;
      const effT=+(35+1.6*Math.log(p/(1-p))).toFixed(1);
      /* the grid gives two points of the day-count curve (32C and 35C);
         interpolate t* between them, clamped to what the data can support */
      const dHi=tStar>=35?d35:(tStar<=32?d32:Math.round(d35+(d32-d35)*(35-tStar)/3));
      return {effT,daysOver32:d32,daysOver35:d35,cdd,source:"grid",
              rhWarm:rh,hiT:+heatIndexC(effT,rh).toFixed(1),daysHi35:Math.max(dHi,d35)};
    }}
  const baseT=34-0.35*(Math.abs(la)-18)+6*continentality(la,lo);
  const T=baseT+warming(sc);
  const daysOver=thr=>Math.round(200/(1+Math.exp(-(T-thr)/1.6)));
  return {effT:+T.toFixed(1),daysOver32:daysOver(32),daysOver35:daysOver(35),cdd:Math.round(Math.max(0,T-18)*210),
          rhWarm:rh,hiT:+heatIndexC(T,rh).toFixed(1),daysHi35:Math.max(daysOver(tStar),daysOver(35))};
}
// flood EAD, same frequency integration as siteEad (f descending, tail
// closed, and Task 5's sub-1-in-10 extension included)
function floodEad(vec,value,fb,dmgScale,cap){
  const k=dmgScale==null?1:dmgScale;
  const pts=subTenPts(vec).concat(RPS.map(rp=>({rp,v:vec[rp]||0})))
    .map(p=>{const d=Math.max(p.v,0);return {rp:p.rp,v:d,f:1/p.rp,frac:Math.min(floodMdd(d,fb,cap)*k,1)};});
  const s=pts.slice().sort((x,y)=>y.f-x.f);let ef=0;
  for(let i=0;i<s.length-1;i++)ef+=0.5*(s[i].frac+s[i+1].frac)*(s[i].f-s[i+1].f);
  ef+=s[s.length-1].frac*s[s.length-1].f;
  return {eadUsd:ef*value,eadFrac:ef,
    curve:pts.filter(p=>RPS.indexOf(p.rp)>=0).map(p=>({rp:p.rp,v:p.v,loss:p.frac*value}))};
}
function heatBand(days32){const t=[10,45,100,160],n=["Minimal","Low","Moderate","High","Severe"];let i=0;while(i<t.length&&days32>t[i])i++;return n[i];}

/* Increment 3 / Task 3.5: wildfire and TC-rainfall perils. MIRRORS the
   pipeline's constants; change both sides. Migration safety: with no wfire
   grid and no wui_class, burn probability is ZERO; rainfall has NO interim
   model at all (a grid is required).
   Wildfire semantics after the structural fix: v10 is the annual
   probability fire REACHES THE SITE POINT (USFS WRC burn probability,
   point-sampled by the pipeline - never cell occupancy, never buffered),
   and v25 is the conditional damage ratio given fire at the modeled flame
   length. The retired flat FIRE_MDD=0.6 is replaced: where v25 is absent
   (an older grid, or no CFL raster supplied) the capped INTERIM ratio
   FIRE_COND_INTERIM applies and is LABELED interim on the trust surface. */
const FIRE_WUI_PBURN={interface:0.3,intermix:0.6};  // interim annual point-burn %, by WUI class
/* FIRE_WARMING_UPLIFT and FIRE_COND_INTERIM live in 05_assumptions.js */
const PRAIN_DRAIN_MM=150, PRAIN_POND_COEFF=0.4, PRAIN_FB=0.3;  // site drainage screening constants
function fireBurnPct(site,sc){
  const g=gridByHazard.wfire;
  if(g){const r=g(site.latitude,site.longitude,sc);
    if(!(r.meta&&r.meta.outside)){
      const v25=+r.vec[25]||0;
      return {pct:Math.min(Math.max(+r.vec[10]||0,0),100),
              cond:v25>0?Math.min(v25/100,1):FIRE_COND_INTERIM,
              source:"grid",condSource:v25>0?"grid":"interim"};}}
  const wui=String(site.wui_class||"").toLowerCase();
  const base=FIRE_WUI_PBURN[wui]||0;
  return {pct:base*(1+FIRE_WARMING_UPLIFT*warming(sc)),cond:FIRE_COND_INTERIM,
          source:base?"interim":"none",condSource:"interim"};
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
function archOf(site){
  const key=String((site&&site.archetype)||"").toLowerCase();
  return ARCHETYPES[key]||ARCHETYPES[DEFAULT_ARCHETYPE];
}
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
  let fbBonus=(isFinite(ffe)&&ffe>=0)?Math.min(ffe,FIRST_FLOOR_MAX_M):(site.defended?0.5:0);
  /* archetype layer (schema v2): the archetype moves the CURVES (wind
     half-damage speed, flood freeboard, flood cap); the factor table above
     stays the mapping layer for envelope condition on top. The default
     archetype is neutral, so profiles without one reproduce today's numbers
     exactly. Site-measured equipment_elevated still caps DOWNWARD. */
  const a=archOf(site);
  fbBonus+=a.fb_add_m;
  const capP=site.equipment_elevated?EQUIP_ELEV_FLOOD_CAP:FLOOD_CAP_DEFAULT;
  const cap=a.flood_cap==null?capP:(site.equipment_elevated?Math.min(a.flood_cap,capP):a.flood_cap);
  return {windMult:Math.min(Math.max(w,0.5),1.6), fbBonus,
          floodCap:cap, vHalf:V_HALF*a.v_half_mult};
}

/* ============================================================
   Per-site-per-peril trust
   The trust question used to be answered once per peril ("is a grid
   loaded?"), which let a site display green on a peril whose grid never
   reached it (a Hawaii site on a CONUS-only rainfall grid, say). It is now
   answered per site per peril: "modeled" ONLY when the loaded grid served
   THIS site a value within the 200 km snap and inside coverage; everything
   else is "degraded" (a documented interim model fills in, or the peril
   honestly scores zero for lack of data). No surface may show green for a
   site-peril pair unless siteTrust says modeled.
   ============================================================ */
function trustFallback(site,hz){
  if(hz==="tc")return {basis:"interim",detail:"interim wind anchors fill in"};
  if(hz==="cflood")return {basis:"interim",detail:"coast-proximity screening fills in"};
  if(hz==="rflood")return {basis:"interim",detail:"terrain screening fills in"};
  if(hz==="heat")return {basis:"interim",detail:"latitude climatology fills in"};
  if(hz==="wfire"){
    const wui=FIRE_WUI_PBURN[String(site.wui_class||"").toLowerCase()]!=null;
    return wui?{basis:"interim",detail:"wui_class screening fills in"}
             :{basis:"none",detail:"no data: wildfire scores zero"};
  }
  return {basis:"none",detail:"no interim model: rainfall scores zero"};
}
function siteTrust(site,hz,sc){
  sc=sc||(typeof scenario!=="undefined"?scenario:"present");
  const g=gridByHazard[hz];
  if(g){
    const r=g(site.latitude,site.longitude,sc);
    if(!(r.meta&&r.meta.outside)){
      const t={state:"modeled",basis:"grid",distKm:r.meta&&r.meta.dist};
      /* the wildfire conditional-damage side stays LABELED interim until a
         flame-length (CFL) value reaches this site (v25>0) */
      if(hz==="wfire"&&!(+r.vec[25]>0))
        t.note="conditional damage interim (flat "+FIRE_COND_INTERIM+", capped) until a flame-length layer is supplied";
      /* Task 4: flood/surge depth basis - at the structure when the site
         carries both elevation fields, else MODELED-COARSE (cell average) */
      if(hz==="cflood"||hz==="rflood"){
        const rel=siteRelief(site);
        t.coarse=rel==null;
        t.note=rel==null
          ?"modeled-coarse: cell-average depth; add ground_elev_m + cell_ground_elev_m (survey or enrich_sites.py) to read depth at the structure"
          :"depth at the structure (site sits "+(rel>=0?rel.toFixed(1)+" m above":Math.abs(rel).toFixed(1)+" m below")+" the cell's land ground)";
      }
      return t;
    }
    const fb=trustFallback(site,hz);
    return {state:"degraded",basis:fb.basis,distKm:r.meta.dist,
      detail:"outside grid coverage ("+Math.round(r.meta.dist)+" km to the nearest cell); "+fb.detail};
  }
  const fb=trustFallback(site,hz);
  return {state:"degraded",basis:fb.basis,detail:"no grid loaded; "+fb.detail};
}
function siteTrustSummary(site,sc){
  const byHz={};let modeled=0;
  HAZARDS.forEach(h=>{const t=siteTrust(site,h.key,sc);byHz[h.key]=t;if(t.state==="modeled")modeled++;});
  return {modeled,total:HAZARDS.length,byHz};
}
/* Parallel swap: perils this tool does NOT model, stated on the trust
   surface instead of left implicit. Hail, non-TC pluvial flooding, and
   drought all cost hospitality portfolios real money; a reader must see
   "not modeled" in gray, never infer it from absence. These carry no math:
   they exist only so the trust surface tells the whole truth. */
const NOT_MODELED=[
  {key:"hail",   label:"Hail",             short:"Ha",
   detail:"no hail or convective-storm model in this tool; carry that exposure via loss history and insurance, not this screen"},
  {key:"pluvial",label:"Pluvial (non-TC)", short:"Pv",
   detail:"only tropical-cyclone rainfall is modeled; ordinary cloudburst and drainage flooding is not"},
  {key:"drought",label:"Drought",          short:"Dr",
   detail:"no drought model; water-supply, landscaping, and amenity stress are outside this tool"},
];
function notModeledChips(dark){
  return NOT_MODELED.map(h=>'<span class="pill mini" data-trust="notmodeled" '+
    'style="background:#fff;border:1px dashed #98A6B0;color:#5B6770'+(dark?';background:transparent;color:#C6CFD6;border-color:#7A8893':'')+'" '+
    'title="'+esc(h.label+": NOT MODELED. "+h.detail)+'">'+h.short+'</span>').join("");
}
/* Task 6: the map's per-site confidence. A group's members share one
   location, so grid reach is identical across them; trust is read on the
   largest-value member (the same record the marker's scorecard opens). */
function groupTrust(g,sc){
  const target=g.members.slice().sort((a,b)=>b.asset_value_usd-a.asset_value_usd)[0];
  const t=siteTrustSummary(target,sc);
  const degraded=HAZARDS.filter(h=>t.byHz[h.key].state!=="modeled").map(h=>h.label.toLowerCase());
  return {target,modeled:t.modeled,total:t.total,degraded};
}
/* compact per-site source string for the CSV exports: states, per peril,
   whether this site's figure is grid-fed or degraded. Pipe-separated so it
   stays a single unquoted CSV cell. */
function hazardSourceOf(site,sc){
  const t=siteTrustSummary(site,sc);
  const by={grid:[],interim:[],none:[]};
  HAZARDS.forEach(h=>{const x=t.byHz[h.key];
    by[x.state==="modeled"?"grid":(x.basis==="none"?"none":"interim")].push(h.key);});
  return ["grid:"+(by.grid.join("+")||"-"),
          "interim:"+(by.interim.join("+")||"-"),
          "none:"+(by.none.join("+")||"-")].join("|");
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
    const {eadUsd,eadFrac,curve}=siteEad(vec,val,{dmgMult:vuln.windMult,vHalf:vuln.vHalf});
    return {ead:eadUsd,eadPct:eadFrac*100,band:bandOf(eadFrac*100),curve,vec,hazardMeta:meta};
  }
  if(hz==="wfire"){
    const b=fireBurnPct(site,sc), fv=fireVulnMult(site);
    const frac=(b.pct/100)*b.cond*fv;
    const curve=RPS.map(rp=>({rp,v:b.pct,loss:(b.pct>=100/rp)?val*b.cond*fv:0}));
    return {ead:frac*val,eadPct:frac*100,band:bandOf(frac*100),curve,vec:null,
            burnPct:b.pct,fireCond:b.cond,fireSource:b.source,fireCondSource:b.condSource};
  }
  if(hz==="prain"){
    const dvec=prainToDepth(hzVector("prain",la,lo,sc));
    const {eadUsd,eadFrac,curve}=floodEad(dvec,val,Math.max(PRAIN_FB+vuln.fbBonus,0),null,vuln.floodCap);
    return {ead:eadUsd,eadPct:eadFrac*100,band:bandOf(eadFrac*100),curve,vec:dvec};
  }
  const vec=reliefVec(hzVector(hz,la,lo,sc),siteRelief(site));
  const {eadUsd,eadFrac,curve}=floodEad(vec,val,Math.max((hz==="cflood"?FB_COAST:fbRiver())+vuln.fbBonus,0),null,vuln.floodCap);
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
  const t=[];
  const a=archOf(site);
  const base=vuln.fbBonus-a.fb_add_m;      // the profile share (ffe/defended)
  if(base>0){
    const ffe=+site.first_floor_elev_m;
    const fromFfe=isFinite(ffe)&&ffe>=0;
    t.push({name:fromFfe?("first-floor elevation "+Math.min(ffe,FIRST_FLOOR_MAX_M).toFixed(1)+" m"):"defended site",add:base});
  }
  if(a.fb_add_m)t.push({name:"archetype: "+a.label,add:a.fb_add_m});
  return t;
}
/* wind-side archetype entry for the trace: the archetype moves the CURVE
   (half-damage speed), not the multiplier, so it gets its own line. */
function archWindTrail(site){
  const a=archOf(site);
  return a.v_half_mult===1?[]:[{name:"archetype: "+a.label+" (half-damage speed x"+a.v_half_mult.toFixed(2)+")",mult:1}];
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
    out.factors=windFactorTrail(site).concat(archWindTrail(site));
    out.windMult=vuln.windMult;
    out.notes.push("Emanuel (2011) cubic damage: threshold "+V_THRESH+" m/s, half damage at "+vuln.vHalf.toFixed(1)+" m/s"+(vuln.vHalf!==V_HALF?" (archetype-shifted from "+V_HALF+")":""));
    return out;
  }
  if(hz==="wfire"){
    const b=fireBurnPct(site,sc);
    if(b.source==="grid")out.source=gridSrc();
    else if(b.source==="interim")out.source={kind:"interim",
      detail:String(site.wui_class||"").toLowerCase()+" WUI class: "+
        (FIRE_WUI_PBURN[String(site.wui_class||"").toLowerCase()]||0)+"%/yr base point-burn probability, +"+
        Math.round(FIRE_WARMING_UPLIFT*100)+"% per degree of warming"};
    else out.source={kind:"none",detail:"no wildfire grid loaded and no wui_class on the site profile, so wildfire scores zero"};
    out.inputs={kind:"burn",burnPct:r.burnPct||0};
    out.factors=[b.condSource==="grid"
      ?{name:"conditional damage at the modeled flame length (WRC CFL)",mult:b.cond}
      :{name:"conditional damage given fire reaches the site: INTERIM flat ratio, capped",mult:b.cond}];
    if(b.condSource!=="grid")out.notes.push("the conditional damage side is an interim flat ratio ("+FIRE_COND_INTERIM+", capped) until a flame-length (CFL) layer is supplied; labeled interim here and on the trust chips");
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
  /* Task 4: state the depth basis - structure-adjusted or modeled-coarse */
  const _rel=siteRelief(site);
  if(_rel!=null)out.factors.unshift({name:"depth read at the structure (site ground vs cell land mean)",add:-_rel});
  else out.notes.push("modeled-coarse: depth is the cell average; add ground_elev_m + cell_ground_elev_m (survey or enrich_sites.py) to read it at the structure");
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
