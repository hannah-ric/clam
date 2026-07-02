"""
patch_frontend.py : applies the Phase 2-3 edits to the browser app.

Five surgical, exact-match replacements (any miss aborts with no output file):

 1. RFLOOD_GRID_INCLUDES_PROTECTION constant + fbRiver() helper: when the
    loaded river-flood grid is confirmed to embed FLOPROS-style protection,
    flipping one flag stops the app's riverine freeboard double-counting it.
 2. hzSite + adaptedFinSite use fbRiver() instead of raw FB_RIVER (2 sites).
 3. hzVector: a site OUTSIDE grid coverage (>200 km from any cell) now falls
    back to the interim model for cflood/rflood instead of silently scoring
    ZERO: matters the day a site lands in a country the grid doesn't cover.
 4. buildGridsFromRows: heat rows are now kept (previously discarded), and
    the tc provider gets the same outside-coverage fallback to interim.
 5. heatIndicators: grid-first lookup of the Phase 3 heat layer (v10=days
    over 32C, v25=days over 35C, v50=CDD) with the latitude formula as the
    fallback: every heat consumer (band, revenue at risk, exposure scoping,
    scorecards) flows through this one function, so nothing else changes.

Usage:  python patch_frontend.py <input.html> <output.html>
"""

import sys

EDITS = [

# 1 -- protection flag + helper --------------------------------------------
("""const FB_COAST=1.1, FB_RIVER=0.6;""",
 """const FB_COAST=1.1, FB_RIVER=0.6;
/* Phase 2: if the loaded rflood grid already embeds flood protection
   (FLOPROS-style ISIMIP sets), the interim riverine freeboard must not
   double-count it. Flip to true ONLY after confirming the served dataset's
   protection assumption (see hazard_grid_meta.json and the runbook). */
const RFLOOD_GRID_INCLUDES_PROTECTION=false;
function fbRiver(){return (gridByHazard.rflood&&RFLOOD_GRID_INCLUDES_PROTECTION)?0:FB_RIVER;}"""),

# 2a -- hzSite freeboard ------------------------------------------------------
("""  const {eadUsd,eadFrac,curve}=floodEad(vec,val,(hz==="cflood"?FB_COAST:FB_RIVER)+vuln.fbBonus);""",
 """  const {eadUsd,eadFrac,curve}=floodEad(vec,val,(hz==="cflood"?FB_COAST:fbRiver())+vuln.fbBonus);"""),

# 2b -- adaptedFinSite freeboard ---------------------------------------------
("""  const rf=floodEad(scaleVec(hzVector("rflood",s.latitude,s.longitude,sc)),value,FB_RIVER+vuln.fbBonus+(mods.fbBonus||0),dmgK);""",
 """  const rf=floodEad(scaleVec(hzVector("rflood",s.latitude,s.longitude,sc)),value,fbRiver()+vuln.fbBonus+(mods.fbBonus||0),dmgK);"""),

# 3 -- hzVector outside-coverage fallback ---------------------------------------
("""function hzVector(hz,la,lo,sc){
  if(hz==="tc") return provider()(la,lo,sc).vec;
  const g=gridByHazard[hz];
  if(g){ return g(la,lo,sc).vec; }
  if(hz==="cflood") return coastalFloodVector(la,lo,sc);
  if(hz==="rflood") return riverineFloodVector(la,lo,sc);
  return {};
}""",
 """function hzVector(hz,la,lo,sc){
  if(hz==="tc") return provider()(la,lo,sc).vec;
  const g=gridByHazard[hz];
  if(g){ const r=g(la,lo,sc); if(!(r.meta&&r.meta.outside)) return r.vec; }
  /* outside grid coverage (>200 km from any cell): fall back to the interim
     model rather than silently scoring zero (Phase 2) */
  if(hz==="cflood") return coastalFloodVector(la,lo,sc);
  if(hz==="rflood") return riverineFloodVector(la,lo,sc);
  return {};
}"""),

# 4 -- buildGridsFromRows: keep heat, tc outside-fallback ---------------------------
("""function buildGridsFromRows(rows){
  gridByHazard={};
  const byHaz={};
  rows.forEach(r=>{const h=r.hazard||"tc";(byHaz[h]||(byHaz[h]=[])).push(r);});
  Object.keys(byHaz).forEach(h=>{ if(h!=="heat") gridByHazard[h]=makeGridProvider(byHaz[h]); });
  _baseProvider = gridByHazard.tc || ((la,lo,sc)=>interimVector(la,lo,sc));
}""",
 """function buildGridsFromRows(rows){
  gridByHazard={};
  const byHaz={};
  rows.forEach(r=>{const h=r.hazard||"tc";(byHaz[h]||(byHaz[h]=[])).push(r);});
  /* Phase 3: heat rows are kept (v10=days>32C, v25=days>35C, v50=CDD);
     heatIndicators reads them grid-first. */
  Object.keys(byHaz).forEach(h=>{ gridByHazard[h]=makeGridProvider(byHaz[h]); });
  const tcGrid=gridByHazard.tc;
  _baseProvider = tcGrid
    ? (la,lo,sc)=>{const r=tcGrid(la,lo,sc);return (r.meta&&r.meta.outside)?interimVector(la,lo,sc):r;}
    : ((la,lo,sc)=>interimVector(la,lo,sc));
}"""),

# 5 -- heatIndicators grid-first -------------------------------------------------
("""function heatIndicators(la,lo,sc){
  const baseT=34-0.35*(Math.abs(la)-18)+6*continentality(la,lo);
  const T=baseT+warming(sc);
  const daysOver=thr=>Math.round(200/(1+Math.exp(-(T-thr)/1.6)));
  return {effT:+T.toFixed(1),daysOver32:daysOver(32),daysOver35:daysOver(35),cdd:Math.round(Math.max(0,T-18)*210)};
}""",
 """function heatIndicators(la,lo,sc){
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
}"""),

# 6 -- version string, so the deployed file is identifiable ------------------------
("""v1.5 trust &amp; depth""",
 """v1.6 petals data layers"""),
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
        print("usage: python patch_frontend.py <input.html> <output.html>")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
