"""
patch_frontend_p7.py : applies the building-profile v2 edits to the v1.9 app,
producing v1.10.

What v1.10 adds, in one paragraph: richer site profiles drive the damage
math. The sites CSV accepts optional roof_type (shingle|metal|tile|membrane),
roof_year, opening_protection (none|partial|impact), first_floor_elev_m, and
equipment_elevated columns; vulnOf becomes the v2 factor table MIRRORED from
pipeline/refresh_impacts.py (roof detail supersedes the year-built proxy, a
measured first-floor height supersedes the defended 0.5 m proxy, elevated
critical systems cap the flood damage ratio at 0.5 instead of 0.75). A site
with none of the new fields scores exactly as before: the compatibility rule
every layer of this system keeps.

Nine exact-match edits; any miss aborts with no output written.

Usage:  python patch_frontend_p7.py TNL_Resort_Climate_Risk_Explorer_v19.html \
                                    TNL_Resort_Climate_Risk_Explorer_v110.html
"""

import sys

EDITS = [

# 1 -- vulnOf v2: the factor table, mirrored from refresh_impacts.py ------------
("""function vulnOf(site){
  let w=1;
  const c=String(site.construction||"").toLowerCase();
  if(CONSTR_FACTOR[c]!=null)w*=CONSTR_FACTOR[c];
  const y=+site.year_built;
  if(isFinite(y)&&y>1800){ if(y<1995)w*=1.15; else if(y>=2010)w*=0.9; }
  return {windMult:Math.min(Math.max(w,0.5),1.6), fbBonus:site.defended?0.5:0};
}""",
 """/* Profile v2 factor table. MIRRORS refresh_impacts.py; change both sides.
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
}"""),

# 2 -- floodMdd gains the cap parameter --------------------------------------------
("""function floodMdd(d,fb){const e=d-(fb||0);return e<=0?0:Math.min(0.75,1-Math.exp(-0.6*e));}""",
 """function floodMdd(d,fb,cap){const e=d-(fb||0);return e<=0?0:Math.min(cap==null?0.75:cap,1-Math.exp(-0.6*e));}"""),

# 3 -- floodEad threads the cap ------------------------------------------------------
("""function floodEad(vec,value,fb,dmgScale){
  const k=dmgScale==null?1:dmgScale;
  const pts=RPS.map(rp=>{const d=Math.max(vec[rp]||0,0);return {rp,v:d,f:1/rp,frac:Math.min(floodMdd(d,fb)*k,1)};});""",
 """function floodEad(vec,value,fb,dmgScale,cap){
  const k=dmgScale==null?1:dmgScale;
  const pts=RPS.map(rp=>{const d=Math.max(vec[rp]||0,0);return {rp,v:d,f:1/rp,frac:Math.min(floodMdd(d,fb,cap)*k,1)};});"""),

# 4 -- hzSite passes the site's cap ---------------------------------------------------
("""  const {eadUsd,eadFrac,curve}=floodEad(vec,val,(hz==="cflood"?FB_COAST:fbRiver())+vuln.fbBonus);""",
 """  const {eadUsd,eadFrac,curve}=floodEad(vec,val,(hz==="cflood"?FB_COAST:fbRiver())+vuln.fbBonus,null,vuln.floodCap);"""),

# 5a -- adaptedFinSite coastal call ----------------------------------------------------
("""  const cf=floodEad(cvec,value,FB_COAST+vuln.fbBonus+(mods.fbBonus||0),dmgK);""",
 """  const cf=floodEad(cvec,value,FB_COAST+vuln.fbBonus+(mods.fbBonus||0),dmgK,vuln.floodCap);"""),

# 5b -- adaptedFinSite river call -------------------------------------------------------
("""  const rf=floodEad(scaleVec(hzVector("rflood",s.latitude,s.longitude,sc)),value,fbRiver()+vuln.fbBonus+(mods.fbBonus||0),dmgK);""",
 """  const rf=floodEad(scaleVec(hzVector("rflood",s.latitude,s.longitude,sc)),value,fbRiver()+vuln.fbBonus+(mods.fbBonus||0),dmgK,vuln.floodCap);"""),

# 6 -- the site CSV loader ingests the v2 columns ----------------------------------------
("""    if(hasDef){const dv=row.get("defended");if(dv!==undefined&&String(dv).trim()!=="")rec.defended=truthy(dv);}
    arr.push(rec);""",
 """    if(hasDef){const dv=row.get("defended");if(dv!==undefined&&String(dv).trim()!=="")rec.defended=truthy(dv);}
    /* profile v2 columns, all optional (absent = today's behavior) */
    const rt2=String(row.get("roof_type")||"").trim().toLowerCase();if(ROOF_TYPE_FACTOR[rt2]!=null)rec.roof_type=rt2;
    const op2=String(row.get("opening_protection")||"").trim().toLowerCase();if(OPENING_FACTOR[op2]!=null)rec.opening_protection=op2;
    const ry2=toNum(row.get("roof_year"));if(isFinite(ry2)&&ry2>1800&&ry2<2100)rec.roof_year=Math.round(ry2);
    const ffe2=toNum(row.get("first_floor_elev_m"));if(isFinite(ffe2)&&ffe2>=0)rec.first_floor_elev_m=ffe2;
    const ee2=row.get("equipment_elevated");if(ee2!==undefined&&String(ee2).trim()!=="")rec.equipment_elevated=truthy(ee2);
    arr.push(rec);"""),

# 7 -- the downloadable template documents the new columns ---------------------------------
("""    "name,brand,latitude,longitude,asset_value_usd,country,coastal,annual_revenue_usd,construction,year_built,defended\\n"+
    "Example Beachfront Resort,Club Wyndham,27.9500,-82.4600,40000000,USA,true,14000000,masonry,2002,false\\n"+
    "Example Inland Resort,WorldMark,29.4241,-98.4936,22000000,USA,false,,frame,2005,\\n"+
    "Example Island Resort,Margaritaville,18.3797,-65.8083,51000000,USA,true,18000000,engineered,2011,true\\n";""",
 """    "name,brand,latitude,longitude,asset_value_usd,country,coastal,annual_revenue_usd,construction,year_built,defended,roof_type,roof_year,opening_protection,first_floor_elev_m,equipment_elevated\\n"+
    "Example Beachfront Resort,Club Wyndham,27.9500,-82.4600,40000000,USA,true,14000000,masonry,2002,false,metal,2018,impact,1.2,true\\n"+
    "Example Inland Resort,WorldMark,29.4241,-98.4936,22000000,USA,false,,frame,2005,,shingle,2005,none,,\\n"+
    "Example Island Resort,Margaritaville,18.3797,-65.8083,51000000,USA,true,18000000,engineered,2011,true,,,,,\\n";"""),

# 8 -- version string --------------------------------------------------------------------------
("""v1.9 renewal & capital""",
 """v1.10 building profiles"""),
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
        print("usage: python patch_frontend_p7.py <v19.html> <v110.html>")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
