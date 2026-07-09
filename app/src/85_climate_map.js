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

/* the map's peril layers: label, physical unit, and how the field is
   read. Grid-backed layers draw the loaded rows; interim layers call
   the app's own screening models; "none" states why a layer is off. */
const MAP_PERILS=[
  {key:"tc",    label:"Wind",       unit:"m/s · 1-in-100 wind speed",
   interim:(la,lo,sc)=>interimVector(la,lo,sc).vec[100]},
  {key:"cflood",label:"Surge",      unit:"m · 1-in-100 flood depth",
   interim:(la,lo,sc)=>coastalFloodVector(la,lo,sc)[100]},
  {key:"rflood",label:"River flood",unit:"m · 1-in-100 flood depth",
   interim:(la,lo,sc)=>riverineFloodVector(la,lo,sc)[100]},
  {key:"heat",  label:"Heat",       unit:"days over 32°C per year",
   interim:(la,lo,sc)=>heatIndicators(la,lo,sc).daysOver32},
  {key:"wfire", label:"Wildfire",   unit:"% annual burn probability",
   interim:null,offReason:"wildfire has no interim spatial field (burn probability is point data); load a wfire grid"},
  {key:"prain", label:"Rain",       unit:"mm · 1-in-100 event rainfall",
   interim:null,offReason:"TC rainfall has no interim model by design; load a prain grid"},
];
const MAP_PERIL_BY={};MAP_PERILS.forEach(p=>MAP_PERIL_BY[p.key]=p);

let cmdMapState={peril:"tc",opacity:0.7,enc:"tcor",accum:false,eventId:null,
  year:null,holdYear:false,playing:false,userMoved:false};
let _clMap=null,_clReady=false,_clFailed=false;
let _clHaz=null;        // {key,peril,domain,bases:[..],built:[bool x4]}
let _clSiteInfo=null;   // {key,maxT}
let _clFitKey="";
let _clTcorCache={};    // scenario -> tcorPortfolio rows total map
let _clTcorCacheKey=null;
let _clPlayT=null;
let _clThemeObs=null;

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

/* ---- hazard field for one peril at one modeled scenario ----
   Returns {features:[{lon,lat,v}], basis:"grid"|"interim",
   cells, partialFrom} or {none:true, reason}. */
