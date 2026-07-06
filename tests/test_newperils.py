"""Increment 3 tests: the wildfire and TC-rainfall grid producers, pure ops
and end-to-end with every CLIMADA seam mocked, through merge_grids and the
extended validate_grid gate. Run from pipeline/:
    PYTHONPATH=. python3 ../tests/test_newperils.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
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


def test_firms_io():
    """load_firms + filter_firms_to_regions (the pure FIRMS input path) and the
    graceful no-FIRMS degradation, none of which needs CLIMADA."""
    rw._ensure_cartopy_cache()   # import-safe no-op when cartopy is absent
    modis = pd.DataFrame({"LATITUDE": [34.0, 12.0], "LONGITUDE": [-116.5, 40.0],
                          "ACQ_DATE": ["2020-08-01", "2020-01-01"],
                          "INSTRUMENT": ["MODIS", "MODIS"],
                          "CONFIDENCE": [80, 90], "BRIGHTNESS": [330.0, 300.0]})
    viirs = pd.DataFrame({"latitude": [30.0], "longitude": [-98.5],
                          "acq_date": ["2019-09-10"], "instrument": ["VIIRS"],
                          "confidence": ["n"], "bright_ti4": [340.0]})
    modis.to_csv("sim_firms_modis.csv", index=False)
    viirs.to_csv("sim_firms_viirs.csv", index=False)
    df = rw.load_firms(["sim_firms_modis.csv", "sim_firms_viirs.csv"])
    assert set(rw.FIRMS_REQUIRED).issubset(df.columns)
    assert "brightness" in df.columns and "bright_ti4" in df.columns
    assert len(df) == 3 and df["latitude"].dtype.kind == "f"
    kept = rw.filter_firms_to_regions(df)
    assert len(kept) == 2 and (kept["latitude"] < 40).all(), \
        "only detections inside the portfolio region boxes survive"
    ok("load_firms/filter: MODIS+VIIRS concat, header normalise, region box")
    pd.DataFrame({"latitude": [1.0], "longitude": [2.0]}).to_csv("sim_firms_bad.csv", index=False)
    try:
        rw.load_firms(["sim_firms_bad.csv"]); rejected = False
    except ValueError:
        rejected = True
    assert rejected, "a FIRMS CSV missing required columns must raise a clear error"

    # confidence floor + near-site buffer (pure, cwd-independent)
    fc = pd.DataFrame({"latitude": [34.0, 34.0, 30.0], "longitude": [-116.5, -116.5, -98.5],
                       "acq_date": ["2020-01-01"] * 3, "instrument": ["MODIS", "MODIS", "VIIRS"],
                       "confidence": [80, 20, "l"], "brightness": [330.0, 300.0, np.nan],
                       "bright_ti4": [np.nan, np.nan, 340.0]})
    kept_c = rw.filter_firms_confidence(fc, min_conf=50)
    assert len(kept_c) == 1 and int(kept_c.iloc[0]["confidence"]) == 80, \
        "drops low-confidence MODIS and VIIRS 'l'"
    near = rw.filter_firms_near_sites(fc, [34.0], [-116.5], buffer_km=50)
    assert len(near) == 2 and (abs(near["latitude"] - 34.0) < 0.01).all(), \
        "keeps only detections within the buffer of a site"
    ok("filter_firms: confidence floor and near-site buffer")

    # resolve_firms and the no-FIRMS path, run in an isolated temp dir with
    # FIRMS_CSV unset, so the test never touches (or is fooled by) a real ./firms/
    # or firms_us.csv an operator may have placed in pipeline/.
    assert rw.resolve_firms(["a.csv", "b.csv"]) == ["a.csv", "b.csv"], "explicit --firms wins"
    saved_env = os.environ.pop("FIRMS_CSV", None)
    cwd = os.getcwd()
    tmp = tempfile.mkdtemp()
    try:
        os.chdir(tmp)
        assert rw.resolve_firms(None) is None, "nothing to auto-discover"
        Path("firms_us.csv").write_text("x")
        assert rw.resolve_firms(None) == ["firms_us.csv"], "firms_us.csv is discovered"
        Path("firms_us.csv").unlink(); os.mkdir("firms")
        assert rw.resolve_firms(None) == ["firms"], "a ./firms/ folder is discovered"
        os.rmdir("firms")
        assert rw.resolve_sites("explicit.csv") == "explicit.csv", "explicit --sites wins"
        assert rw.resolve_sites(None) is None, "no sites.csv to discover"
        Path("sites.csv").write_text("latitude,longitude\n1,2\n")
        assert rw.resolve_sites(None) == "sites.csv", "sites.csv is discovered"
        Path("sites.csv").unlink()
        rc = rw.main(["--out", "wfire_nofirms.csv"])
        assert rc == 1, "no FIRMS anywhere is a clean exit 1, not a crash"
        meta = json.loads(Path("wfire_nofirms_meta.json").read_text())
        assert meta["skipped"] and "FIRMS" in meta["skipped"][0]["reason"]
    finally:
        os.chdir(cwd)
        shutil.rmtree(tmp, ignore_errors=True)
        if saved_env is not None:
            os.environ["FIRMS_CSV"] = saved_env
    ok("resolve_firms: explicit wins else FIRMS_CSV/./firms/; no FIRMS exits 1 cleanly")


def test_petals_deprecation_filter():
    """The Petals deprecation flood is a logging.WARNING record (LOGGER.warning),
    not a Python warning, so warnings.simplefilter can't reach it. Verify the
    logging filter drops ONLY the 'is deprecated' notices, leaves real progress
    and warnings alone, and is fully removed the moment the context exits."""
    import logging
    name = "climada_petals.hazard.wildfire"
    logger = logging.getLogger(name)
    captured = []

    class _Capture(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    handler = _Capture()
    logger.addHandler(handler)
    saved_level, saved_prop = logger.level, logger.propagate
    logger.setLevel(logging.INFO)
    logger.propagate = False              # don't double-print via the root handler
    before = list(logger.filters)
    try:
        with rw._quiet_petals_deprecation(name):
            assert len(logger.filters) == len(before) + 1, "filter installed"
            logger.warning("The use of WildFire.set_hist_fire_FIRMS is deprecated."
                           "Use WildFire.from_hist_fire_FIRMS .")
            logger.info("Setting up historical fire seasons 2020.")
            logger.warning("a genuine problem the operator must see")
        assert list(logger.filters) == before, "filter removed on context exit"
        logger.warning("still deprecated after exit")   # no longer swallowed
    finally:
        logger.removeHandler(handler)
        logger.setLevel(saved_level)
        logger.propagate = saved_prop

    assert not any("is deprecated" in m for m in captured), \
        "deprecation notices dropped while the context is active"
    assert "Setting up historical fire seasons 2020." in captured, \
        "genuine INFO progress still shows"
    assert "a genuine problem the operator must see" in captured, \
        "genuine WARNINGs still show"
    assert "still deprecated after exit" in captured, \
        "filtering stops the moment the context exits"
    ok("petals deprecation flood dropped via a scoped, reversible logging filter")


def run():
    # FIRMS input + the corrected seam: Petals is mocked (build_wildfire_hazard),
    # but the real load_firms + filter_firms_to_regions + main plumbing run. The
    # detections sit in the SW and SE/Gulf boxes (plus one outside, to be dropped).
    firms = pd.DataFrame({
        "latitude":   [34.00, 34.05, 30.00, 12.00],
        "longitude":  [-116.50, -116.55, -98.50, 40.00],
        "acq_date":   ["2020-08-01", "2021-07-15", "2019-09-10", "2020-01-01"],
        "instrument": ["MODIS", "MODIS", "VIIRS", "MODIS"],
        "confidence": [80, 65, "n", 90],
        "brightness": [330.0, 320.0, np.nan, 300.0],
        "bright_ti4": [np.nan, np.nan, 340.0, np.nan],
    })
    firms.to_csv("sim_firms.csv", index=False)
    # explicit --sites (co-located with the detections) so the run is deterministic
    # regardless of any real sites.csv the operator may have in pipeline/.
    pd.DataFrame({"name": ["SW", "Gulf"], "latitude": [34.0, 30.0],
                  "longitude": [-116.5, -98.5], "asset_value_usd": [1e7, 1e7]}
                 ).to_csv("sim_firms_sites.csv", index=False)
    rw.build_wildfire_hazard = lambda df, **kw: FakeFire()
    rc = rw.main(["--firms", "sim_firms.csv", "--sites", "sim_firms_sites.csv",
                  "--out", "sim_wfire_grid.csv"])
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
    test_firms_io()
    test_petals_deprecation_filter()
    run()
