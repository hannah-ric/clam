"""End-to-end simulation of refresh_impacts.py with CLIMADA mocked out.

Mirrors test_pipeline_sim.py: exercises the real main() plumbing with fake
hazards (including a failing wind source and a missing river-flood dataset),
then validate_pack.py must accept the output and reject corrupted variants.
Run from pipeline/:   PYTHONPATH=. python3 ../tests/test_impacts_sim.py
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import refresh_hazard as rh
import refresh_impacts as ri

# ---- synthetic world: two coastal sites, one inland, near 5 centroids -------
CEN_LAT = np.array([25.00, 25.25, 29.25, 30.00, 29.50])
CEN_LON = np.array([-80.00, -80.00, -94.75, -95.00, -98.50])

UPLIFT = {"present": 1.00,
          "rcp26_2040": 1.02, "rcp26_2060": 1.03, "rcp26_2080": 1.03,
          "rcp45_2040": 1.03, "rcp45_2060": 1.05, "rcp45_2080": 1.08,
          "rcp85_2040": 1.05, "rcp85_2060": 1.09, "rcp85_2080": 1.16}
FAIL_SOURCES = {"rcp26_2060"}
N_EVENTS = 60
RNG = np.random.default_rng(7)
BASE_EVENT = RNG.uniform(0.4, 1.3, N_EVENTS)     # shared event severity shape


class FakeCentroids:
    def __init__(self):
        self.lat, self.lon = CEN_LAT, CEN_LON


class FakeWind:
    """Synthetic TC wind: same event catalog per source, severity uplifted."""
    def __init__(self, skey):
        self._skey = skey
        self.centroids = FakeCentroids()
        base = np.array([62.0, 58.0, 55.0, 40.0, 30.0]) * UPLIFT[skey]
        self.intensity = BASE_EVENT[:, None] * base[None, :]
        self.frequency = np.full(N_EVENTS, 1.0 / N_EVENTS * 2.0)


class FakeSurge:
    """SLOSH-ish: linear in wind minus 1 m elevation, coastal cells only."""
    def __init__(self, wind, slr):
        self.centroids = FakeCentroids()
        self.intensity = np.maximum(0.12 * (wind.intensity - 26.0) - 1.0 + slr, 0.0)
        self.intensity[:, 3:] = 0.0                      # inland cells dry
        self.frequency = wind.frequency


RIVER_EVENTS = np.random.default_rng(11).uniform(0.3, 1.6, (30, 1))


class FakeRiver:
    def __init__(self, app_key, member=0):
        self.centroids = FakeCentroids()
        up = (1.0 + 0.1 * rh.SLR_M.get(app_key, 0.0) / 0.62) * (1.0 + 0.05 * member)
        depth = np.array([0.0, 0.0, 0.9, 1.1, 1.4]) * up
        self.intensity = RIVER_EVENTS * depth[None, :]
        self.frequency = np.full(30, 1.0 / 30.0)


def fake_fetch_wind(iso3, source, meta):
    skey = rh.source_key(source)
    if skey in FAIL_SOURCES:
        raise RuntimeError(f"simulated: no single dataset match for {skey}")
    meta.setdefault("wind_sources", {})[f"{iso3}:{skey}"] = {"simulated": skey}
    return FakeWind(skey)


def fake_compute_surge(wind_haz, slr):
    return FakeSurge(wind_haz, slr)


RF_MISSING = {"ssp126_2030"}

def fake_fetch_river(iso3, app_key, meta):
    if app_key in RF_MISSING:
        return []
    meta.setdefault("rflood_sources", {})[f"{iso3}:{app_key}"] = {"n_members": 2}
    return [FakeRiver(app_key, 0), FakeRiver(app_key, 1)]


def run():
    rh.fetch_wind = fake_fetch_wind
    rh.compute_surge = fake_compute_surge
    ri.fetch_river_flood_hazards = fake_fetch_river
    dem = Path("fake_dem.tiff"); dem.write_bytes(b"\0" * 16)
    rh.TOPO_PATH = dem

    sites = pd.DataFrame({
        "name": ["Reef Bay", "Dune Point", "River Bend"],
        "latitude": [25.02, 25.24, 29.49],
        "longitude": [-80.01, -80.02, -98.52],
        "asset_value_usd": [120e6, 80e6, 60e6],
        "construction": ["engineered", "frame", "masonry"],
        "year_built": [2015, 1988, 2001],
        "defended": [True, False, False],
        "country": ["USA", "USA", "USA"],
    })
    sites.to_csv("sim_sites.csv", index=False)

    rc = ri.main(["--sites", "sim_sites.csv", "--out", "sim_results_pack.json",
                  "--mc", "120", "--seed", "42"])
    assert rc == 0, "producer returned nonzero"
    pack = json.loads(Path("sim_results_pack.json").read_text())
    meta = json.loads(Path("sim_results_pack_meta.json").read_text())

    # 1. shape and coverage
    assert pack["kind"] == "results_pack" and pack["pack_version"] == 1
    assert set(pack["scenarios"]) == set(rh.APP_SCENARIOS), \
        "every app scenario must be present (failed source degrades, not drops)"
    assert all(len(s["per_site"]) == 3 for s in pack["scenarios"].values())
    print("ok  pack shape, all 10 scenarios, 3 sites per scenario")

    # 2. failed wind source degrades gracefully and is recorded
    assert any(s.get("source") == "rcp26_2060" for s in meta["skipped"])
    aal126 = pack["scenarios"]["ssp126_2050"]["portfolio"]["direct_aal_usd"]
    assert aal126 > 0, "ssp126_2050 must be carried by the surviving member"
    print("ok  failed wind source: recorded in meta, scenario still served")

    # 3. missing river dataset skipped, not fatal
    assert any(s.get("layer") == "rflood" and s.get("scenario") == "ssp126_2030"
               for s in meta["skipped"])
    assert pack["scenarios"]["ssp126_2030"]["portfolio"]["by_peril_aal_usd"]["rflood"] == 0
    print("ok  missing river-flood dataset: skipped and recorded, rflood AAL 0")

    # 4. physics sanity: climate signal, EP monotone, defended site drier
    now = pack["scenarios"]["present"]["portfolio"]["direct_aal_usd"]
    fut = pack["scenarios"]["ssp585_2080"]["portfolio"]["direct_aal_usd"]
    assert fut > now > 0, (now, fut)
    for s in pack["scenarios"].values():
        ep = [s["portfolio"]["ep_usd"][str(rp)] for rp in ri.RPS]
        assert all(ep[i] <= ep[i + 1] + 0.01 for i in range(len(ep) - 1))
    inland = pack["scenarios"]["present"]["per_site"][2]
    assert inland["by_peril"]["cflood"] == 0, "inland site must have no surge"
    print("ok  climate signal rises, EP curves monotone, inland surge zero")

    # 5. adaptation and uncertainty sections
    for mk in ("wind", "flood", "buffer"):
        rec = pack["adaptation"][mk]["per_scenario"]["present"]
        assert rec["averted_direct_aal_usd"] >= 0 and rec["cost_usd"] > 0
    assert pack["adaptation"]["wind"]["per_scenario"]["present"][
        "averted_direct_aal_usd"] > 0
    for sk in ("present", "ssp245_2050", "ssp585_2080"):
        b = pack["uncertainty"][sk]["acute_aal_usd"]
        assert b["p5"] <= b["p50"] <= b["p95"]
    print("ok  adaptation appraises, uncertainty bands ordered")

    # 5a2. capital plan: present, ranked, and gated
    plan = pack.get("capital_plan")
    assert plan and plan["projects"], "capital plan must be present"
    bcrs = [p["bcr"] for p in plan["projects"]]
    assert bcrs == sorted(bcrs, reverse=True)
    assert plan["scenario"] == "ssp245_2050"
    bad_plan = json.loads(Path("sim_results_pack.json").read_text())
    bad_plan["capital_plan"]["projects"].reverse()
    Path("sim_pack_badplan.json").write_text(json.dumps(bad_plan))
    r_plan = subprocess.run([sys.executable, "validate_pack.py",
                             "sim_pack_badplan.json"],
                            capture_output=True, text=True)
    assert r_plan.returncode == 1 and "not sorted by BCR" in r_plan.stdout
    print("ok  capital plan: ranked in the pack, unsorted plan rejected")

    # 5b. backtest calibration: recorded, sane, and gated
    pd.DataFrame({"name": ["Reef Bay", "Dune Point", "Nowhere Resort"],
                  "observed_annual_loss_usd": [900_000, 400_000, 1]}
                 ).to_csv("sim_backtest.csv", index=False)
    rc_cal = ri.main(["--sites", "sim_sites.csv", "--out",
                      "sim_results_pack_cal.json", "--mc", "60",
                      "--seed", "42", "--backtest", "sim_backtest.csv"])
    assert rc_cal == 0
    cal = json.loads(Path("sim_results_pack_cal.json").read_text())["calibration"]
    assert cal["matched_sites"] == 2, "only names present in sites count"
    assert cal["observed_total_usd"] == 1_300_000.0
    assert cal["applied"] is False
    assert ri.VHALF_LO <= cal["fitted_v_half"] <= ri.VHALF_HI
    r_cal = subprocess.run([sys.executable, "validate_pack.py",
                            "sim_results_pack_cal.json"],
                           capture_output=True, text=True)
    assert r_cal.returncode == 0 and "calibration recorded" in r_cal.stdout
    print("ok  calibration: matched sites only, recorded not applied, gated")

    # 6. determinism: same seed reproduces the pack byte for byte
    rc2 = ri.main(["--sites", "sim_sites.csv", "--out", "sim_results_pack2.json",
                   "--mc", "120", "--seed", "42"])
    assert rc2 == 0
    a = json.loads(Path("sim_results_pack.json").read_text())
    b = json.loads(Path("sim_results_pack2.json").read_text())
    a.pop("generated_utc"); b.pop("generated_utc")
    assert a == b, "same inputs and seed must reproduce the pack exactly"
    print("ok  same seed reproduces the pack exactly (timestamps aside)")

    # 7. the validator accepts the pack...
    r = subprocess.run([sys.executable, "validate_pack.py",
                        "sim_results_pack.json", "sim_results_pack_meta.json"],
                       capture_output=True, text=True)
    print("\n--- validate_pack.py on the simulated pack ---")
    print(r.stdout)
    assert r.returncode == 0 and "pack is shippable" in r.stdout

    # 8. ...and rejects corrupted variants
    bad = json.loads(Path("sim_results_pack.json").read_text())
    bad["scenarios"] = {"present": bad["scenarios"]["present"]}
    Path("sim_pack_presentonly.json").write_text(json.dumps(bad))
    r2 = subprocess.run([sys.executable, "validate_pack.py",
                         "sim_pack_presentonly.json"],
                        capture_output=True, text=True)
    assert r2.returncode == 1 and "ONLY the present scenario" in r2.stdout

    bad2 = json.loads(Path("sim_results_pack.json").read_text())
    bad2["scenarios"]["present"]["portfolio"]["ep_usd"]["500"] = 1.0  # tail dips
    Path("sim_pack_badep.json").write_text(json.dumps(bad2))
    r3 = subprocess.run([sys.executable, "validate_pack.py",
                         "sim_pack_badep.json"], capture_output=True, text=True)
    assert r3.returncode == 1 and "DECREASE with return period" in r3.stdout

    bad3 = json.loads(Path("sim_results_pack_meta.json").read_text())
    bad3["layers"].append({"scenario": "ssp999_2100"})
    Path("sim_pack_ghostmeta.json").write_text(json.dumps(bad3))
    r4 = subprocess.run([sys.executable, "validate_pack.py",
                         "sim_results_pack.json", "sim_pack_ghostmeta.json"],
                        capture_output=True, text=True)
    assert r4.returncode == 1 and "meta claims scenarios absent" in r4.stdout
    print("ok  validator: accepts the good pack, rejects present-only, "
          "non-monotone EP, and ghost meta")

    print("\nALL IMPACTS SIMULATION TESTS PASSED")


if __name__ == "__main__":
    run()
