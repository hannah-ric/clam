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

import portfolio_regions
import refresh_hazard as rh
import refresh_wildfire as rw
import refresh_prain as rp


def ok(msg):
    print("ok ", msg)


def test_shared_regions():
    """The region boxes live once in portfolio_regions and every consumer
    reads that copy; the union must cover the whole documented portfolio
    footprint (SE US/Gulf, desert SW, Hawaii, PR/USVI)."""
    import refresh_heat as hh
    assert hh.REGIONS is portfolio_regions.REGIONS
    assert rw.FIRE_REGIONS is portfolio_regions.REGIONS
    # the app's own sample portfolio, one representative site per region
    inside = portfolio_regions.in_regions(
        [26.27, 33.83, 19.64, 22.07, 18.38, 18.34],
        [-80.09, -116.55, -155.99, -159.32, -65.81, -64.90])
    assert inside.all(), "sample-portfolio locations must all be covered"
    out = portfolio_regions.sites_outside_regions(
        ["NYC"], [40.7], [-74.0])
    assert out == [("NYC", 40.7, -74.0)], \
        "a site outside every box is reported by name, never dropped silently"
    ok("portfolio_regions: one source of truth, portfolio covered, outsiders named")


def test_rain_domains():
    """The coverage audit behind the prain rework: Hawaii gets its own
    EP-basin domain (the old BBOXES had no Hawaii box and hardcoded the
    North Atlantic basin, silently zeroing Hawaii TC rainfall), and
    domains_for only fetches domains that cover actual sites."""
    hi = [d for d in rp.DOMAINS if d["key"] == "hawaii"]
    assert hi and hi[0]["basin"] == "EP" and hi[0]["iso3"] == "USA", \
        "Hawaii must be an EP-basin domain of the USA"
    assert {d["key"] for d in rp.domains_for("USA")} == {"conus", "hawaii"}
    # a CONUS-only portfolio never fetches Pacific tracks
    doms = rp.domains_for("USA", [25.0, 29.5], [-80.0, -98.5])
    assert [d["key"] for d in doms] == ["conus"]
    # a mixed portfolio fetches both
    doms = rp.domains_for("USA", [25.0, 19.64], [-80.0, -155.99])
    assert {d["key"] for d in doms} == {"conus", "hawaii"}
    # domain_covers: Kona is Hawaii's to speak for, Miami is not
    cov = rp.domain_covers(hi[0], [19.64, 25.0], [-155.99, -80.0])
    assert cov.tolist() == [True, False]
    ok("rain domains: Hawaii EP domain present, site-driven domain selection")


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
    up = rw.scenario_pburn(p, rw.WARMING["ssp585_2080"])
    assert abs(up[0] - 0.01 * (1 + 0.14 * rw.WARMING["ssp585_2080"])) < 1e-12
    assert up[1] <= 1.0
    ok("scenario_pburn: warming uplift applied, capped at 1")


def test_wfire_rows_encoding():
    # point semantics: rows AT the site coordinates, v10 = point burn
    # probability %, v25 = conditional damage % given fire; co-located
    # records dedupe; NO thinning, NO buffering
    lat = np.array([30.0, 30.0, 34.0])
    lon = np.array([-98.5, -98.5, -116.5])          # first two co-located
    p = np.array([0.004, 0.004, 0.015])
    cond = np.array([0.35, 0.35, 0.55])
    rows = rw.wfire_rows(lat, lon, p, cond)
    assert set(rows["scenario"]) == set(rw.WARMING)
    per_sc = rows.groupby("scenario").size()
    assert per_sc.nunique() == 1 and per_sc.iloc[0] == 2, \
        "one shared SITE-POINT set across scenarios, co-located rows deduped"
    pres = rows[rows.scenario == "present"].sort_values("lon")
    assert np.isclose(pres["v10"].to_numpy(), [0.4, 1.5]).all() or \
        np.isclose(sorted(pres["v10"]), [0.4, 1.5]).all(), \
        "v10 is the POINT probability in percent, exactly as sampled"
    assert set(np.round(pres["v25"], 1)) == {35.0, 55.0}, \
        "v25 carries the conditional damage ratio in percent"
    assert (rows[["v50", "v100", "v250", "v500"]].to_numpy() == 0).all()
    now = rows[rows.scenario == "present"]["v10"].mean()
    fut = rows[rows.scenario == "ssp585_2080"]["v10"].mean()
    assert fut > now > 0
    assert rows["v10"].max() <= 100.0
    ok("wfire_rows: site-point encoding with conditional damage, "
       "rising signal, percent")


