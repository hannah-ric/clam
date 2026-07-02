"""
patch_frontend_p10.py : applies the six-peril coherence edits to the v1.12
app, producing v1.13.

What v1.13 fixes, in one paragraph: everything an adversarial product review
found where the surface still described a four-peril product wrapped around
six-peril math. The Power BI export gains the wildfire and rainfall EAD and
rating columns (appended, so existing consumers keep working), its physical
totals and return-period losses now sum ALL acute perils (they were
irreconcilable with the financial columns), and a grid_perils coverage stamp
rides every row. The site CSV loader ingests the wildfire profile fields the
interim model requires (wui_class, defensible_space_m, roof_class_a), and the
downloadable template carries them, so wildfire is reachable by real users,
not just tests. The risk-driver panel derives from the acute peril list so
shares sum to 100% and wildfire or rainfall can be named the dominant driver.
The pack panel iterates whatever perils the pack actually carries and drops
its stale wildfire caveat. The two newest perils get real INFO popovers,
including the honest note that the app's wildfire step curve carries EAD but
not tail VaR at screening probabilities (the results pack's event math holds
the fire tail). Rainfall's site table is labeled in ponding metres, not mm.
And the whole four-peril copy corpus is swept.

Twenty exact-match edits; any miss aborts with no output written.

Usage:  python patch_frontend_p10.py TNL_Resort_Climate_Risk_Explorer_v112.html \
                                     TNL_Resort_Climate_Risk_Explorer_v113.html
"""

import sys

