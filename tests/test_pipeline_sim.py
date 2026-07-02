"""End-to-end simulation of refresh_hazard.py with CLIMADA mocked out.

Exercises the real process_country/main plumbing: source fetching with one
deliberately FAILING source (rcp26_2060), surge computed on a COASTAL SUBSET
of centroids (as Petals may do), blending, alignment, CSV + meta writing.
Then validate_grid.py must pass the output. python3 test_pipeline_sim.py
"""
import json
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

import refresh_hazard as rh

RPS = rh.RETURN_PERIODS

# ---- synthetic world: 3 coastal + 2 inland centroids per country -----------
LAT = np.array([25.00, 25.25, 29.25, 30.00, 29.50])
LON = np.array([-80.00, -80.00, -94.75, -95.00, -98.50])
COASTAL = np.array([True, True, True, False, False])

# wind climate: base v100 per centroid, uplift per source
BASE_V100 = np.array([60.0, 58.0, 55.0, 40.0, 30.0])
UPLIFT = {"present": 1.00,
          "rcp26_2040": 1.02, "rcp26_2060": 1.03, "rcp26_2080": 1.03,
          "rcp45_2040": 1.03, "rcp45_2060": 1.05, "rcp45_2080": 1.08,
          "rcp85_2040": 1.05, "rcp85_2060": 1.09, "rcp85_2080": 1.16}
RP_SHAPE = {10: 0.6, 25: 0.75, 50: 0.88, 100: 1.0, 250: 1.15, 500: 1.25}
FAIL_SOURCES = {"rcp26_2060"}          # simulate a Data API miss


class FakeCentroids:
    def __init__(self, lat, lon):
        self.lat, self.lon = lat, lon


class FakeHaz:
    def __init__(self, kind, skey, slr=0.0, subset=None):
        idx = np.arange(len(LAT)) if subset is None else np.where(subset)[0]
        self.centroids = FakeCentroids(LAT[idx], LON[idx])
        self._rp = np.zeros((len(RPS), len(idx)))
        for i, rp in enumerate(RPS):
            if kind == "wind":
                self._rp[i] = BASE_V100[idx] * UPLIFT[skey] * RP_SHAPE[rp]
            else:  # surge: SLOSH-ish linear from wind, minus fake 1m elevation, + SLR
                v = BASE_V100[idx] * UPLIFT[skey] * RP_SHAPE[rp]
                self._rp[i] = np.maximum(0.10 * (v - 26.0) - 1.0 + slr, 0.0)


def fake_fetch_wind(iso3, source, meta):
    skey = rh.source_key(source)
    if skey in FAIL_SOURCES:
        raise RuntimeError(f"simulated: no single dataset match for {skey}")
    meta.setdefault("wind_sources", {})[f"{iso3}:{skey}"] = {
        "data_type": "tropical_cyclone",
        "properties_matched": {"simulated": True, "source": skey}}
    h = FakeHaz("wind", skey)
    h._skey = skey
    return h


def fake_compute_surge(wind_haz, slr):
    # Petals-style behaviour: returns a hazard on the COASTAL SUBSET only,
    # forcing align_to_cells to restore inland zeros.
    return FakeHaz("surge", wind_haz._skey, slr=slr, subset=COASTAL)


def fake_local_rp(haz, rps):
    return haz._rp


RF_MISSING = {("USA", "ssp126_2030")}      # simulate one absent API dataset

def fake_fetch_river_flood_grid(iso3, app_key, meta):
    if (iso3, app_key) in RF_MISSING:
        return None, {"reason": "simulated: no river_flood dataset"}
    # depth grows mildly with warming; only the two inland-ish cells are wet,
    # and coverage is DELIBERATELY partial (wet cells only) to force alignment
    up = {"present": 1.0}.get(app_key, 1.0 + 0.1 * rh.SLR_M.get(app_key, 0) / 0.62)
    import pandas as pd
    rows = []
    for (la, lo), d100 in (((29.25, -94.75), 0.9), ((29.5, -98.5), 1.4)):
        r = {"lat": la, "lon": lo}
        for rp, sh in zip(RPS, (0.3, 0.55, 0.8, 1.0, 1.3, 1.55)):
            r[f"v{rp}"] = d100 * sh * up
        rows.append(r)
    return pd.DataFrame(rows), {"climate_scenario_matched": "rcp60",
                                "members": [{"dataset_name": "sim_model"}]}


