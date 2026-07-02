"""Unit tests for Phase 2 selection logic and Phase 3 heat math.
No CLIMADA/xarray needed. python3 test_phase23_ops.py"""
import types

import numpy as np
import pandas as pd

import refresh_hazard as rh
import refresh_heat as hh


# ---------------------------------------------------------------------------
# Phase 2: rf_year_of / rf_pick against both API tagging vocabularies
# ---------------------------------------------------------------------------

def info(name, **props):
    return types.SimpleNamespace(name=name, properties=props)


def test_rf_year_of():
    assert rh.rf_year_of(info("x", ref_year="2040")) == 2040
    assert rh.rf_year_of(info("x", year_range="2030_2050")) == 2040
    assert rh.rf_year_of(info("river_flood_150arcsec_rcp60_USA_2070_2090")) == 2080
    assert rh.rf_year_of(info("nodate")) is None
    print("ok  rf_year_of: ref_year, year_range, name-parse fallback")


def test_rf_pick_prefers_rcp45_else_rcp60():
    # release WITH rcp45: ssp245 must take it
    infos = [info("a", climate_scenario="rcp45", ref_year="2050"),
             info("b", climate_scenario="rcp60", ref_year="2050")]
    got, scen, _ = rh.rf_pick(infos, "ssp245_2050")
    assert scen == "rcp45" and [i.name for i in got] == ["a"]
    # release WITHOUT rcp45 (ISIMIP2b reality): fall through to rcp60
    infos = [info("b", climate_scenario="rcp60", ref_year="2050"),
             info("c", climate_scenario="rcp85", ref_year="2050")]
    got, scen, _ = rh.rf_pick(infos, "ssp245_2050")
    assert scen == "rcp60" and [i.name for i in got] == ["b"]
    print("ok  rf_pick: ssp245 -> rcp45 when offered, rcp60 otherwise")


def test_rf_pick_nearest_year_and_ensemble_cap():
    infos = [info(f"m{k}", climate_scenario="rcp85", year_range="2030_2050")
             for k in range(6)] + \
            [info("far", climate_scenario="rcp85", year_range="2070_2090")]
    got, scen, _ = rh.rf_pick(infos, "ssp585_2050", max_models=4)
    assert len(got) == 4 and all("m" in i.name for i in got), \
        "must take nearest year group (mid 2040) and cap the ensemble"
    got80, _, _ = rh.rf_pick(infos, "ssp585_2080")
    assert [i.name for i in got80] == ["far"]
    # present maps to historical tagging variants
    infos_h = [info("h", climate_scenario="historical", year_range="1980_2000")]
    got_p, scen_p, _ = rh.rf_pick(infos_h, "present")
    assert scen_p == "historical" and got_p[0].name == "h"
    # nothing available -> empty, layer skipped upstream
    assert rh.rf_pick([], "ssp126_2030")[0] == []
    print("ok  rf_pick: nearest-year selection, ensemble cap, historical, empty")


# ---------------------------------------------------------------------------
# Phase 3: HeatAccumulator against brute force, NaN masking, encoding
# ---------------------------------------------------------------------------

def brute(tmax_years, tmean_years, delta):
    """Reference implementation: literally shift the dailies and count."""
    d32 = d35 = cdd = 0.0
    for tx, tm in zip(tmax_years, tmean_years):
        d32 += ((tx + delta) > hh.THRESH_HOT).sum(axis=0)
        d35 += ((tx + delta) > hh.THRESH_DANGER).sum(axis=0)
        cdd += np.maximum((tm + delta) - hh.CDD_BASE, 0).sum(axis=0)
    n = len(tmax_years)
    return d32 / n, d35 / n, cdd / n


def test_accumulator_matches_bruteforce():
    rng = np.random.default_rng(7)
    shape = (365, 4, 5)
    tmax_years = [rng.normal(30, 6, shape) for _ in range(3)]
    tmean_years = [t - 4.0 for t in tmax_years]
    deltas = hh.scen_deltas()
    acc = hh.HeatAccumulator(deltas, shape[1:])
    for tx, tm in zip(tmax_years, tmean_years):
        acc.add_year(tx, tm)
    out = acc.finalize()
    for sc, d in deltas.items():
        b32, b35, bcdd = brute(tmax_years, tmean_years, d)
        assert np.allclose(out[sc]["days32"], b32), sc
        assert np.allclose(out[sc]["days35"], b35), sc
        assert np.allclose(out[sc]["cdd"], bcdd, atol=1e-9), sc
    # warming must monotonically raise every indicator everywhere
    assert (out["ssp585_2080"]["days35"] >= out["present"]["days35"]).all()
    assert (out["ssp585_2080"]["cdd"] >= out["present"]["cdd"]).all()
    print("ok  HeatAccumulator: threshold-shift == brute-force shift, all scenarios")


def test_accumulator_nan_ocean():
    shape = (10, 2, 2)
    tx = np.full(shape, 33.0); tx[:, 0, 0] = np.nan           # ocean cell
    tm = np.full(shape, 25.0); tm[:, 0, 0] = np.nan
    acc = hh.HeatAccumulator(hh.scen_deltas(), shape[1:])
    acc.add_year(tx, tm)
    out = acc.finalize()
    assert np.isnan(out["present"]["days32"][0, 0])
    assert np.isfinite(out["present"]["days32"][1, 1])
    la2, lo2 = np.meshgrid([10.0, 10.5], [20.0, 20.5], indexing="ij")
    rows = hh.indicators_to_rows(la2, lo2, out)
    n_sc = len(hh.WARMING)
    assert len(rows) == 3 * n_sc, "NaN cell must be dropped, 3 land cells remain"
    assert set(rows["hazard"]) == {"heat"}
    assert (rows[["v100", "v250", "v500"]].to_numpy() == 0).all()
    # encoding: v10 days32 >= v25 days35
    assert (rows["v10"] >= rows["v25"]).all()
    print("ok  indicators_to_rows: NaN drop, Option A encoding, v10>=v25")


def test_deltas_and_lon():
    d = hh.scen_deltas(1.25)
    assert d["present"] == 0.0
    assert np.isclose(d["ssp585_2080"], 3.6 * 1.25)
    assert d["ssp126_2030"] < d["ssp245_2050"] < d["ssp585_2080"]
    lon = hh.to_pm180(np.array([0.25, 179.75, 180.25, 359.75]))
    assert np.allclose(lon, [0.25, 179.75, -179.75, -0.25])
    print("ok  scen_deltas mirrors app WARMING x land amp; lon 0..360 -> -180..180")


def test_heat_meta_shape():
    import pandas as pd
    df = pd.DataFrame({"scenario": ["present", "present", "ssp585_2080"],
                       "hazard": "heat", "lat": 0, "lon": 0})
    m = hh.heat_meta(df, [2005, 2024])
    assert m["script"].startswith("refresh_heat.py")
    assert m["years"] == [2005, 2024] and m["method"]
    lay = {(l["scenario"], l["cells"]) for l in m["layers"]}
    assert lay == {("present", 2), ("ssp585_2080", 1)}
    assert m["deltas_c"]["ssp585_2080"] == round(3.6 * 1.25, 3)
    print("ok  heat_meta: script, years, per-scenario layer counts, deltas")


if __name__ == "__main__":
    test_rf_year_of()
    test_rf_pick_prefers_rcp45_else_rcp60()
    test_rf_pick_nearest_year_and_ensemble_cap()
    test_accumulator_matches_bruteforce()
    test_accumulator_nan_ocean()
    test_deltas_and_lon()
    test_heat_meta_shape()
    print("\nALL PHASE 2-3 OP TESTS PASSED")
