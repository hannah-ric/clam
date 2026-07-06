"""
refresh_wildfire.py  (adaptation-first increment 3: the fifth peril)
=====================================================================

Produces the wildfire layer (hazard="wfire") of the hazard grid from CLIMADA
Petals' WildFire module (NASA FIRMS fire history, probabilistic fire seasons).

Encoding (indicator style, like heat's Option A):
    v10  = annual burn probability, PERCENT (0..100)
    v25..v500 = 0
The app computes wildfire expected damage as value x burn probability x a
documented conditional damage ratio, modified by the site's wildfire profile
fields (roof_class_a, defensible_space_m). Fire loss is near-binary per
structure, so a burn probability is the honest screening quantity; return
period depth/speed columns would suggest precision the science lacks.

Scenarios by a documented uplift: burn probability scales with warming at
FIRE_WARMING_UPLIFT per degree C (fire-weather-day scaling, screening grade),
using the app's own WARMING table so grid and app never disagree.

Honest limits: FIRMS observes fire, not structure loss; the probabilistic
event set is research grade; the uplift is a scalar on a complex system.
This layer flags WHERE wildfire belongs on the agenda, not parcel risk.

Input: a NASA FIRMS archive CSV of active-fire detections (MODIS and/or VIIRS),
downloaded once from https://firms.modaps.eosdis.nasa.gov/download/. Petals'
WildFire builds its hazard FROM that DataFrame; it has no download-by-country
constructor (the prior code passed a "USA" string where a DataFrame was
expected, hence "'str' object has no attribute 'columns'"). The operator
supplies the file, exactly like the one-time DEM. Without it the app keeps
wildfire on its wui_class interim model, by design.

Usage (the FIRMS source is auto-discovered, so a plain run works once the CSVs
are in ./firms/):
    python refresh_wildfire.py                          # uses ./firms/ or firms_us.csv
    python refresh_wildfire.py --firms firms_us.csv     # or an explicit path
    python refresh_wildfire.py --firms firms/           # a folder of FIRMS CSVs
    python merge_grids.py hazard_grid.csv wfire_grid.csv -o hazard_grid.csv
    python validate_grid.py hazard_grid.csv hazard_grid_meta.json
"""

from __future__ import annotations

import argparse
import os
import tempfile
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import refresh_hazard as rh

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
LOG = logging.getLogger("refresh_wildfire")

# MIRRORS the WARMING table in the app and refresh_heat.py; change all three.
WARMING = {
    "present": 0.0,
    "ssp126_2030": 0.6, "ssp126_2050": 1.0, "ssp126_2080": 1.3,
    "ssp245_2030": 0.7, "ssp245_2050": 1.4, "ssp245_2080": 2.3,
    "ssp585_2030": 0.8, "ssp585_2050": 2.0, "ssp585_2080": 3.6,
}
FIRE_WARMING_UPLIFT = 0.14      # fractional burn-probability increase per deg C

# The resort footprint. A nationwide FIRMS download is trimmed to these boxes so
# Petals builds centroids over cells that can actually host a site (mirrors the
# REGIONS in refresh_heat.py). Wildfire is portfolio-wide, not only the desert SW.
FIRE_REGIONS = [
    ("conus_se_gulf", 24.0, 37.5, -100.5, -74.0),
    ("southwest",     32.0, 38.0, -120.0, -110.0),   # Palm Springs, desert SW
    ("hawaii",        18.0, 23.0, -161.0, -154.0),
    ("caribbean",     17.0, 19.5, -68.0, -64.0),     # PR, USVI
]
# Columns climada_petals' WildFire._clean_firms_df reads. MODIS carries
# 'brightness' with a numeric 'confidence'; VIIRS carries 'bright_ti4' with l/n/h.
FIRMS_REQUIRED = ["latitude", "longitude", "acq_date", "instrument", "confidence"]
# Auto-discovered when --firms is not passed: the FIRMS_CSV env var, then a
# ./firms/ folder of CSVs, then a single firms_us.csv, in the working directory.
DEFAULT_FIRMS = ["firms", "firms_us.csv"]


# ---------------------------------------------------------------------------
# Pure ops (unit-tested in test_newperils.py)
# ---------------------------------------------------------------------------

