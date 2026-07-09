/* ============================================================
   SURFACE 3: the climate map (v3 overhaul).

   A genuine WebGL geospatial map (MapLibre GL JS, vendored in
   90_vendor_maplibre.js; BSD, no API key, no tile service) over a
   bundled offline basemap (88_basemap_data.js: Natural Earth 1:50m
   land / lakes / borders, public domain), so the map works from
   file:// with zero network calls.

   WHAT IT RENDERS (all read-only over the engines):
   - Per-peril hazard surfaces. When a CLIMADA hazard grid is loaded,
     the grid's OWN cells are drawn (never resampled); without one,
     the app's documented interim screening fields are evaluated on a
     mesh and the legend says so. Wildfire and TC rainfall have no
     interim spatial field by design, so those layers stay off with
     the reason stated, never a fabricated surface.
   - Sites as a data layer: sized by TCOR, coloured by TCOR intensity,
     dominant component, or confidence (switchable).
   - Event footprints from the results pack's event table: one storm,
     these sites, one shared deductible per campus.
   - An accumulation (TCOR concentration) heatmap.

   THE PATHWAY SIMULATION: a timeline scrubber from present (2026)
   through 2030 / 2050 / 2080 under the selected SSP. Hazard surfaces
   for the bracketing modeled horizons cross-fade and the site TCOR
   encoding lerps continuously, while the label states plainly whether
   the current position is MODELED or INTERPOLATED (a visual between
   modeled years, never new precision; no sub-annual detail exists).
   The scrubber IS the global scenario control: it snaps the app's
   scenario to the nearest modeled point, so the headline and the
   decision list follow the map.
   ============================================================ */

const CMD_YEARS=[2026,2030,2050,2080];
function scenOfYearIdx(i,pw){ return i===0?"present":pw+"_"+CMD_YEARS[i]; }
function yearOfScen(sc){ return sc==="present"?CMD_YEARS[0]:(+String(sc).split("_")[1]||CMD_YEARS[0]); }
function nearestYearIdx(y){
  let best=0,bd=Infinity;
  CMD_YEARS.forEach((cy,i)=>{const d=Math.abs(cy-y);if(d<bd){bd=d;best=i;}});
  return best;
}
/* bracketing modeled horizons + fraction for a scrub year */
function yearBracket(y){
  y=Math.max(CMD_YEARS[0],Math.min(CMD_YEARS[CMD_YEARS.length-1],y));
  for(let i=0;i<CMD_YEARS.length-1;i++){
    if(y<=CMD_YEARS[i+1])return {i,f:(y-CMD_YEARS[i])/(CMD_YEARS[i+1]-CMD_YEARS[i])};
  }
  return {i:CMD_YEARS.length-2,f:1};
}

/* MAP_PERILS / hazardField / fieldDomain / fieldFC live in 10_hazard_engine.js
   so the Node harness can contract-test the map's data path. */

const LS_CMDMAP="rtv_cmdmap_v1";
function clLoadMapState(){
  const base={peril:"tc",opacity:0.7,enc:"tcor",accum:false,eventId:null,
    year:null,holdYear:false,playing:false,userMoved:false,
    aggregate:true,compare:false,brand:""};
  try{
    const raw=localStorage.getItem(LS_CMDMAP);
    if(!raw)return base;
    const s=JSON.parse(raw)||{};
    if(typeof s.peril==="string")base.peril=s.peril;
    if(typeof s.opacity==="number"&&s.opacity>=0.1&&s.opacity<=1)base.opacity=s.opacity;
    if(s.enc==="tcor"||s.enc==="component"||s.enc==="confidence")base.enc=s.enc;
    if(typeof s.accum==="boolean")base.accum=s.accum;
    if(typeof s.aggregate==="boolean")base.aggregate=s.aggregate;
    if(typeof s.compare==="boolean")base.compare=s.compare;
    if(typeof s.brand==="string")base.brand=s.brand;
  }catch(e){}
  return base;
}
function clPersistMapState(){
  try{
    localStorage.setItem(LS_CMDMAP,JSON.stringify({
      peril:cmdMapState.peril,opacity:cmdMapState.opacity,enc:cmdMapState.enc,
      accum:cmdMapState.accum,aggregate:cmdMapState.aggregate,
      compare:cmdMapState.compare,brand:cmdMapState.brand}));
  }catch(e){}
}
function clPrefersReducedMotion(){
  try{return !!(window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches);}
  catch(e){return false;}
}
function clAnnounce(msg){
  const el=document.getElementById("cmdMapLive");
  if(el)el.textContent=msg||"";
}

let cmdMapState=clLoadMapState();
let _clMap=null,_clReady=false,_clFailed=false;
let _clHaz=null;        // {key,peril,domain,fields:[..]}
let _clSiteInfo=null;   // {key,maxT,nMarkers,nRecords}
let _clFitKey="";
let _clTcorCache={};    // scenario -> tcorPortfolio rows total map
let _clTcorCacheKey=null;
let _clPlayT=null;
let _clThemeObs=null;
let _clHoverId=null;

/* resolve a CSS token to its current concrete value (theme-aware) */
function cssTok(name,fallback){
  try{
    const v=getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v||fallback;
  }catch(e){return fallback;}
}
function clIsDark(){
  try{return document.documentElement.getAttribute("data-theme")==="dark";}catch(e){return false;}
}

/* ---- colour ramps: one hue per peril (sequential = single hue,
   light end recedes toward transparency so near-zero hazard vanishes
   instead of painting the map). Steps are mixed from the peril's
   identity colour, per theme. ---- */
function hex2rgb(h){h=h.replace("#","");return [parseInt(h.slice(0,2),16),parseInt(h.slice(2,4),16),parseInt(h.slice(4,6),16)];}
function mixRgb(a,b,t){return [Math.round(a[0]+(b[0]-a[0])*t),Math.round(a[1]+(b[1]-a[1])*t),Math.round(a[2]+(b[2]-a[2])*t)];}
function rgba(c,a){return "rgba("+c[0]+","+c[1]+","+c[2]+","+a+")";}
function perilRamp(hz){
  const base=hex2rgb(HAZARD_BY[hz]?HAZARD_BY[hz].color:"#20718B");
  const dark=clIsDark();
  const light=mixRgb(base,dark?[210,230,235]:[255,255,255],dark?0.55:0.72);
  const deep=mixRgb(base,[0,0,0],dark?0.05:0.35);
  return [rgba(light,0),rgba(light,0.45),rgba(base,0.7),rgba(deep,0.9)];
}
function rampCss(stops){
  return "linear-gradient(90deg,"+stops.join(",")+")";
}

