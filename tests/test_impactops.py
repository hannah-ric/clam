"""Unit tests for refresh_impacts.py's pure impact math.

These pin the parity contract: the curves must match the app's formulas
exactly (values computed independently from the v1.7 source), and the
event-based exceedance arithmetic must match hand-computed cases.
Pure pandas/numpy; no CLIMADA needed.   python3 test_impactops.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import refresh_impacts as ri


def ok(msg):
    print("ok ", msg)


# --- curves match the app exactly ------------------------------------------------

def test_emanuel():
    # app: vt=max((v-25.7)/(74.7-25.7),0); c=vt^3; c/(1+c)
    for v in (0.0, 25.7, 40.0, 74.7, 100.0, 200.0):
        vt = max((v - 25.7) / (74.7 - 25.7), 0.0)
        c = vt ** 3
        want = c / (1 + c)
        got = float(ri.emanuel_mdd(v))
        assert abs(got - want) < 1e-12, (v, got, want)
    assert float(ri.emanuel_mdd(74.7)) == 0.5           # v_half means half damage
    assert float(ri.emanuel_mdd(100.0, dmg_mult=3.0)) <= 1.0   # cap
    assert float(ri.emanuel_mdd(10.0)) == 0.0
    ok("emanuel_mdd matches the app curve (incl. v_half=0.5, cap, threshold)")


def test_flood():
    # app: e=d-fb; e<=0 -> 0 else min(0.75, 1-exp(-0.6e))
    for d, fb in ((0.0, 1.1), (1.1, 1.1), (2.0, 1.1), (5.0, 0.6), (20.0, 0.0)):
        e = d - fb
        want = 0.0 if e <= 0 else min(0.75, 1 - np.exp(-0.6 * e))
        got = float(ri.flood_mdd(d, fb))
        assert abs(got - want) < 1e-12, (d, fb, got, want)
    assert float(ri.flood_mdd(50.0, 0.0)) == 0.75       # hard cap
    ok("flood_mdd matches the app curve (freeboard, cap 0.75)")


def test_vuln():
    assert ri.vuln_of() == (1.0, 0.0)
    assert ri.vuln_of("engineered", 2015) == (0.75 * 0.9, 0.0)
    assert ri.vuln_of("frame", 1980) == (min(1.3 * 1.15, 1.6), 0.0)
    assert ri.vuln_of("frame", 1980, defended=True)[1] == 0.5
    assert ri.vuln_of("masonry", 2000) == (1.0, 0.0)    # 1995..2009: no age factor
    assert ri.vuln_of("engineered", 2020) == (0.75 * 0.9, 0.0)   # floor of the
    # reachable range; the 0.5 clamp itself is unreachable by construction
    ok("vuln_of matches the app (construction x age, clip, defended bonus)")


# --- exceedance arithmetic --------------------------------------------------------

def test_ep_curve_exact():
    # three events: losses 100, 50, 10 with frequencies chosen so the
    # exceedance points sit exactly at RP 1000, 100, 10
    losses = np.array([100.0, 50.0, 10.0])
    freq = np.array([0.001, 0.009, 0.09])
    ep = ri.ep_curve(losses, freq, rps=(10, 100, 250, 500))
    assert abs(ep[100] - 50.0) < 1e-9
    assert abs(ep[10] - 10.0) < 1e-9
    # between 100 and 1000: log-interpolated, strictly between the two losses
    assert 50.0 < ep[250] < 100.0 and 50.0 < ep[500] < 100.0
    ok("ep_curve: exact at event RPs, log-interpolated between")


def test_ep_curve_edges():
    losses = np.array([100.0, 50.0])
    freq = np.array([0.01, 0.01])           # RPs 100 and 50
    ep = ri.ep_curve(losses, freq, rps=(10, 25, 500))
    assert ep[10] == 0.0 and ep[25] == 0.0  # commoner than any event: no loss yet
    assert ep[500] == 100.0                 # tail flat beyond the largest RP
    ep0 = ri.ep_curve(np.zeros(4), np.full(4, 0.01))
    assert all(v == 0.0 for v in ep0.values())
    ok("ep_curve: zero below coverage, flat tail, all-zero events")


def test_site_ead():
    losses = np.array([[10.0, 0.0], [0.0, 20.0]])
    freq = np.array([0.1, 0.01])
    ead = ri.site_ead(losses, freq)
    assert np.allclose(ead, [1.0, 0.2])
    ok("site_ead is the frequency-weighted event loss (eai_exp)")


def test_nearest_and_snap_guard():
    idx, dist = ri.nearest_centroids([25.0, 45.0], [-80.0, -80.0],
                                     [25.1, 26.0], [-80.1, -80.0])
    assert idx[0] == 0 and dist[0] < 20
    assert idx[1] == -1 and dist[1] > ri.MAX_SNAP_KM      # outside 200 km
    class H:                                              # minimal hazard stub
        intensity = np.array([[30.0, 40.0], [50.0, 60.0]])
    got = ri.site_intensity(H(), np.array([1, -1]))
    assert np.allclose(got, [[40.0, 0.0], [60.0, 0.0]])   # excluded site zeroed
    ok("nearest_centroids guards the 200 km snap; excluded sites score zero")


def test_blend_renormalisation():
    a = {"aal": 10.0, "ep": {rp: 1.0 for rp in ri.RPS}, "ead": np.array([10.0])}
    b = {"aal": 30.0, "ep": {rp: 3.0 for rp in ri.RPS}, "ead": np.array([30.0])}
    r = ri.blend_results([(0.5, a), (0.5, b)])
    assert abs(r["aal"] - 20.0) < 1e-12
    r2 = ri.blend_results([(0.5, a)])                     # missing member
    assert abs(r2["aal"] - 10.0) < 1e-12                  # renormalised, not halved
    ok("blend_results: weighted mean with missing-member renormalisation")


def test_losses_and_measures():
    values = np.array([1_000_000.0])
    wind_int = np.array([[80.0], [40.0]])
    base = ri.wind_losses(wind_int, values, np.array([1.0]))
    hard = ri.wind_losses(wind_int, values, np.array([0.65]))
    assert np.all(hard <= base) and hard[0, 0] < base[0, 0]
    depth = np.array([[2.0], [0.5]])
    fb = np.array([1.1])
    fl = ri.flood_losses(depth, values, fb)
    fl_fb = ri.flood_losses(depth, values, fb + 0.5)      # dry floodproofing
    fl_red = ri.flood_losses(depth, values, fb, depth_red=0.3)  # buffer
    assert fl[1, 0] == 0.0                                # below freeboard: dry
    assert fl_fb[0, 0] < fl[0, 0] and fl_red[0, 0] < fl[0, 0]
    ok("wind/flood losses: hardening, freeboard, and depth reduction all avert")


def test_eval_scenario_and_adaptation():
    # one site, one wind source covering all recipes via 'present' only
    prep = {"wind": {"present": {"freq": np.array([0.01, 0.02]),
                                 "int": np.array([[70.0], [45.0]])}},
            "surge": {("present", "present"): {"int": np.array([[2.0], [0.8]])}},
            "rflood": {"present": [{"freq": np.array([0.02]),
                                    "int": np.array([[1.5]])}]}}
    vals = np.array([2_000_000.0])
    wm = np.array([1.0])
    r = ri.eval_scenario(prep, "present", vals, wm,
                         np.array([ri.FB_COAST]), np.array([ri.FB_RIVER]))
    assert r["acute"]["aal"] > 0
    assert abs(r["acute"]["aal"] - (r["tc"]["aal"] + r["cflood"]["aal"]
                                    + r["rflood"]["aal"])) < 1e-6
    ep = r["acute"]["ep"]
    assert all(ep[ri.RPS[i]] <= ep[ri.RPS[i + 1]] + 1e-9
               for i in range(len(ri.RPS) - 1))
    ad = ri.run_adaptation(prep, vals, wm, np.array([ri.FB_COAST]),
                           np.array([ri.FB_RIVER]), {"present": r})
    for mk in ("wind", "flood", "buffer"):
        rec = ad[mk]["per_scenario"]["present"]
        assert rec["averted_direct_aal_usd"] >= 0
        assert rec["cost_usd"] > 0
        assert rec["bcr"] is not None
    assert ad["wind"]["per_scenario"]["present"]["averted_direct_aal_usd"] > 0
    ok("eval_scenario: joint AAL reconciles, EP monotone; measures avert")


def test_uncertainty_deterministic():
    prep = {"wind": {"present": {"freq": np.array([0.01]),
                                 "int": np.array([[70.0]])}},
            "surge": {}, "rflood": {}}
    vals = np.array([1_000_000.0])
    wm = np.array([1.0])
    u1 = ri.run_uncertainty(prep, vals, wm, np.array([1.1]), np.array([0.6]),
                            ["present"], 200, 42)
    u2 = ri.run_uncertainty(prep, vals, wm, np.array([1.1]), np.array([0.6]),
                            ["present"], 200, 42)
    b1, b2 = u1["present"]["acute_aal_usd"], u2["present"]["acute_aal_usd"]
    assert b1 == b2                                        # same seed, same band
    assert b1["p5"] <= b1["p50"] <= b1["p95"]
    assert b1["p5"] <= b1["central"] <= b1["p95"]
    assert len(u1["present"]["drivers"]) == len(ri.MC_FACTORS)
    ok("uncertainty: seeded determinism, quantile order, central in band")


def test_partial_surge_failure_reconciles():
    # ssp585_2050 blends rcp85_2040 and rcp85_2060; surge exists for only one
    # of them (the other failed). The perils must still reconcile with acute.
    freq = np.array([0.01, 0.02])
    prep = {"wind": {"rcp85_2040": {"freq": freq,
                                    "int": np.array([[70.0], [45.0]])},
                     "rcp85_2060": {"freq": freq,
                                    "int": np.array([[74.0], [48.0]])}},
            "surge": {("rcp85_2040", "ssp585_2050"):
                      {"int": np.array([[2.2], [0.9]])}},
            "rflood": {}}
    vals = np.array([2_000_000.0])
    r = ri.eval_scenario(prep, "ssp585_2050", vals, np.array([1.0]),
                         np.array([ri.FB_COAST]), np.array([ri.FB_RIVER]))
    parts = r["tc"]["aal"] + r["cflood"]["aal"] + r["rflood"]["aal"]
    assert abs(parts - r["acute"]["aal"]) < 1e-6, (parts, r["acute"]["aal"])
    assert r["cflood"]["aal"] > 0            # surviving member still counts
    ok("partial surge failure: zero part keeps tc+cflood+rflood == acute")


def test_water_snap_guard():
    # coastal-band-only surge centroids; the coastal site snaps, the site
    # ~100 km inland must NOT inherit the coastal cell's depth
    coast_lat, coast_lon = np.array([25.00, 25.05]), np.array([-80.00, -80.05])
    sites_lat = [25.02, 25.90]               # second site ~97 km from the band
    sites_lon = [-80.02, -80.02]
    wind_dist = np.array([2.0, 3.0])         # both sit ON the wind grid
    idx = ri.water_snap(sites_lat, sites_lon, coast_lat, coast_lon, wind_dist)
    assert idx[0] >= 0 and idx[1] == -1
    class H:
        intensity = np.array([[2.5, 2.4]])
    got = ri.site_intensity(H(), idx)
    assert got[0, 0] > 0 and got[0, 1] == 0.0
    ok("water_snap: inland site scores zero instead of inheriting coastal surge")


def test_adaptation_scope_no_free_benefit():
    # a site below the exposure threshold: flood/buffer must claim NO averted
    # AAL (nothing was installed) and cost nothing
    prep = {"wind": {"present": {"freq": np.array([0.001]),
                                 "int": np.array([[30.0]])}},
            "surge": {("present", "present"): {"int": np.array([[1.2]])}},
            "rflood": {}}
    vals = np.array([1_000_000.0])
    base = ri.eval_scenario(prep, "present", vals, np.array([1.0]),
                            np.array([ri.FB_COAST]), np.array([ri.FB_RIVER]))
    assert base["cflood"]["ead"][0] < ri.SCOPE_EAD_USD   # out of scope by design
    ad = ri.run_adaptation(prep, vals, np.array([1.0]), np.array([ri.FB_COAST]),
                           np.array([ri.FB_RIVER]), {"present": base})
    for mk in ("flood", "buffer"):
        rec = ad[mk]["per_scenario"]["present"]
        assert rec["sites_in_scope"] == 0
        assert rec["cost_usd"] == 0.0
        assert rec["averted_direct_aal_usd"] == 0.0, \
            "no benefit may be claimed from a measure installed nowhere"
        assert rec["bcr"] is None
    ok("adaptation scope: out-of-scope sites yield zero benefit, zero cost")


def test_combine_countries_padding():
    # country A lacks ssp585_2080 entirely (all sources failed there);
    # its 2 sites must appear as explicit zeros, aligned, and recorded
    mk = lambda n, aal: {p: {"aal": aal if p in ("tc", "acute") else 0.0,
                             "ep": {rp: aal if p in ("tc", "acute") else 0.0
                                    for rp in ri.RPS},
                             "ead": (np.full(n, aal / n) if p in ("tc", "acute")
                                     else np.zeros(n))}
                         for p in ("tc", "cflood", "rflood", "acute")}
    res_a = {"present": mk(2, 10.0)}
    res_b = {"present": mk(3, 20.0), "ssp585_2080": mk(3, 30.0)}
    meta = {"skipped": []}
    out = ri.combine_countries([res_a, res_b], [2, 3], ["PRI", "USA"], meta)
    assert len(out["present"]["acute"]["ead"]) == 5
    assert len(out["ssp585_2080"]["acute"]["ead"]) == 5      # padded, aligned
    assert np.allclose(out["ssp585_2080"]["acute"]["ead"][:2], 0.0)
    assert abs(out["ssp585_2080"]["acute"]["aal"] - 30.0) < 1e-12
    assert any(s["country"] == "PRI" and s["scenario"] == "ssp585_2080"
               and s["layer"] == "pack" for s in meta["skipped"])
    # and build_pack no longer misaligns or crashes
    pack_scen = ri.build_pack(out, ["a1", "a2", "b1", "b2", "b3"],
                              np.ones(5), {}, {}, "x.csv")["scenarios"]
    assert pack_scen["ssp585_2080"]["per_site"][0]["direct_ead_usd"] == 0.0
    assert pack_scen["ssp585_2080"]["per_site"][2]["direct_ead_usd"] > 0.0
    ok("combine_countries: scenario gaps pad with aligned zeros and are recorded")


def test_capital_plan():
    # two sites, wind + surge; run_adaptation must emit per-site detail and
    # build_capital_plan must rank in-scope pairs by BCR with exact math
    prep = {"wind": {"present": {"freq": np.array([0.01, 0.02]),
                                 "int": np.array([[70.0, 40.0], [45.0, 30.0]])},
                     "rcp45_2040": {"freq": np.array([0.01, 0.02]),
                                    "int": np.array([[72.0, 41.0], [46.0, 31.0]])},
                     "rcp45_2060": {"freq": np.array([0.01, 0.02]),
                                    "int": np.array([[74.0, 42.0], [47.0, 32.0]])}},
            "surge": {("present", "present"): {"int": np.array([[2.0, 0.0], [0.8, 0.0]])},
                      ("rcp45_2040", "ssp245_2050"): {"int": np.array([[2.2, 0.0], [0.9, 0.0]])},
                      ("rcp45_2060", "ssp245_2050"): {"int": np.array([[2.3, 0.0], [0.95, 0.0]])}},
            "rflood": {}}
    vals = np.array([2_000_000.0, 1_500_000.0])
    wm = np.array([1.0, 1.0])
    fbc, fbr = np.full(2, ri.FB_COAST), np.full(2, ri.FB_RIVER)
    base = {k: ri.eval_scenario(prep, k, vals, wm, fbc, fbr)
            for k in ("present", "ssp245_2050")}
    ad = ri.run_adaptation(prep, vals, wm, fbc, fbr, base)
    ps = ad["wind"]["per_scenario"]["ssp245_2050"]["per_site"]
    assert len(ps["averted_usd"]) == 2 and all(a >= 0 for a in ps["averted_usd"])
    plan = ri.build_capital_plan(ad, ["Alpha", "Beta"])
    assert plan["scenario"] == "ssp245_2050"
    prj = plan["projects"]
    assert prj, "in-scope pairs must produce projects"
    bcrs = [p["bcr"] for p in prj]
    assert bcrs == sorted(bcrs, reverse=True), "sorted by BCR descending"
    an = ri.annuity(ri.HORIZON_YEARS, ri.DISCOUNT_RATE)
    for p in prj:
        assert abs(p["bcr"] - round(p["averted_direct_aal_usd"] * an
                                    / p["cost_usd"], 3)) <= 0.001
    # site Beta is dry (no surge): flood/buffer must not list it
    assert not any(p["site"] == "Beta" and p["measure_key"] in ("flood", "buffer")
                   for p in prj)
    ok("capital plan: per-site detail, BCR-desc ranking, exact math, scoping")


def test_vhalf_calibration_roundtrip():
    # generate "observed" losses with a known v_half; the fit must recover it
    wind = {"freq": np.array([0.01, 0.02, 0.005]),
            "int": np.array([[70.0, 55.0], [45.0, 40.0], [95.0, 80.0]])}
    values = np.array([50e6, 30e6])
    wm = np.array([1.0, 1.15])
    true_vh = 85.0
    wl = ri.wind_losses(wind["int"], values, wm, v_half=true_vh)
    observed = float(ri.site_ead(wl, wind["freq"]).sum()) + 12345.0
    parts = [{"wind": wind, "values": values, "wind_mult": wm,
              "flood_fixed": 12345.0}]
    vh, modeled, clipped = ri.fit_v_half(parts, observed)
    assert not clipped
    assert abs(vh - true_vh) < 0.1, vh
    assert abs(modeled - observed) / observed < 1e-6
    # unreachable target clips at the bound instead of pretending precision
    vh_lo, _m, clip_lo = ri.fit_v_half(parts, observed * 100)
    assert clip_lo and vh_lo == ri.VHALF_LO
    cal = ri.build_calibration(parts, observed, matched=2)
    assert cal["applied"] is False and cal["fitted_v_half"] == round(true_vh, 1)
    assert cal["portfolio_bias_obs_over_model"] is not None
    ok("v_half calibration: round-trip recovery, bound clipping, record shape")


def test_annuity():
    # 25 years at 3%: standard annuity factor ~17.413
    assert abs(ri.annuity(25, 0.03) - 17.4131) < 5e-4
    ok("annuity matches the closed-form factor")


def test_named_insured_rollup():
    # two named insureds (HOA, TNL) share the first physical site; a third
    # site has no named insured. The rollup must group by party, sum to the
    # portfolio total, and label the missing party Unspecified.
    ead = np.array([100.0, 40.0, 25.0])
    parties = ["HOA", "TNL", None]
    roll = ri.named_insured_rollup(ead, parties)
    assert roll == {"HOA": 100.0, "TNL": 40.0, "Unspecified": 25.0}
    assert abs(sum(roll.values()) - float(ead.sum())) < 1e-9
    # empty/nan strings also fall to Unspecified and MERGE with the None site
    roll2 = ri.named_insured_rollup([10.0, 5.0, 3.0], ["HOA", "", "nan"])
    assert roll2 == {"HOA": 10.0, "Unspecified": 8.0}

    # build_pack threads the party and grouping id into per_site and adds the
    # portfolio by-named-insured decomposition, reconciling with direct AAL.
    mk = lambda n, aal: {p: {"aal": aal if p in ("tc", "acute") else 0.0,
                             "ep": {rp: aal if p in ("tc", "acute") else 0.0
                                    for rp in ri.RPS},
                             "ead": (np.array([70.0, 30.0]) if p in ("tc", "acute")
                                     else np.zeros(n))}
                         for p in ("tc", "cflood", "rflood", "acute")}
    scen = {"present": mk(2, 100.0)}
    pack = ri.build_pack(scen, ["A", "B"], np.ones(2), {}, {}, "x.csv",
                         site_named_insured=["HOA", "TNL"],
                         site_ids=["CAMPUS-1", "CAMPUS-1"])
    port = pack["scenarios"]["present"]["portfolio"]
    ps = pack["scenarios"]["present"]["per_site"]
    assert port["by_named_insured_aal_usd"] == {"HOA": 70.0, "TNL": 30.0}
    assert abs(sum(port["by_named_insured_aal_usd"].values())
               - port["direct_aal_usd"]) < 1e-6
    assert ps[0]["named_insured"] == "HOA" and ps[0]["site_id"] == "CAMPUS-1"
    assert ps[1]["named_insured"] == "TNL"
    # default (no arrays) stays backward compatible: Unspecified, no site_id
    pack0 = ri.build_pack(scen, ["A", "B"], np.ones(2), {}, {}, "x.csv")
    p0 = pack0["scenarios"]["present"]["per_site"][0]
    assert p0["named_insured"] == "Unspecified" and p0["site_id"] is None
    ok("named-insured rollup: grouping, reconciliation, pack threading")


if __name__ == "__main__":
    test_emanuel()
    test_flood()
    test_vuln()
    test_ep_curve_exact()
    test_ep_curve_edges()
    test_site_ead()
    test_nearest_and_snap_guard()
    test_blend_renormalisation()
    test_losses_and_measures()
    test_eval_scenario_and_adaptation()
    test_uncertainty_deterministic()
    test_partial_surge_failure_reconciles()
    test_water_snap_guard()
    test_adaptation_scope_no_free_benefit()
    test_combine_countries_padding()
    test_capital_plan()
    test_vhalf_calibration_roundtrip()
    test_annuity()
    test_named_insured_rollup()
    print("\nALL IMPACT-OP TESTS PASSED")
