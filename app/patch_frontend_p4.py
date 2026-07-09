"""
patch_frontend_p4.py : applies the Phase 4 (provenance and trust surface)
edits to the v1.6 app, producing v1.7.

What Phase 4 does in the app, in one paragraph: the pipeline already writes a
provenance sidecar (hazard_grid_meta.json) that nothing consumed. Now the
hazard drop zone accepts it (alone, or dragged together with the CSV, in any
order), the app persists it, and three surfaces render it: the top-bar badge
becomes per-peril ("CLIMADA x n/4 perils", run date on hover), the Method
tab's Hazard source panel shows chips per peril (green = grid-fed with full
scenario coverage, amber = grid-fed but partial coverage so missing horizons
fall back to present, gray = interim) plus the run record (date, CLIMADA and
Petals versions, track count, DEM, heat method, skipped layers), and the
hazNote narrows the disclosure caveat peril by peril instead of app-wide.

Eleven exact-match edits; any miss aborts with no output written.

Usage:  python patch_frontend_p4.py Resort_Climate_Risk_Explorer_v16.html \
                                    Resort_Climate_Risk_Explorer_v17.html
"""

import sys

EDITS = [

# 1 -- drop zone markup: two files, one zone -----------------------------------
("""        <div id="hazDrop" class="drop" style="margin-top:14px">
          <div class="big">Load CLIMADA hazard grid</div>
          <small>Drop <span class="mono">hazard_grid.csv</span> from refresh_hazard.py, or click to browse. Schema: <span class="mono">lat, lon, scenario, hazard, v10..v500</span></small>
        </div>
        <input type="file" id="hazFile" accept=".csv" hidden>""",
 """        <div id="hazDrop" class="drop" style="margin-top:14px">
          <div class="big">Load CLIMADA hazard grid + provenance</div>
          <small>Drop <span class="mono">hazard_grid.csv</span> and <span class="mono">hazard_grid_meta.json</span> from the pipeline, together or one at a time, or click to browse. Grid schema: <span class="mono">lat, lon, scenario, hazard, v10..v500</span></small>
        </div>
        <input type="file" id="hazFile" accept=".csv,.json" multiple hidden>"""),

# 2 -- badge info popover mentions the sidecar --------------------------------
("""    "<p>Drop a <b>CLIMADA hazard grid</b> on the Method tab to replace any peril with authoritative values. Perils not in the grid stay on the interim model. The badge in the top bar shows which source is live.</p>"},""",
 """    "<p>Drop a <b>CLIMADA hazard grid</b> on the Method tab to replace any peril with authoritative values. Perils not in the grid stay on the interim model. The badge in the top bar shows which source is live, per peril.</p>"+
    "<p>The pipeline also writes <code>hazard_grid_meta.json</code>. Drop it on the same zone to attach the run record (date, CLIMADA and Petals versions, datasets matched, DEM, anything skipped) to the badge and the Method tab.</p>"},"""),

# 3 -- state: hazardMeta global (also removes a legacy em dash comment) -------
("""let hazardGrid=null;       // {rows, meta} \u2014 badge/provenance for a loaded grid""",
 """let hazardGrid=null;       // {rows, meta}: the loaded grid and its summary
let hazardMeta=null;       // provenance sidecar (hazard_grid_meta.json), optional"""),

# 4 -- renderHazProv: full replacement -----------------------------------------
("""function renderHazProv(){
  const badge=document.getElementById("hazBadge"),text=document.getElementById("hazText");
  if(hazardGrid){
    badge.classList.add("authoritative");text.textContent="CLIMADA grid";
    document.getElementById("hazProv").innerHTML=
      '<span class="k">Source</span><span class="v">CLIMADA hazard grid (loaded)</span>'+
      '<span class="k">File</span><span class="v mono">'+esc(hazardGrid.meta.name)+'</span>'+
      '<span class="k">Grid cells</span><span class="v mono">'+hazardGrid.meta.cells+'</span>'+
      '<span class="k">Perils</span><span class="v mono">'+((hazardGrid.meta.hazards||["tc"]).join(", "))+'</span>'+
      '<span class="k">Scenarios</span><span class="v mono">'+hazardGrid.meta.scenarios.join(", ")+'</span>'+
      '<span class="k">Loaded</span><span class="v mono">'+hazardGrid.meta.loaded+'</span>';
    document.getElementById("hazNote").textContent="Authoritative hazard is active for the perils in the grid. Any peril without grid cells still uses the interim model. Each site snaps to the nearest cell for the selected peril and scenario.";
  }else{
    badge.classList.remove("authoritative");text.textContent="Interim model";
    document.getElementById("hazProv").innerHTML=
      '<span class="k">Source</span><span class="v">Built-in interim model</span>'+
      '<span class="k">Perils</span><span class="v">Wind, coastal flood, riverine flood, extreme heat</span>'+
      '<span class="k">Basis</span><span class="v">Regional wind anchors, coast-distance flood proxies, latitude-and-continentality heat</span>'+
      '<span class="k">Status</span><span class="v">Exploration only, not for disclosure</span>';
  }
}""",
 """/* Phase 4: per-peril authority. Which perils are grid-fed, with how many
   cells, and whether every app scenario is covered (partial coverage means
   the app silently serves that peril's PRESENT grid for missing horizons,
   which is exactly the failure the v1 deployment shipped with: so it is
   surfaced, not hidden). Tolerates grids persisted before perHaz existed by
   recomputing from the rows. */
function perilAuthority(){
  let ph=(hazardGrid&&hazardGrid.meta&&hazardGrid.meta.perHaz)||null;
  if(!ph&&hazardGrid&&hazardGrid.rows){
    ph={};hazardGrid.rows.forEach(r=>{const h=r.hazard||"tc";
      const e=ph[h]||(ph[h]={cells:0,scenarios:[]});e.cells++;
      if(e.scenarios.indexOf(r.scenario)<0)e.scenarios.push(r.scenario);});
  }
  return HAZARDS.map(h=>{
    const live=!!gridByHazard[h.key], info=ph&&ph[h.key];
    return {key:h.key,label:h.label,short:h.short,live,
      cells:info?info.cells:0,nScen:info?info.scenarios.length:0,
      full:info?info.scenarios.length>=SCEN_KEYS.length:false};
  });
}
function metaSources(m){ return m?((m.sources&&m.sources.length)?m.sources:[m]):[]; }
function metaSourceLine(s){
  const bits=[];
  if(s.script)bits.push(esc(String(s.script).split(" ")[0]));
  if(s.generated_utc)bits.push("run "+esc(String(s.generated_utc).slice(0,10)));
  if(s.climada_version)bits.push("climada "+esc(s.climada_version)+(s.climada_petals_version?" + petals "+esc(s.climada_petals_version):""));
  if(s.nb_synth_tracks)bits.push(esc(s.nb_synth_tracks)+" synth tracks");
  if(s.surge&&s.surge.dem_path)bits.push("DEM "+esc(String(s.surge.dem_path).split(/[\\/\\\\]/).pop()));
  if(s.method)bits.push(esc(s.method));
  if(s.years&&s.years.length)bits.push("climatology "+esc(s.years[0])+"-"+esc(s.years[s.years.length-1]));
  return bits.join(" \\u00b7 ");
}
function renderHazProv(){
  const badge=document.getElementById("hazBadge"),text=document.getElementById("hazText");
  const auth=perilAuthority();
  const chip=a=>'<span class="pill mini" title="'+esc(a.label+": "+(a.live?("CLIMADA grid, "+a.cells+" cells, "+a.nScen+"/"+SCEN_KEYS.length+" scenarios"):"interim model"))+'" style="background:'+(a.live?(a.full?"var(--r-low)":"var(--r-mod)"):"var(--r-min)")+'">'+a.short+'</span>';
  const chips=auth.map(chip).join("");
  const md=hazardMeta&&hazardMeta.data;
  if(hazardGrid){
    const nLive=auth.filter(a=>a.live).length;
    const liveL=auth.filter(a=>a.live).map(a=>a.label.toLowerCase());
    const interimL=auth.filter(a=>!a.live).map(a=>a.label.toLowerCase());
    const partial=auth.filter(a=>a.live&&!a.full);
    badge.classList.add("authoritative");
    text.textContent="CLIMADA \\u00b7 "+nLive+"/"+HAZARDS.length+" perils";
    badge.title=md&&md.generated_utc?("Pipeline run "+String(md.generated_utc).slice(0,10)):"Per-peril detail on the Method tab";
    let kv=
      '<span class="k">Perils</span><span class="v">'+chips+(partial.length?' <small>amber: partial scenario coverage, missing horizons fall back to that peril\\u2019s present grid</small>':'')+'</span>'+
      '<span class="k">File</span><span class="v mono">'+esc(hazardGrid.meta.name)+'</span>'+
      '<span class="k">Grid cells</span><span class="v mono">'+hazardGrid.meta.cells+'</span>'+
      '<span class="k">Scenarios</span><span class="v mono">'+hazardGrid.meta.scenarios.length+' keys</span>'+
      '<span class="k">Loaded</span><span class="v mono">'+hazardGrid.meta.loaded+'</span>';
    if(md){
      metaSources(md).forEach((s,i)=>{const line=metaSourceLine(s);
        if(line)kv+='<span class="k">'+(i===0?"Pipeline":"")+'</span><span class="v">'+line+'</span>';});
      const skipped=(md.skipped||[]).length;
      if(skipped)kv+='<span class="k">Skipped</span><span class="v">'+skipped+' layer'+(skipped>1?"s":"")+' in the last run fell back to interim (details in the meta file)</span>';
      kv+='<span class="k">Meta file</span><span class="v mono">'+esc(hazardMeta.name)+' \\u00b7 '+hazardMeta.loaded+'</span>';
    }else{
      kv+='<span class="k">Provenance</span><span class="v">Drop <span class="mono">hazard_grid_meta.json</span> here too to attach the run record: date, CLIMADA versions, datasets matched, DEM.</span>';
    }
    document.getElementById("hazProv").innerHTML=kv;
    document.getElementById("hazNote").textContent=
      "CLIMADA hazard is live for "+liveL.join(", ")+"."+
      (interimL.length?" Still on the interim model: "+interimL.join(", ")+".":"")+
      (partial.length?" Partial scenario coverage on "+partial.map(a=>a.label.toLowerCase()).join(", ")+": missing horizons use that peril's present grid.":"")+
      (md&&md.generated_utc?" Pipeline run "+String(md.generated_utc).slice(0,10)+".":"")+
      " Each site snaps to the nearest cell within 200 km; beyond that, the interim model takes over.";
  }else{
    badge.classList.remove("authoritative");text.textContent="Interim model";badge.title="";
    document.getElementById("hazProv").innerHTML=
      '<span class="k">Perils</span><span class="v">'+chips+' <small>all on the interim model until a grid is loaded</small></span>'+
      '<span class="k">Source</span><span class="v">Built-in interim model</span>'+
      '<span class="k">Basis</span><span class="v">Regional wind anchors, coast-distance flood proxies, latitude-and-continentality heat</span>'+
      '<span class="k">Status</span><span class="v">Exploration only, not for disclosure</span>';
  }
}"""),

# 5 -- loadHazardCsv: per-hazard bookkeeping (three small anchors) --------------
("""  const rows=[];const scens=new Set();const hazSet=new Set();""",
 """  const rows=[];const scens=new Set();const hazSet=new Set();const perHaz={};"""),

("""    rows.push(r);scens.add(r.scenario);hazSet.add(hazard);""",
 """    rows.push(r);scens.add(r.scenario);hazSet.add(hazard);
    const ph=perHaz[hazard]||(perHaz[hazard]={cells:0,scen:{}});ph.cells++;ph.scen[r.scenario]=1;"""),

("""  hazardGrid={rows,meta:{name:name||"hazard_grid.csv",cells:rows.length,scenarios:[...scens],hazards:[...hazSet],loaded:new Date().toISOString().slice(0,16).replace("T"," ")}};""",
 """  const perHazOut={};Object.keys(perHaz).forEach(k=>perHazOut[k]={cells:perHaz[k].cells,scenarios:Object.keys(perHaz[k].scen)});
  hazardGrid={rows,meta:{name:name||"hazard_grid.csv",cells:rows.length,scenarios:[...scens],hazards:[...hazSet],perHaz:perHazOut,loaded:new Date().toISOString().slice(0,16).replace("T"," ")}};"""),

# 6 -- loadHazardMeta, inserted before readFile ---------------------------------
("""function readFile(file,cb){""",
 """function loadHazardMeta(text,name){
  let data=null;
  try{ data=JSON.parse(text); }catch(e){ toast("Could not parse the provenance JSON."); return; }
  if(!data||typeof data!=="object"||!(data.layers||data.sources||data.generated_utc)){
    toast("That JSON does not look like a hazard_grid_meta file."); return;
  }
  hazardMeta={data,name:name||"hazard_grid_meta.json",loaded:new Date().toISOString().slice(0,16).replace("T"," ")};
  persistMeta();
  const n=metaSources(data).length;
  toast("Provenance attached ("+n+" pipeline record"+(n>1?"s":"")+")");
  render();
}
function readFile(file,cb){"""),

# 7 -- persistence: new key + persistMeta ---------------------------------------
("""const LS_STATE="rtv_state_v1", LS_HAZ="rtv_hazard_v1";""",
 """const LS_STATE="rtv_state_v1", LS_HAZ="rtv_hazard_v1", LS_META="rtv_hazmeta_v1";"""),

("""function persistHazard(){ try{ localStorage.setItem(LS_HAZ,JSON.stringify(hazardGrid)); }catch(e){ /* grid too large to cache: fine, keeps working in-session */ } }""",
 """function persistHazard(){ try{ localStorage.setItem(LS_HAZ,JSON.stringify(hazardGrid)); }catch(e){ /* grid too large to cache: fine, keeps working in-session */ } }
function persistMeta(){ try{ localStorage.setItem(LS_META,JSON.stringify(hazardMeta)); }catch(e){} }"""),

# 8 -- restore the sidecar with the grid ------------------------------------------
("""    const h=JSON.parse(localStorage.getItem(LS_HAZ)||"null");
    if(h&&h.rows&&h.rows.length){ hazardGrid=h; buildGridsFromRows(h.rows); }""",
 """    const h=JSON.parse(localStorage.getItem(LS_HAZ)||"null");
    if(h&&h.rows&&h.rows.length){ hazardGrid=h; buildGridsFromRows(h.rows); }
    const hm=JSON.parse(localStorage.getItem(LS_META)||"null");
    if(hm&&hm.data)hazardMeta=hm;"""),

# 9 -- hazard drop wiring: route CSV vs JSON, allow several files at once ---------
("""  const hd=document.getElementById("hazDrop"),hf=document.getElementById("hazFile");
  hd.onclick=()=>hf.click();hf.onchange=()=>{if(hf.files[0])readFile(hf.files[0],t=>loadHazardCsv(t,hf.files[0].name));};
  dropZone(hd,f=>readFile(f,t=>loadHazardCsv(t,f.name)));""",
 """  const hd=document.getElementById("hazDrop"),hf=document.getElementById("hazFile");
  const routeHaz=f=>readFile(f,t=>{ if(/\\.json$/i.test(f.name||"")||/^\\s*\\{/.test(t)) loadHazardMeta(t,f.name); else loadHazardCsv(t,f.name); });
  hd.onclick=()=>hf.click();
  hf.onchange=()=>{ for(const f of hf.files) routeHaz(f); hf.value=""; };
  dropZone(hd,routeHaz);"""),

# 10 -- dropZone handles multi-file drops (per-file callback, as before for one) ---
("""  el.addEventListener("drop",e=>{e.preventDefault();el.classList.remove("over");if(e.dataTransfer.files[0])cb(e.dataTransfer.files[0]);});""",
 """  el.addEventListener("drop",e=>{e.preventDefault();el.classList.remove("over");for(const f of e.dataTransfer.files)cb(f);});"""),

# 11 -- version string ---------------------------------------------------------------
("""v1.6 petals data layers""",
 """v1.7 provenance"""),
]


def main(src_path, dst_path) -> int:
    html = open(src_path, encoding="utf-8").read()
    for i, (old, new) in enumerate(EDITS, 1):
        n = html.count(old)
        if n != 1:
            print(f"ABORT: edit {i} matched {n} times (need exactly 1). "
                  f"The app source has drifted; refresh the anchors.")
            return 1
        html = html.replace(old, new)
        print(f"applied edit {i}")
    open(dst_path, "w", encoding="utf-8").write(html)
    print(f"wrote {dst_path}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python patch_frontend_p4.py <v16.html> <v17.html>")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
