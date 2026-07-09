"""
patch_frontend_p8.py : applies the catalog-plan edits to the v1.10 app,
producing v1.11.

What v1.11 adds, in one paragraph: the pack's capital plan now comes from
the realistic measure catalog, so each project carries a plan year (phased
against the refurbishment calendar and any annual budget the pipeline was
given) and possibly a deferred flag; the panel renders the year, marks
renovation-synergy pricing, shows the annual budget when one applied, and
adds a line for measures the catalog IDENTIFIED but cannot yet price
(wildfire ahead of its hazard layer, continuity measures that act on the
financial layer), so unpriced exposure stays visible instead of absent.

Two exact-match edits; any miss aborts with no output written.

Usage:  python patch_frontend_p8.py Resort_Climate_Risk_Explorer_v110.html \
                                    Resort_Climate_Risk_Explorer_v111.html
"""

import sys

EDITS = [

# 1 -- capital plan rows gain year, deferral, budget, and the identified line ----
("""      row("Top capital projects",pk.capital_plan.projects.slice(0,5).map(cp=>
        esc(cp.site)+" \\u00b7 "+esc(cp.measure)+" \\u00b7 BCR "+esc(cp.bcr)+
        " ("+fmt$(cp.averted_direct_aal_usd)+"/yr averted, "+fmt$(cp.cost_usd)+")"
      ).join("<br>")+"<br><small>ranked by canonical benefit-cost ratio, "+
        esc(pk.capital_plan.scenario)+" appraisal</small>"):"")+""",
 """      row("Top capital projects",pk.capital_plan.projects.slice(0,5).map(cp=>
        (cp.year!=null?"Y"+esc(cp.year)+" \\u00b7 ":(("year" in cp)?"deferred \\u00b7 ":""))+
        esc(cp.site)+" \\u00b7 "+esc(cp.measure)+" \\u00b7 BCR "+esc(cp.bcr)+
        " ("+fmt$(cp.averted_direct_aal_usd)+"/yr averted, "+fmt$(cp.cost_usd)+
        (cp.renovation_synergy?", refurbishment-phased":"")+")"
      ).join("<br>")+"<br><small>ranked by canonical benefit-cost ratio, "+
        esc(pk.capital_plan.scenario)+" appraisal"+
        (pk.capital_plan.budget_annual_usd?", "+fmt$(pk.capital_plan.budget_annual_usd)+"/yr budget":"")+
        "</small>"):"")+
    (pk.measures_catalog&&pk.measures_catalog.identified&&pk.measures_catalog.identified.length?
      row("Identified, not yet priced",pk.measures_catalog.identified.map(m=>
        esc(m.name)+" ("+esc(m.sites_in_scope)+" site"+(m.sites_in_scope===1?"":"s")+")"
      ).join("<br>")+"<br><small>wildfire measures await the wildfire hazard "+
        "layer; continuity measures are appraised in this app\\u2019s financial "+
        "model</small>"):"")+""",),

# 2 -- version string -----------------------------------------------------------------
("""v1.10 building profiles""",
 """v1.11 measure catalog"""),
]


def main(src_path, dst_path) -> int:
    html = open(src_path, encoding="utf-8").read()
    for i, edit in enumerate(EDITS, 1):
        old, new = edit[0], edit[1]
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
        print("usage: python patch_frontend_p8.py <v110.html> <v111.html>")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
