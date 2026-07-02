"""
patch_frontend_p6.py : applies the renewal-and-capital edits to the v1.8 app,
producing v1.9.

What v1.9 adds, in one paragraph: when a results pack is loaded, the risk
layering panel gains an EVENT-SET BENCHMARK row: the expected annual loss to
the configured layer and the technical premium (expected loss x the load
slider), both computed from the pack's joint exceedance curve instead of the
app's diversified upper-bound blend. That is the number a broker's quote can
be judged against at renewal. The Method-tab pack panel gains the same
benchmark plus the pack's capital plan: every (site, measure) pair ranked by
canonical benefit-cost ratio, the prioritised resilience capex list.

Four exact-match edits; any miss aborts with no output written.

Usage:  python patch_frontend_p6.py TNL_Resort_Climate_Risk_Explorer_v18.html \
                                    TNL_Resort_Climate_Risk_Explorer_v19.html
"""

import sys

EDITS = [

# 1 -- packLayerStats helper, in front of the pack panel renderer -----------------
("""function renderResultsPack(){""",
 """/* layer stats on the PACK's joint exceedance curve: the event-set benchmark
   for the insurance layer the sliders configure. Uses the same integral as
   the live model (layerStatsCalc), so the two rows differ only by curve. */
function packLayerStats(sc){
  const pk=resultsPack&&resultsPack.data;
  if(!pk||!pk.scenarios)return null;
  const s=pk.scenarios[sc]||pk.scenarios.present;
  if(!s)return null;
  const ep={};RPS.forEach(rp=>ep[rp]=+((s.portfolio.ep_usd||{})[String(rp)])||0);
  return layerStatsCalc(ep,+s.portfolio.direct_aal_usd||0);
}
function renderResultsPack(){"""),

# 2 -- the layering panel gains the event-set benchmark row -------------------------
("""    '<span class="k">Indicative premium</span><span class="v mono">'+fmt$(ls.premium)+'/yr</span>'+
    '<span class="k">Cost of certainty</span><span class="v mono">'+fmt$(ls.premium-ls.transferred)+'/yr</span>';""",
 """    '<span class="k">Indicative premium</span><span class="v mono">'+fmt$(ls.premium)+'/yr</span>'+
    '<span class="k">Cost of certainty</span><span class="v mono">'+fmt$(ls.premium-ls.transferred)+'/yr</span>'+
    (function(){const ps=packLayerStats(scenario);return (ps&&ps.limit>0)?
      '<span class="k">Event-set benchmark</span><span class="v mono">'+fmt$(ps.transferred)+'/yr to layer \\u00b7 technical premium '+fmt$(ps.premium)+'/yr <small>CLIMADA results pack, direct damage; judge quotes against this</small></span>':'';})();"""),

# 3 -- the pack panel gains the benchmark and the capital plan ------------------------
("""    row("Provenance",esc(String(pk.script||"refresh_impacts.py").split(" ")[0])+""",
 """    (function(){const ps=packLayerStats(sc);return (ps&&ps.limit>0)?
      row("Layer benchmark","1-in-"+adapt.attach+" to 1-in-"+adapt.exhaust+": "+
        fmt$(ps.transferred)+"/yr expected to layer \\u00b7 technical premium "+
        fmt$(ps.premium)+"/yr at load "+adapt.load):"";})()+
    (pk.capital_plan&&pk.capital_plan.projects&&pk.capital_plan.projects.length?
      row("Top capital projects",pk.capital_plan.projects.slice(0,5).map(cp=>
        esc(cp.site)+" \\u00b7 "+esc(cp.measure)+" \\u00b7 BCR "+esc(cp.bcr)+
        " ("+fmt$(cp.averted_direct_aal_usd)+"/yr averted, "+fmt$(cp.cost_usd)+")"
      ).join("<br>")+"<br><small>ranked by canonical benefit-cost ratio, "+
        esc(pk.capital_plan.scenario)+" appraisal</small>"):"")+
    row("Provenance",esc(String(pk.script||"refresh_impacts.py").split(" ")[0])+"""),

# 4 -- version string -------------------------------------------------------------------
("""v1.8 results pack""",
 """v1.9 renewal & capital"""),
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
        print("usage: python patch_frontend_p6.py <v18.html> <v19.html>")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
