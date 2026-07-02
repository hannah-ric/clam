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
    w, _ = ri.vuln_of("engineered", 2020)
    assert w >= 0.5                                      # clip floor
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


def test_annuity():
    # 25 years at 3%: standard annuity factor ~17.413
    assert abs(ri.annuity(25, 0.03) - 17.4131) < 5e-4
    ok("annuity matches the closed-form factor")


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
    test_combine_countries_padding()
    test_annuity()
    print("\nALL IMPACT-OP TESTS PASSED")