def burn_probability(freq, hits):
    """Annual burn probability per centroid from a probabilistic fire event
    set: the Poisson rate of fire arrivals at the centroid, converted to a
    probability. `hits` is the boolean [events x centroids] burned matrix."""
    lam = (np.asarray(freq, float)[:, None] * np.asarray(hits, bool)).sum(axis=0)
    return 1.0 - np.exp(-lam)


def scenario_pburn(p_present, warming_c, uplift=FIRE_WARMING_UPLIFT):
    """Scale present burn probability for a warming level, capped at 1."""
    return np.minimum(np.asarray(p_present, float) * (1.0 + uplift * warming_c),
                      1.0)


def wfire_rows(lat, lon, p_present, grid_deg=rh.GRID_DEG):
    """Grid rows for every app scenario. Thinning happens on the PRESENT
    probability, then scenarios scale the thinned field, so all ten
    scenarios share exactly one cell set (coverage never varies by horizon)."""
    thinned = rh.thin_to_grid(lat, lon, {10: np.asarray(p_present, float)},
                              grid_deg=grid_deg)
    frames = []
    for sc, w in WARMING.items():
        df = thinned.copy()
        df["v10"] = np.round(scenario_pburn(df["v10"].to_numpy(), w) * 100.0, 3)
        for c in ("v25", "v50", "v100", "v250", "v500"):
            df[c] = 0.0
        df["scenario"], df["hazard"] = sc, "wfire"
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    cols = ["lat", "lon", "scenario", "hazard"] + [f"v{rp}" for rp in rh.RETURN_PERIODS]
    return out[cols]


# ---------------------------------------------------------------------------
# FIRMS input (operator-supplied CSV; Petals has no download-by-country)
# ---------------------------------------------------------------------------

def resolve_firms(paths):
    """The FIRMS source to use: the explicit --firms list if given, else the
    FIRMS_CSV env var, else a ./firms/ folder or firms_us.csv found in the working
    directory, else None. Lets a plain `refresh_wildfire.py` run pick up dropped
    files without a flag."""
    if paths:
        return list(paths)
    env = os.environ.get("FIRMS_CSV")
    if env:
        return [env]
    found = [c for c in DEFAULT_FIRMS if Path(c).exists()]
    return found or None


def load_firms(paths):
    """Read one or more NASA FIRMS archive CSVs (or a directory of them) into the
    single DataFrame climada_petals' WildFire expects. FIRMS archive downloads
    already carry latitude, longitude, acq_date, instrument, confidence and the
    instrument brightness column (MODIS 'brightness', VIIRS 'bright_ti4'); this
    concatenates them, lower-cases headers, validates, and coerces coordinates.
    Pure I/O so the producer is testable without CLIMADA."""
    files = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            files.extend(sorted(pp.glob("*.csv")))
        elif pp.exists():
            files.append(pp)
        else:
            raise FileNotFoundError(f"FIRMS path not found: {p}")
    if not files:
        raise FileNotFoundError("no FIRMS CSV files found in the given path(s)")
    frames = []
    for f in files:
        df = pd.read_csv(f)
        df.columns = [str(c).strip().lower() for c in df.columns]
        frames.append(df)
        LOG.info("  read %s (%d detections)", f.name, len(df))
    df = pd.concat(frames, ignore_index=True, sort=False)
    missing = [c for c in FIRMS_REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(
            "FIRMS CSV missing required column(s): " + ", ".join(missing)
            + ". Download the MODIS/VIIRS archive CSV from "
              "https://firms.modaps.eosdis.nasa.gov/download/")
    if "brightness" not in df.columns and "bright_ti4" not in df.columns:
        raise ValueError("FIRMS CSV needs a brightness column: 'brightness' "
                         "(MODIS) or 'bright_ti4' (VIIRS).")
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    return df.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)


def filter_firms_to_regions(df, regions=FIRE_REGIONS):
    """Keep only detections inside the union of the portfolio region boxes, so
    Petals builds its centroids over the resort footprint rather than the whole
    nation (which would be intractable). Pure and testable."""
    lat = df["latitude"].to_numpy(float)
    lon = df["longitude"].to_numpy(float)
    keep = np.zeros(len(df), bool)
    for _name, la0, la1, lo0, lo1 in regions:
        keep |= (lat >= la0) & (lat <= la1) & (lon >= lo0) & (lon <= lo1)
    return df.loc[keep].reset_index(drop=True)


