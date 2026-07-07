"""Unit tests for profile schema v2: the vuln_v2 factor table, the flood MDD
cap, backward compatibility with six-field sites, and enrich_sites.py's merge
logic with every fetcher mocked. Pure pandas/numpy; no CLIMADA, no network.
    python3 test_profileops.py
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import refresh_impacts as ri
import enrich_sites as es


def ok(msg):
    print("ok ", msg)


# --- vuln_v2: compatibility first --------------------------------------------------

def test_v2_reduces_to_v1():
    # no v2 fields: EXACTLY the legacy behavior, including the default cap
    for args in ((None, None, False), ("frame", 1980, True),
                 ("engineered", 2015, False), ("masonry", 2000, False)):
        legacy = ri.vuln_of(*args)
        v2 = ri.vuln_v2(*args)
        assert v2[0] == legacy[0] and v2[1] == legacy[1], (args, legacy, v2)
        assert v2[2] == ri.FLOOD_CAP_DEFAULT
    ok("vuln_v2 with no v2 fields reproduces vuln_of exactly (cap 0.75)")


def test_v2_wind_factor_table():
    # roof detail supersedes the year-built proxy (no double counting)
    w, _, _ = ri.vuln_v2("masonry", 1980, roof_type="metal", roof_year=2020,
                         opening_protection="impact")
    assert abs(w - 1.0 * 0.85 * 0.9 * 0.85) < 1e-12, w
    # old shingle roof, unprotected openings on frame: clipped at 1.6
    w, _, _ = ri.vuln_v2("frame", 2015, roof_type="shingle", roof_year=2000,
                         opening_protection="none")
    assert w == 1.6, w                       # 1.3*1.1*1.2*1.05 = 1.80 -> clip
    # single v2 field present: others neutral, legacy age factor NOT applied
    w, _, _ = ri.vuln_v2("masonry", 1980, roof_type="tile")
    assert abs(w - 0.95) < 1e-12, w
    # roof age bands at the boundaries (reference year pinned)
    for ry, f in ((ri.ROOF_AGE_REF_YEAR - 10, 0.9),
                  (ri.ROOF_AGE_REF_YEAR - 11, 1.0),
                  (ri.ROOF_AGE_REF_YEAR - 20, 1.0),
                  (ri.ROOF_AGE_REF_YEAR - 21, 1.2)):
        w, _, _ = ri.vuln_v2("masonry", None, roof_year=ry)
        assert abs(w - f) < 1e-12, (ry, w, f)
    ok("wind factor table: composition, clipping, neutrality, age bands")


def test_v2_flood_fields():
    # measured first-floor height supersedes the defended proxy
    _, fb, cap = ri.vuln_v2("masonry", None, defended=True,
                            first_floor_elev_m=1.2)
    assert fb == 1.2 and cap == ri.FLOOD_CAP_DEFAULT
    _, fb, _ = ri.vuln_v2("masonry", None, defended=True)
    assert fb == 0.5                          # proxy still honored alone
    _, fb, _ = ri.vuln_v2("masonry", None, first_floor_elev_m=9.0)
    assert fb == ri.FIRST_FLOOR_MAX_M         # sanity cap
    _, _, cap = ri.vuln_v2("masonry", None, equipment_elevated=True)
    assert cap == ri.EQUIP_ELEV_FLOOD_CAP
    ok("flood fields: first-floor supersedes proxy, sanity cap, equipment cap")


def test_flood_cap_in_losses():
    # deep water: elevated equipment caps the damage fraction at 0.5
    depth = np.array([[6.0]])
    vals = np.array([1_000_000.0])
    base = ri.flood_losses(depth, vals, np.array([1.1]))
    capped = ri.flood_losses(depth, vals, np.array([1.1]),
                             cap=np.array([ri.EQUIP_ELEV_FLOOD_CAP]))
    assert abs(base[0, 0] - 750_000.0) < 1e-6
    assert abs(capped[0, 0] - 500_000.0) < 1e-6
    # shallow water below both caps: identical (the cap never adds damage)
    shallow = np.array([[1.5]])
    assert np.allclose(ri.flood_losses(shallow, vals, np.array([1.1])),
                       ri.flood_losses(shallow, vals, np.array([1.1]),
                                       cap=np.array([0.5])))
    ok("flood cap: binds only in deep water, never adds damage")


def test_load_sites_v2_columns():
    p = Path("_tmp_sites_v1.csv")
    p.write_text("name,latitude,longitude,asset_value_usd\nA,25.0,-80.0,1000000\n")
    try:
        df = ri.load_sites(str(p))
        for c in ("roof_type", "first_floor_elev_m", "wui_class",
                  "renovation_year"):
            assert c in df.columns and es.is_blank(df[c].iloc[0])
        for c in ("defended", "equipment_elevated", "roof_class_a"):
            assert df[c].iloc[0] == False   # noqa: E712 (pandas bool)
    finally:
        p.unlink()
    ok("load_sites: a six-field CSV gains blank v2 columns, booleans false")


# --- enrichment merge logic (fetchers mocked) --------------------------------------

def test_merge_never_overwrites():
    df = pd.DataFrame({"name": ["A", "B"], "fema_zone": ["AE", None]})
    prov = {"filled": [], "kept": [], "skipped": []}
    assert not es.merge_field(df, 0, "fema_zone", "X", "src", prov)
    assert es.merge_field(df, 1, "fema_zone", "VE", "src", prov)
    assert df.at[0, "fema_zone"] == "AE"       # operator value untouched
    assert df.at[1, "fema_zone"] == "VE"
    assert prov["kept"][0]["reason"] == "operator value kept"
    assert prov["filled"][0]["needs_review"] is True
    ok("merge_field: fills blanks only, provenance both ways, needs_review")


def test_cell_mean_ground():
    """Task 4: the cell reference excludes bathymetry, so a beachfront cell's
    ground is read against its LAND surface, not the sea floor."""
    got = es.cell_mean_ground([[2.0, 4.0, -30.0, float("nan")],
                               [-5.0, -12.0, float("nan"), -1.0],
                               [0.0, 1.0, 2.0, 3.0]])
    assert got[0] == 3.0, "underwater and missing samples stay out of the mean"
    assert got[1] is None, "an all-water cell has no land reference"
    assert got[2] == 1.5
    ok("cell_mean_ground: land-only mean, honest None for all-water cells")


def test_enrich_end_to_end_mocked():
    es.sample_dem = lambda lats, lons: ([3.2, 41.0], None)
    es.sample_dem_cell = lambda lats, lons, grid_deg=None: ([1.2, 40.0], None)
    es.coast_distance_km = lambda lats, lons: ([0.4, 55.2], None)
    es.fetch_fema_zone = lambda lat, lon: (("VE", None) if lat < 26
                                           else ("AE", None))
    es.fetch_osm_buildings = lambda lat, lon, radius_m=150: (
        (12, None) if lat < 26 else (None, "Overpass unreachable"))
    src, out = Path("_tmp_sites.csv"), Path("_tmp_enriched.csv")
    src.write_text("name,latitude,longitude,asset_value_usd,fema_zone\n"
                   "Coast,25.0,-80.0,1000000,\n"
                   "Inland,29.5,-98.5,2000000,X\n")
    try:
        rc = es.main([str(src), "-o", str(out)])
        assert rc == 0
        df = pd.read_csv(out)
        meta = json.loads(out.with_name(out.stem + "_meta.json").read_text())
        assert df.at[0, "fema_zone"] == "VE"          # drafted
        assert df.at[1, "fema_zone"] == "X"           # fetched AE, operator kept
        assert df.at[0, "ground_elev_m"] == 3.2
        assert df.at[0, "cell_ground_elev_m"] == 1.2, \
            "the cell land-ground reference is drafted beside the point sample"
        assert df.at[0, "buildings"] == 12
        assert any(s["source"] == "osm" for s in meta["skipped"])
        assert all(f["needs_review"] for f in meta["filled"])
        assert any(k["reason"] == "operator value kept" for k in meta["kept"])
    finally:
        for f in (src, out, out.with_name(out.stem + "_meta.json")):
            if f.exists():
                f.unlink()
    ok("enrich end-to-end: drafts, keeps, skips, and records, all mocked")


def test_enrich_degrades_gracefully():
    es.sample_dem = lambda lats, lons: (None, "DEM not found")
    es.sample_dem_cell = lambda lats, lons, grid_deg=None: (None, "DEM not found")
    es.coast_distance_km = lambda lats, lons: (None, "offline")
    src, out = Path("_tmp_sites2.csv"), Path("_tmp_enriched2.csv")
    src.write_text("name,latitude,longitude\nA,25.0,-80.0\n")
    try:
        rc = es.main([str(src), "-o", str(out), "--no-network"])
        assert rc == 0                                 # skips, never crashes
        meta = json.loads(out.with_name(out.stem + "_meta.json").read_text())
        assert len(meta["skipped"]) == 3 and not meta["filled"]
    finally:
        for f in (src, out, out.with_name(out.stem + "_meta.json")):
            if f.exists():
                f.unlink()
    ok("enrich degrades gracefully: every source down, exit 0, all recorded")


if __name__ == "__main__":
    test_v2_reduces_to_v1()
    test_v2_wind_factor_table()
    test_v2_flood_fields()
    test_flood_cap_in_losses()
    test_load_sites_v2_columns()
    test_merge_never_overwrites()
    test_cell_mean_ground()
    test_enrich_end_to_end_mocked()
    test_enrich_degrades_gracefully()
    print("\nALL PROFILE-OP TESTS PASSED")