def test_cfl_mapping_and_wrc_sampling():
    """The intensity-conditioned damage side: CFL bands map monotonically,
    nodata flags coverage, and a non-probability BP raster is refused."""
    import assumptions as A
    got = A.cfl_to_damage([0.5, 3.0, 7.9, 11.0, 25.0])
    assert list(got) == A.FIRE_CFL_DAMAGE["ratios"], got
    calls = []
    def fake_sample(path, lat, lon):
        calls.append(str(path))
        lat = np.asarray(lat, float)
        if "bp" in str(path):
            return np.where(lat < 20, -9999.0, 0.012), lat >= 20
        return np.where(lat >= 30, 9.0, -9999.0), np.asarray(lat) >= 30
    saved = rw.sample_raster_points
    try:
        rw.sample_raster_points = fake_sample
        w = rw.wrc_at_points([19.6, 25.0, 34.0], [-155.9, -80.0, -116.5],
                             "bp.tif", "cfl.tif")
        assert w["covered"].tolist() == [False, True, True], \
            "nodata at the point means NOT covered (flag, never zero)"
        assert w["bp"][0] == 0.0 and np.isclose(w["bp"][1], 0.012)
        assert np.isclose(w["cond"][2], 0.55), "9 ft flame length -> 0.55"
        assert np.isclose(w["cond"][1], rw.FIRE_COND_INTERIM) \
            and w["cond_interim"][1], \
            "no CFL value -> the capped interim ratio, marked interim"
        # a raster that is not a probability is refused, not rescaled
        rw.sample_raster_points = lambda p, la, lo: (
            np.full(len(la), 42.0), np.ones(len(la), bool))
        try:
            rw.wrc_at_points([25.0], [-80.0], "bp.tif")
            refused = False
        except ValueError:
            refused = True
        assert refused, "BP values above 1 must raise, not be guessed at"
    finally:
        rw.sample_raster_points = saved
    ok("WRC sampling: coverage flags, CFL banding, interim marking, "
       "unit-sanity refusal")


def test_prain_scaling():
    assert abs(rp.cc_scale(2.0) - 1.14) < 1e-12
    present = pd.DataFrame({"lat": [29.5], "lon": [-98.5],
                            "v10": [120.0], "v25": [180.0], "v50": [240.0],
                            "v100": [310.0], "v250": [420.0], "v500": [500.0]})
    rows = rp.prain_rows(present)
    assert set(rows["scenario"]) == set(rp.WARMING)
    r85 = rows[rows.scenario == "ssp585_2080"].iloc[0]
    assert abs(r85["v100"] - round(310.0 * rp.cc_scale(rp.WARMING["ssp585_2080"]), 1)) < 1e-9
    v = rows[[f"v{x}" for x in rh.RETURN_PERIODS]].to_numpy()
    assert (np.diff(v, axis=1) >= 0).all(), "scaling preserves monotonicity"
    ok("prain_rows: Clausius-Clapeyron scaling, monotone RP field")


