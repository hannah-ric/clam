"""Unit tests for the measure catalog and capital plan v2: applicability
predicates, factor-table-derived effects, cost models, phasing, and budget
selection. Pure pandas/numpy.   python3 test_catalogops.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import refresh_impacts as ri
import measures_catalog as mc


def ok(msg):
    print("ok ", msg)


def _site(**kw):
    base = {"name": "S", "asset_value_usd": 50e6, "construction": "masonry",
            "year_built": 2000, "defended": False, "roof_type": None,
            "roof_year": None, "opening_protection": None, "stories": None,
            "keys": None, "wui_class": None, "defensible_space_m": None,
            "roof_class_a": False, "equipment_elevated": False,
            "backup_power": None, "renovation_year": None}
    base.update(kw)
    return base


EAD_WET = {"tc": 5000.0, "cflood": 3000.0, "rflood": 500.0}
EAD_DRY = {"tc": 5000.0, "cflood": 0.0, "rflood": 0.0}


def _m(key):
    return next(m for m in mc.CATALOG if m["key"] == key)


def test_applicability():
    # re-roof: needs roof data; a new metal roof is already best practice
    assert not _m("reroof")["applies"](_site(), EAD_WET)[0]
    assert "roof profile data" in _m("reroof")["applies"](_site(), EAD_WET)[1]
    assert not _m("reroof")["applies"](
        _site(roof_type="metal", roof_year=2024), EAD_WET)[0]
    assert _m("reroof")["applies"](
        _site(roof_type="shingle", roof_year=2000), EAD_WET)[0]
    # elevation: high-rise excluded, low-rise wet site allowed
    assert not _m("elevate")["applies"](_site(stories=8), EAD_WET)[0]
    assert "cannot be elevated" in _m("elevate")["applies"](
        _site(stories=8), EAD_WET)[1]
    assert _m("elevate")["applies"](_site(stories=2), EAD_WET)[0]
    assert not _m("elevate")["applies"](_site(stories=2), EAD_DRY)[0]
    # openings: needs data; impact-rated already done
    assert not _m("openings")["applies"](_site(), EAD_WET)[0]
    assert not _m("openings")["applies"](
        _site(opening_protection="impact"), EAD_WET)[0]
    assert _m("openings")["applies"](
        _site(opening_protection="none"), EAD_WET)[0]
    # tiedown: pre-2002 frame yes, engineered no
    assert _m("tiedown")["applies"](
        _site(construction="frame", year_built=1990), EAD_WET)[0]
    assert not _m("tiedown")["applies"](
        _site(construction="engineered", year_built=1990), EAD_WET)[0]
    # wildfire: WUI-gated
    assert _m("defensible")["applies"](
        _site(wui_class="intermix", defensible_space_m=5), EAD_DRY)[0]
    assert not _m("defensible")["applies"](_site(), EAD_DRY)[0]
    ok("applicability: data-gated, baseline-aware, physically constrained")


def test_effects_from_factor_table():
    # re-roofing an old shingle roof: effect is exactly the factor delta
    s = _site(roof_type="shingle", roof_year=2000)
    eff = _m("reroof")["effect"](s)
    base = ri.vuln_v2("masonry", 2000, roof_type="shingle", roof_year=2000)[0]
    new = ri.vuln_v2("masonry", 2000, roof_type="metal",
                     roof_year=ri.ROOF_AGE_REF_YEAR)[0]
    assert abs(eff["wind_dmg_mult"] - new / base) < 1e-12
    assert eff["wind_dmg_mult"] < 1.0
    ok("effects: re-roof benefit is exactly the vuln_v2 factor delta")


def test_cost_models():
    per_key = _m("reroof")["cost"](_site(keys=300))
    assert per_key == 300 * 9000
    fallback = _m("reroof")["cost"](_site(keys=None))
    assert fallback == 50e6 * 2.0 / 100.0
    ok("cost models: per-key when known, value-percent fallback")


def test_catalog_effects_scope():
    df = pd.DataFrame([_site(name="A", roof_type="shingle", roof_year=2000),
                       _site(name="B", roof_type="metal", roof_year=2024)])
    ead = {"tc": np.array([5000.0, 5000.0]),
           "cflood": np.array([3000.0, 0.0]),
           "rflood": np.array([0.0, 0.0])}
    mask, knobs, costs, reasons = mc.catalog_effects(df, ead, _m("reroof"))
    assert mask.tolist() == [True, False]
    assert knobs["wind_dmg_mult"][1] == 1.0        # out of scope: neutral
    assert costs[1] == 0.0 and "best practice" in reasons[1]
    ok("catalog_effects: neutral knobs and zero cost outside scope")


def test_phasing_and_budget():
    prj = [{"site": "A", "measure_key": "reroof", "bcr": 5.0, "cost_usd": 900.0,
            "averted_direct_aal_usd": 100.0, "annuity_years": 25},
           {"site": "B", "measure_key": "openings", "bcr": 3.0, "cost_usd": 800.0,
            "averted_direct_aal_usd": 60.0, "annuity_years": 25},
           {"site": "C", "measure_key": "tiedown", "bcr": 2.0, "cost_usd": 700.0,
            "averted_direct_aal_usd": 40.0, "annuity_years": 25}]
    df = pd.DataFrame([_site(name="A"),
                       _site(name="B",
                             renovation_year=ri.ROOF_AGE_REF_YEAR + 1),
                       _site(name="C")])
    out = mc.phase_projects([dict(p) for p in prj], df, budget_annual_usd=1000.0)
    by = {p["site"]: p for p in out}
    assert by["B"]["renovation_synergy"] and by["B"]["cost_usd"] == 800.0 * mc.RENOV_SYNERGY
    assert by["B"]["year"] == 2                    # phased with the refurbishment
    assert by["A"]["year"] == 1                    # best BCR takes year 1
    assert by["C"]["year"] in (2, 3)               # fits under a later budget
    years = {}
    for p in out:
        if p["year"] is not None:
            years[p["year"]] = years.get(p["year"], 0.0) + p["cost_usd"]
    assert all(v <= 1000.0 for v in years.values())
    # a tight budget defers the worst project instead of dropping it
    tight = mc.phase_projects([dict(p) for p in prj], df, budget_annual_usd=750.0)
    assert any(p.get("deferred") for p in tight)
    assert tight[-1].get("deferred"), "deferred projects trail the plan"
    # no budget: everything lands in year 1 unless renovation-phased
    free = mc.phase_projects([dict(p) for p in prj], df, budget_annual_usd=None)
    assert all(p["year"] is not None for p in free)
    ok("phasing: renovation synergy, budget fill by BCR, deferral not deletion")


def test_renovation_year_exact_boundary():
    """The off-by-one this pins: a renovation_year exactly PLAN_YEARS out maps
    to plan year PLAN_YEARS + 1, which has no budget line. It used to crash
    the budgeted plan with KeyError (and land in a nonexistent year 4 without
    a budget); it must instead be treated as outside the renovation window."""
    ref = ri.ROOF_AGE_REF_YEAR
    prj = [{"site": "B", "measure_key": "reroof", "bcr": 5.0, "cost_usd": 900.0,
            "averted_direct_aal_usd": 100.0, "annuity_years": 25}]

    # exactly at the boundary: renovation_year = ref + PLAN_YEARS (year 4)
    df = pd.DataFrame([_site(name="B", renovation_year=ref + mc.PLAN_YEARS)])
    out = mc.phase_projects([dict(p) for p in prj], df,
                            budget_annual_usd=1000.0)   # must not KeyError
    assert out[0]["year"] in range(1, mc.PLAN_YEARS + 1), \
        "boundary case must land inside the plan, never a nonexistent year"
    assert not out[0].get("renovation_synergy"), \
        "a renovation outside the plan window earns no synergy discount"
    assert out[0]["cost_usd"] == 900.0
    free = mc.phase_projects([dict(p) for p in prj], df, budget_annual_usd=None)
    assert free[0]["year"] == 1 and not free[0].get("renovation_synergy"), \
        "without a budget the boundary case defaults to year 1, not year 4"

    # last year INSIDE the window: renovation_year = ref + PLAN_YEARS - 1
    df_in = pd.DataFrame([_site(name="B",
                                renovation_year=ref + mc.PLAN_YEARS - 1)])
    out_in = mc.phase_projects([dict(p) for p in prj], df_in,
                               budget_annual_usd=1000.0)
    assert out_in[0]["year"] == mc.PLAN_YEARS and \
        out_in[0].get("renovation_synergy"), \
        "the last in-window year still phases with the refurbishment"

    # first year of the window: a renovation in the reference year itself
    df_now = pd.DataFrame([_site(name="B", renovation_year=ref)])
    out_now = mc.phase_projects([dict(p) for p in prj], df_now,
                                budget_annual_usd=1000.0)
    assert out_now[0]["year"] == 1 and out_now[0].get("renovation_synergy")

    # far future and past renovations stay untouched by the window
    for far in (ref + mc.PLAN_YEARS + 5, ref - 1):
        df_far = pd.DataFrame([_site(name="B", renovation_year=far)])
        out_far = mc.phase_projects([dict(p) for p in prj], df_far,
                                    budget_annual_usd=1000.0)
        assert out_far[0]["year"] == 1 and not out_far[0].get("renovation_synergy")
    ok("renovation window: exact PLAN_YEARS boundary excluded, no KeyError, "
       "in-window years keep synergy")


def test_run_catalog_end_to_end():
    prep = {"wind": {"present": {"freq": np.array([0.01, 0.02]),
                                 "int": np.array([[70.0, 40.0], [45.0, 30.0]])},
                     "rcp45_2040": {"freq": np.array([0.01, 0.02]),
                                    "int": np.array([[72.0, 41.0], [46.0, 31.0]])},
                     "rcp45_2060": {"freq": np.array([0.01, 0.02]),
                                    "int": np.array([[74.0, 42.0], [47.0, 32.0]])}},
            "surge": {("rcp45_2040", "ssp245_2050"): {"int": np.array([[2.2, 0.0], [0.9, 0.0]])},
                      ("rcp45_2060", "ssp245_2050"): {"int": np.array([[2.3, 0.0], [0.95, 0.0]])}},
            "rflood": {},
            # WRC point shape (Task 3.5): burn probability + conditional
            # damage per site, not a FIRMS event set
            "wfire": {"bp": np.array([0.0, 0.008]),
                      "cond": np.array([ri.FIRE_COND_INTERIM,
                                        ri.FIRE_COND_INTERIM])}}
    sites = pd.DataFrame([
        _site(name="Wet", keys=200, stories=2, roof_type="shingle",
              roof_year=2000, opening_protection="none"),
        _site(name="Dry", keys=150, stories=6, roof_type="metal",
              roof_year=2024, wui_class="intermix", defensible_space_m=5)])
    vals = np.array([50e6, 40e6])
    wm = np.array([ri.vuln_v2(r["construction"], r["year_built"], False,
                              roof_type=r["roof_type"], roof_year=r["roof_year"],
                              opening_protection=r["opening_protection"])[0]
                   for r in sites.to_dict("records")])
    fbc, fbr = np.full(2, ri.FB_COAST), np.full(2, ri.FB_RIVER)
    fcap = np.full(2, ri.FLOOD_CAP_DEFAULT)
    fvuln = np.array([ri.fire_vuln_of(r["roof_class_a"],
                                      r["defensible_space_m"])
                      for r in sites.to_dict("records")])
    base = {"ssp245_2050": ri.eval_scenario(prep, "ssp245_2050", vals, wm,
                                            fbc, fbr, flood_cap=fcap,
                                            fire_vuln=fvuln)}
    section, projects, sc = ri.run_catalog(prep, sites, vals, wm, fbc, fbr,
                                           fcap, base, fire_vuln=fvuln)
    assert sc == "ssp245_2050"
    assert "reroof" in section["modeled"]
    assert section["modeled"]["reroof"]["sites_in_scope"] == 1
    assert any(e["site"] == "Dry" and "best practice" in e["reason"]
               for e in section["modeled"]["reroof"]["excluded"])
    assert "defensible" in section["modeled"], \
        "wildfire measures are now priced against the fire event layer"
    assert section["modeled"]["defensible"]["sites_in_scope"] == 1
    dfp = next(p for p in projects if p["measure_key"] == "defensible")
    assert dfp["site"] == "Dry" and dfp["bcr"] > 0 \
        and dfp["averted_direct_aal_usd"] > 0
    fire_base = base["ssp245_2050"]["wfire"]["ead"][1]
    assert abs(dfp["averted_direct_aal_usd"]
               - round(float(fire_base) * (1 - ri.FIRE_DEFENSIBLE), 2)) <= 0.02, \
        "defensible-space benefit is exactly the fire factor delta"
    assert any(i["key"] == "backup_power" for i in section["identified"])
    assert projects and all(p["averted_direct_aal_usd"] >= 0 for p in projects)
    bcrs = [p["bcr"] for p in projects]
    assert bcrs == sorted(bcrs, reverse=True)
    assert not any(p["site"] == "Dry" and p["peril"] == "flood"
                   for p in projects), "dry site gets no flood projects"
    an = ri.annuity(min(40, ri.HORIZON_YEARS), ri.DISCOUNT_RATE)
    top = next(p for p in projects if p["measure_key"] == "reroof")
    assert abs(top["bcr"] - round(top["averted_direct_aal_usd"] * an
                                  / top["cost_usd"], 3)) <= 0.001
    ok("run_catalog: modeled + identified, scoping, ranking, lifecycle BCR")


if __name__ == "__main__":
    test_applicability()
    test_effects_from_factor_table()
    test_cost_models()
    test_catalog_effects_scope()
    test_phasing_and_budget()
    test_renovation_year_exact_boundary()
    test_run_catalog_end_to_end()
    print("\nALL CATALOG-OP TESTS PASSED")
