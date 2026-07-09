"""
patch_frontend_p5.py : applies the Phase 5 (results pack) edits to the v1.7
app, producing v1.8.

What v1.8 adds, in one paragraph: the pipeline's refresh_impacts.py writes
results_pack.json, the CLIMADA-native portfolio figures (event-set loss
exceedance, per-site expected annual damage, direct-damage adaptation
appraisal, Monte Carlo bands) that the browser's live model can only
approximate. The hazard drop zone now accepts that file too (it sniffs the
JSON kind, so the provenance sidecar and the pack can be dropped together in
any order), persists it like the grid, and renders a "CLIMADA results pack"
panel on the Method tab showing the pack's figures for the currently selected
scenario NEXT TO the live model's equivalents, never replacing them: the live
model stays interactive and holds the financial layer (business interruption,
chronic heat, insurance), while the pack anchors the direct-damage numbers to
the full event sets.

Eight exact-match edits; any miss aborts with no output written.

Usage:  python patch_frontend_p5.py Resort_Climate_Risk_Explorer_v17.html \
                                    Resort_Climate_Risk_Explorer_v18.html
"""

import sys

EDITS = [

# 1 -- drop zone copy + the pack panel container --------------------------------
("""          <small>Drop <span class="mono">hazard_grid.csv</span> and <span class="mono">hazard_grid_meta.json</span> from the pipeline, together or one at a time, or click to browse. Grid schema: <span class="mono">lat, lon, scenario, hazard, v10..v500</span></small>
        </div>
        <input type="file" id="hazFile" accept=".csv,.json" multiple hidden>""",
 """          <small>Drop <span class="mono">hazard_grid.csv</span>, <span class="mono">hazard_grid_meta.json</span>, and <span class="mono">results_pack.json</span> from the pipeline, together or one at a time, or click to browse. Grid schema: <span class="mono">lat, lon, scenario, hazard, v10..v500</span></small>
        </div>
        <input type="file" id="hazFile" accept=".csv,.json" multiple hidden>
        <div id="packPanel" style="margin-top:14px"></div>"""),

# 2 -- state: the pack global ------------------------------------------------------
("""let hazardMeta=null;       // provenance sidecar (hazard_grid_meta.json), optional""",
 """let hazardMeta=null;       // provenance sidecar (hazard_grid_meta.json), optional
let resultsPack=null;      // CLIMADA results pack (results_pack.json), optional"""),

# 3 -- renderResultsPack, appended right after renderHazProv ------------------------
("""      '<span class="k">Status</span><span class="v">Exploration only, not for disclosure</span>';
  }
}""",
 """      '<span class="k">Status</span><span class="v">Exploration only, not for disclosure</span>';
  }
}
/* Phase 5: the results pack panel. Shows the pipeline's event-set figures
   for the selected scenario BESIDE the live model's equivalents. The pack is
   direct damage only; business interruption, chronic heat, and insurance
   stay in this app's live model, which is why both columns exist. */
function renderResultsPack(){
  const el=document.getElementById("packPanel"); if(!el)return;
  const pk=resultsPack&&resultsPack.data;
  if(!pk||!pk.scenarios){ el.innerHTML=""; return; }
  const sc=pk.scenarios[scenario]?scenario:"present";
  const s=pk.scenarios[sc]; if(!s){ el.innerHTML=""; return; }
  const p=s.portfolio, ep=p.ep_usd||{};
  const live=sites.length?finPortfolio(sites,sc):null;
  const unc=(pk.uncertainty||{})[sc], band=unc&&unc.acute_aal_usd;
  const scLabel=sc==="present"?"Present day":sc.replace("_"," \\u00b7 ");
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
    row("Loss exceedance",RPS.map(rp=>rp+"y "+fmt$(+ep[String(rp)]||0)).join(" \\u00b7 "))+
    row("By peril",["tc","cflood","rflood"].map(z=>z+" "+fmt$((p.by_peril_aal_usd||{})[z]||0)).join(" \\u00b7 "))+
    (band?row("Uncertainty",fmt$(band.p5)+" .. "+fmt$(band.p95)+" (p5..p95, AAL)"):"")+
    (pk.calibration?row("Calibration","v_half "+esc(pk.calibration.fitted_v_half)+
        " (model/observed bias "+esc(pk.calibration.portfolio_bias)+")"):"")+
    row("Provenance",esc(String(pk.script||"refresh_impacts.py").split(" ")[0])+
        " \\u00b7 run "+esc(String(pk.generated_utc||"").slice(0,10))+
        " \\u00b7 "+esc((pk.sites&&pk.sites.count)||"?")+" sites \\u00b7 file "+esc(resultsPack.name))+
    '</div>'+
    '<small>Pack figures are DIRECT damage from the full CLIMADA event sets '+
    '(per-event losses summed across sites before the exceedance curve, so the '+
    'portfolio tail is joint, not an upper bound). Business interruption, '+
    'chronic heat, and insurance layering remain in this app\\u2019s live model.</small></div>';
  el.innerHTML=h;
}"""),

# 4 -- loadResultsPack + the JSON dispatcher, before readFile ------------------------
("""function readFile(file,cb){""",
 """function loadResultsPack(text,name){
  let data=null;
  try{ data=JSON.parse(text); }catch(e){ toast("Could not parse the results pack JSON."); return; }
  if(!data||data.kind!=="results_pack"||data.pack_version!==1||!data.scenarios){
    toast("That JSON does not look like a results_pack file."); return;
  }
  resultsPack={data,name:name||"results_pack.json",loaded:new Date().toISOString().slice(0,16).replace("T"," ")};
  persistPack();
  toast("Results pack attached ("+Object.keys(data.scenarios).length+" scenario"+(Object.keys(data.scenarios).length>1?"s":"")+")");
  render();
}
/* one JSON drop zone, two JSON artifacts: sniff the pack marker, else treat
   the file as the provenance sidecar (whose own shape check still applies) */
function routeHazJson(text,name){
  let peek=null; try{ peek=JSON.parse(text); }catch(e){}
  if(peek&&peek.kind==="results_pack") loadResultsPack(text,name);
  else loadHazardMeta(text,name);
}
function readFile(file,cb){"""),

# 5 -- the drop wiring routes JSON through the dispatcher ----------------------------
("""  const routeHaz=f=>readFile(f,t=>{ if(/\\.json$/i.test(f.name||"")||/^\\s*\\{/.test(t)) loadHazardMeta(t,f.name); else loadHazardCsv(t,f.name); });""",
 """  const routeHaz=f=>readFile(f,t=>{ if(/\\.json$/i.test(f.name||"")||/^\\s*\\{/.test(t)) routeHazJson(t,f.name); else loadHazardCsv(t,f.name); });"""),

# 6a -- persistence: new key ----------------------------------------------------------
("""const LS_STATE="rtv_state_v1", LS_HAZ="rtv_hazard_v1", LS_META="rtv_hazmeta_v1";""",
 """const LS_STATE="rtv_state_v1", LS_HAZ="rtv_hazard_v1", LS_META="rtv_hazmeta_v1", LS_PACK="rtv_respack_v1";"""),

# 6b -- persistPack beside persistMeta -------------------------------------------------
("""function persistMeta(){ try{ localStorage.setItem(LS_META,JSON.stringify(hazardMeta)); }catch(e){} }""",
 """function persistMeta(){ try{ localStorage.setItem(LS_META,JSON.stringify(hazardMeta)); }catch(e){} }
function persistPack(){ try{ localStorage.setItem(LS_PACK,JSON.stringify(resultsPack)); }catch(e){} }"""),

# 6c -- restore the pack with the rest ---------------------------------------------------
("""    const hm=JSON.parse(localStorage.getItem(LS_META)||"null");
    if(hm&&hm.data)hazardMeta=hm;""",
 """    const hm=JSON.parse(localStorage.getItem(LS_META)||"null");
    if(hm&&hm.data)hazardMeta=hm;
    const rpk=JSON.parse(localStorage.getItem(LS_PACK)||"null");
    if(rpk&&rpk.data)resultsPack=rpk;"""),

# 7 -- render() fan-out -----------------------------------------------------------------
("""  renderBacktest();
  renderHazProv();
}""",
 """  renderBacktest();
  renderHazProv();
  renderResultsPack();
}"""),

# 8 -- version string ---------------------------------------------------------------------
("""v1.7 provenance""",
 """v1.8 results pack"""),
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
        print("usage: python patch_frontend_p5.py <v17.html> <v18.html>")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
