"""Increment 3 tests: the wildfire and TC-rainfall grid producers, pure ops
and end-to-end with every CLIMADA seam mocked, through merge_grids and the
extended validate_grid gate. Run from pipeline/:
    PYTHONPATH=. python3 ../tests/test_newperils.py
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import refresh_hazard as rh
import refresh_wildfire as rw
import refresh_prain as rp


def ok(msg):
    print("ok ", msg)


# --- pure ops -----------------------------------------------------------------

def test_burn_probability():
    freq = np.array([0.02, 0.03])
    hits = np.array([[True, False], [True, False]])
    p = rw.burn_probability(freq, hits)
    assert abs(p[0] - (1 - np.exp(-0.05))) < 1e-12
    assert p[1] == 0.0
    ok("burn_probability: Poisson rate to probability, unburned cell zero")


def test_scenario_uplift():
    p = np.array([0.01, 0.9])
    up = rw.scenario_pburn(p, 3.6)
    assert abs(up[0] - 0.01 * (1 + 0.14 * 3.6)) < 1e-12
    assert up[1] <= 1.0
    ok("scenario_pburn: warming uplift applied, capped at 1")


def test_wfire_rows_encoding():
    lat = np.array([30.0, 30.0, 34.0])
    lon = np.array([-98.5, -98.51, -116.5])
    p = np.array([0.004, 0.006, 0.02])
    rows = rw.wfire_rows(lat, lon, p)
    assert set(rows["scenario"]) == set(rw.WARMING)
    per_sc = rows.groupby("scenario").size()
    assert per_sc.nunique() == 1, "one shared cell set across scenarios"
    assert (rows[["v25", "v50", "v100", "v250", "v500"]].to_numpy() == 0).all()
    now = rows[rows.scenario == "present"]["v10"].mean()
    fut = rows[rows.scenario == "ssp585_2080"]["v10"].mean()
    assert fut > now > 0
    assert rows["v10"].max() <= 100.0
    ok("wfire_rows: indicator encoding, shared cells, rising signal, percent")


def test_prain_scaling():
    assert abs(rp.cc_scale(2.0) - 1.14) < 1e-12
    present = pd.DataFrame({"lat": [29.5], "lon": [-98.5],
                            "v10": [120.0], "v25": [180.0], "v50": [240.0],
                            "v100": [310.0], "v250": [420.0], "v500": [500.0]})
    rows = rp.prain_rows(present)
    assert set(rows["scenario"]) == set(rp.WARMING)
    r85 = rows[rows.scenario == "ssp585_2080"].iloc[0]
    assert abs(r85["v100"] - round(310.0 * rp.cc_scale(3.6), 1)) < 1e-9
    v = rows[[f"v{x}" for x in rh.RETURN_PERIODS]].to_numpy()
    assert (np.diff(v, axis=1) >= 0).all(), "scaling preserves monotonicity"
    ok("prain_rows: Clausius-Clapeyron scaling, monotone RP field")


# --- producers end-to-end with mocked seams ------------------------------------

class FakeFire:
    def __init__(self):
        class C:
            lat = np.array([30.0, 30.2, 34.0, 34.2])
            lon = np.array([-98.5, -98.6, -116.5, -116.6])
        self.centroids = C()
        self.frequency = np.full(20, 0.01)
        rng = np.random.default_rng(5)
        burn = rng.random((20, 4)) < np.array([0.05, 0.08, 0.30, 0.25])
        self.intensity = burn.astype(float) * 320.0     # FIRMS-like Kelvin


class FakeRainHaz:
    def __init__(self):
        class C:
            lat = np.array([29.4, 29.6, 30.0])
            lon = np.array([-98.5, -98.4, -95.0])
        self.centroids = C()
        self.frequency = np.full(30, 1 / 30.0)


def run():
    rw.fetch_wildfire_hazard = lambda iso3: FakeFire()
    rc = rw.main(["--countries", "USA", "--out", "sim_wfire_grid.csv"])
    assert rc == 0
    wf = pd.read_csv("sim_wfire_grid.csv")
    assert set(wf["hazard"]) == {"wfire"} and set(wf["scenario"]) == set(rw.WARMING)
    assert wf["v10"].between(0, 100).all()
    print("ok  wildfire producer: mocked FIRMS seam through the real main()")

    rp.fetch_tracks = lambda iso3: object()
    rp.rain_hazard = lambda tracks, iso3: FakeRainHaz()
    base = np.array([90.0, 140.0, 200.0, 280.0, 380.0, 460.0])
    rh.local_rp_intensity = lambda haz, rps: np.stack(
        [base[i] * np.array([1.0, 1.1, 0.7]) for i in range(len(rps))])
    rc = rp.main(["--countries", "USA", "--out", "sim_prain_grid.csv"])
    assert rc == 0
    pr = pd.read_csv("sim_prain_grid.csv")
    assert set(pr["hazard"]) == {"prain"} and set(pr["scenario"]) == set(rp.WARMING)
    assert pr["v100"].max() > 0
    print("ok  rainfall producer: mocked track/rain seams through main()")

    # a minimal tc base so coverage checks engage, then the real merge + gate
    cells = wf[wf.scenario == "present"][["lat", "lon"]].drop_duplicates()
    tc = []
    for sc in rw.WARMING:
        d = cells.copy()
        up = 1 + 0.05 * rw.WARMING[sc]
        for i, rpd in enumerate(rh.RETURN_PERIODS):
            d[f"v{rpd}"] = (20 + 8 * i) * up
        d["scenario"], d["hazard"] = sc, "tc"
        tc.append(d)
    pd.concat(tc).to_csv("sim_tc_base.csv", index=False)
    m = subprocess.run([sys.executable, "merge_grids.py", "sim_tc_base.csv",
                        "sim_wfire_grid.csv", "sim_prain_grid.csv",
                        "-o", "sim_sixperil_grid.csv", "--no-meta"],
                       capture_output=True, text=True)
    assert m.returncode == 0, m.stderr
    r = subprocess.run([sys.executable, "validate_grid.py",
                        "sim_sixperil_grid.csv"], capture_output=True, text=True)
    print("\n--- validate_grid.py on the six-peril merge ---")
    print(r.stdout)
    assert r.returncode == 0 and "wfire layer" in r.stdout \
        and "prain layer" in r.stdout
    assert "hazard 'wfire' covers all 10 app scenarios" in r.stdout
    print("ok  merged six-peril grid passes the extended gate")

    bad = pd.read_csv("sim_sixperil_grid.csv")
    bad.loc[bad["hazard"] == "wfire", "v10"] = 150.0
    bad.to_csv("sim_badfire_grid.csv", index=False)
    r2 = subprocess.run([sys.executable, "validate_grid.py",
                         "sim_badfire_grid.csv"], capture_output=True, text=True)
    assert r2.returncode == 1 and "outside 0..100" in r2.stdout
    print("ok  burn probability outside 0..100 percent is rejected")

    print("\nALL NEW-PERIL TESTS PASSED")


if __name__ == "__main__":
    test_burn_probability()
    test_scenario_uplift()
    test_wfire_rows_encoding()
    test_prain_scaling()
    run()