/* ---- the offline basemap style ---- */
function clBaseColors(){
  const dark=clIsDark();
  return dark
    ?{water:"#0B141B",land:"#1B2730",lakes:"#0B141B",countries:"#3B4954",states:"#2C3944",grat:"#1E2A33"}
    :{water:"#D9E4E6",land:"#F4F1E7",lakes:"#D9E4E6",countries:"#AEBCC2",states:"#C8D2D6",grat:"#E3E9EA"};
}
function clBasemapFC(kind){
  const L=CLAM_BASEMAP.layers[kind];
  if(L.type==="polygons")
    return {type:"FeatureCollection",features:L.coords.map(p=>({type:"Feature",properties:{},geometry:{type:"Polygon",coordinates:p}}))};
  return {type:"FeatureCollection",features:[{type:"Feature",properties:{},geometry:{type:"MultiLineString",coordinates:L.coords}}]};
}
function clGraticuleFC(){
  const b=CLAM_BASEMAP.bbox,lines=[];
  for(let lo=Math.ceil(b[0]/10)*10;lo<=b[2];lo+=10)lines.push([[lo,b[1]],[lo,b[3]]]);
  for(let la=Math.ceil(b[1]/10)*10;la<=b[3];la+=10)lines.push([[b[0],la],[b[2],la]]);
  return {type:"FeatureCollection",features:[{type:"Feature",properties:{},geometry:{type:"MultiLineString",coordinates:lines}}]};
}
function clBaseStyle(){
  const c=clBaseColors();
  return {version:8,
    sources:{
      "bm-land":{type:"geojson",data:clBasemapFC("land")},
      "bm-lakes":{type:"geojson",data:clBasemapFC("lakes")},
      "bm-countries":{type:"geojson",data:clBasemapFC("countries")},
      "bm-states":{type:"geojson",data:clBasemapFC("states")},
      "bm-grat":{type:"geojson",data:clGraticuleFC()}
    },
    layers:[
      {id:"bg",type:"background",paint:{"background-color":c.water}},
      {id:"grat",type:"line",source:"bm-grat",paint:{"line-color":c.grat,"line-width":0.6}},
      {id:"land",type:"fill",source:"bm-land",paint:{"fill-color":c.land,"fill-outline-color":c.countries}},
      {id:"lakes",type:"fill",source:"bm-lakes",paint:{"fill-color":c.lakes,"fill-outline-color":c.states}},
      {id:"countries",type:"line",source:"bm-countries",paint:{"line-color":c.countries,"line-width":1.0}},
      {id:"states",type:"line",source:"bm-states",paint:{"line-color":c.states,"line-width":0.7}}
    ]};
}
function clApplyBaseTheme(){
  if(!_clMap||!_clReady)return;
  const c=clBaseColors();
  try{
    _clMap.setPaintProperty("bg","background-color",c.water);
    _clMap.setPaintProperty("grat","line-color",c.grat);
    _clMap.setPaintProperty("land","fill-color",c.land);
    _clMap.setPaintProperty("land","fill-outline-color",c.countries);
    _clMap.setPaintProperty("lakes","fill-color",c.lakes);
    _clMap.setPaintProperty("lakes","fill-outline-color",c.states);
    _clMap.setPaintProperty("countries","line-color",c.countries);
    _clMap.setPaintProperty("states","line-color",c.states);
  }catch(e){}
}

/* ---- init ---- */
function clInit(){
  if(_clMap)return true;
  if(_clFailed)return false;
  if(typeof maplibregl==="undefined"||typeof CLAM_BASEMAP==="undefined"){_clFailed=true;return false;}
  const host=document.getElementById("cmdMap");
  if(!host||!host.offsetWidth)return true;   /* container not laid out yet; retry next render */
  try{
    _clMap=new maplibregl.Map({container:host,style:clBaseStyle(),
      center:[-95,27],zoom:3.2,minZoom:1.5,maxZoom:12,attributionControl:false,
      fadeDuration:0});
    _clMap.addControl(new maplibregl.NavigationControl({showCompass:false}),"top-right");
    _clMap.on("dragstart",()=>{cmdMapState.userMoved=true;});
    _clMap.on("wheel",()=>{cmdMapState.userMoved=true;});
    _clMap.on("load",()=>{
      _clReady=true;
      try{
        _clMap.addSource("clam-sites",{type:"geojson",data:{type:"FeatureCollection",features:[]}});
        _clMap.addLayer({id:"clam-accum",type:"heatmap",source:"clam-sites",
          layout:{visibility:"none"},
          paint:{"heatmap-radius":["interpolate",["linear"],["zoom"],2,34,7,90],
                 "heatmap-intensity":0.9,
                 "heatmap-color":["interpolate",["linear"],["heatmap-density"],
                   0,"rgba(32,113,139,0)",0.25,"rgba(95,169,191,0.36)",
                   0.55,"rgba(32,113,139,0.62)",1,"rgba(9,63,82,0.85)"]}});
        _clMap.addLayer({id:"clam-evt-hull",type:"fill",source:{type:"geojson",data:{type:"FeatureCollection",features:[]}},
          paint:{"fill-color":"rgba(194,86,27,0.10)","fill-outline-color":"rgba(194,86,27,0.6)"}});
        _clMap.addLayer({id:"clam-evt-line",type:"line",source:{type:"geojson",data:{type:"FeatureCollection",features:[]}},
          paint:{"line-color":"rgba(194,86,27,0.8)","line-width":1.4,"line-dasharray":[2,2]}});
        _clMap.addLayer({id:"clam-evt-pt",type:"circle",source:{type:"geojson",data:{type:"FeatureCollection",features:[]}},
          paint:{"circle-color":"rgba(194,86,27,0.55)","circle-stroke-color":"#C2561B","circle-stroke-width":1.5,
                 "circle-radius":["get","r"]}});
        _clMap.addLayer({id:"clam-sel",type:"circle",source:"clam-sites",
          filter:["==",["get","id"],-1],
          paint:{"circle-radius":26,"circle-color":"rgba(0,0,0,0)",
                 "circle-stroke-color":cssTok("--focus","#1E7FA6"),"circle-stroke-width":2.5}});
        _clMap.addLayer({id:"clam-hover",type:"circle",source:"clam-sites",
          filter:["==",["get","id"],-1],
          paint:{"circle-radius":22,"circle-color":"rgba(0,0,0,0)",
                 "circle-stroke-color":cssTok("--ink-2","#5B6770"),"circle-stroke-width":1.5,
                 "circle-stroke-opacity":0.7}});
        _clMap.addLayer({id:"clam-sites-l",type:"circle",source:"clam-sites",
          paint:{"circle-radius":6,"circle-color":cssTok("--seq-5","#20718B"),
                 "circle-stroke-color":cssTok("--surface","#fff"),"circle-stroke-width":1.5,
                 "circle-opacity":0.88}});
        /* Top-N site labels at mid-zoom (halo for contrast on hazard surfaces). */
        _clMap.addLayer({id:"clam-labels",type:"symbol",source:"clam-sites",
          layout:{"text-field":["get","name"],"text-size":11,"text-offset":[0,1.35],
                  "text-anchor":"top","text-optional":true,"text-max-width":10,
                  "symbol-sort-key":["-",["get","tcorNow"]],
                  "text-allow-overlap":false,"text-ignore-placement":false},
          paint:{"text-color":cssTok("--heading","#1A2A33"),
                 "text-halo-color":cssTok("--surface","#fff"),"text-halo-width":1.4},
          minzoom:5});
        _clMap.on("click","clam-sites-l",e=>{
          const f=e.features&&e.features[0];if(!f)return;
          const p=f.properties;
          selectedId=+p.id;
          try{_clMap.setFilter("clam-sel",["==",["get","id"],+p.id]);}catch(err){}
          clBrushList(+p.id);
          const nMem=+p.nMembers||1;
          const html='<div style="font-family:inherit;min-width:180px">'+
            '<b style="font-family:var(--font-display);font-size:14px;color:var(--heading)">'+esc(p.name)+'</b>'+
            (nMem>1?'<div style="font-size:10.5px;color:var(--muted)">'+nMem+' named-insured records</div>':'')+
            '<div class="mono" style="font-size:11px;margin:3px 0">TCOR '+fmt$(+p.tcorNow)+'/yr'+(p.conf==="est"?' · <span style="color:var(--warn-ink)">estimate</span>':'')+'</div>'+
            '<div style="font-size:11px;color:var(--ink-2)">dominant: '+esc(p.domLabel)+'</div>'+
            '<button class="lightbtn primary" style="margin-top:6px;font-size:12px" onclick="openSiteView('+(+p.id)+')">Open site view</button></div>';
          new maplibregl.Popup({closeButton:true,maxWidth:"260px"}).setLngLat(e.lngLat).setHTML(html).addTo(_clMap);
        });
        _clMap.on("mouseenter","clam-sites-l",e=>{
          _clMap.getCanvas().style.cursor="pointer";
          const f=e.features&&e.features[0];if(!f)return;
          _clHoverId=+f.properties.id;
          try{_clMap.setFilter("clam-hover",["==",["get","id"],_clHoverId]);}catch(err){}
          clBrushList(_clHoverId,true);
        });
        _clMap.on("mouseleave","clam-sites-l",()=>{
          _clMap.getCanvas().style.cursor="";
          _clHoverId=null;
          try{_clMap.setFilter("clam-hover",["==",["get","id"],-1]);}catch(err){}
          clBrushList(selectedId,true);
        });
        _clMap.getCanvas().setAttribute("tabindex","0");
        _clMap.getCanvas().setAttribute("aria-label","Portfolio climate map. Arrow keys pan, plus and minus zoom.");
        _clMap.getCanvas().addEventListener("keydown",clMapKeyNav);
      }catch(e){}
      /* theme flips restyle the basemap and re-colour the data layers */
      try{
        if(!_clThemeObs&&typeof MutationObserver!=="undefined"){
          _clThemeObs=new MutationObserver(()=>{clApplyBaseTheme();clRestyleData();});
          _clThemeObs.observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
        }
      }catch(e){}
      climateMapUpdate(typeof cmdCtx==="function"?cmdCtx():null);
    });
  }catch(e){_clFailed=true;return false;}
  return true;
}

