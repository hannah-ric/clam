"""Unit tests for refresh_hazard.py's pure grid functions and recipes.
Runs anywhere with pandas/numpy: no CLIMADA needed. python3 test_gridops.py"""
import numpy as np
import pandas as pd

import refresh_hazard as rh

RPS = rh.RETURN_PERIODS
V = [f"v{rp}" for rp in RPS]


def mkgrid(cells, val):
    """grid df with constant value `val` in every v column at given cells."""
    df = pd.DataFrame(cells, columns=["lat", "lon"])
    for c in V:
        df[c] = float(val)
    return df


def test_recipes():
    r = rh.APP_SCENARIOS
    assert set(r) == {"present"} | {f"{p}_{h}" for p in ("ssp126", "ssp245", "ssp585")
                                    for h in (2030, 2050, 2080)}
    for k, recipe in r.items():
        assert abs(sum(w for w, _ in recipe) - 1.0) < 1e-9, k
    assert r["ssp245_2050"] == [(0.5, ("rcp45", "2040")), (0.5, ("rcp45", "2060"))]
    assert r["ssp585_2030"][0] == (0.5, "present")
    assert r["ssp126_2080"] == [(1.0, ("rcp26", "2080"))]
    srcs = {rh.source_key(s) for s in rh.unique_sources(r)}
    assert srcs == {"present"} | {f"{rcp}_{y}" for rcp in ("rcp26", "rcp45", "rcp85")
                                  for y in ("2040", "2060", "2080")}
    print("ok  recipes: 10 keys, weights sum to 1, 10 unique sources")


def test_thin_to_grid():
    # four centroids in one 0.25-deg cell, two in another; values average per cell
    lat = [25.01, 25.02, 24.99, 25.03, 25.26, 25.24]
    lon = [-80.01, -80.02, -79.99, -80.03, -80.01, -80.02]
    vals = {rp: np.array([10, 20, 30, 40, 100, 200], float) for rp in RPS}
    g = rh.thin_to_grid(lat, lon, vals, grid_deg=0.25)
    assert len(g) == 2
    cell1 = g[(g.lat == 25.0) & (g.lon == -80.0)]
    cell2 = g[(g.lat == 25.25) & (g.lon == -80.0)]
    assert np.isclose(cell1["v100"].iloc[0], 25.0)
    assert np.isclose(cell2["v100"].iloc[0], 150.0)
    print("ok  thin_to_grid: cell assignment and within-cell averaging")


def test_blend_equal_and_renormalised():
    cells = [(25.0, -80.0), (25.25, -80.0)]
    a, b = mkgrid(cells, 10), mkgrid(cells, 30)
    out = rh.blend_grids([(0.5, a), (0.5, b)])
    assert np.allclose(out[V].to_numpy(), 20.0)
    # member b missing one cell -> that cell averages over a only (renormalise)
    b2 = b.iloc[[0]]
    out2 = rh.blend_grids([(0.5, a), (0.5, b2)]).sort_values(["lat", "lon"])
    both = out2[(out2.lat == 25.0)]["v100"].iloc[0]
    only_a = out2[(out2.lat == 25.25)]["v100"].iloc[0]
    assert np.isclose(both, 20.0) and np.isclose(only_a, 10.0)
    # asymmetric weights
    out3 = rh.blend_grids([(0.25, a), (0.75, b)])
    assert np.allclose(out3[V].to_numpy(), 25.0)
    print("ok  blend_grids: weighted mean, missing-member renormalisation")


def test_align_to_cells():
    base = mkgrid([(25.0, -80.0), (25.25, -80.0), (30.0, -95.0)], 0)  # wind cells
    surge = mkgrid([(25.0, -80.0)], 2.5)                              # coastal only
    out = rh.align_to_cells(surge, base)
    assert len(out) == 3
    inland = out[(out.lat == 30.0)]
    assert np.allclose(inland[V].to_numpy(), 0.0), "inland cells must be explicit zeros"
    coast = out[(out.lat == 25.0) & (out.lon == -80.0)]
    assert np.isclose(coast["v100"].iloc[0], 2.5)
    print("ok  align_to_cells: full coverage restored, inland zeros explicit")


def test_blend_reproduces_single_source():
    """A recipe with one source must reproduce that source exactly."""
    g = mkgrid([(25.0, -80.0)], 42.0)
    out = rh.blend_grids([(1.0, g)])
    assert np.allclose(out[V].to_numpy(), 42.0)
    print("ok  blend_grids: identity on single-source recipes")


if __name__ == "__main__":
    test_recipes()
    test_thin_to_grid()
    test_blend_equal_and_renormalised()
    test_align_to_cells()
    test_blend_reproduces_single_source()
    print("\nALL GRID-OP TESTS PASSED")
