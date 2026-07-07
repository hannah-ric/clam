"""Cross-file contract, registry edition. The scenario constants (WARMING,
regional SLR, scenario scalars, appraisal convention) live ONCE in
pipeline/assumptions.py; every producer imports that module and the app
embeds a GENERATED module (app/src/05_assumptions.js). This gate asserts:

  1. registry self-consistency: every effective value equals its AR6 central
     plus its EXPLICIT conservative delta, and every entry carries units, a
     baseline period, and a citation (no silently higher numbers);
  2. producer aliasing: refresh_heat / refresh_wildfire / refresh_prain /
     refresh_hazard / refresh_impacts read the registry objects, not copies;
  3. app sync: the generated JS module matches assumptions.py byte for byte
     AND is embedded verbatim in the deployable HTML, whose tables parse
     back to the registry's effective values;
  4. appraisal unification: pack constants and app slider defaults both read
     the registry (3% real / 25 years, comparable BCRs);
  5. the vulnerability and damage constants the results pack shares with the
     app (refresh_impacts.py) remain mirrored exactly, as before.

    python3 test_warming_parity.py
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import assumptions as A
import refresh_hazard as rh
import refresh_heat as hh
import refresh_impacts as ri
import refresh_prain as rp
import refresh_wildfire as rw


def deployable():
    """Highest-versioned app file: the one users open."""
    def ver(p):
        m = re.search(r"_v(\d+)\.html$", p.name)
        return int(m.group(1)) if m else -1
    apps = sorted(ROOT.glob("app/TNL_Resort_Climate_Risk_Explorer*.html"),
                  key=ver)
    return apps[-1]


def extract_json_const(html, name):
    """Parse a generated `const NAME={...};` JSON block (quoted keys)."""
    m = re.search(re.escape(name) + r"=(\{.*?\});", html)
    assert m, f"{name} not found in the app"
    return json.loads(m.group(1))


def extract_js_scalar(html, name):
    """Parse the first `NAME=<number>` assignment into a float."""
    m = re.search(r"\b" + re.escape(name) + r"\s*=\s*([0-9]+(?:\.[0-9]+)?)", html)
    assert m, f"{name} scalar not found in the app"
    return float(m.group(1))


def check_registry_self_consistency():
    for sc, e in A.WARMING.items():
        assert abs(e["value"] - round(e["ar6_central"]
                                      + e["conservative_delta"], 6)) < 1e-9, \
            f"WARMING[{sc}]: effective != ar6_central + delta"
        assert e["units"] and e["baseline"] and e["citation"], \
            f"WARMING[{sc}]: missing units/baseline/citation"
        if e["conservative_delta"]:
            assert len(e.get("delta_reason", "")) > 20, \
                f"WARMING[{sc}]: a nonzero delta needs a real reason"
    print("ok  WARMING registry: AR6 central + explicit delta, all cited")
    for region, tab in A.SLR.items():
        f = A.SLR_REGION_FACTOR[region][0]
        for sc, e in tab.items():
            want = round((e["ar6_central"] + e["conservative_delta"]) * f, 2)
            assert abs(e["value"] - want) < 1e-9, \
                f"SLR[{region}][{sc}]: effective != (central + delta) x factor"
            assert e["units"] and e["baseline"] and e["citation"]
    assert A.SLR_TABLES["gulf"]["ssp585_2080"] \
        > A.SLR_TABLES["florida_atlantic"]["ssp585_2080"] \
        > A.SLR_TABLES["global_mean"]["ssp585_2080"] * 0.99, \
        "regional ordering: gulf above florida_atlantic above/at global mean"
    print("ok  SLR registry: regional tables cited, deltas explicit, ordered")
    for k, e in A.SCALARS.items():
        assert e["units"] and e["baseline"] and e["citation"], k
    for k, e in A.APPRAISAL.items():
        assert e["units"] and e["citation"], k
    print("ok  scalars and appraisal entries all carry units and citations")
    # archetypes: a documented default that is exactly neutral, sane bounds
    assert 6 <= len(A.ARCHETYPES) <= 10, "6 to 10 resort archetypes"
    d = A.ARCHETYPES[A.DEFAULT_ARCHETYPE]
    assert d["v_half_mult"] == 1.0 and d["fb_add_m"] == 0.0 \
        and d["flood_cap"] is None, \
        "the default archetype must reproduce the published curve exactly"
    for k, a in A.ARCHETYPES.items():
        assert a["label"] and a["basis"] and a["citation"], k
        assert 0.8 <= a["v_half_mult"] <= 1.5, k
        assert -0.3 <= a["fb_add_m"] <= 1.0, \
            f"{k}: fb_add below -0.3 would push effective freeboard negative"
        assert a["flood_cap"] is None or 0.0 < a["flood_cap"] <= 1.0, k
    print("ok  archetypes: neutral default, bounded curve shifts, all cited")
    # wildfire conditional-damage assumptions (Task 3.5)
    fci = A.SCALARS["fire_cond_interim"]
    assert 0 < fci["value"] < 0.6, \
        "the interim conditional ratio must sit below the retired flat 0.6"
    assert "interim" in fci["citation"].lower()
    m = A.FIRE_CFL_DAMAGE
    assert len(m["ratios"]) == len(m["bands_ft"]) + 1 and m["citation"]
    assert all(m["ratios"][i] < m["ratios"][i + 1]
               for i in range(len(m["ratios"]) - 1)), \
        "conditional damage must rise with flame length"
    assert list(A.cfl_to_damage([1.0, 3.0, 6.0, 10.0, 40.0])) == m["ratios"], \
        "the band lookup maps each flame-length class to its ratio"
    print("ok  fire conditional damage: interim ratio capped below 0.6, "
          "CFL bands monotone and cited")


def check_producer_aliasing():
    assert hh.WARMING is A.WARMING_TABLE, "refresh_heat mirrors WARMING"
    assert rw.WARMING is A.WARMING_TABLE, "refresh_wildfire mirrors WARMING"
    assert rp.WARMING is A.WARMING_TABLE, "refresh_prain mirrors WARMING"
    assert rh.SLR_M is A.SLR_TABLES["global_mean"], \
        "refresh_hazard mirrors SLR instead of reading the registry"
    assert rh.SLR_REGIONS is A.SLR_TABLES
    assert hh.LAND_AMPLIFICATION == A.scalar("heat_land_amplification")
    assert rw.FIRE_WARMING_UPLIFT == A.scalar("fire_warming_uplift_per_c")
    assert rp.PRAIN_CC_PER_C == A.scalar("prain_cc_per_c")
    disc, horizon = A.appraisal_defaults()
    assert ri.DISCOUNT_RATE == disc and ri.HORIZON_YEARS == horizon, \
        "the pack's appraisal must read the registry"
    print("ok  every producer reads the registry objects (no mirrored copies)")


def check_app_sync(html):
    gen = (ROOT / "app/src/05_assumptions.js").read_text()
    assert gen == A.to_app_js(), \
        "05_assumptions.js drifted from assumptions.py: regenerate with " \
        "python pipeline/assumptions.py --write-app"
    assert gen in html, "the deployable HTML does not embed the generated " \
                        "assumptions module verbatim (reassemble the app)"
    print("ok  generated app module in sync and embedded verbatim")

    app_warming = extract_json_const(html, "const WARMING")
    assert app_warming == A.WARMING_TABLE, "WARMING drifted in the app"
    app_slr = extract_json_const(html, "const SLR_REGIONS")
    assert app_slr == {r: {k: A.SLR_TABLES[r][k] for k in A.SCEN_KEYS}
                       for r in A.SLR_TABLES}, "SLR_REGIONS drifted in the app"
    print("ok  app WARMING and regional SLR parse back to the registry values")

    disc, horizon = A.appraisal_defaults()
    m = re.search(r'id="horizon"[^>]*\bvalue="(\d+)"', html)
    assert m and int(m.group(1)) == horizon, \
        "app horizon slider default must equal the registry horizon"
    m = re.search(r'id="disc"[^>]*\bvalue="([\d.]+)"', html)
    assert m and abs(float(m.group(1)) - disc * 100) < 1e-9, \
        "app discount slider default must equal the registry rate"
    apd = extract_json_const(html, "const APPRAISAL_DEFAULTS")
    assert apd == {"discountPct": disc * 100, "horizonYears": horizon}
    print(f"ok  appraisal unified: pack and app defaults both "
          f"{disc:.0%} / {horizon}y (comparable BCRs)")


def check_vuln_constants(html):
    # vulnerability / damage constants shared with the results pack
    assert not re.search(r"\bconst\s+FIRE_MDD\s*=", html), \
        "the flat FIRE_MDD is retired; the app must not define it"
    for name, val in (("V_THRESH", ri.V_THRESH), ("V_HALF", ri.V_HALF),
                      ("FB_COAST", ri.FB_COAST), ("FB_RIVER", ri.FB_RIVER),
                      ("FIRE_COND_INTERIM", ri.FIRE_COND_INTERIM),
                      ("FIRE_WARMING_UPLIFT", rw.FIRE_WARMING_UPLIFT),
                      ("PRAIN_DRAIN_MM", ri.PRAIN_DRAIN_MM),
                      ("PRAIN_POND_COEFF", ri.PRAIN_POND_COEFF),
                      ("PRAIN_FB", ri.PRAIN_FB)):
        assert extract_js_scalar(html, name) == float(val), \
            f"{name} drifted between the app and the pipeline"
        print(f"ok  {name} identical: app == pipeline")
    m = re.search(r"const CONSTR_FACTOR\s*=\s*\{(.*?)\};", html, re.S)
    assert m, "CONSTR_FACTOR not found in the app"
    body = re.sub(r"(\w+):", r'"\1":', "{" + m.group(1) + "}")
    assert json.loads(body) == {k: float(v)
                                for k, v in ri.CONSTR_FACTOR.items()}, \
        "CONSTR_FACTOR drifted between the app and refresh_impacts"
    print("ok  CONSTR_FACTOR identical: app == refresh_impacts")


def main():
    app = deployable()
    html = app.read_text()
    print(f"deployable: {app.name}")
    check_registry_self_consistency()
    check_producer_aliasing()
    check_app_sync(html)
    check_vuln_constants(html)
    print("\nALL ASSUMPTIONS-REGISTRY PARITY CHECKS PASSED")


if __name__ == "__main__":
    main()