function hazardField(hz,sc){
  const P=MAP_PERIL_BY[hz];
  if(gridByHazard[hz]&&hazardGrid&&hazardGrid.rows){
    let rows=hazardGrid.rows.filter(r=>(r.hazard||"tc")===hz&&r.scenario===sc);
    let partialFrom=null;
    if(!rows.length&&sc!=="present"){
      rows=hazardGrid.rows.filter(r=>(r.hazard||"tc")===hz&&r.scenario==="present");
      partialFrom="present";
    }
    if(rows.length){
      const feats=rows.map(r=>({lon:r.lon,lat:r.lat,
        v:Math.max(hz==="heat"?(+r.v10||0):(hz==="wfire"?(+r.v10||0):(+r.v100||0)),0)}));
      return {features:feats,basis:"grid",cells:rows.length,partialFrom};
    }
  }
  if(!P.interim)return {none:true,reason:P.offReason||"no data"};
  /* interim screening field on a coarse mesh over the basemap region */
  const b=(typeof CLAM_BASEMAP!=="undefined"&&CLAM_BASEMAP.bbox)||[-180,5,-50,55];
  const step=0.7,feats=[];
  for(let la=b[1]+step/2;la<b[3];la+=step)
    for(let lo=b[0]+step/2;lo<b[2];lo+=step){
      const v=Math.max(P.interim(la,lo,sc)||0,0);
      if(v>0)feats.push({lon:+lo.toFixed(2),lat:+la.toFixed(2),v});
    }
  return {features:feats,basis:"interim",cells:feats.length,partialFrom:null};
}
function fieldFC(field){
  return {type:"FeatureCollection",features:field.features.map(f=>({
    type:"Feature",geometry:{type:"Point",coordinates:[f.lon,f.lat]},
    properties:{v:f.v}}))};
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
        _clMap.addLayer({id:"clam-sites-l",type:"circle",source:"clam-sites",
          paint:{"circle-radius":6,"circle-color":cssTok("--seq-5","#20718B"),
                 "circle-stroke-color":cssTok("--surface","#fff"),"circle-stroke-width":1.5,
                 "circle-opacity":0.88}});
        _clMap.on("click","clam-sites-l",e=>{
          const f=e.features&&e.features[0];if(!f)return;
          const p=f.properties;
          selectedId=+p.id;
          try{_clMap.setFilter("clam-sel",["==",["get","id"],+p.id]);}catch(err){}
          const html='<div style="font-family:inherit;min-width:180px">'+
            '<b style="font-family:var(--font-display);font-size:14px;color:var(--heading)">'+esc(p.name)+'</b>'+
            '<div class="mono" style="font-size:11px;margin:3px 0">TCOR '+fmt$(+p.tcorNow)+'/yr'+(p.conf==="est"?' · <span style="color:var(--warn-ink)">estimate</span>':'')+'</div>'+
            '<div style="font-size:11px;color:var(--ink-2)">dominant: '+esc(p.domLabel)+'</div>'+
            '<button class="lightbtn primary" style="margin-top:6px;font-size:12px" onclick="openSiteView('+(+p.id)+')">Open site view</button></div>';
          new maplibregl.Popup({closeButton:true,maxWidth:"260px"}).setLngLat(e.lngLat).setHTML(html).addTo(_clMap);
        });
        _clMap.on("mouseenter","clam-sites-l",()=>{_clMap.getCanvas().style.cursor="pointer";});
        _clMap.on("mouseleave","clam-sites-l",()=>{_clMap.getCanvas().style.cursor="";});
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
  const key=clHazKey();
  if(_clHaz&&_clHaz.key===key)return;
  /* clear previous */
  for(let i=0;i<CMD_YEARS.length;i++){
    try{if(_clMap.getLayer("clam-haz-"+i))_clMap.removeLayer("clam-haz-"+i);}catch(e){}
    try{if(_clMap.getSource("clam-haz-"+i))_clMap.removeSource("clam-haz-"+i);}catch(e){}
  }
  _clHaz={key,peril:cmdMapState.peril,fields:[],domain:null};
  if(cmdMapState.peril==="none"){clLegend();return;}
  const pw=cmdScenParts().pathway;
  const fields=CMD_YEARS.map((y,i)=>hazardField(cmdMapState.peril,scenOfYearIdx(i,pw)));
  _clHaz.fields=fields;
  if(fields.every(f=>f.none)){clLegend();return;}
  /* one fixed domain across all horizons so the animation reads:
     2nd..98th percentile, zero-anchored */
  const vals=[];
  fields.forEach(f=>{if(!f.none)f.features.forEach(x=>vals.push(x.v));});
  vals.sort((a,b)=>a-b);
  const q=p=>vals.length?vals[Math.min(vals.length-1,Math.floor(p*vals.length))]:0;
  /* fields with a sparse high tail (surge hugging the coast) need the
     ramp anchored near the true top, not a global percentile that a
     sea of near-zeros drags down; p99.5 keeps one wild grid cell from
     stretching the ramp instead */
  let lo=0,hi=q(0.995);
  if(!(hi>0))hi=1;
  _clHaz.domain=[lo,hi];
  const ramp=perilRamp(cmdMapState.peril);
  const colorExpr=["interpolate",["linear"],["get","v"],
    lo,ramp[0], lo+(hi-lo)*0.33,ramp[1], lo+(hi-lo)*0.66,ramp[2], hi,ramp[3]];
  fields.forEach((f,i)=>{
    if(f.none)return;
    try{
      _clMap.addSource("clam-haz-"+i,{type:"geojson",data:fieldFC(f)});
      _clMap.addLayer({id:"clam-haz-"+i,type:"circle",source:"clam-haz-"+i,
        paint:{
          "circle-radius":["interpolate",["exponential",1.9],["zoom"],2,3.6,4,8.5,6,26,9,100],
          "circle-blur":0.85,
          "circle-color":colorExpr,
          "circle-opacity":0}},"clam-accum");
    }catch(e){}
  });
  clApplyYear();
  clLegend();
}
function clRestyleData(){
  /* theme change: rebuild colour expressions with the new tokens */
  if(!_clMap||!_clReady||!_clHaz)return;
  if(_clHaz.domain){
    const [lo,hi]=_clHaz.domain,ramp=perilRamp(_clHaz.peril);
    const colorExpr=["interpolate",["linear"],["get","v"],
      lo,ramp[0], lo+(hi-lo)*0.33,ramp[1], lo+(hi-lo)*0.66,ramp[2], hi,ramp[3]];
    for(let i=0;i<CMD_YEARS.length;i++){
      try{if(_clMap.getLayer("clam-haz-"+i))_clMap.setPaintProperty("clam-haz-"+i,"circle-color",colorExpr);}catch(e){}
    }
  }
  try{_clMap.setPaintProperty("clam-sel","circle-stroke-color",cssTok("--focus","#1E7FA6"));}catch(e){}
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
function clBuildSites(c){
  if(!_clMap||!_clReady||!c)return;
  const pw=cmdScenParts().pathway;
  const key=cmdStateKey()+"|"+pw+"|"+scenario;
  if(_clSiteInfo&&_clSiteInfo.key===key)return;
  const perScen=CMD_YEARS.map((y,i)=>clTcorTotals(scenOfYearIdx(i,pw)));
  let maxT=0;
  const feats=c.rows.map(r=>{
    const t=perScen.map(m=>m[r.id]||0);
    t.forEach(v=>{if(v>maxT)maxT=v;});
    return {type:"Feature",geometry:{type:"Point",coordinates:[r.lon,r.lat]},
      properties:{id:r.id,name:r.name,
        t0:t[0],t1:t[1],t2:t[2],t3:t[3],
        tcorNow:r.total,dom:r.domComp,domLabel:TCOR_COMP_BY[r.domComp].label,
        conf:r.estimate?"est":"ok"}};
  });
  _clSiteInfo={key,maxT:maxT||1};
  try{_clMap.getSource("clam-sites").setData({type:"FeatureCollection",features:feats});}catch(e){}
  try{_clMap.setFilter("clam-sel",["==",["get","id"],selectedId==null?-1:+selectedId]);}catch(e){}
  /* frame the portfolio once per site-set; never fight the user's hand */
  const fit=c.rows.map(r=>r.id).sort().join(",");
  if(fit!==_clFitKey&&!cmdMapState.userMoved&&c.rows.length){
    _clFitKey=fit;
    let lo0=Infinity,la0=Infinity,lo1=-Infinity,la1=-Infinity;
    c.rows.forEach(r=>{lo0=Math.min(lo0,r.lon);la0=Math.min(la0,r.lat);lo1=Math.max(lo1,r.lon);la1=Math.max(la1,r.lat);});
    try{_clMap.fitBounds([[lo0,la0],[lo1,la1]],{padding:70,maxZoom:6,duration:600});}catch(e){}
  }
  clApplyYear();
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
  /* hazard cross-fade: exact at modeled points */
  for(let k=0;k<CMD_YEARS.length;k++){
    let op=0;
    if(k===i)op=(1-f)*cmdMapState.opacity;
    else if(k===i+1)op=f*cmdMapState.opacity;
    try{if(_clMap.getLayer("clam-haz-"+k))_clMap.setPaintProperty("clam-haz-"+k,"circle-opacity",op);}catch(e){}
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
    infoBtn("mapAccum")+
    '</div>';
  if(evs.length){
    h+='<div class="mapchips" role="group" aria-label="Event footprints"><span class="lbl">Event</span>'+
      '<select id="clEvtSel" aria-label="Modeled event footprint"><option value="">footprint off</option>'+
      evs.map(e=>'<option value="'+esc(e.id)+'"'+(st.eventId===e.id?" selected":"")+'>'+
        esc(e.id)+' · 1-in-'+Math.round(1/Math.max(e.freq,1e-6))+' · '+e.hits.length+' site'+(e.hits.length>1?'s':'')+' · '+fmt$(e.tot)+'</option>').join("")+
      '</select>'+infoBtn("mapEvents")+'</div>';
  }else if(st.eventId){st.eventId=null;clShowEvent(null);}
  host.innerHTML=h;
  host.querySelectorAll("[data-clperil]").forEach(b=>b.onclick=()=>{
    st.peril=b.dataset.clperil;_clHaz=null;
    clBuildHazard();clRenderCtl(c);
  });
  host.querySelectorAll("[data-clenc]").forEach(b=>b.onclick=()=>{
    st.enc=b.dataset.clenc;clApplyYear();clLegend();clRenderCtl(c);
  });
  const ac=document.getElementById("clAccum");
  if(ac)ac.onclick=()=>{st.accum=!st.accum;clApplyYear();clRenderCtl(c);};
  const op=document.getElementById("clOpacity");
  if(op)op.oninput=()=>{st.opacity=(+op.value)/100;clApplyYear();};
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
        (partial?" · missing horizons reuse the present-day grid (partial coverage, flagged)":"")+'</div>';
    }else{
      const f=_clHaz.fields[0];
      h+='<div class="lh">'+esc(P.label)+'</div><div class="lgd-basis est">layer off: '+esc((f&&f.reason)||"no data")+'</div>';
    }
  }
  const encLab={tcor:"colour = TCOR intensity · area = TCOR",component:"colour = dominant component · area = TCOR",confidence:"colour = confidence · area = TCOR"};
  h+='<div class="lh" style="margin-top:6px">Sites</div><div class="lgd-basis">'+encLab[cmdMapState.enc]+'</div>';
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
  return true;
}
function climateMapResize(){ if(_clMap&&_clReady){try{_clMap.resize();}catch(e){}} }
/* fly the map to one site (used by the site view's "view on map") */
function climateMapFocus(id){
  const s=sites.find(x=>x.id===id);
  if(!s||!_clMap||!_clReady)return;
  selectedId=id;
  try{_clMap.setFilter("clam-sel",["==",["get","id"],+id]);}catch(e){}
  cmdMapState.userMoved=true;
  try{_clMap.flyTo({center:[+s.longitude,+s.latitude],zoom:7.5,duration:900});}catch(e){}
}