/* ---- hazard layers: 4 modeled horizons, cross-faded ---- */
function clHazKey(){
  const pw=cmdScenParts().pathway;
  return cmdMapState.peril+"|"+pw+"|"+(hazardGrid?hazardGrid.meta.loaded+":"+hazardGrid.meta.cells:"-");
}
function clBuildHazard(){
  if(!_clMap||!_clReady)return;
  const key=clHazKey()+(cmdMapState.compare?"|cmp":"");
  if(_clHaz&&_clHaz.key===key)return;
  /* clear previous */
  for(let i=0;i<CMD_YEARS.length;i++){
    try{if(_clMap.getLayer("clam-haz-"+i))_clMap.removeLayer("clam-haz-"+i);}catch(e){}
    try{if(_clMap.getSource("clam-haz-"+i))_clMap.removeSource("clam-haz-"+i);}catch(e){}
  }
  _clHaz={key,peril:cmdMapState.peril,fields:[],domain:null};
  if(cmdMapState.peril==="none"){clLegend();clAnnounceSummary();return;}
  const pw=cmdScenParts().pathway;
  const bbox=(typeof CLAM_BASEMAP!=="undefined"&&CLAM_BASEMAP.bbox)||[-180,5,-50,55];
  const fields=CMD_YEARS.map((y,i)=>hazardField(cmdMapState.peril,scenOfYearIdx(i,pw),{bbox}));
  _clHaz.fields=fields;
  if(fields.every(f=>f.none)){clLegend();clAnnounceSummary();return;}
  _clHaz.domain=fieldDomain(fields);
  const [lo,hi]=_clHaz.domain;
  const ramp=perilRamp(cmdMapState.peril);
  const colorExpr=["interpolate",["linear"],["get","v"],
    lo,ramp[0], lo+(hi-lo)*0.33,ramp[1], lo+(hi-lo)*0.66,ramp[2], hi,ramp[3]];
  fields.forEach((f,i)=>{
    if(f.none)return;
    try{
      _clMap.addSource("clam-haz-"+i,{type:"geojson",data:fieldFC(f)});
      /* Heatmap for dense grid/interim fields reads as a continuous surface;
         circle-blur remains as a fallback when a field is very sparse. */
      const useHeat=(f.features||[]).length>=40;
      _clMap.addLayer({id:"clam-haz-"+i,type:useHeat?"heatmap":"circle",source:"clam-haz-"+i,
        paint:useHeat?{
          "heatmap-weight":["interpolate",["linear"],["get","v"],lo,0,hi,1],
          "heatmap-intensity":["interpolate",["linear"],["zoom"],2,0.55,6,1.15],
          "heatmap-radius":["interpolate",["linear"],["zoom"],2,18,4,32,6,55,9,90],
          "heatmap-opacity":0,
          "heatmap-color":["interpolate",["linear"],["heatmap-density"],
            0,ramp[0],0.25,ramp[1],0.55,ramp[2],1,ramp[3]]
        }:{
          "circle-radius":["interpolate",["exponential",1.9],["zoom"],2,3.6,4,8.5,6,26,9,100],
          "circle-blur":0.85,
          "circle-color":colorExpr,
          "circle-opacity":0}},"clam-accum");
    }catch(e){}
  });
  clApplyYear();
  clLegend();
  clAnnounceSummary();
}
function clRestyleData(){
  /* theme change: rebuild colour expressions with the new tokens */
  if(!_clMap||!_clReady||!_clHaz)return;
  if(_clHaz.domain){
    const [lo,hi]=_clHaz.domain,ramp=perilRamp(_clHaz.peril);
    const colorExpr=["interpolate",["linear"],["get","v"],
      lo,ramp[0], lo+(hi-lo)*0.33,ramp[1], lo+(hi-lo)*0.66,ramp[2], hi,ramp[3]];
    for(let i=0;i<CMD_YEARS.length;i++){
      try{
        if(!_clMap.getLayer("clam-haz-"+i))continue;
        const t=_clMap.getLayer("clam-haz-"+i).type;
        if(t==="heatmap"){
          _clMap.setPaintProperty("clam-haz-"+i,"heatmap-color",
            ["interpolate",["linear"],["heatmap-density"],0,ramp[0],0.25,ramp[1],0.55,ramp[2],1,ramp[3]]);
        }else{
          _clMap.setPaintProperty("clam-haz-"+i,"circle-color",colorExpr);
        }
      }catch(e){}
    }
  }
  try{_clMap.setPaintProperty("clam-sel","circle-stroke-color",cssTok("--focus","#1E7FA6"));}catch(e){}
  try{_clMap.setPaintProperty("clam-labels","text-color",cssTok("--heading","#1A2A33"));}catch(e){}
  try{_clMap.setPaintProperty("clam-labels","text-halo-color",cssTok("--surface","#fff"));}catch(e){}
  clApplyYear();
  clLegend();
}