def run():
    rh.fetch_wind = fake_fetch_wind
    rh.compute_surge = fake_compute_surge
    rh.local_rp_intensity = fake_local_rp
    rh.fetch_river_flood_grid = fake_fetch_river_flood_grid
    dem = Path("fake_dem.tiff"); dem.write_bytes(b"\0" * 16)
    rh.TOPO_PATH = dem

    rc = rh.main(["--countries", "USA", "--out", "sim_hazard_grid.csv"])
    assert rc == 0, "pipeline returned nonzero"

    df = pd.read_csv("sim_hazard_grid.csv")
    meta = json.loads(Path("sim_hazard_grid_meta.json").read_text())

    # 1. schema and key coverage
    assert list(df.columns) == ["lat", "lon", "scenario", "hazard"] + [f"v{rp}" for rp in RPS]
    app_keys = set(rh.APP_SCENARIOS)
    assert set(df["scenario"]) == app_keys, "every app scenario key must be present"
    assert set(df["hazard"]) == {"tc", "cflood", "rflood"}

    # 2. failed source degrades gracefully: ssp126_2050 = blend(rcp26_2040, FAILED)
    #    must still exist, carried by rcp26_2040 alone via weight renormalisation
    sub = df[(df.hazard == "tc") & (df.scenario == "ssp126_2050")]
    assert len(sub) > 0
    got = sub[np.isclose(sub.lat, 25.0) & np.isclose(sub.lon, -80.0)]["v100"].iloc[0]
    assert np.isclose(got, 60.0 * UPLIFT["rcp26_2040"], atol=0.02), got
    skipped = [s for s in meta["skipped"] if s.get("source") == "rcp26_2060"]
    assert skipped, "the failed source must be recorded in meta.skipped"

    # 3. blend arithmetic: ssp585_2050 wind = mean of rcp85_2040 and rcp85_2060
    sub = df[(df.hazard == "tc") & (df.scenario == "ssp585_2050")]
    got = sub[np.isclose(sub.lat, 25.0)].sort_values("lon")["v100"].iloc[0]
    want = 60.0 * (UPLIFT["rcp85_2040"] + UPLIFT["rcp85_2060"]) / 2
    assert np.isclose(got, want, atol=0.02), (got, want)

    # 4. surge: inland cells exist as explicit zeros; coastal cells wet; SLR raises them
    cf = df[df.hazard == "cflood"]
    for sc in rh.APP_SCENARIOS:
        s = cf[cf.scenario == sc]
        assert len(s) == len(df[(df.hazard == "tc") & (df.scenario == sc)]), \
            "cflood coverage must equal tc coverage (inland zeros)"
        inland = s[np.isclose(s.lat, 29.5)]
        assert np.allclose(inland[[f"v{rp}" for rp in RPS]].to_numpy(), 0.0)
    d_now = cf[(cf.scenario == "present") & np.isclose(cf.lat, 25.0)]["v100"].iloc[0]
    d_fut = cf[(cf.scenario == "ssp585_2080") & np.isclose(cf.lat, 25.0)]["v100"].iloc[0]
    assert d_fut > d_now > 0, (d_now, d_fut)
    # SLR + wind uplift both enter: future minus present exceeds SLR alone
    assert d_fut - d_now >= rh.SLR_M["ssp585_2080"] - 0.03

    # 4b. rflood: partial-coverage input restored to full coverage with dry zeros;
    #     the simulated missing dataset is skipped and recorded, not fatal
    rf = df[df.hazard == "rflood"]
    assert set(rf.scenario) == set(rh.APP_SCENARIOS) - {"ssp126_2030"}
    for sc in rf.scenario.unique():
        s = rf[rf.scenario == sc]
        assert len(s) == len(df[(df.hazard == "tc") & (df.scenario == sc)]),             "rflood coverage must equal tc coverage (dry zeros)"
        coast = s[np.isclose(s.lat, 25.0)]
        assert np.allclose(coast[[f"v{rp}" for rp in RPS]].to_numpy(), 0.0),             "cells the flood model was silent about must be explicit zeros"
    wet = rf[(rf.scenario == "present") & np.isclose(rf.lat, 29.5)]["v100"].iloc[0]
    assert np.isclose(wet, 1.4, atol=0.02)
    assert any(s.get("layer") == "rflood" for s in meta["skipped"])
    print("ok  rflood sim: dry zeros restored, missing dataset skipped gracefully")

    # 4c. heat layer: synthetic climatology through the real Phase 3 code path,
    #     merged into the same CSV via merge_grids.py
    import refresh_heat as hh
    rng = np.random.default_rng(3)
    shape = (365, 3, 3)
    la2, lo2 = np.meshgrid([25.0, 29.5, 33.75], [-80.0, -98.5, -116.5], indexing="ij")
    hot_bias = np.array([[2, 6, 9]] * 3)          # inland/desert columns hotter
    acc = hh.HeatAccumulator(hh.scen_deltas(), shape[1:])
    for _ in range(3):
        tx = rng.normal(28, 5, shape) + hot_bias
        acc.add_year(tx, tx - 4.0)
    heat_rows = hh.indicators_to_rows(la2, lo2, acc.finalize())
    heat_rows.to_csv("sim_heat_grid.csv", index=False)
    Path("sim_heat_grid_meta.json").write_text(
        json.dumps(hh.heat_meta(heat_rows, [2005, 2024])))
    import subprocess
    m = subprocess.run([sys.executable, "merge_grids.py", "sim_hazard_grid.csv",
                        "sim_heat_grid.csv", "-o", "sim_hazard_grid.csv"],
                       capture_output=True, text=True)
    assert m.returncode == 0, m.stderr
    df = pd.read_csv("sim_hazard_grid.csv")
    ht = df[df.hazard == "heat"]
    assert set(ht.scenario) == set(rh.APP_SCENARIOS)
    d35_now = ht[(ht.scenario == "present")]["v25"].mean()
    d35_fut = ht[(ht.scenario == "ssp585_2080")]["v25"].mean()
    assert d35_fut > d35_now, "warming must raise days>35C"
    print("ok  heat sim: real accumulator path, merged into one CSV, signal present")

    # 4d. Phase 4: the merge combined both provenance sidecars
    cmeta = json.loads(Path("sim_hazard_grid_meta.json").read_text())
    assert cmeta.get("combined") is True and len(cmeta["sources"]) == 2, \
        "combined meta must carry both producers"
    claimed = {(l.get("hazard"), l.get("scenario")) for l in cmeta["layers"]}
    assert ("heat", "present") in claimed and ("tc", "ssp585_2080") in claimed
    assert any(s.get("method") for s in cmeta["sources"]), "heat method recorded"
    assert any((s.get("surge") or {}).get("dem_path") for s in cmeta["sources"]), \
        "DEM path recorded"
    # re-running the merge must flatten, not nest, the combined meta
    m2 = subprocess.run([sys.executable, "merge_grids.py", "sim_hazard_grid.csv",
                         "-o", "sim_hazard_grid.csv"], capture_output=True, text=True)
    assert m2.returncode == 0, m2.stderr
    cmeta2 = json.loads(Path("sim_hazard_grid_meta.json").read_text())
    assert len(cmeta2["sources"]) == 2 and not any(
        "sources" in s for s in cmeta2["sources"]), "re-merge stays flat"
    print("ok  Phase 4 merge: combined sidecar, layers union, idempotent re-merge")

    # 4e. Phase 4: validator cross-checks meta against CSV
    r4 = subprocess.run([sys.executable, "validate_grid.py", "sim_hazard_grid.csv",
                         "sim_hazard_grid_meta.json"], capture_output=True, text=True)
    assert r4.returncode == 0 and "meta layers and CSV layers agree" in r4.stdout, \
        "validator must pass the consistent meta"
    ghost = dict(cmeta2)
    ghost["layers"] = cmeta2["layers"] + [{"hazard": "wildfire",
                                           "scenario": "present", "cells": 9}]
    Path("sim_ghost_meta.json").write_text(json.dumps(ghost))
    r5 = subprocess.run([sys.executable, "validate_grid.py", "sim_hazard_grid.csv",
                         "sim_ghost_meta.json"], capture_output=True, text=True)
    assert r5.returncode == 1 and "meta claims layers absent" in r5.stdout, \
        "validator must hard-fail a meta that overstates coverage"
    print("ok  Phase 4 validator: consistent meta passes, ghost layers hard-fail")

    # 5. meta completeness
    assert meta["surge"]["enabled"] is True
    assert meta.get("climada_version") is None            # absent in sim, expected
    assert len(meta["layers"]) == 3 * len(app_keys) - 1  # tc+cflood per key, rflood minus 1 missing
    print("ok  pipeline sim: schema, keys, graceful source failure, blend math, "
          "inland zeros, SLR signal, meta layers")

    # 6. the validator must pass this grid...
    import subprocess
    r = subprocess.run([sys.executable, "validate_grid.py", "sim_hazard_grid.csv"],
                       capture_output=True, text=True)
    print("\n--- validate_grid.py on simulated output ---")
    print(r.stdout)
    assert r.returncode == 0, "validator must accept the simulated grid"

    # 7. ...and must REJECT a v1-style grid (present-only, no hazard column),
    #    built here as a fixture so this gate is real on every machine, not
    #    just where the originally deployed file happened to live
    v1 = df[df.scenario == "present"].drop(columns=["hazard"])
    v1.to_csv("sim_v1_grid.csv", index=False)
    r2 = subprocess.run([sys.executable, "validate_grid.py", "sim_v1_grid.csv"],
                        capture_output=True, text=True)
    print("--- validate_grid.py on a v1-style present-only grid ---")
    print(r2.stdout)
    assert r2.returncode == 1, "validator must reject the v1 present-only grid"
    assert "ONLY the present scenario" in r2.stdout, \
        "rejection must be for the right reason, not an incidental crash"
    print("ok  validator: accepts v2 output, rejects a v1-style grid for the "
          "right reason")
    print("\nALL PIPELINE SIMULATION TESTS PASSED")


if __name__ == "__main__":
    run()