# ---------------------------------------------------------------------------
# CLIMADA Petals seam (version-sensitive, mocked in tests)
# ---------------------------------------------------------------------------

def _ensure_cartopy_cache():
    """CLIMADA/Petals use cartopy, which caches Natural Earth shapefiles in
    ~/.local/share/cartopy by default. On locked-down machines that path is not
    writable ('[Errno 13] Permission denied: .../.local/share/cartopy'), which
    kills the WildFire build. If the default is not writable, redirect cartopy to
    a writable directory (CLAM_CARTOPY_DIR, then ~/.cache/cartopy, then a temp
    dir). A no-op when the default already works or cartopy is absent. Set the
    override BEFORE the WildFire call downloads, since cartopy reads
    config['data_dir'] at download time."""
    try:
        import cartopy
    except Exception:
        return
    cur = cartopy.config.get("data_dir")
    if cur is not None:
        cur = str(cur)
        try:
            os.makedirs(cur, exist_ok=True)
            if os.access(cur, os.W_OK):
                return
        except Exception:
            pass
    for cand in (os.environ.get("CLAM_CARTOPY_DIR"),
                 os.path.join(os.path.expanduser("~"), ".cache", "cartopy"),
                 os.path.join(tempfile.gettempdir(), "clam-cartopy")):
        if not cand:
            continue
        try:
            os.makedirs(cand, exist_ok=True)
            if os.access(cand, os.W_OK):
                cartopy.config["data_dir"] = cand
                LOG.info("  cartopy cache redirected to %s (default not writable)",
                         cand)
                return
        except Exception:
            continue
    LOG.warning("  no writable cartopy cache found; the WildFire build may fail. "
                "Set CLAM_CARTOPY_DIR to a writable directory.")


def build_wildfire_hazard(df_firms, centr_res_factor=0.05,
                          year_start=None, year_end=None, n_proba_seasons=0):
    """Probabilistic wildfire Hazard from a FIRMS DataFrame via Petals' WildFire.

    Corrects the prior seam: WildFire.from_hist_fire_seasons_FIRMS takes the
    FIRMS DataFrame (df_firms), NOT a country code. Prefers the classmethod and
    falls back to the deprecated instance setter (which forwards to it) on older
    releases. Optionally augments the historic fire seasons with probabilistic
    ones for a smoother burn probability; historic-only (0) is the robust
    screening default."""
    _ensure_cartopy_cache()
    from climada_petals.hazard import WildFire
    ctor = getattr(WildFire, "from_hist_fire_seasons_FIRMS", None)
    if ctor is not None:
        wf = ctor(df_firms, centr_res_factor=centr_res_factor,
                  year_start=year_start, year_end=year_end)
    else:                                   # pre-classmethod releases
        wf = WildFire()
        wf.set_hist_fire_seasons_FIRMS(df_firms, centr_res_factor=centr_res_factor,
                                       year_start=year_start, year_end=year_end)
    if n_proba_seasons and n_proba_seasons > 0:
        try:
            wf.set_proba_fire_seasons(n_fire_seasons=int(n_proba_seasons))
        except Exception as exc:
            LOG.info("  set_proba_fire_seasons skipped: %s", str(exc)[:160])
    return wf