/* ---- sites: per-horizon TCOR totals for the continuous encoding ---- */
function clTcorTotals(sc){
  const key=cmdStateKey().split("|").slice(1).join("|");  /* everything but the scenario */
  if(_clTcorCacheKey!==key){_clTcorCache={};_clTcorCacheKey=key;}
  if(!_clTcorCache[sc]){
    const tp=tcorPortfolio(sites,sc);
    const m={};tp.rows.forEach(r=>m[r.id]=r.total);
    _clTcorCache[sc]=m;
  }
  return _clTcorCache[sc];
}
/* Aggregate named-insured records that share a campus (site_id / coords)
   into one marker, matching the legacy analyst map. Toggleable. */
function clSiteMarkers(c){
  const brand=(cmdMapState.brand||"").trim().toLowerCase();
  let rows=c.rows;
  if(brand)rows=rows.filter(r=>String(r.brand||"").toLowerCase()===brand);
  if(!cmdMapState.aggregate||typeof siteGroupKey!=="function"){
    return rows.map(r=>({id:r.id,name:r.name,lat:r.lat,lon:r.lon,dom:r.domComp,
      conf:r.estimate?"est":"ok",ids:[r.id],nMembers:1,tiv:r.tiv||0}));
  }
  const m=new Map();
  rows.forEach(r=>{
    const s=r.site||sites.find(x=>x.id===r.id)||{latitude:r.lat,longitude:r.lon,name:r.name,brand:r.brand};
    const k=siteGroupKey(s);
    let g=m.get(k);
    if(!g){g={id:r.id,name:r.name,lat:r.lat,lon:r.lon,dom:r.domComp,conf:r.estimate?"est":"ok",
      ids:[],nMembers:0,tiv:0,domT:0};m.set(k,g);}
    g.ids.push(r.id);g.nMembers++;g.tiv+=(r.tiv||0);
    if(r.total>g.domT){g.domT=r.total;g.dom=r.domComp;g.id=r.id;g.name=r.name;
      g.conf=r.estimate?"est":g.conf;g.lat=r.lat;g.lon=r.lon;}
    if(r.estimate)g.conf="est";
  });
  return [...m.values()];
}
function clBuildSites(c){
  if(!_clMap||!_clReady||!c)return;
  const pw=cmdScenParts().pathway;
  const key=cmdStateKey()+"|"+pw+"|"+scenario+"|"+(cmdMapState.aggregate?"agg":"rec")+"|"+(cmdMapState.brand||"");
  if(_clSiteInfo&&_clSiteInfo.key===key)return;
  const markers=clSiteMarkers(c);
  const perScen=CMD_YEARS.map((y,i)=>clTcorTotals(scenOfYearIdx(i,pw)));
  let maxT=0;
  const feats=markers.map(m=>{
    const t=perScen.map(scMap=>m.ids.reduce((a,id)=>a+(scMap[id]||0),0));
    t.forEach(v=>{if(v>maxT)maxT=v;});
    const now=m.ids.reduce((a,id)=>a+((c.rows.find(r=>r.id===id)||{}).total||0),0);
    return {type:"Feature",geometry:{type:"Point",coordinates:[m.lon,m.lat]},
      properties:{id:m.id,name:m.name,nMembers:m.nMembers,
        t0:t[0],t1:t[1],t2:t[2],t3:t[3],
        tcorNow:now,dom:m.dom,domLabel:TCOR_COMP_BY[m.dom].label,
        conf:m.conf}};
  });
  _clSiteInfo={key,maxT:maxT||1,nMarkers:feats.length,nRecords:c.rows.length};
  try{_clMap.getSource("clam-sites").setData({type:"FeatureCollection",features:feats});}catch(e){}
  try{_clMap.setFilter("clam-sel",["==",["get","id"],selectedId==null?-1:+selectedId]);}catch(e){}
  /* frame the portfolio once per site-set; never fight the user's hand */
  const fit=markers.map(m=>m.id).sort().join(",")+"|"+(cmdMapState.brand||"");
  if(fit!==_clFitKey&&!cmdMapState.userMoved&&markers.length){
    _clFitKey=fit;
    let lo0=Infinity,la0=Infinity,lo1=-Infinity,la1=-Infinity;
    markers.forEach(r=>{lo0=Math.min(lo0,r.lon);la0=Math.min(la0,r.lat);lo1=Math.max(lo1,r.lon);la1=Math.max(la1,r.lat);});
    const dur=clPrefersReducedMotion()?0:600;
    try{_clMap.fitBounds([[lo0,la0],[lo1,la1]],{padding:70,maxZoom:6,duration:dur});}catch(e){}
  }
  clApplyYear();
  clAnnounceSummary();
}