EDITS = [

# 1 -- export columns: new perils appended, coverage stamp -----------------------
("""    "direct_damage_aal_usd","business_interruption_aal_usd","heat_revenue_at_risk_usd","total_climate_aal_usd","total_aal_pct_revenue"]
    .concat(RPS.map(rp=>"loss_rp"+rp+"_physical_usd"));""",
 """    "direct_damage_aal_usd","business_interruption_aal_usd","heat_revenue_at_risk_usd","total_climate_aal_usd","total_aal_pct_revenue"]
    .concat(RPS.map(rp=>"loss_rp"+rp+"_physical_usd"))
    .concat(["ead_prain_usd","ead_wfire_usd","rating_prain","rating_wfire","grid_perils"]);
  const gridPerils=perilAuthority().filter(a=>a.live).length+"/"+HAZARDS.length;"""),

# 2 -- export rows: five-peril physical totals and RP losses ------------------------
("""    const tc=hzSite(s,"tc",scenario),cf=hzSite(s,"cflood",scenario),rf=hzSite(s,"rflood",scenario),ht=hzSite(s,"heat",scenario);
    const physEad=tc.ead+cf.ead+rf.ead, physPct=s.asset_value_usd?physEad/s.asset_value_usd*100:0;
    const fin=finSite(s,scenario);
    const rpLoss=RPS.map(rp=>(g(tc.curve,rp)+g(cf.curve,rp)+g(rf.curve,rp)).toFixed(0));""",
 """    const tc=hzSite(s,"tc",scenario),cf=hzSite(s,"cflood",scenario),rf=hzSite(s,"rflood",scenario),ht=hzSite(s,"heat",scenario),
          pv=hzSite(s,"prain",scenario),wf=hzSite(s,"wfire",scenario);
    const physEad=tc.ead+cf.ead+rf.ead+pv.ead+wf.ead, physPct=s.asset_value_usd?physEad/s.asset_value_usd*100:0;
    const fin=finSite(s,scenario);
    const rpLoss=RPS.map(rp=>(g(tc.curve,rp)+g(cf.curve,rp)+g(rf.curve,rp)+g(pv.curve,rp)+g(wf.curve,rp)).toFixed(0));"""),

("""      (fin.revenue?fin.totalAal/fin.revenue*100:0).toFixed(3)].concat(rpLoss);""",
 """      (fin.revenue?fin.totalAal/fin.revenue*100:0).toFixed(3)].concat(rpLoss)
      .concat([pv.ead.toFixed(0),wf.ead.toFixed(0),pv.band,wf.band,gridPerils]);"""),

# 3 -- the site CSV loader ingests the wildfire profile fields ------------------------
("""    const ee2=row.get("equipment_elevated");if(ee2!==undefined&&String(ee2).trim()!=="")rec.equipment_elevated=truthy(ee2);""",
 """    const ee2=row.get("equipment_elevated");if(ee2!==undefined&&String(ee2).trim()!=="")rec.equipment_elevated=truthy(ee2);
    const wu2=String(row.get("wui_class")||"").trim().toLowerCase();if(FIRE_WUI_PBURN[wu2]!=null||wu2==="none")rec.wui_class=wu2;
    const ds2=toNum(row.get("defensible_space_m"));if(isFinite(ds2)&&ds2>=0)rec.defensible_space_m=ds2;
    const ra2=row.get("roof_class_a");if(ra2!==undefined&&String(ra2).trim()!=="")rec.roof_class_a=truthy(ra2);"""),

# 4 -- the downloadable template carries the wildfire fields ---------------------------
("""    "name,brand,latitude,longitude,asset_value_usd,country,coastal,annual_revenue_usd,construction,year_built,defended,roof_type,roof_year,opening_protection,first_floor_elev_m,equipment_elevated\\n"+
    "Example Beachfront Resort,Club Wyndham,27.9500,-82.4600,40000000,USA,true,14000000,masonry,2002,false,metal,2018,impact,1.2,true\\n"+
    "Example Inland Resort,WorldMark,29.4241,-98.4936,22000000,USA,false,,frame,2005,,shingle,2005,none,,\\n"+
    "Example Island Resort,Margaritaville,18.3797,-65.8083,51000000,USA,true,18000000,engineered,2011,true,,,,,\\n";""",
 """    "name,brand,latitude,longitude,asset_value_usd,country,coastal,annual_revenue_usd,construction,year_built,defended,roof_type,roof_year,opening_protection,first_floor_elev_m,equipment_elevated,wui_class,defensible_space_m,roof_class_a\\n"+
    "Example Beachfront Resort,Club Wyndham,27.9500,-82.4600,40000000,USA,true,14000000,masonry,2002,false,metal,2018,impact,1.2,true,,,\\n"+
    "Example Inland Resort,WorldMark,29.4241,-98.4936,22000000,USA,false,,frame,2005,,shingle,2005,none,,,intermix,10,false\\n"+
    "Example Island Resort,Margaritaville,18.3797,-65.8083,51000000,USA,true,18000000,engineered,2011,true,,,,,,,,\\n";"""),

# 5 -- risk drivers derive from the acute peril list --------------------------------------
("""  const items=[
    {label:"Tropical cyclone",ead:rd.byHazard.tc},
    {label:"Coastal flood",ead:rd.byHazard.cflood},
    {label:"Riverine flood",ead:rd.byHazard.rflood},
  ].sort((a,b)=>b.ead-a.ead);""",
 """  const items=ACUTE.map(hz=>({label:HAZARD_LABEL[hz],ead:rd.byHazard[hz]||0}))
    .sort((a,b)=>b.ead-a.ead);"""),

# 6 -- pack panel: by-peril row shows what the pack carries ---------------------------------
("""    row("By peril",["tc","cflood","rflood"].map(z=>z+" "+fmt$((p.by_peril_aal_usd||{})[z]||0)).join(" \\u00b7 "))+""",
 """    row("By peril",Object.keys(p.by_peril_aal_usd||{}).map(z=>z+" "+fmt$(p.by_peril_aal_usd[z]||0)).join(" \\u00b7 "))+"""),

# 7 -- pack panel: stale wildfire caveat dropped ----------------------------------------------
("""      ).join("<br>")+"<br><small>wildfire measures await the wildfire hazard "+
        "layer; continuity measures are appraised in this app\\u2019s financial "+
        "model</small>"):"")+""",
 """      ).join("<br>")+"<br><small>continuity measures are appraised in this "+
        "app\\u2019s financial model</small>"):"")+"""),

# 8 -- rainfall RP table labeled in ponding metres ---------------------------------------------
("""  {key:"prain",  label:"TC rainfall",      short:"P", color:"#4E7B8C", type:"damage",    unit:"mm"},""",
 """  {key:"prain",  label:"TC rainfall",      short:"P", color:"#4E7B8C", type:"damage",    unit:"m ponding"},"""),

# 9 -- INFO entries for the two new perils (with the honest fire-tail note) --------------------
("""  tc:{t:"Tropical-cyclone wind",b:""",
 """  wfire:{t:"Wildfire",b:
    "<p>Wildfire uses an <b>annual burn probability</b>, not a return-period intensity: expected damage = value x burn probability x a "+(FIRE_MDD*100)+"% conditional damage ratio, cut by a Class A roof (x0.6) and defensible space of 30 m or more (x0.7).</p>"+
    "<p>The probability comes from a wfire grid when loaded, else from the site's <code>wui_class</code> (interface "+FIRE_WUI_PBURN.interface+"%/yr, intermix "+FIRE_WUI_PBURN.intermix+"%/yr), scaled with warming. Without either, wildfire is zero by design.</p>"+
    "<p><b>Honest limit:</b> at screening probabilities wildfire contributes to expected annual damage but not to the 1-in-100 tail figures in this app (a burn probability below 1% never crosses the 100-year threshold). The results pack's event math carries the fire tail properly.</p>"},
  prain:{t:"TC rainfall",b:
    "<p>Event rainfall (mm at each return period, from a prain grid) becomes ponding depth through documented drainage constants: depth = max(0, rain - "+PRAIN_DRAIN_MM+" mm) x "+PRAIN_POND_COEFF+", then the flood damage curve with a "+PRAIN_FB+" m freeboard.</p>"+
    "<p>There is deliberately <b>no interim model</b>: rainfall cannot be proxied honestly from regional anchors, so this peril stays zero until a grid is loaded and the trust chip says so.</p>"},
  tc:{t:"Tropical-cyclone wind",b:"""),

# 10 -- copy sweep: the four-peril corpus -------------------------------------------------------
("""Every peril in one currency: expected annual cost, all four hazards, damage plus interruption.""",
 """Every peril in one currency: expected annual cost across all six hazards, damage plus interruption."""),

("""            <th title="Ratings: W wind, F coastal flood, R riverine flood, H heat">W&nbsp;F&nbsp;R&nbsp;H<button type="button" class="info" data-info="ratings" aria-label="How this is calculated" aria-expanded="false">i</button></th>""",
 """            <th title="Ratings: W wind, F coastal flood, R riverine flood, H heat, B wildfire, P rainfall">Ratings<button type="button" class="info" data-info="ratings" aria-label="How this is calculated" aria-expanded="false">i</button></th>"""),

("""  ratings:{t:"Per-peril ratings (W F R H)",b:
    "<p>Four letters, one per peril: <b>W</b> wind, <b>F</b> coastal flood, <b>R</b> riverine flood, <b>H</b> heat.</p>"+""",
 """  ratings:{t:"Per-peril ratings",b:
    "<p>One letter per peril: <b>W</b> wind, <b>F</b> coastal flood, <b>R</b> riverine flood, <b>H</b> heat, <b>B</b> wildfire, <b>P</b> TC rainfall.</p>"+"""),

("""'<span class="hint" style="margin-left:8px">W wind &middot; F coastal &middot; R riverine &middot; H heat</span></div>';""",
 """'<span class="hint" style="margin-left:8px">W wind &middot; F coastal &middot; R riverine &middot; H heat &middot; B wildfire &middot; P rainfall</span></div>';"""),

("""tropical-cyclone wind, coastal flood, riverine flood, or extreme heat. The Overview risk-driver panel always shows all perils together.""",
 """tropical-cyclone wind, coastal flood, riverine flood, extreme heat, wildfire, or TC rainfall. The Overview risk-driver panel always shows all perils together."""),

("""    "<p>It is the least precise of the four perils and improves the most when a CLIMADA river-flood grid is loaded.</p>"},""",
 """    "<p>It is among the least precise perils here and improves the most when a CLIMADA river-flood grid is loaded.</p>"},"""),

("""    "<p>The total expected annual cost split across all four perils. Each acute peril carries its own direct damage plus the business interruption it causes; heat carries its revenue-at-risk.</p>"+
    "<p>The four shares add up to the same total as the cost-by-type view.</p>"},""",
 """    "<p>The total expected annual cost split across all six perils. Each acute peril carries its own direct damage plus the business interruption it causes; heat carries its revenue-at-risk.</p>"+
    "<p>The shares add up to the same total as the cost-by-type view.</p>"},"""),

("""    "<p>Wind and both floods summed into one physical expected-annual-damage figure, compared across emissions pathways at the horizon selected in the top bar.</p>"+""",
 """    "<p>All acute perils summed into one physical expected-annual-damage figure, compared across emissions pathways at the horizon selected in the top bar.</p>"+"""),

("""    "<p>How many sites fall into each combined physical-risk band (wind plus both floods) at the selected scenario. A quick read on how concentrated the exposure is.</p>"},""",
 """    "<p>How many sites fall into each combined physical-risk band (all acute perils) at the selected scenario. A quick read on how concentrated the exposure is.</p>"},"""),

("""    "<p><b>Acute</b> risk is event-driven: wind, coastal flood, riverine flood, and the business interruption they cause. <b>Chronic</b> risk is gradual: heat's steady drag on operations.</p>"+""",
 """    "<p><b>Acute</b> risk is event-driven: wind, coastal flood, riverine flood, TC rainfall, wildfire, and the business interruption they cause. <b>Chronic</b> risk is gradual: heat's steady drag on operations.</p>"+"""),

("""Until a grid is loaded, hazard comes from a built-in interim model spanning four perils. Good for exploration, not for disclosure. A CLIMADA grid supersedes any peril it carries; perils absent from the grid stay on the interim model.""",
 """Until a grid is loaded, hazard comes from built-in interim models where an honest one exists (wildfire needs the site's wui_class; TC rainfall has no interim model at all and stays zero without a grid). Good for exploration, not for disclosure. A CLIMADA grid supersedes any peril it carries."""),

("""            <span class="k">Perils</span><span class="v">Tropical-cyclone wind, coastal flood and surge, riverine flood, extreme heat</span>""",
 """            <span class="k">Perils</span><span class="v">Tropical-cyclone wind, coastal flood and surge, riverine flood, extreme heat, wildfire (burn probability), TC rainfall (ponding)</span>"""),

("""            <span class="k">Portfolio EAD</span><span class="v">Exact sum of site EAD per peril; combined physical risk sums wind and both floods</span>""",
 """            <span class="k">Portfolio EAD</span><span class="v">Exact sum of site EAD per peril; combined physical risk sums every acute peril</span>"""),

("""v1.12 six perils &middot; perils: TC wind (Emanuel 2011), coastal &amp; riverine flood, extreme heat &middot;""",
 """v1.13 six-peril coherence &middot; perils: TC wind (Emanuel 2011), coastal &amp; riverine flood, extreme heat, wildfire, TC rainfall &middot;"""),
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
        print("usage: python patch_frontend_p10.py <v112.html> <v113.html>")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
