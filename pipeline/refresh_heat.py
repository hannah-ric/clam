"""
refresh_heat.py  (Phase 3)
==========================

Companion to refresh_hazard.py: produces the heat layer (hazard="heat") of the
hazard grid from OBSERVED daily temperature climatology instead of the app's
latitude proxy, which the app itself documents as underrepresenting arid
inland microclimates (Palm Springs, San Antonio). Separate script because the
data source, cadence, and dependencies differ from the CLIMADA pipeline: this
one needs no CLIMADA at all.

Method (screening-grade, every choice stated)
---------------------------------------------
1. PRESENT climatology from NOAA CPC Global Daily Temperature (tmax + tmin,
   0.5 degree, land-only, anonymous HTTPS from NOAA PSL, ~55 MB per variable
   per year, cached locally). Default window 2005-2024. This replaces the
   latitude formula with what thermometers recorded per cell.
2. SCENARIOS by the DELTA METHOD: each app scenario shifts the observed daily
   distribution by its warming (the app's own AR6-consistent WARMING table,
   mirrored below) times a land-amplification factor (default 1.25: land
   warms faster than the global mean; AR6 central). Day counts under a shift
   need no second dataset because  days(T + d > thr) == days(T > thr - d):
   one pass over each year file accumulates every scenario at once by
   counting exceedances of shifted thresholds.
3. Indicators per cell per scenario, encoded in the existing grid schema
   ("Option A", so the app needs one small patched function and no new file
   format):   v10 = days/yr over 32 C     (drives the app's heat band)
              v25 = days/yr over 35 C     (drives heat revenue at risk)
              v50 = cooling degree days   (base 18 C, from tmean)
              v100 = v250 = v500 = 0
4. Output rows only where CPC has land data. The app falls back to its
   formula for any site >200 km from a heat cell (small-island mask gaps),
   so coverage holes degrade to the current behaviour, never to zero.

Honest limits: the delta method shifts the whole distribution uniformly, so
it carries no change in variability or humidity; CPC is 0.5 degree, coarser
than the 0.25 wind grid but adequate for a smooth field like temperature; the
upgrade path when heat starts driving capital decisions is a NEX-GDDP-CMIP6
ensemble (native 0.25 degree, true per-scenario dailies): the seam is
`scen_deltas()` and this script's accumulator, nothing in the app.

Usage
-----
    # xarray, netcdf4, requests are added to climada_env by setup_env.sh
    python refresh_heat.py                   # downloads ~2 GB once, cached
    python merge_grids.py hazard_grid.csv heat_grid.csv -o hazard_grid.csv
    python validate_grid.py hazard_grid.csv

Then drop the merged hazard_grid.csv into the app as usual.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
LOG = logging.getLogger("refresh_heat")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

YEARS = list(range(2005, 2025))          # present-day climatology window
CACHE_DIR = Path("cpc_cache")
OUT_CSV = "heat_grid.csv"
OUT_META = "heat_grid_meta.json"

CPC_URL = "https://downloads.psl.noaa.gov/Datasets/cpc_global_temp/{var}.{year}.nc"

# Regions to process: (name, lat_min, lat_max, lon_min, lon_max), lon in -180..180.
# Cover the portfolio with margin; add boxes as it grows.
REGIONS = [
    ("conus_se_gulf", 24.0, 37.5, -100.5, -74.0),   # FL, Gulf, Carolinas, TX triangle
    ("southwest",     32.0, 38.0, -120.0, -110.0),  # Palm Springs, desert SW
    ("hawaii",        18.0, 23.0, -161.0, -154.0),
    ("caribbean",     17.0, 19.5, -68.0, -64.0),    # PR, USVI
]

THRESH_HOT = 32.0        # C, drives the app's heat band (daysOver32)
THRESH_DANGER = 35.0     # C, drives heat revenue at risk (daysOver35)
CDD_BASE = 18.0          # C, cooling degree days base, matches the app

# Warming (deg C above present) per app scenario. MIRRORS the WARMING table in
# TNL_Resort_Climate_Risk_Explorer.html; if you change one, change both.
WARMING = {
    "present": 0.0,
    "ssp126_2030": 0.6, "ssp126_2050": 1.0, "ssp126_2080": 1.3,
    "ssp245_2030": 0.7, "ssp245_2050": 1.4, "ssp245_2080": 2.3,
    "ssp585_2030": 0.8, "ssp585_2050": 2.0, "ssp585_2080": 3.6,
}
# Land warms faster than the global mean the WARMING table expresses; 1.25 is
# an AR6-consistent central land-amplification for these latitudes.
LAND_AMPLIFICATION = 1.25


# ---------------------------------------------------------------------------
# Pure computation (no IO: unit-tested in test_heatops.py)
# ---------------------------------------------------------------------------

def scen_deltas(land_amp: float = LAND_AMPLIFICATION) -> dict:
    """App scenario key -> local warming shift in deg C."""
    return {k: round(w * land_amp, 3) for k, w in WARMING.items()}


class HeatAccumulator:
    """Accumulates day counts and degree days per cell for EVERY scenario in
    one pass over daily arrays, using threshold shifting:
        days(T + d > thr)      == days(T > thr - d)
        sum(max(T + d - b, 0)) == sum(max(T - (b - d), 0))
    Arrays are [n_days, ny, nx]; NaN (ocean in CPC) propagates and marks the
    cell invalid. Call add_year() per year, then finalize() for per-year means.
    """

    def __init__(self, deltas: dict, shape):
        self.deltas = dict(deltas)
        self.n_years = 0
        z = lambda: np.zeros(shape, dtype=float)
        self.d_hot = {k: z() for k in deltas}
        self.d_danger = {k: z() for k in deltas}
        self.cdd = {k: z() for k in deltas}
        self.valid = np.zeros(shape, dtype=bool)

    def add_year(self, tmax_c: np.ndarray, tmean_c: np.ndarray):
        assert tmax_c.shape == tmean_c.shape and tmax_c.ndim == 3
        finite = np.isfinite(tmax_c).all(axis=0) & np.isfinite(tmean_c).all(axis=0)
        self.valid = finite if self.n_years == 0 else (self.valid & finite)
        for k, d in self.deltas.items():
            self.d_hot[k] += np.nansum(tmax_c > (THRESH_HOT - d), axis=0)
            self.d_danger[k] += np.nansum(tmax_c > (THRESH_DANGER - d), axis=0)
            self.cdd[k] += np.nansum(np.maximum(tmean_c - (CDD_BASE - d), 0.0), axis=0)
        self.n_years += 1

    def finalize(self) -> dict:
        """scenario -> dict(days32, days35, cdd) as per-year means, NaN where
        the cell was ever invalid (ocean / missing)."""
        out = {}
        n = max(self.n_years, 1)
        mask = ~self.valid
        for k in self.deltas:
            d32 = self.d_hot[k] / n
            d35 = self.d_danger[k] / n
            cdd = self.cdd[k] / n
            for a in (d32, d35, cdd):
                a[mask] = np.nan
            out[k] = {"days32": d32, "days35": d35, "cdd": cdd}
        return out


def indicators_to_rows(lat2d, lon2d, per_scenario: dict) -> pd.DataFrame:
    """Flatten finalized indicator fields into hazard-grid rows.

    Encoding (Option A): v10=days32, v25=days35, v50=cdd, v100..v500=0.
    Cells with NaN indicators (ocean) are dropped: the app snaps to the
    nearest land cell within 200 km and falls back to its formula beyond.
    """
    frames = []
    la = np.asarray(lat2d, float).ravel()
    lo = np.asarray(lon2d, float).ravel()
    for sc, ind in per_scenario.items():
        d32 = np.asarray(ind["days32"], float).ravel()
        d35 = np.asarray(ind["days35"], float).ravel()
        cdd = np.asarray(ind["cdd"], float).ravel()
        keep = np.isfinite(d32) & np.isfinite(d35) & np.isfinite(cdd)
        df = pd.DataFrame({
            "lat": np.round(la[keep], 3), "lon": np.round(lo[keep], 3),
            "scenario": sc, "hazard": "heat",
            "v10": np.round(d32[keep], 1), "v25": np.round(d35[keep], 1),
            "v50": np.round(cdd[keep], 0),
            "v100": 0.0, "v250": 0.0, "v500": 0.0,
        })
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def to_pm180(lon):
    """CPC longitudes run 0..360; the grid contract is -180..180."""
    lon = np.asarray(lon, float)
    return np.where(lon > 180.0, lon - 360.0, lon)


# ---------------------------------------------------------------------------
# IO: NOAA CPC download + region extraction (needs xarray + netcdf4)
# ---------------------------------------------------------------------------

def cpc_fetch(var: str, year: int) -> Path:
    """Download (once) and cache one CPC global daily file."""
    import requests
    CACHE_DIR.mkdir(exist_ok=True)
    dest = CACHE_DIR / f"{var}.{year}.nc"
    if dest.exists() and dest.stat().st_size > 1_000_000:
        return dest
    url = CPC_URL.format(var=var, year=year)
    LOG.info("Downloading %s", url)
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        tmp.rename(dest)
    return dest


def region_slices(ds, lat_min, lat_max, lon_min, lon_max):
    """Boolean index arrays selecting a region from a CPC dataset (0..360 lon,
    latitude order either way)."""
    la = np.asarray(ds["lat"].values, float)
    lo = to_pm180(ds["lon"].values)
    return ((la >= lat_min) & (la <= lat_max),
            (lo >= lon_min) & (lo <= lon_max))


def year_region_arrays(year: int, lat_sel, lon_sel):
    """(tmax_c, tmean_c) as [days, ny, nx] for one year and one region."""
    import xarray as xr
    with xr.open_dataset(cpc_fetch("tmax", year)) as dx, \
         xr.open_dataset(cpc_fetch("tmin", year)) as dn:
        tmax = dx["tmax"].values[:, lat_sel, :][:, :, lon_sel]
        tmin = dn["tmin"].values[:, lat_sel, :][:, :, lon_sel]
    tmean = 0.5 * (tmax + tmin)
    return tmax, tmean


def heat_meta(out_df: pd.DataFrame, years: list, land_amp: float = LAND_AMPLIFICATION) -> dict:
    """Provenance sidecar for the heat layer, same shape the app's Phase 4
    renderer and merge_grids.py expect (pure: unit-tested)."""
    from datetime import datetime, timezone
    layers = [{"hazard": "heat", "scenario": sc,
               "cells": int((out_df["scenario"] == sc).sum())}
              for sc in sorted(out_df["scenario"].unique())]
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "refresh_heat.py (Phase 3)",
        "method": "CPC daily climatology + AR6 warming deltas",
        "data_source": "NOAA CPC Global Daily Temperature (tmax, tmin), 0.5 deg, land-only",
        "years": [years[0], years[-1]],
        "land_amplification": land_amp,
        "deltas_c": scen_deltas(land_amp),
        "regions": [r[0] for r in REGIONS],
        "encoding": {"v10": "days/yr over 32C", "v25": "days/yr over 35C",
                     "v50": "cooling degree days (base 18C)",
                     "v100": 0, "v250": 0, "v500": 0},
        "units": {"heat": "indicator encoding, see 'encoding'"},
        "layers": layers,
        "skipped": [],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the heat layer of the hazard grid "
                                             "from CPC climatology + AR6 warming deltas.")
    ap.add_argument("--years", nargs=2, type=int, default=[YEARS[0], YEARS[-1]],
                    metavar=("FIRST", "LAST"))
    ap.add_argument("--out", default=OUT_CSV)
    args = ap.parse_args(argv)
    years = list(range(args.years[0], args.years[1] + 1))
    deltas = scen_deltas()
    LOG.info("Scenario shifts (deg C, local): %s", deltas)

    import xarray as xr
    all_rows = []
    for name, la0, la1, lo0, lo1 in REGIONS:
        LOG.info("Region %s: lat %.1f..%.1f lon %.1f..%.1f", name, la0, la1, lo0, lo1)
        with xr.open_dataset(cpc_fetch("tmax", years[0])) as ds0:
            lat_sel, lon_sel = region_slices(ds0, la0, la1, lo0, lo1)
            lat = np.asarray(ds0["lat"].values, float)[lat_sel]
            lon = to_pm180(ds0["lon"].values)[lon_sel]
        lon2d, lat2d = np.meshgrid(lon, lat)
        acc = HeatAccumulator(deltas, (lat_sel.sum(), lon_sel.sum()))
        for y in years:
            tmax, tmean = year_region_arrays(y, lat_sel, lon_sel)
            acc.add_year(tmax, tmean)
            LOG.info("  %s %d: %d days accumulated", name, y, tmax.shape[0])
        rows = indicators_to_rows(lat2d, lon2d, acc.finalize())
        LOG.info("  %s -> %d rows (%d land cells x %d scenarios)",
                 name, len(rows), len(rows) // max(len(deltas), 1), len(deltas))
        all_rows.append(rows)

    out = pd.concat(all_rows, ignore_index=True)
    # regions may overlap; keep one row per cell/scenario
    out = out.drop_duplicates(subset=["lat", "lon", "scenario", "hazard"], keep="first")
    out.to_csv(args.out, index=False)
    import json
    meta_path = Path(args.out).with_name(Path(args.out).stem + "_meta.json")
    meta_path.write_text(json.dumps(heat_meta(out, years), indent=2))
    LOG.info("Wrote %d heat rows to %s and provenance to %s",
             len(out), args.out, meta_path)
    LOG.info("Next: python merge_grids.py hazard_grid.csv %s -o hazard_grid.csv "
             "&& python validate_grid.py hazard_grid.csv", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