/* ---- the continuous year: cross-fade + lerp everything ---- */
function clLerpExpr(i,f){
  if(f<=0)return ["get","t"+i];
  if(f>=1)return ["get","t"+(i+1)];
  return ["+",["*",["get","t"+i],1-f],["*",["get","t"+(i+1)],f]];
}
function clApplyYear(){
  if(!_clMap||!_clReady)return;
  const y=cmdMapState.year!=null?cmdMapState.year:yearOfScen(scenario);
  const {i,f}=yearBracket(y);
  /* hazard cross-fade: exact at modeled points. Compare mode holds present
     (horizon 0) at half opacity beside the scrubbed future so the pathway
     delta is visible without a swipe control. */
  for(let k=0;k<CMD_YEARS.length;k++){
    let op=0;
    if(cmdMapState.compare){
      if(k===0)op=0.45*cmdMapState.opacity;
      if(k===i)op=Math.max(op,(1-f)*cmdMapState.opacity);
      if(k===i+1)op=Math.max(op,f*cmdMapState.opacity);
    }else{
      if(k===i)op=(1-f)*cmdMapState.opacity;
      else if(k===i+1)op=f*cmdMapState.opacity;
    }
    try{
      if(!_clMap.getLayer("clam-haz-"+k))continue;
      const t=_clMap.getLayer("clam-haz-"+k).type;
      if(t==="heatmap")_clMap.setPaintProperty("clam-haz-"+k,"heatmap-opacity",op);
      else _clMap.setPaintProperty("clam-haz-"+k,"circle-opacity",op);
    }catch(e){}
  }
  /* site encoding lerp */
  const maxT=(_clSiteInfo&&_clSiteInfo.maxT)||1;
  const lerp=clLerpExpr(i,f);
  const share=["min",1,["max",0,["/",lerp,maxT]]];
  /* dots shrink at low zoom so a 245-site portfolio stays readable
     (the accumulation layer is the aggregate view); full size from z6 */
  const radius=["*",["interpolate",["linear"],["zoom"],3,0.55,6,1],
    ["+",4,["*",17,["sqrt",share]]]];
  let color;
  if(cmdMapState.enc==="component"){
    color=["match",["get","dom"],
      "prop",cssTok("--c-prop","#0E7A9B"),"bi",cssTok("--c-bi","#C2561B"),
      "prem",cssTok("--c-prem","#7048C6"),"freq",cssTok("--c-freq","#1E8E5A"),
      "admin",cssTok("--c-admin","#B84A82"),cssTok("--seq-5","#20718B")];
  }else if(cmdMapState.enc==="confidence"){
    color=["match",["get","conf"],"ok",cssTok("--seq-5","#20718B"),"est","#B07B10","#B07B10"];
  }else{
    color=["interpolate",["linear"],share,
      0.02,cssTok("--seq-2","#8FC6D6"),0.35,cssTok("--seq-4","#3A8CA6"),
      0.7,cssTok("--seq-6","#105A72"),1,cssTok("--seq-7","#093F52")];
  }
  try{
    _clMap.setPaintProperty("clam-sites-l","circle-radius",radius);
    _clMap.setPaintProperty("clam-sites-l","circle-color",color);
    _clMap.setPaintProperty("clam-sites-l","circle-stroke-color",cssTok("--surface","#fff"));
    _clMap.setLayoutProperty("clam-accum","visibility",cmdMapState.accum?"visible":"none");
    if(cmdMapState.accum)_clMap.setPaintProperty("clam-accum","heatmap-weight",share);
    /* show labels only when the portfolio is small enough to read */
    const n=(_clSiteInfo&&_clSiteInfo.nMarkers)||0;
    _clMap.setLayoutProperty("clam-labels","visibility",n>0&&n<=40?"visible":"none");
  }catch(e){}
  clSyncScrubUI();
}

/* ---- events: one storm, these sites, one shared deductible ---- */
function clEventList(c){
  if(!c||!c.join||!resultsPack||!resultsPack.data||!resultsPack.data.event_sets)return [];
  const evScen=resultsPack.data.event_sets.scenarios&&resultsPack.data.event_sets.scenarios[scenario];
  if(!evScen)return [];
  const out=[];
  evScen.forEach(part=>{
    const w=+part.weight||0;
    (part.events||[]).forEach(e=>{
      let tot=0;const hits=[];
      (e.sites||[]).forEach(p=>{
        const s=c.join.map[p[0]];
        if(s)hits.push({id:s.id,name:s.name,lat:+s.latitude,lon:+s.longitude,loss:+p[1]||0});
        tot+=(+p[1]||0);
      });
      if(hits.length)out.push({id:String(e.id),freq:+e.freq||0,tot,hits,w,
        exp:w*(+e.freq||0)*tot});
    });
  });
  out.sort((a,b)=>(b.hits.length-a.hits.length)||(b.exp-a.exp));
  return out.slice(0,9);
}
function clHull(pts){
  /* gift wrapping; tiny n */
  if(pts.length<3)return null;
  const P=pts.slice().sort((a,b)=>a[0]-b[0]||a[1]-b[1]);
  const cross=(o,a,b)=>(a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0]);
  const lower=[];P.forEach(p=>{while(lower.length>=2&&cross(lower[lower.length-2],lower[lower.length-1],p)<=0)lower.pop();lower.push(p);});
  const upper=[];P.slice().reverse().forEach(p=>{while(upper.length>=2&&cross(upper[upper.length-2],upper[upper.length-1],p)<=0)upper.pop();upper.push(p);});
  return lower.slice(0,-1).concat(upper.slice(0,-1));
}
function clShowEvent(ev){
  if(!_clMap||!_clReady)return;
  const empty={type:"FeatureCollection",features:[]};
  const setSrc=(id,data)=>{try{const s=_clMap.getSource(id);if(s)s.setData(data);}catch(e){}};
  if(!ev){setSrc("clam-evt-hull",empty);setSrc("clam-evt-line",empty);setSrc("clam-evt-pt",empty);return;}
  const maxL=Math.max.apply(null,ev.hits.map(h=>h.loss))||1;
  setSrc("clam-evt-pt",{type:"FeatureCollection",features:ev.hits.map(h=>({
    type:"Feature",geometry:{type:"Point",coordinates:[h.lon,h.lat]},
    properties:{r:6+14*Math.sqrt(h.loss/maxL)}}))});
  const pts=ev.hits.map(h=>[h.lon,h.lat]);
  const hull=clHull(pts);
  setSrc("clam-evt-hull",hull?{type:"FeatureCollection",features:[{type:"Feature",properties:{},
    geometry:{type:"Polygon",coordinates:[hull.concat([hull[0]])]}}]}:empty);
  setSrc("clam-evt-line",pts.length>1?{type:"FeatureCollection",features:[{type:"Feature",properties:{},
    geometry:{type:"LineString",coordinates:pts.slice().sort((a,b)=>a[0]-b[0])}}]}:empty);
}

/* ---- scrubbing & playback ---- */
function clOnScrub(y){
  cmdMapState.year=Math.round(y);
  cmdMapState.holdYear=true;
  clApplyYear();
  const snap=scenOfYearIdx(nearestYearIdx(cmdMapState.year),cmdScenParts().pathway);
  if(snap!==scenario)cmdSetScenario(snap);   /* headline + list follow the map */
  else clSyncScrubUI();
}
function clStopPlay(){
  cmdMapState.playing=false;
  if(_clPlayT!=null){try{cancelAnimationFrame(_clPlayT);}catch(e){} _clPlayT=null;}
  const b=document.getElementById("clPlay");if(b)b.textContent="▶";
  clSyncScrubUI();
}
function clPlayToggle(){
  if(cmdMapState.playing){clStopPlay();return;}
  if(clPrefersReducedMotion()){
    /* jump to end rather than animate when the user asked for less motion */
    clOnScrub(CMD_YEARS[CMD_YEARS.length-1]);return;
  }
  cmdMapState.playing=true;cmdMapState.holdYear=true;
  const b=document.getElementById("clPlay");if(b)b.textContent="◼";
  let y=cmdMapState.year!=null?cmdMapState.year:yearOfScen(scenario);
  if(y>=CMD_YEARS[CMD_YEARS.length-1]-0.5)y=CMD_YEARS[0];
  let last=null;
  const step=(ts)=>{
    if(!cmdMapState.playing)return;
    if(last==null)last=ts;
    const dt=Math.min((ts-last)/1000,0.1);last=ts;
    y+=dt*7;                                   /* ~8 s for the full sweep */
    if(y>=CMD_YEARS[CMD_YEARS.length-1]){y=CMD_YEARS[CMD_YEARS.length-1];clOnScrub(y);clStopPlay();return;}
    cmdMapState.year=y;
    clApplyYear();
    const snap=scenOfYearIdx(nearestYearIdx(y),cmdScenParts().pathway);
    if(snap!==scenario)cmdSetScenario(snap);
    const sl=document.getElementById("clScrub");if(sl)sl.value=Math.round(y);
    _clPlayT=requestAnimationFrame(step);
  };
  _clPlayT=requestAnimationFrame(step);
}
function clSetPathway(pw){
  clStopPlay();
  if(scenario==="present"){
    if(ui){ui.futureSc=pw+"_"+(ui.futureSc?ui.futureSc.split("_")[1]||"2050":"2050");if(typeof persist==="function")persist();}
    _clHaz=null;_clSiteInfo=null;
    climateMapUpdate(typeof cmdCtx==="function"?cmdCtx():null);
    if(typeof renderCommand==="function")renderCommand();
  }else{
    cmdSetScenario(pw+"_"+cmdScenParts().horizon);
  }
}

