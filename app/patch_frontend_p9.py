"""
patch_frontend_p9.py : applies the six-peril edits to the v1.11 app,
producing v1.12.

What v1.12 adds, in one paragraph: wildfire (hazard="wfire", annual burn
probability) and tropical-cyclone rainfall (hazard="prain", mm at return
periods) become the fifth and sixth perils, everywhere: the peril selector,
the trust chips (n/6), site ratings, the combined physical score, risk
drivers, the by-peril cost split, business interruption, the adaptation
engine (a new wildfire-hardening measure), and the site scorecards.
MIGRATION SAFETY is the design center: with no wfire/prain grid rows loaded
and no wui_class profile data, both new perils score exactly zero, so every
number in the app equals v1.11's until data arrives; the chips honestly show
the new perils gray until then. Rainfall deliberately has NO interim model
(rain cannot be proxied honestly from regional anchors); wildfire's interim
needs the site's wui_class. Every new constant is documented in place.

Fifteen exact-match edits; any miss aborts with no output written.

Usage:  python patch_frontend_p9.py TNL_Resort_Climate_Risk_Explorer_v111.html \
                                    TNL_Resort_Climate_Risk_Explorer_v112.html
"""

import sys

EDITS = [

# 1 -- peril selector gains the two options -----------------------------------------
("""          <option value="heat">Extreme heat</option>
        </select>""",
 """          <option value="heat">Extreme heat</option>
          <option value="wfire">Wildfire</option>
          <option value="prain">TC rainfall</option>
        </select>"""),

# 2 -- HAZARDS registry --------------------------------------------------------------
("""  {key:"heat",   label:"Extreme heat",     short:"H", color:"#C06B2E", type:"indicator", unit:"days"},
];""",
 """  {key:"heat",   label:"Extreme heat",     short:"H", color:"#C06B2E", type:"indicator", unit:"days"},
  {key:"wfire",  label:"Wildfire",         short:"B", color:"#A6432E", type:"damage",    unit:"%/yr"},
  {key:"prain",  label:"TC rainfall",      short:"P", color:"#4E7B8C", type:"damage",    unit:"mm"},
];"""),

# 3 -- fire and rainfall constants + helpers, after heatBand --------------------------
("""function heatBand(days32){const t=[10,45,100,160],n=["Minimal","Low","Moderate","High","Severe"];let i=0;while(i<t.length&&days32>t[i])i++;return n[i];}""",
 """function heatBand(days32){const t=[10,45,100,160],n=["Minimal","Low","Moderate","High","Severe"];let i=0;while(i<t.length&&days32>t[i])i++;return n[i];}

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
}"""),

# 4 -- hzSite branches for the new perils ----------------------------------------------
("""  const vec=hzVector(hz,la,lo,sc);""",
 """  if(hz==="wfire"){
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
  const vec=hzVector(hz,la,lo,sc);"""),

# 5 -- acute peril list ------------------------------------------------------------------
("""const ACUTE=["tc","cflood","rflood"];""",
 """const ACUTE=["tc","cflood","rflood","prain","wfire"];"""),

# 6 -- combined physical score -------------------------------------------------------------
("""    const tc=hzSite(s,"tc",sc),cf=hzSite(s,"cflood",sc),rf=hzSite(s,"rflood",sc);
    const ead=tc.ead+cf.ead+rf.ead,pct=s.asset_value_usd?ead/s.asset_value_usd*100:0;
    return Object.assign({},s,{ead,eadPct:pct,band:bandOf(pct),parts:{tc:tc.ead,cflood:cf.ead,rflood:rf.ead}});""",
 """    const tc=hzSite(s,"tc",sc),cf=hzSite(s,"cflood",sc),rf=hzSite(s,"rflood",sc),
          pv=hzSite(s,"prain",sc),wf=hzSite(s,"wfire",sc);
    const ead=tc.ead+cf.ead+rf.ead+pv.ead+wf.ead,pct=s.asset_value_usd?ead/s.asset_value_usd*100:0;
    return Object.assign({},s,{ead,eadPct:pct,band:bandOf(pct),parts:{tc:tc.ead,cflood:cf.ead,rflood:rf.ead,prain:pv.ead,wfire:wf.ead}});"""),

# 7 -- risk drivers ---------------------------------------------------------------------------
("""  const t={tc:0,cflood:0,rflood:0};
  for(const s of sites){t.tc+=hzSite(s,"tc",sc).ead;t.cflood+=hzSite(s,"cflood",sc).ead;t.rflood+=hzSite(s,"rflood",sc).ead;}
  const sum=t.tc+t.cflood+t.rflood||1;
  return {byHazard:t,total:t.tc+t.cflood+t.rflood,share:{tc:t.tc/sum,cflood:t.cflood/sum,rflood:t.rflood/sum}};""",
 """  const t={tc:0,cflood:0,rflood:0,prain:0,wfire:0};
  for(const s of sites)for(const hz of ACUTE)t[hz]+=hzSite(s,hz,sc).ead;
  const total=ACUTE.reduce((a,hz)=>a+t[hz],0),sum=total||1;
  const share={};ACUTE.forEach(hz=>share[hz]=t[hz]/sum);
  return {byHazard:t,total,share};"""),

# 8 -- by-peril split ---------------------------------------------------------------------------
("""  const byPeril={tc:0,cflood:0,rflood:0,heat:f.heatCost};""",
 """  const byPeril={tc:0,cflood:0,rflood:0,prain:0,wfire:0,heat:f.heatCost};"""),

# 9 -- summary peril labels and array become registry-driven -------------------------------------
("""  const perilName={tc:"Tropical cyclone wind",cflood:"Coastal flood",rflood:"Riverine flood",heat:"Extreme heat"};
  const perilArr=[["tc",agg.byPeril.tc],["cflood",agg.byPeril.cflood],["rflood",agg.byPeril.rflood],["heat",agg.byPeril.heat]].sort((a,b)=>b[1]-a[1]);""",
 """  const perilName={tc:"Tropical cyclone wind",cflood:"Coastal flood",rflood:"Riverine flood",heat:"Extreme heat",wfire:"Wildfire",prain:"TC rainfall"};
  const perilArr=Object.keys(agg.byPeril).map(k=>[k,agg.byPeril[k]]).sort((a,b)=>b[1]-a[1]);"""),

# 10 -- adaptedFinSite gains the two peril terms (identical to finSite with no mods) --------------
("""  const rf=floodEad(scaleVec(hzVector("rflood",s.latitude,s.longitude,sc)),value,fbRiver()+vuln.fbBonus+(mods.fbBonus||0),dmgK,vuln.floodCap);
  directEad+=rf.eadUsd; biEad+=gop*reopenShare*rf.eadFrac;""",
 """  const rf=floodEad(scaleVec(hzVector("rflood",s.latitude,s.longitude,sc)),value,fbRiver()+vuln.fbBonus+(mods.fbBonus||0),dmgK,vuln.floodCap);
  directEad+=rf.eadUsd; biEad+=gop*reopenShare*rf.eadFrac;
  const pv=floodEad(prainToDepth(scaleVec(hzVector("prain",s.latitude,s.longitude,sc))),value,PRAIN_FB+vuln.fbBonus+(mods.fbBonus||0),dmgK,vuln.floodCap);
  directEad+=pv.eadUsd; biEad+=gop*reopenShare*pv.eadFrac;
  const fb2=fireBurnPct(s,sc);
  const fFrac=Math.min((fb2.pct/100)*haz,1)*FIRE_MDD*fireVulnMult(s)*dmgK*(mods.fireMult==null?1:mods.fireMult);
  directEad+=fFrac*value; biEad+=gop*reopenShare*fFrac;"""),

# 11 -- fire-exposure scope predicate ---------------------------------------------------------------
("""function isHeatExposed(s,sc){return heatIndicators(s.latitude,s.longitude,sc).daysOver35>HEAT_COMFORT_DAYS;}""",
 """function isHeatExposed(s,sc){return heatIndicators(s.latitude,s.longitude,sc).daysOver35>HEAT_COMFORT_DAYS;}
function isFireExposed(s,sc){return fireBurnPct(s,sc).pct>0;}"""),

# 12 -- the wildfire-hardening measure --------------------------------------------------------------
("""];
function measureCost(m,sitesArr,sc){""",
 """  {key:"fire",name:"Wildfire hardening (defensible space & Class A roof)",info:"mFire",target:"Wildfire damage + its BI",
   sliders:[{p:"red",label:"Burn-loss reduction",min:20,max:70,step:5,fmt:v=>v+"%"},
            {p:"cost",label:"Cost, % of site value",min:0.1,max:1.5,step:0.1,fmt:v=>(+v).toFixed(1)+"%"}],
   mods:st=>({fireMult:1-st.red/100}),
   inScope:isFireExposed,
   siteCost:(s,st)=>s.asset_value_usd*st.cost/100},
];
function measureCost(m,sitesArr,sc){"""),

# 13 -- the measure's default state ------------------------------------------------------------------
("""     cool:{on:false,red:40,cost:0.5}}};""",
 """     cool:{on:false,red:40,cost:0.5},
     fire:{on:false,red:40,cost:0.6}}};"""),

# 14 -- the measure's info popover --------------------------------------------------------------------
("""  layering:{t:"Risk layering & insurance",b:""",
 """  mFire:{t:"Wildfire hardening",b:
    "<p>Defensible space and a Class A roof assembly cut the share of value lost when fire reaches the site. The slider is the burn-loss reduction; the measure applies only where the site has wildfire exposure (a wfire grid or a wui_class profile field).</p>"+
    "<p>Wildfire uses an annual burn probability, not a return-period depth: expected damage = value x burn probability x conditional damage ratio ("+(FIRE_MDD*100)+"%), modified by roof_class_a and defensible_space_m.</p>"},
  layering:{t:"Risk layering & insurance",b:"""),

# 15 -- version string ----------------------------------------------------------------------------------
("""v1.11 measure catalog""",
 """v1.12 six perils"""),
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
        print("usage: python patch_frontend_p9.py <v111.html> <v112.html>")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