# --- producers end-to-end with mocked seams ------------------------------------

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
        # WRC resolution: explicit wins, env second, ./wrc/ discovered, and
        # graceful exit-1 guidance when the raster is absent
        saved_bp = os.environ.pop(rw.WRC_BP_ENV, None)
        saved_cfl = os.environ.pop(rw.WRC_CFL_ENV, None)
        try:
            assert rw.resolve_wrc("a.tif", "b.tif") == ("a.tif", "b.tif")
            assert rw.resolve_wrc(None, None) == (None, None)
            os.environ[rw.WRC_BP_ENV] = "env_bp.tif"
            assert rw.resolve_wrc(None, None)[0] == "env_bp.tif", "env var wins"
            del os.environ[rw.WRC_BP_ENV]
            os.mkdir("wrc")
            Path("wrc/BP_CONUS.tif").write_bytes(b"x")
            Path("wrc/CFL_CONUS.tif").write_bytes(b"x")
            bp, cfl = rw.resolve_wrc(None, None)
            assert bp.endswith("BP_CONUS.tif") and cfl.endswith("CFL_CONUS.tif"), \
                "./wrc/ folder is discovered"
            shutil.rmtree("wrc")
            rc = rw.main(["--out", "wfire_nofirms.csv"])
            assert rc == 1, "no WRC raster is a clean exit 1, not a crash"
            meta = json.loads(Path("wfire_nofirms_meta.json").read_text())
            assert meta["skipped"] and "WRC" in meta["skipped"][0]["reason"]
            Path("sites.csv").unlink()
            rc = rw.main(["--out", "wfire_nofirms.csv"])
            assert rc == 1, "no sites is a clean exit 1 with guidance"
        finally:
            if saved_bp is not None:
                os.environ[rw.WRC_BP_ENV] = saved_bp
            if saved_cfl is not None:
                os.environ[rw.WRC_CFL_ENV] = saved_cfl
    finally:
        os.chdir(cwd)
        shutil.rmtree(tmp, ignore_errors=True)
        if saved_env is not None:
            os.environ["FIRMS_CSV"] = saved_env
    ok("resolvers: FIRMS context + WRC rasters discovered; missing inputs "
       "exit 1 cleanly")


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
    # WRC input through the real main(): rasterio is mocked at the sampling
    # seam; resolve_wrc, coverage flagging, encoding, and meta all run for
    # real. The site list includes Kona, which the fake BP raster does not
    # cover: it must be FLAGGED, never silently zeroed.
    pd.DataFrame({"name": ["SW", "Gulf", "Kona"],
                  "latitude": [34.0, 30.0, 19.64],
                  "longitude": [-116.5, -98.5, -155.99],
                  "asset_value_usd": [1e7, 1e7, 1e7]}
                 ).to_csv("sim_firms_sites.csv", index=False)

    def fake_sample(path, lat, lon):
        lat = np.asarray(lat, float)
        if "bp" in str(path):
            vals = np.where(np.isclose(lat, 34.0), 0.015,
                            np.where(np.isclose(lat, 30.0), 0.004, -9999.0))
            return vals, lat > 20.0
        vals = np.where(np.isclose(lat, 34.0), 9.0, -9999.0)
        return vals, np.isclose(lat, 34.0)
    rw.sample_raster_points = fake_sample
    rc = rw.main(["--wrc-bp", "sim_bp.tif", "--wrc-cfl", "sim_cfl.tif",
                  "--sites", "sim_firms_sites.csv",
                  "--out", "sim_wfire_grid.csv"])
    assert rc == 0
    wf = pd.read_csv("sim_wfire_grid.csv")
    assert set(wf["hazard"]) == {"wfire"} and set(wf["scenario"]) == set(rw.WARMING)
    assert wf["v10"].between(0, 100).all() and wf["v25"].between(0, 100).all()
    pres = wf[wf.scenario == "present"].sort_values("lon")
    assert len(pres) == 2, "only the covered sites produce rows"
    assert np.isclose(pres.iloc[0]["v10"], 1.5) \
        and np.isclose(pres.iloc[0]["v25"], 55.0), \
        "SW: point BP 1.5%, CFL 9 ft -> 55% conditional damage"
    assert np.isclose(pres.iloc[1]["v10"], 0.4) and np.isclose(
        pres.iloc[1]["v25"], rw.FIRE_COND_INTERIM * 100), \
        "Gulf: no CFL value -> the capped interim conditional ratio"
    wmeta = json.loads(Path("sim_wfire_grid_meta.json").read_text())
    assert any(s.get("site") == "Kona" and "coverage" in s.get("reason", "")
               for s in wmeta["skipped"]), \
        "the uncovered Hawaii site is flagged by name in the meta sidecar"
    assert wmeta["wrc"]["cond_interim_sites"] == 1
    print("ok  wildfire producer: WRC point sampling through the real "
          "main(), uncovered site flagged")

    # the FIRMS historical-context export: separate file, separate columns,
    # never a hazard layer
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
    ctx = rw.write_firms_context(["sim_firms.csv"], "sim_firms_context.csv",
                                 "sim_firms_sites.csv")
    assert (ctx["kind"] == "firms_historical_context").all()
    assert "hazard" not in ctx.columns and "v10" not in ctx.columns, \
        "the context export must not look like a hazard layer"
    assert ctx["detections"].sum() == 3, "the out-of-region detection drops"
    print("ok  FIRMS context export: separated from the loss path entirely")

    fetched_domains = []
    def _fake_tracks(domain):
        fetched_domains.append(domain["key"])
        return object()
    rp.fetch_tracks = _fake_tracks
    rp.rain_hazard = lambda tracks, domain: FakeRainHaz()
    base = np.array([90.0, 140.0, 200.0, 280.0, 380.0, 460.0])
    rh.local_rp_intensity = lambda haz, rps: np.stack(
        [base[i] * np.array([1.0, 1.1, 0.7]) for i in range(len(rps))])
    rc = rp.main(["--countries", "USA", "--out", "sim_prain_grid.csv"])
    assert rc == 0
    pr = pd.read_csv("sim_prain_grid.csv")
    assert set(pr["hazard"]) == {"prain"} and set(pr["scenario"]) == set(rp.WARMING)
    assert pr["v100"].max() > 0
    # both USA domains were attempted (conus AND the new EP-basin hawaii)...
    assert set(fetched_domains) == {"conus", "hawaii"}
    # ...and the fake CONUS-coordinate cells were trimmed out of the hawaii
    # domain and RECORDED as skipped, not silently written into its box
    prm = json.loads(Path("sim_prain_grid_meta.json").read_text())
    assert any(s.get("domain") == "hawaii" for s in prm["skipped"])
    assert all(l.get("domain") == "conus" for l in prm["layers"])
    print("ok  rainfall producer: basin domains through main(), stray cells "
          "trimmed and recorded")

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

    # the per-site coverage audit: a Hawaii site far from every cell must be
    # NAMED as outside coverage per hazard (warning surface, not a gate fail)
    pd.DataFrame({"name": ["Gulf OK", "Kona Shore"],
                  "latitude": [30.0, 19.64], "longitude": [-98.5, -155.99],
                  "asset_value_usd": [1e7, 1e7]}
                 ).to_csv("sim_cov_sites.csv", index=False)
    r3 = subprocess.run([sys.executable, "validate_grid.py",
                         "sim_sixperil_grid.csv", "--sites",
                         "sim_cov_sites.csv"], capture_output=True, text=True)
    assert r3.returncode == 0, "coverage gaps warn, they do not block shipping"
    assert "Per-site coverage audit" in r3.stdout
    assert "Kona Shore" in r3.stdout and "OUTSIDE coverage" in r3.stdout, \
        "the uncovered site must be flagged by name, never silently zeroed"
    audit = r3.stdout.split("Per-site coverage audit")[1]
    assert "Kona Shore:" in audit and "Gulf OK:" not in audit, \
        "only the uncovered site is listed; covered sites stay quiet"
    print("ok  validate_grid --sites names every site outside a peril's coverage")

    print("\nALL NEW-PERIL TESTS PASSED")


if __name__ == "__main__":
    test_burn_probability()
    test_scenario_uplift()
    test_wfire_rows_encoding()
    test_cfl_mapping_and_wrc_sampling()
    test_prain_scaling()
    test_shared_regions()
    test_rain_domains()
    test_firms_io()
    test_petals_deprecation_filter()
    run()