def _write_meta(out_path, meta):
    mp = Path(out_path).with_name(Path(out_path).stem + "_meta.json")
    mp.write_text(json.dumps(meta, indent=2))
    return mp


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the wildfire layer of the "
                                             "hazard grid (burn probability) from "
                                             "a NASA FIRMS archive CSV.")
    ap.add_argument("--firms", nargs="+", default=None,
                    help="FIRMS archive CSV file(s) or a directory of them "
                         "(https://firms.modaps.eosdis.nasa.gov/download/)")
    ap.add_argument("--out", default="wfire_grid.csv")
    ap.add_argument("--centr-res-factor", type=float, default=0.05,
                    help="Petals centroid resolution factor (~0.05 -> ~20 km)")
    ap.add_argument("--year-start", type=int, default=None)
    ap.add_argument("--year-end", type=int, default=None)
    ap.add_argument("--proba-seasons", type=int, default=0,
                    help="augment historic seasons with N probabilistic ones "
                         "(0 = historic only, the robust screening default)")
    ap.add_argument("--country", default="USA", help="provenance label only")
    args = ap.parse_args(argv)

    meta = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "script": "refresh_wildfire.py v2 (FIRMS DataFrame input)",
            "method": "Petals WildFire from a FIRMS archive CSV; burn probability "
                      "per cell, scenarios scale by WARMING x FIRE_WARMING_UPLIFT",
            "fire_warming_uplift_per_c": FIRE_WARMING_UPLIFT,
            "encoding": {"v10": "annual burn probability, percent",
                         "v25": 0, "v50": 0, "v100": 0, "v250": 0, "v500": 0},
            "units": {"wfire": "indicator encoding, see 'encoding'"},
            "layers": [], "skipped": []}

    firms = resolve_firms(args.firms)
    if not firms:
        LOG.error("No FIRMS data found. Petals' WildFire builds its hazard from a "
                  "FIRMS DataFrame, not a country code, and cannot download it. "
                  "Put the MODIS and/or VIIRS archive CSV(s) from "
                  "https://firms.modaps.eosdis.nasa.gov/download/ in ./firms/ (or "
                  "pass --firms PATH, or set FIRMS_CSV). The app keeps wildfire on "
                  "its wui_class interim model until then.")
        meta["skipped"].append({"country": args.country, "layer": "wfire",
                                "reason": "no FIRMS CSV found (--firms / FIRMS_CSV "
                                          "/ ./firms/)"})
        _write_meta(args.out, meta)
        return 1

    try:
        df = load_firms(firms)
    except Exception as exc:
        LOG.error("Could not read FIRMS data: %s", exc)
        meta["skipped"].append({"country": args.country, "layer": "wfire",
                                "reason": str(exc)[:300]})
        _write_meta(args.out, meta)
        return 1
    n_all = len(df)
    df = filter_firms_to_regions(df)
    LOG.info("FIRMS: %d detections, %d within the portfolio regions",
             n_all, len(df))
    if df.empty:
        LOG.error("No FIRMS detections fall within the portfolio regions "
                  "(SE/Gulf, SW, Hawaii, Caribbean). Check the download area.")
        meta["skipped"].append({"country": args.country, "layer": "wfire",
                                "reason": "no FIRMS detections in the portfolio "
                                          "regions"})
        _write_meta(args.out, meta)
        return 1

    try:
        haz = build_wildfire_hazard(df, centr_res_factor=args.centr_res_factor,
                                    year_start=args.year_start,
                                    year_end=args.year_end,
                                    n_proba_seasons=args.proba_seasons)
    except Exception as exc:
        LOG.warning("Skipping %s: %s", args.country, exc)
        meta["skipped"].append({"country": args.country, "layer": "wfire",
                                "reason": str(exc)[:300]})
        _write_meta(args.out, meta)
        LOG.error("No wildfire layer produced.")
        return 1

    inten = haz.intensity
    hits = (inten.toarray() if hasattr(inten, "toarray")
            else np.asarray(inten)) > 0
    p = burn_probability(haz.frequency, hits)
    rows = wfire_rows(np.asarray(haz.centroids.lat, float),
                      np.asarray(haz.centroids.lon, float), p)
    for sc in WARMING:
        meta["layers"].append({"hazard": "wfire", "scenario": sc,
                               "country": args.country,
                               "cells": int(len(rows) / len(WARMING))})
    meta["firms"] = {"files": [Path(x).name for x in firms],
                     "detections_total": int(n_all),
                     "detections_in_regions": int(len(df)),
                     "centr_res_factor": args.centr_res_factor,
                     "proba_seasons": int(args.proba_seasons)}
    LOG.info("  wfire %s -> %d cells x %d scenarios (max p %.2f%%)",
             args.country, len(rows) // len(WARMING), len(WARMING),
             float(rows["v10"].max()))
    rows.to_csv(args.out, index=False)
    meta_path = _write_meta(args.out, meta)
    LOG.info("Wrote %d rows to %s and provenance to %s",
             len(rows), args.out, meta_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