/* ---- the map chrome: layer chips, encoding, opacity, events, scrub bar ---- */
function clRenderCtl(c){
  const host=document.getElementById("cmdMapCtl");
  if(!host)return;
  const st=cmdMapState;
  const evs=clEventList(c);
  const brands=[...new Set((c.rows||[]).map(r=>r.brand).filter(Boolean))].sort();
  let h='<div class="mapchips" role="group" aria-label="Hazard layer">'+
    '<span class="lbl">Hazard</span>'+
    MAP_PERILS.map(p=>{
      const off=!gridByHazard[p.key]&&!p.interim;
      return '<button type="button" class="mapchip" data-clperil="'+p.key+'"'+(off?' disabled title="'+esc(p.offReason||"no data")+'"':' title="'+esc(p.label+" · "+p.unit)+'"')+
        ' aria-pressed="'+(st.peril===p.key?"true":"false")+'">'+esc(p.label)+'</button>';
    }).join("")+
    '<button type="button" class="mapchip" data-clperil="none" aria-pressed="'+(st.peril==="none"?"true":"false")+'">Off</button>'+
    '<span class="lbl">Opacity</span><input type="range" id="clOpacity" min="10" max="100" step="5" value="'+Math.round(st.opacity*100)+'" aria-label="Hazard layer opacity">'+
    infoBtn("mapLayers")+
    '</div>';
  h+='<div class="mapchips" role="group" aria-label="Site encoding and views">'+
    '<span class="lbl">Sites</span>'+
    [["tcor","TCOR intensity"],["component","Dominant part"],["confidence","Confidence"]].map(([k,l])=>
      '<button type="button" class="mapchip" data-clenc="'+k+'" aria-pressed="'+(st.enc===k?"true":"false")+'">'+l+'</button>').join("")+
    '<button type="button" class="mapchip" id="clAccum" aria-pressed="'+(st.accum?"true":"false")+'" title="Where the portfolio\'s TCOR concentrates geographically">Accumulation</button>'+
    '<button type="button" class="mapchip" id="clAgg" aria-pressed="'+(st.aggregate?"true":"false")+'" title="One marker per campus (named-insured records sharing a site)">Campus</button>'+
    '<button type="button" class="mapchip" id="clCompare" aria-pressed="'+(st.compare?"true":"false")+'" title="Hold present-day hazard beside the scrubbed future">Compare</button>'+
    infoBtn("mapAccum")+
    '</div>';
  if(brands.length>1){
    h+='<div class="mapchips" role="group" aria-label="Brand filter"><span class="lbl">Brand</span>'+
      '<select id="clBrandSel" aria-label="Filter map sites by brand"><option value="">all brands</option>'+
      brands.map(b=>'<option value="'+esc(b)+'"'+(st.brand===b?" selected":"")+'>'+esc(b)+'</option>').join("")+
      '</select></div>';
  }
  if(evs.length){
    h+='<div class="mapchips" role="group" aria-label="Event footprints"><span class="lbl">Event</span>'+
      '<select id="clEvtSel" aria-label="Modeled event footprint"><option value="">footprint off</option>'+
      evs.map(e=>'<option value="'+esc(e.id)+'"'+(st.eventId===e.id?" selected":"")+'>'+
        esc(e.id)+' · 1-in-'+Math.round(1/Math.max(e.freq,1e-6))+' · '+e.hits.length+' site'+(e.hits.length>1?'s':'')+' · '+fmt$(e.tot)+'</option>').join("")+
      '</select>'+infoBtn("mapEvents")+'</div>';
  }else if(st.eventId){st.eventId=null;clShowEvent(null);}
  host.innerHTML=h;
  host.querySelectorAll("[data-clperil]").forEach(b=>b.onclick=()=>{
    st.peril=b.dataset.clperil;_clHaz=null;clPersistMapState();
    clBuildHazard();clRenderCtl(c);
  });
  host.querySelectorAll("[data-clenc]").forEach(b=>b.onclick=()=>{
    st.enc=b.dataset.clenc;clPersistMapState();clApplyYear();clLegend();clRenderCtl(c);
  });
  const ac=document.getElementById("clAccum");
  if(ac)ac.onclick=()=>{st.accum=!st.accum;clPersistMapState();clApplyYear();clRenderCtl(c);};
  const ag=document.getElementById("clAgg");
  if(ag)ag.onclick=()=>{st.aggregate=!st.aggregate;_clSiteInfo=null;clPersistMapState();clBuildSites(c);clRenderCtl(c);clLegend();};
  const cm=document.getElementById("clCompare");
  if(cm)cm.onclick=()=>{st.compare=!st.compare;_clHaz=null;clPersistMapState();clBuildHazard();clRenderCtl(c);clLegend();};
  const op=document.getElementById("clOpacity");
  if(op)op.oninput=()=>{st.opacity=(+op.value)/100;clPersistMapState();clApplyYear();};
  const br=document.getElementById("clBrandSel");
  if(br)br.onchange=()=>{st.brand=br.value||"";_clSiteInfo=null;clPersistMapState();clBuildSites(c);clLegend();clAnnounceSummary();};
  const es=document.getElementById("clEvtSel");
  if(es)es.onchange=()=>{
    st.eventId=es.value||null;
    clShowEvent(st.eventId?evs.find(e=>e.id===st.eventId):null);
    clLegend(st.eventId?evs.find(e=>e.id===st.eventId):null);
  };
}
function clRenderScrub(){
  const bar=document.getElementById("cmdMapScrubBar");
  if(!bar)return;
  bar.style.display="";
  if(!bar._built){
    bar._built=true;
    const pw=cmdScenParts().pathway;
    const Y0=CMD_YEARS[0],Y1=CMD_YEARS[CMD_YEARS.length-1];
    bar.innerHTML='<div class="scrub-row">'+
      '<button type="button" class="scrub-play" id="clPlay" title="Play the pathway from present to 2080" aria-label="Play or pause the climate pathway">▶</button>'+
      '<span class="scrub-year" id="clYearLab">'+Y0+'</span>'+
      '<div style="flex:1;position:relative">'+
        '<input type="range" id="clScrub" min="'+Y0+'" max="'+Y1+'" step="1" value="'+Y0+'" aria-label="Climate pathway year">'+
        '<div class="scrub-ticks">'+CMD_YEARS.map((y,i)=>{
          /* every modeled point gets a dot; the 2030 label would collide
             with "Now" on narrow tracks, so it rides in the title */
          const lab=(i===1)?"":(y===Y0?"Now":String(y));
          return '<span class="tk" style="left:'+(((y-Y0)/(Y1-Y0))*100).toFixed(1)+'%" title="'+y+' · modeled horizon"><i></i>'+lab+'</span>';
        }).join("")+'</div>'+
      '</div>'+
      '<span class="scrub-state modeled" id="clStateLab">modeled</span>'+
      '<span class="scrub-pw" role="group" aria-label="Emissions pathway" id="clPwChips"></span>'+
      infoBtn("mapScrub")+
      '</div>';
    const sl=document.getElementById("clScrub");
    if(sl){
      sl.oninput=()=>{clStopPlay();clOnScrub(+sl.value);};
    }
    const pb=document.getElementById("clPlay");
    if(pb)pb.onclick=clPlayToggle;
  }
  const chips=document.getElementById("clPwChips");
  if(chips){
    const pw=cmdScenParts().pathway;
    chips.innerHTML=[["ssp126","1-2.6"],["ssp245","2-4.5"],["ssp585","5-8.5"]].map(([k,l])=>
      '<button type="button" class="mapchip" data-clpw="'+k+'" title="'+esc(PATHWAY_LABEL[k])+'" aria-pressed="'+(pw===k?"true":"false")+'">'+l+'</button>').join("");
    chips.querySelectorAll("[data-clpw]").forEach(b=>b.onclick=()=>clSetPathway(b.dataset.clpw));
  }
  clSyncScrubUI();
}
function clSyncScrubUI(){
  const y=Math.round(cmdMapState.year!=null?cmdMapState.year:yearOfScen(scenario));
  const yl=document.getElementById("clYearLab");if(yl)yl.textContent=y===CMD_YEARS[0]?"Now":String(y);
  const sl=document.getElementById("clScrub");if(sl&&!cmdMapState.playing&&+sl.value!==y)sl.value=y;
  const stl=document.getElementById("clStateLab");
  if(stl){
    const modeled=CMD_YEARS.indexOf(y)>=0;
    stl.textContent=modeled?(y===CMD_YEARS[0]?"present · modeled":y+" · modeled")
      :y+" · interpolated";
    stl.className="scrub-state "+(modeled?"modeled":"interp");
    stl.title=modeled?"This point is a modeled horizon: the engine computed it."
      :"A visual interpolation between the bracketing modeled horizons for the animation only; the headline and list show the nearest modeled point. No precision exists between modeled years.";
  }
}