/* ---- plain-language explanations for the map surfaces ---- */
Object.assign(INFO,{
  mapLayers:{t:"Hazard layers",b:
    "<p>Each layer draws CLAM's own modeled hazard as a continuous coloured surface with a physical-unit legend: 1-in-100 wind speed (m/s), 1-in-100 flood or surge depth (m), days over 32&deg;C, annual burn probability (%), 1-in-100 event rainfall (mm).</p>"+
    "<p><b>Where the surface comes from is stated in the legend.</b> With a CLIMADA hazard grid loaded, the map draws the grid's own cells, never a resampling. Without one, the app's documented interim screening field fills in and the legend says so (exploration only). Wildfire and TC rainfall have no interim spatial field by design, so those layers stay off until a grid supplies them, with the reason stated.</p>",
    s:"The same hazard engine every figure uses; the map adds no new science."},
  mapScrub:{t:"The climate pathway timeline",b:
    "<p>Drag the year, or press play, to watch the portfolio's hazard and TCOR migrate along the selected emissions pathway from present through 2030, 2050, and 2080. The hazard surfaces cross-fade between the bracketing modeled horizons and the site encoding interpolates continuously, so the eye sees the pathway rather than a hard cut.</p>"+
    "<p><b>Modeled vs interpolated, honestly:</b> the chip beside the year says which one you are on. Dots on the track mark the modeled horizons the engine actually computed; every position between them is a visual interpolation only, and the headline and decision list always show the nearest modeled point. No precision exists between modeled years, and none is implied.</p>",
    s:"The timeline IS the global scenario control: scrubbing the map updates the headline and the list."},
  mapAccum:{t:"Accumulation",b:
    "<p>A concentration view of TCOR: kernel density weighted by each site's TCOR at the current point on the pathway, so geographic clustering of exposure is obvious at a glance. Where the teal deepens, one storm can reach several sites at once.</p>"+
    "<p>The event footprints (when a results pack is loaded) make the same point with real modeled events: one storm, these sites, one shared hurricane deductible per campus.</p>"},
  mapEvents:{t:"Event footprints",b:
    "<p>Pick a modeled event from the results pack's event table and the map draws which sites it hit, sized by each site's loss in that event, with the hull of the footprint outlined.</p>"+
    "<p>This is the shared-deductible and accumulation logic made visible: sites inside one footprint share ONE per-occurrence hurricane deductible per campus, which is why portfolio retained loss is computed per event, never per site.</p>",
    s:"Events come straight from the pack's event_sets table; nothing is re-derived."},
});
