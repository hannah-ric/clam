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

import measures_catalog as mc
import refresh_hazard as rh
import refresh_impacts as ri
import refresh_prain as rpn
import refresh_wildfire as rw

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
        # the present catalog carries event names (the real Data API path);
        # future sources leave them off so the source:index fallback is
        # exercised end to end too
        if skey == "present":
            self.event_name = [f"SIM{i:03d}" for i in range(N_EVENTS)]


class FakeSurge:
    """SLOSH-ish: linear in wind minus 1 m elevation, coastal cells only.
    Works on WHATEVER centroid subset the wind hazard carries (per-region
    SLR subsets it), so 'inland' is geographic (lon < -94.9), not
    positional."""
    def __init__(self, wind, slr):
        self.centroids = wind.centroids
        self.intensity = np.maximum(0.12 * (wind.intensity - 26.0) - 1.0 + slr, 0.0)
        inland = np.asarray(wind.centroids.lon, float) < -94.9
        self.intensity[:, inland] = 0.0                  # inland cells dry
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


# WRC point-sampling fake (Task 3.5): a "raster" defined by site latitude.
# The BP raster covers CONUS only (Kona, lat < 20, reads nodata -> FLAGGED);
# the CFL raster has a value only at River Bend (the others get the capped
# interim conditional ratio, labeled).
def fake_sample_raster(path, lat, lon):
    lat = np.asarray(lat, float)
    if "bp" in str(path):
        vals = np.where(np.isclose(lat, 25.02), 0.0,
                        np.where(np.isclose(lat, 25.24), 0.004,
                                 np.where(np.isclose(lat, 29.49), 0.012,
                                          -9999.0)))
        return vals, lat > 20.0
    vals = np.where(np.isclose(lat, 29.49), 9.0, -9999.0)   # 9 ft flame length
    return vals, np.isclose(lat, 29.49)


RAIN_EVENTS = np.linspace(0.4, 1.9, 25)[:, None]


class FakeRainHaz2:
    def __init__(self):
        class C:
            lat = np.array([25.02, 25.24, 29.49])
            lon = np.array([-80.01, -80.02, -98.52])
        self.centroids = C()
        self.frequency = np.full(25, 1 / 25.0)
        self.intensity = RAIN_EVENTS * np.array([[600.0, 500.0, 900.0]])


RF_MISSING = {"ssp126_2030"}

def fake_fetch_river(iso3, app_key, meta, cache=None):
    if app_key in RF_MISSING:
        return []
    meta.setdefault("rflood_sources", {})[f"{iso3}:{app_key}"] = {"n_members": 2}
    return [FakeRiver(app_key, 0), FakeRiver(app_key, 1)]