/* ---- legend: physical units, basis, encoding key ---- */
function clLegend(ev){
  const lg=document.getElementById("cmdMapLegend");
  if(!lg)return;
  let h="";
  const P=MAP_PERIL_BY[cmdMapState.peril];
  if(P&&_clHaz&&_clHaz.peril===cmdMapState.peril){
    if(_clHaz.domain){
      const f0=_clHaz.fields.find(f=>!f.none);
      const basis=f0.basis==="grid"?"CLIMADA hazard grid ("+f0.cells+" cells)":"interim screening model";
      const partial=_clHaz.fields.some(f=>!f.none&&f.partialFrom);
      const ramp=perilRamp(cmdMapState.peril);
      h+='<div class="lh">'+esc(P.label)+' · '+esc(P.unit)+'</div>'+
        '<span class="lgd-ramp" style="background:'+rampCss(ramp)+'"></span>'+
        '<div class="lgd-minmax"><span>'+(+_clHaz.domain[0].toFixed(1))+'</span><span>'+(+_clHaz.domain[1].toFixed(_clHaz.domain[1]<2?2:(_clHaz.domain[1]<20?1:0)))+'+</span></div>'+
        '<div class="lgd-basis'+(f0.basis==="grid"?"":" est")+'">'+esc(basis)+
        (f0.basis==="grid"?"":" · exploration only, not disclosure")+
        (partial?" · missing horizons reuse the present-day grid (partial coverage, flagged)":"")+
        (cmdMapState.compare?" · compare: present held beside the scrubbed future":"")+'</div>';
    }else{
      const f=_clHaz.fields[0];
      h+='<div class="lh">'+esc(P.label)+'</div><div class="lgd-basis est">layer off: '+esc((f&&f.reason)||"no data")+'</div>';
    }
  }
  const encLab={tcor:"colour = TCOR intensity · area = TCOR",component:"colour = dominant component · area = TCOR",confidence:"colour = confidence · area = TCOR"};
  const nMark=_clSiteInfo?_clSiteInfo.nMarkers:0,nRec=_clSiteInfo?_clSiteInfo.nRecords:0;
  h+='<div class="lh" style="margin-top:6px">Sites</div><div class="lgd-basis">'+encLab[cmdMapState.enc]+
    (cmdMapState.aggregate&&nRec>nMark?" · "+nMark+" campus marker"+(nMark===1?"":"s")+" ("+nRec+" records)":"")+
    (cmdMapState.brand?" · brand filter: "+esc(cmdMapState.brand):"")+'</div>';
  if(cmdMapState.enc==="component"){
    h+=TCOR_COMPONENTS.map(cc=>'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:8px;font-size:10px;color:var(--ink-2)"><i style="width:8px;height:8px;border-radius:2px;background:'+cc.color+';display:inline-block"></i>'+esc(cc.label)+'</span>').join("");
  }else if(cmdMapState.enc==="confidence"){
    h+='<span style="font-size:10px;color:var(--ink-2)"><i style="width:8px;height:8px;border-radius:50%;background:'+cssTok("--seq-5","#20718B")+';display:inline-block;margin-right:4px"></i>complete data '+
      '<i style="width:8px;height:8px;border-radius:50%;background:#B07B10;display:inline-block;margin:0 4px 0 10px"></i>estimate</span>';
  }
  if(cmdMapState.accum)h+='<div class="lgd-basis" style="margin-top:4px">Accumulation: where TCOR concentrates geographically (kernel density, teal ramp)</div>';
  if(ev){
    h+='<div class="evt-card"><b>'+esc(ev.id)+'</b> · 1-in-'+Math.round(1/Math.max(ev.freq,1e-6))+' · '+fmt$(ev.tot)+' across <b>'+ev.hits.length+' site'+(ev.hits.length>1?"s":"")+'</b><br>one storm, one shared hurricane deductible per campus: the accumulation the shared-retention math prices.</div>';
  }
  lg.innerHTML=h;
}