def run():
    rh.fetch_wind = fake_fetch_wind
    rh.compute_surge = fake_compute_surge
    ri.fetch_river_flood_hazards = fake_fetch_river
    # rasterio is mocked at the sampling seam; the real resolve/wrc_at_points
    # plumbing runs, so the pack path exercises WRC exactly like production
    rw.sample_raster_points = fake_sample_raster
    rpn.fetch_tracks = lambda iso3: object()
    rpn.rain_hazard = lambda tracks, iso3: FakeRainHaz2()
    dem = Path("fake_dem.tiff"); dem.write_bytes(b"\0" * 16)
    rh.TOPO_PATH = dem

    # Kona Shore sits in Hawaii, far outside every fake hazard's centroids:
    # the per-site coverage path must FLAG it on every peril, never let it
    # silently score zero while looking modeled.
    sites = pd.DataFrame({
        "name": ["Reef Bay", "Dune Point", "River Bend", "Kona Shore"],
        "latitude": [25.02, 25.24, 29.49, 19.64],
        "longitude": [-80.01, -80.02, -98.52, -155.99],
        "asset_value_usd": [120e6, 80e6, 60e6, 50e6],
        "construction": ["engineered", "frame", "masonry", "frame"],
        "year_built": [2015, 1988, 2001, 1992],
        "defended": [True, False, False, False],
        "country": ["USA", "USA", "USA", "USA"],
        # profile v2 fields, exercised through the real producer path
        "roof_type": ["metal", "shingle", None, None],
        "roof_year": [2019, 1999, None, None],
        "opening_protection": ["impact", "none", None, None],
        "first_floor_elev_m": [1.4, None, None, None],
        "equipment_elevated": [True, False, False, False],
        "wui_class": [None, None, "intermix", None],
        "defensible_space_m": [None, None, 10, None],
        # exercise the archetype layer through the real producer path
        "archetype": [None, "beachfront_lowrise", None, None],
        # Task 4: Reef Bay carries both elevation fields (relief +1.0 m ->
        # depth read at the structure); the rest stay cell-average (flagged)
        "ground_elev_m": [2.6, None, None, None],
        "cell_ground_elev_m": [1.6, None, None, None],
        # Dune Point's renovation sits EXACTLY PLAN_YEARS out: the boundary
        # that used to crash the budgeted plan with KeyError (year 4)
        "renovation_year": [None, ri.ROOF_AGE_REF_YEAR + mc.PLAN_YEARS, None,
                            None],
    })
    sites.to_csv("sim_sites.csv", index=False)

    rc = ri.main(["--sites", "sim_sites.csv", "--out", "sim_results_pack.json",
                  "--mc", "120", "--seed", "42",
                  "--wrc-bp", "sim_bp.tif", "--wrc-cfl", "sim_cfl.tif"])
    assert rc == 0, "producer returned nonzero"
    pack = json.loads(Path("sim_results_pack.json").read_text())
    meta = json.loads(Path("sim_results_pack_meta.json").read_text())

    # 1. shape and coverage
    assert pack["kind"] == "results_pack" and pack["pack_version"] == 1
    assert set(pack["scenarios"]) == set(rh.APP_SCENARIOS), \
        "every app scenario must be present (failed source degrades, not drops)"
    assert all(len(s["per_site"]) == 4 for s in pack["scenarios"].values())
    print("ok  pack shape, all 10 scenarios, 4 sites per scenario")

    # 1b. per-site-per-peril coverage: Kona Shore (Hawaii, outside every fake
    # hazard's centroids) is flagged on every peril; the CONUS sites read
    # covered. Its zeros are thereby labeled "not modeled", not "modeled safe".
    cov = {x["name"]: x["coverage"]
           for x in pack["scenarios"]["present"]["per_site"]}
    assert set(cov["Reef Bay"]) == {"tc", "cflood", "rflood", "prain", "wfire"}
    assert all(cov["Reef Bay"].values()), "coastal CONUS site fully covered"
    assert not any(cov["Kona Shore"].values()), \
        "the Hawaii site must be flagged outside coverage on every peril here"
    for layer in ("tc", "wfire", "prain"):
        assert any(s.get("site") == "Kona Shore" and s.get("layer") == layer
                   for s in meta["skipped"]), \
            f"Kona Shore must be recorded as outside {layer} coverage"
    print("ok  per-site coverage: Hawaii site flagged on every peril, "
          "CONUS sites covered")

    # 1c. Task 4: flood depth basis per site, flagged in pack and meta
    basis = {x["name"]: x["flood_depth_basis"]
             for x in pack["scenarios"]["present"]["per_site"]}
    assert basis["Reef Bay"] == "structure", \
        "both elevation fields present: depth read at the structure"
    assert basis["Dune Point"] == "cell" and basis["Kona Shore"] == "cell", \
        "missing elevation falls back to the cell value, flagged not silent"
    assert meta["flood_depth_basis"]["at_structure_sites"] == 1
    assert meta["flood_depth_basis"]["cell_average_sites"] == 3
    print("ok  flood depth basis: at-structure vs cell-average flagged "
          "per site and counted in meta")

    # 1d. Task 5: per-site return-period losses beside the EAD
    ps0 = {x["name"]: x for x in pack["scenarios"]["present"]["per_site"]}
    for x in ps0.values():
        assert x["loss_rp250_usd"] >= x["loss_rp100_usd"] >= 0
    assert ps0["Reef Bay"]["loss_rp100_usd"] > 0, \
        "an exposed coastal site carries a 1-in-100 loss figure"
    assert ps0["Kona Shore"]["loss_rp100_usd"] == 0, \
        "a site outside every hazard's coverage carries zero (and is flagged)"
    print("ok  per-site 1-in-100 / 1-in-250 losses in the pack, monotone")

    # 1e. TCOR Task A: per-event, per-site joint losses with event ids (the
    # shared hurricane deductible's hard dependency) and frequent ladders
    ev = pack["event_sets"]
    assert set(ev["scenarios"]) == set(rh.APP_SCENARIOS), \
        "every served scenario carries its joint event table"
    parts = ev["scenarios"]["present"]
    assert len(parts) == 1 and parts[0]["source"] == "present"
    assert parts[0]["country"] == "USA" and parts[0]["weight"] == 1.0
    evs = parts[0]["events"]
    assert evs and all(e["id"].startswith("SIM") for e in evs), \
        "present catalog events carry the catalog's own names"
    assert any(e["id"].startswith("rcp85_2040:") for p2 in
               ev["scenarios"]["ssp585_2050"] for e in p2["events"]), \
        "sources without names fall back to source:index ids"
    # event-level reconciliation: sum freq x loss over the kept table equals
    # the recorded kept AAL, which is within floor-tolerance of tc + cflood
    kept = sum(e["freq"] * sum(l for _j, l in e["sites"]) for e in evs)
    assert abs(kept - parts[0]["kept_aal_usd"]) < 1.0
    bp_now = pack["scenarios"]["present"]["portfolio"]["by_peril_aal_usd"]
    joint = bp_now["tc"] + bp_now["cflood"]
    assert abs(parts[0]["aal_usd"] - joint) / joint < 0.02
    assert kept >= joint * 0.90
    # multi-site events: one storm touching several sites appears as ONE
    # event with several site entries (what the shared deductible needs)
    assert any(len(e["sites"]) >= 2 for e in evs)
    # Kona Shore (index 3) is outside wind coverage: no event may touch it
    assert all(j != 3 for e in evs for j, _l in e["sites"])

    lad = pack["frequent_losses"]
    assert lad["ladder_rps"] == list(ri.LADDER_RPS)
    ladp = lad["scenarios"]["present"]
    assert set(ladp) >= {"tc", "cflood", "tc_joint", "rflood", "prain",
                         "wfire"}
    for p2, rows in ladp.items():
        assert len(rows) == 4, (p2, len(rows))
        for row in rows:
            assert len(row) == len(ri.LADDER_RPS)
            assert all(row[i] <= row[i + 1] + 0.01
                       for i in range(len(row) - 1)), (p2, row)
    assert all(x == 0 for x in ladp["tc_joint"][3]), \
        "the uncovered Hawaii site reads zero on the ladder (and is flagged)"
    assert ladp["tc_joint"][0][0] > 0, \
        "the frequent 1-in-2 band is populated for the exposed coastal site"
    print("ok  event sets: ids, joint reconciliation, multi-site events, "
          "ladders down to 1-in-2")

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

    # 4f. the five-peril pack: WRC point fire math and rain in the pack
    bp = pack["scenarios"]["present"]["portfolio"]["by_peril_aal_usd"]
    assert set(bp) == {"tc", "cflood", "rflood", "prain", "wfire"}
    assert bp["wfire"] > 0 and bp["prain"] > 0
    ps = {x["name"]: x for x in pack["scenarios"]["present"]["per_site"]}
    # the fire EAD is EXACTLY point p x conditional x value, site by site:
    # River Bend has a CFL value (9 ft -> 0.55), the others the interim ratio
    assert abs(ps["River Bend"]["by_peril"]["wfire"]
               - 0.012 * 0.55 * 60e6) < 1.0, ps["River Bend"]["by_peril"]
    assert abs(ps["Dune Point"]["by_peril"]["wfire"]
               - 0.004 * ri.FIRE_COND_INTERIM * 80e6) < 1.0
    assert ps["Reef Bay"]["by_peril"]["wfire"] == 0    # zero point probability
    assert ps["Kona Shore"]["by_peril"]["wfire"] == 0  # uncovered AND flagged
    fut = pack["scenarios"]["ssp585_2080"]["portfolio"]["by_peril_aal_usd"]
    assert fut["wfire"] > bp["wfire"], \
        "warming scales the fire arrival probability"
    assert fut["prain"] > bp["prain"], "rainfall scales with warming"
    assert any(p["measure_key"] == "defensible"
               for p in pack["capital_plan"]["projects"]), \
        "wildfire measures price against the point-probability layer"
    # sanity (Task 3.5): no site anywhere near the old 13-18%/yr regime
    assert float(max(0.0, 0.012)) <= 0.02, "fixture stays in the 0-2% band"
    print("ok  five-peril pack: WRC point fire math exact per site, "
          "plan prices wildfire")

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

    # 5a3. measures catalog + budgeted plan
    catsec = pack.get("measures_catalog")
    assert catsec and "reroof" in catsec["modeled"]
    assert any(e["reason"] for m in catsec["modeled"].values()
               for e in m["excluded"]), "exclusions carry plain-language reasons"
    assert any(i["key"] == "backup_power" for i in catsec["identified"])
    rc_b = ri.main(["--sites", "sim_sites.csv", "--out",
                    "sim_results_pack_b.json", "--mc", "60", "--seed", "42",
                    "--budget", "1500000"])
    assert rc_b == 0
    pb = json.loads(Path("sim_results_pack_b.json").read_text())
    planb = pb["capital_plan"]
    assert planb["budget_annual_usd"] == 1500000.0
    spent = {}
    for p in planb["projects"]:
        if p.get("year") is not None:
            spent[p["year"]] = spent.get(p["year"], 0.0) + p["cost_usd"]
    assert all(v <= 1500000.0 * 1.001 for v in spent.values())
    # the exact-boundary renovation (Dune Point, PLAN_YEARS out) must phase
    # inside the plan without synergy, never into a nonexistent year 4
    assert all(p["year"] in (None, 1, 2, 3) for p in planb["projects"])
    dune = [p for p in planb["projects"] if p["site"] == "Dune Point"]
    assert dune and not any(p.get("renovation_synergy") for p in dune), \
        "a renovation exactly PLAN_YEARS out earns no synergy discount"
    r_b = subprocess.run([sys.executable, "validate_pack.py",
                          "sim_results_pack_b.json"],
                         capture_output=True, text=True)
    assert r_b.returncode == 0
    print("ok  catalog section, exclusion reasons, budgeted plan gated")

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
                   "--mc", "120", "--seed", "42",
                   "--wrc-bp", "sim_bp.tif", "--wrc-cfl", "sim_cfl.tif"])
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

    # corrupted event table: duplicate event ids within one source must fail
    # (the shared-deductible math would double-count an occurrence)
    bad4 = json.loads(Path("sim_results_pack.json").read_text())
    ev4 = bad4["event_sets"]["scenarios"]["present"][0]["events"]
    ev4[1]["id"] = ev4[0]["id"]
    Path("sim_pack_dupevent.json").write_text(json.dumps(bad4))
    r5 = subprocess.run([sys.executable, "validate_pack.py",
                         "sim_pack_dupevent.json"],
                        capture_output=True, text=True)
    assert r5.returncode == 1 and "duplicate event ids" in r5.stdout

    # a ladder that decreases with rarity must fail
    bad5 = json.loads(Path("sim_results_pack.json").read_text())
    bad5["frequent_losses"]["scenarios"]["present"]["tc_joint"][0][-1] = 0.5
    Path("sim_pack_badladder.json").write_text(json.dumps(bad5))
    r6 = subprocess.run([sys.executable, "validate_pack.py",
                         "sim_pack_badladder.json"],
                        capture_output=True, text=True)
    assert r6.returncode == 1 and "decreases with rarity" in r6.stdout
    print("ok  validator: accepts the good pack, rejects present-only, "
          "non-monotone EP, ghost meta, duplicate event ids, bad ladder")

    print("\nALL IMPACTS SIMULATION TESTS PASSED")


if __name__ == "__main__":
    run()