function clBrushList(id,hoverOnly){
  const scroll=document.getElementById("cmdListScroll");
  if(!scroll)return;
  scroll.querySelectorAll("tr[data-sv]").forEach(tr=>{
    const on=+tr.dataset.sv===+id;
    tr.classList.toggle("map-hover",!!hoverOnly&&on);
    if(!hoverOnly)tr.classList.toggle("sel",on);
  });
  if(!hoverOnly&&id!=null){
    const tr=scroll.querySelector('tr[data-sv="'+id+'"]');
    if(tr&&typeof tr.scrollIntoView==="function")try{tr.scrollIntoView({block:"nearest",behavior:clPrefersReducedMotion()?"auto":"smooth"});}catch(e){}
  }
}
function clAnnounceSummary(){
  if(!_clSiteInfo)return;
  const P=MAP_PERIL_BY[cmdMapState.peril];
  const y=Math.round(cmdMapState.year!=null?cmdMapState.year:yearOfScen(scenario));
  const basis=_clHaz&&_clHaz.fields?(_clHaz.fields.find(f=>!f.none)||{}).basis:null;
  const msg=_clSiteInfo.nMarkers+" site marker"+(_clSiteInfo.nMarkers===1?"":"s")
    +" on the map"
    +(P?" · "+P.label+(basis==="grid"?" from the hazard grid":basis==="interim"?" from the interim screening field":" off"):"")
    +" · year "+(y===CMD_YEARS[0]?"present":y)
    +(cmdMapState.compare?" · compare on":"");
  clAnnounce(msg);
}
function clMapKeyNav(e){
  if(!_clMap||!_clReady)return;
  const pan=40;
  if(e.key==="ArrowLeft"){_clMap.panBy([-pan,0]);e.preventDefault();}
  else if(e.key==="ArrowRight"){_clMap.panBy([pan,0]);e.preventDefault();}
  else if(e.key==="ArrowUp"){_clMap.panBy([0,-pan]);e.preventDefault();}
  else if(e.key==="ArrowDown"){_clMap.panBy([0,pan]);e.preventDefault();}
  else if(e.key==="+"||e.key==="="){_clMap.zoomIn();e.preventDefault();}
  else if(e.key==="-"||e.key==="_"){_clMap.zoomOut();e.preventDefault();}
}

/* ---- entry point, called from renderCommand() every paint ----
   Returns true when the WebGL map owns the panel (or is still
   initializing); false lets the caller fall back to the SVG plot. */
function climateMapUpdate(c){
  if(_clFailed)return false;
  if(!clInit())return false;
  const attrib=document.getElementById("cmdMapAttrib");if(attrib)attrib.style.display="";
  const note=document.getElementById("cmdMapNote");if(note)note.style.display="none";
  if(!_clReady||!c)return true;   /* map is loading; chrome arrives on load */
  try{_clMap.resize();}catch(e){}
  /* year follows the global scenario unless the user is mid-scrub on
     the same snap (see clOnScrub); an external scenario change moves
     the thumb */
  const scenYear=yearOfScen(scenario);
  if(!cmdMapState.holdYear||CMD_YEARS[nearestYearIdx(cmdMapState.year!=null?cmdMapState.year:scenYear)]!==scenYear){
    cmdMapState.year=scenYear;cmdMapState.holdYear=false;
  }
  clBuildHazard();
  clBuildSites(c);
  clApplyYear();
  clRenderCtl(c);
  clRenderScrub();
  if(!cmdMapState.eventId)clShowEvent(null);
  try{_clMap.setFilter("clam-sel",["==",["get","id"],selectedId==null?-1:+selectedId]);}catch(e){}
  clBrushList(selectedId);
  return true;
}
function climateMapResize(){ if(_clMap&&_clReady){try{_clMap.resize();}catch(e){}} }
/* fly the map to one site (used by the site view's "view on map") */
function climateMapFocus(id){
  const s=sites.find(x=>x.id===id);
  if(!s||!_clMap||!_clReady)return;
  selectedId=id;
  try{_clMap.setFilter("clam-sel",["==",["get","id"],+id]);}catch(e){}
  clBrushList(id);
  cmdMapState.userMoved=true;
  const dur=clPrefersReducedMotion()?0:900;
  try{_clMap.flyTo({center:[+s.longitude,+s.latitude],zoom:7.5,duration:dur});}catch(e){}
}

/* ---- plain-language explanations for the map surfaces ---- */
Object.assign(INFO,{
  mapLayers:{t:"Hazard layers",b:
    "<p>Each layer draws CLAM's own modeled hazard as a continuous coloured surface with a physical-unit legend: 1-in-100 wind speed (m/s), 1-in-100 flood or surge depth (m), days over 32&deg;C, annual burn probability (%), 1-in-100 event rainfall (mm).</p>"+
    "<p><b>Where the surface comes from is stated in the legend.</b> With a CLIMADA hazard grid loaded, the map draws the grid's own cells, never a resampling. Without one, the app's documented interim screening field fills in and the legend says so (exploration only). Wildfire and TC rainfall have no interim spatial field by design, so those layers stay off until a grid supplies them, with the reason stated.</p>"+
    "<p><b>Compare</b> holds the present-day surface at half strength beside the scrubbed future so the pathway delta is visible without inventing a swipe control.</p>",
    s:"The same hazard engine every figure uses; the map adds no new science."},
  mapScrub:{t:"The climate pathway timeline",b:
    "<p>Drag the year, or press play, to watch the portfolio's hazard and TCOR migrate along the selected emissions pathway from present through 2030, 2050, and 2080. The hazard surfaces cross-fade between the bracketing modeled horizons and the site encoding interpolates continuously, so the eye sees the pathway rather than a hard cut.</p>"+
    "<p><b>Modeled vs interpolated, honestly:</b> the chip beside the year says which one you are on. Dots on the track mark the modeled horizons the engine actually computed; every position between them is a visual interpolation only, and the headline and decision list always show the nearest modeled point. No precision exists between modeled years, and none is implied.</p>"+
    "<p>Playback respects <code>prefers-reduced-motion</code>: when that preference is on, play jumps to 2080 instead of animating.</p>",
    s:"The timeline IS the global scenario control: scrubbing the map updates the headline and the list."},
  mapAccum:{t:"Accumulation",b:
    "<p>A concentration view of TCOR: kernel density weighted by each site's TCOR at the current point on the pathway, so geographic clustering of exposure is obvious at a glance. Where the teal deepens, one storm can reach several sites at once.</p>"+
    "<p><b>Campus</b> aggregates named-insured records that share a site into one marker (the legacy analyst behaviour). <b>Brand</b> filters the map to one collection without touching the decision list.</p>"+
    "<p>The event footprints (when a results pack is loaded) make the same point with real modeled events: one storm, these sites, one shared hurricane deductible per campus.</p>"},
  mapEvents:{t:"Event footprints",b:
    "<p>Pick a modeled event from the results pack's event table and the map draws which sites it hit, sized by each site's loss in that event, with the hull of the footprint outlined.</p>"+
    "<p>This is the shared-deductible and accumulation logic made visible: sites inside one footprint share ONE per-occurrence hurricane deductible per campus, which is why portfolio retained loss is computed per event, never per site.</p>",
    s:"Events come straight from the pack's event_sets table; nothing is re-derived."},
});
