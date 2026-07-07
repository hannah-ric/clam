"""
refresh_hazard.py  (v3 : Phases 0 + 1 + 2)
==========================================

The ONE script behind the Resort Portfolio Risk-to-Value browser app.

It runs CLIMADA (ETH Zurich) headless and writes the hazard-grid CSV the browser
app reads, plus a provenance sidecar JSON. Schedule it quarterly and forget it.

What changed from v1
--------------------
Phase 0 (repairs to the wind pipeline):
  * Scenario keys are now the APP'S OWN keys ("present", "ssp245_2050", ...),
    so future scenarios reach the browser at all. v1 wrote "rcp45_2050"-style
    keys, which the app could not match, and its RCP fetches could fail
    silently, so a v1 grid could quietly serve present-day hazard everywhere.
  * The RCP fetch now uses the same candidate-fallback pattern as the
    present-day fetch, because the Data API's property vocabulary has changed
    across releases (nb_synth_tracks vs model_name tagging).
  * Every row carries a `hazard` column ("tc", "cflood").
  * Each app horizon is built from the Data API ref-years that bracket it:
    2050 = mean(2040, 2060); 2030 = mean(present, 2040); 2080 = 2080. This is
    more honest than v1's silent "2040 means 2050" relabel. Blending happens on
    the thinned grid with weight renormalisation, so a missing member degrades
    the blend gracefully instead of failing it.
  * A hazard_grid_meta.json sidecar records versions, matched dataset
    properties, DEM, SLR, and per-layer row counts: the provenance trail.

Phase 1 (new coastal-flood layer, hazard="cflood"):
  * Storm-surge depth from CLIMADA Petals' TCSurgeBathtub: a SLOSH-fitted
    linear wind-surge relationship, minus land elevation from a DEM you supply,
    with inland decay (0.2 m/km, Pielke & Pielke 1997) and per-scenario
    sea-level rise added before the elevation subtraction. Surge reuses the
    exact wind hazards this script already downloads: no extra API calls.
  * SLR per scenario mirrors the app's own table (IPCC AR6 central estimates),
    so hazard and app never disagree about the water level.
  * Surge output is re-indexed onto the wind grid's cells with explicit zeros
    inland. This matters: the app snaps a site to the NEAREST cflood cell
    within 200 km, so if inland cells were absent instead of zero, an inland
    site would inherit a coastal cell's surge. Zeros mean "no surge here".

Phase 2 (new riverine-flood layer, hazard="rflood"):
  * Annual-maximum river flood DEPTH in metres from the Data API's
    `river_flood` sets (ISIMIP / CaMa-Flood, ~150 arcsec). Selection is
    discovery-driven because these sets have been tagged with ref_year OR
    year_range, and their scenario vocabulary is ISIMIP's (rcp26/rcp60/rcp85,
    sometimes rcp45): the script lists what the release offers in practice, maps
    the app's ssp245 to rcp45 if present else rcp60 (nearest middle pathway,
    a standard screening choice), picks the tagged year nearest each horizon,
    and ensemble-averages up to RF_MAX_MODELS model variants.
  * Like surge, the layer is re-indexed onto the wind grid with explicit
    zeros away from rivers, so the app's nearest-cell snap cannot hand a dry
    site a river cell's depth. Countries the API has no river flood for are
    skipped and recorded; the app keeps its interim model there.
  * ACTION REQUIRED once real data is in hand: confirm whether the served
    datasets embed flood protection (FLOPROS). If they do, flip
    RFLOOD_GRID_INCLUDES_PROTECTION to true in the app so its riverine
    freeboard does not double-count protection. See the runbook.

Output schema (the app parses all of it today; `hazard` defaults to "tc"):

    lat, lon, scenario, hazard, v10, v25, v50, v100, v250, v500

  tc rows are wind speed in m/s at each return period; cflood and rflood rows
  are water depth in metres. One file, all perils, all scenarios. Perils
  absent from the file stay on the app's interim model: that supersession
  already exists.

Requirements
------------
CLIMADA needs a compiled geospatial stack, so use conda/mamba, not plain pip.
Core and Petals must share the same MAJOR version; Petals' minor may lead Core's
(Petals ships between Core releases and declares an open floor like climada>=6.1,
so e.g. Petals 6.2.0 on Core 6.1.0 is the intended, supported pairing):

    # You already have climada_env from the original setup; ADD to it:
    mamba install -n climada_env -c conda-forge \
        "climada-petals=6.*" xarray netcdf4 requests rasterio
    conda activate climada_env
    python check_climada.py      # v1 preflight: env + Data API
    python check_phase1.py       # new preflight: Petals + DEM + dist-coast
    python refresh_hazard.py
    python validate_grid.py hazard_grid.csv

The DEM: download SRTM15+ V2 (global ~15 arcsec topo-bathymetry GeoTIFF, free,
Scripps/UCSD) and set TOPO_PATH below, or export RTV_TOPO_PATH. If the file is
absent the script still runs and simply skips the cflood layer, logging why.
CoastalDEM (Climate Central, on request) is a drop-in upgrade later: SRTM
overstates ground elevation on vegetated and built coasts, so SRTM surge
depths are, if anything, conservative-low.

Written against CLIMADA 6.x + Petals 6.x. The three clearly-marked
version-sensitive spots below are all you touch if ETH revises things.
"""

from __future__ import annotations

import argparse
import concurrent.futures as _futures
import gc
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import assumptions

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
LOG = logging.getLogger("refresh_hazard")


# ---------------------------------------------------------------------------
# Concurrency helper. Every wind source is an independent Data API download, so
# the pipeline spends most of its wall clock waiting on the network; fetching a
# few sources at once overlaps that waiting. The reduce that follows each fetch
# (thin_to_grid, the surge bathtub) is numpy/CLIMADA C code that releases the
# GIL, so threads overlap it too. Peak memory is bounded by the worker count
# because each task frees its hazard before returning.
#
# workers<=1 runs inline: BYTE-FOR-BYTE identical to the old serial loop, and
# the escape hatch if the Data API's local cache ever contends under concurrency
# on a cold first run (pass --workers 1 or set CLAM_WORKERS=1).
# ---------------------------------------------------------------------------

def resolve_workers(requested=None, default=4):
    """Concurrent-fetch worker count: --workers if given, else CLAM_WORKERS,
    else `default`. Always at least 1."""
    val = requested if requested is not None else os.environ.get("CLAM_WORKERS", default)
    try:
        return max(1, int(val))
    except (TypeError, ValueError):
        return default


def parallel_map(func, items, workers):
    """Apply func to each item, returning results in INPUT order regardless of
    completion order, so callers can assemble output deterministically. Runs
    inline for workers<=1 or a single item. func is expected to catch its own
    anticipated failures and return a result object; unexpected exceptions
    propagate (fail loud)."""
    items = list(items)
    if workers <= 1 or len(items) <= 1:
        return [func(x) for x in items]
    results = [None] * len(items)
    with _futures.ThreadPoolExecutor(max_workers=min(workers, len(items))) as ex:
        futs = {ex.submit(func, x): i for i, x in enumerate(items)}
        for fut in _futures.as_completed(futs):
            results[futs[fut]] = fut.result()
    return results


# ---------------------------------------------------------------------------
# Environment guard, shared by every producer that builds a CLIMADA hazard from
# local data (winds/surge here, tracks+TCRain in refresh_prain, FIRMS+WildFire
# in refresh_wildfire). Those builds resolve land/coast geometry through
# cartopy, which caches Natural Earth shapefiles in ~/.local/share/cartopy by
# default; on locked-down machines that path is not writable
# ("[Errno 13] Permission denied: .../cartopy") and the build dies. Call this
# once BEFORE the CLIMADA download so cartopy reads a writable data_dir.
# ---------------------------------------------------------------------------

def ensure_cartopy_cache():
    """Point cartopy at a writable cache when its default dir is not writable.

    If cartopy's configured data_dir cannot be written, redirect it to the
    first writable candidate (CLAM_CARTOPY_DIR, then ~/.cache/cartopy, then a
    temp dir). A no-op when the default already works or cartopy is absent, so
    it is safe to call unconditionally at the top of any producer. Cartopy
    reads config['data_dir'] at download time, so this must run before the
    CLIMADA/Petals call that fetches Natural Earth geometry."""
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
    LOG.warning("  no writable cartopy cache found; the hazard build may fail. "
                "Set CLAM_CARTOPY_DIR to a writable directory.")


# ---------------------------------------------------------------------------
# Configuration. These are the only knobs you would ordinarily touch.
# ---------------------------------------------------------------------------

# Countries / territories your TC-exposed resorts sit in. ISO3 codes.
COUNTRIES = ["USA", "PRI", "VIR"]        # add "MEX", "BHS" etc. as the portfolio grows

# Return periods reported per cell (must match the app's loss table).
RETURN_PERIODS = [10, 25, 50, 100, 250, 500]

# Synthetic-track count requested from the Data API. "10" is fast and fine for
# dev runs; "50" resolves the 250/500-year tail better and is recommended for
# the scheduled authoritative run IF the machine has the memory for the USA
# set (budget >= 32 GB RAM for USA at 50 tracks; PRI/VIR are small either way).
NB_SYNTH_TRACKS = "10"

# Grid resolution for the output, in degrees (~25 km at 0.25). Raw centroids
# are ~150 arcsec (~4-5 km); we thin to keep the CSV small and the app snappy.
GRID_DEG = 0.25

OUT_CSV = "hazard_grid.csv"
# the provenance sidecar is written next to the CSV as <stem>_meta.json

# --- Phase 1: coastal flood (storm surge) ----------------------------------

# Path to the elevation GeoTIFF (SRTM15+ V2, or CoastalDEM when granted).
# Override without editing the file:  export RTV_TOPO_PATH=/path/to/dem.tiff
TOPO_PATH = Path(os.environ.get("RTV_TOPO_PATH", "SRTM15+V2.0.tiff"))

# Surge decay moving inland, m per km (Petals default, Pielke & Pielke 1997).
INLAND_DECAY_M_PER_KM = 0.2

# Sea-level rise (m) per app scenario, from the single sourced registry
# (assumptions.py: AR6 GMSL central + explicit conservative delta, with
# units, baseline period, and citation per entry). SLR is REGIONAL: surge is
# computed per coastline region with that region's table; SLR_M keeps the
# global-mean table for points outside every region box (and for callers
# that predate regionalization).
SLR_M = assumptions.SLR_TABLES["global_mean"]
SLR_REGIONS = assumptions.SLR_TABLES
SLR_REGION_BOXES = assumptions.SLR_REGION_BOXES


def slr_of(app_key, region="global_mean"):
    """Effective SLR (m) for a scenario and coastline region."""
    return assumptions.slr_m(app_key, region)


def subset_hazard_extent(haz, box):
    """The hazard restricted to centroids inside (lat0, lat1, lon0, lon1);
    None when no centroid falls inside, the hazard itself when all do.

    Real CLIMADA hazards go through Hazard.select(extent=...); the manual
    fallback masks intensity columns and rebuilds the centroid holder, which
    also serves any release without extent selection and the test fakes."""
    la0, la1, lo0, lo1 = box
    lat = np.asarray(haz.centroids.lat, float)
    lon = np.asarray(haz.centroids.lon, float)
    m = (lat >= la0) & (lat <= la1) & (lon >= lo0) & (lon <= lo1)
    if not m.any():
        return None
    if m.all():
        return haz
    try:
        sub = haz.select(extent=(lo0, lo1, la0, la1))
        if sub is not None:
            return sub
    except Exception:
        pass
    import copy
    import types
    sub = copy.copy(haz)
    sub.intensity = haz.intensity[:, m]
    frac = getattr(haz, "fraction", None)
    if frac is not None:
        try:
            sub.fraction = frac[:, m]
        except Exception:
            pass
    try:
        from climada.hazard import Centroids
        try:
            sub.centroids = Centroids(lat=lat[m], lon=lon[m], crs="EPSG:4326")
        except TypeError:
            sub.centroids = Centroids.from_lat_lon(lat[m], lon[m])
    except Exception:
        sub.centroids = types.SimpleNamespace(lat=lat[m], lon=lon[m])
    return sub


def slr_region_partition(lat, lon):
    """[(region, bool mask)] partitioning points by SLR region (first box
    wins, 'global_mean' takes the remainder); only non-empty members."""
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    taken = np.zeros(lat.shape, bool)
    out = []
    for name, la0, la1, lo0, lo1 in SLR_REGION_BOXES:
        m = (~taken) & (lat >= la0) & (lat <= la1) \
            & (lon >= lo0) & (lon <= lo1)
        if m.any():
            out.append((name, m))
            taken |= m
    if (~taken).any():
        out.append(("global_mean", ~taken))
    return out

# --- Scenario recipes -------------------------------------------------------
# The app's pathways are CMIP6 SSP labels; the Data API's TC sets are tagged
# with the CMIP5 RCP concentration pathways at ref-years 2040/2060/2080. The
# standard correspondence (same radiative forcing) is:
#     ssp126 <- rcp26      ssp245 <- rcp45      ssp585 <- rcp85
# Each app horizon is a weighted blend of the sources that bracket it. A
# "source" is either the literal string "present" or an (rcp, ref_year) pair.

RCP_OF = {"ssp126": "rcp26", "ssp245": "rcp45", "ssp585": "rcp85"}

# --- Phase 2: riverine flood (Data API river_flood) --------------------------
# The API's river flood sets derive from ISIMIP (CaMa-Flood): annual-maximum
# flood DEPTH in metres per country. Their tagging differs from the TC sets in
# two ways this code must absorb rather than assume:
#   * scenarios: ISIMIP2b provides rcp26/rcp60/rcp85 (no rcp45), so the app's
#     middle pathway ssp245 maps to rcp45 IF the release serves it, else to
#     rcp60 as the nearest middle road: a standard, documented screening choice.
#   * years: releases have tagged time with `ref_year` OR `year_range`
#     ("2030_2050" style), so selection is DISCOVERY-DRIVEN: list what the API
#     serves for the country, then pick the nearest year per horizon.
# Multiple GCM/GHM model variants may exist per scenario+year; we fetch up to
# RF_MAX_MODELS of them and use the ensemble mean, which is more defensible
# than one arbitrary model. Everything matched is recorded in the meta sidecar.

RF_SCEN_PREF = {           # app pathway -> ordered climate_scenario preferences
    "present": ["historical", "hist", "None"],
    "ssp126": ["rcp26"],
    "ssp245": ["rcp45", "rcp60"],
    "ssp585": ["rcp85"],
}
RF_TARGET_YEAR = {"present": 2000, "2030": 2030, "2050": 2050, "2080": 2080}
RF_MAX_MODELS = 4          # ensemble cap per scenario+year (determinism: sorted by name)


def build_recipes() -> dict:
    """app scenario key -> list of (weight, source)."""
    recipes = {"present": [(1.0, "present")]}
    for ssp, rcp in RCP_OF.items():
        recipes[f"{ssp}_2030"] = [(0.5, "present"), (0.5, (rcp, "2040"))]
        recipes[f"{ssp}_2050"] = [(0.5, (rcp, "2040")), (0.5, (rcp, "2060"))]
        recipes[f"{ssp}_2080"] = [(1.0, (rcp, "2080"))]
    return recipes


APP_SCENARIOS = build_recipes()


# ---------------------------------------------------------------------------
# CLIMADA calls. Three clearly-marked spots are the only version-sensitive code.
# ---------------------------------------------------------------------------

def fetch_wind(country_iso3: str, source, meta: dict):
    """Download (and cache) the TC wind Hazard for one country + source.

    `source` is "present" or (rcp, ref_year). Every branch tries a short list
    of candidate property sets because the Data API's tagging vocabulary has
    varied across releases: older releases distinguish synthetic sets by
    `nb_synth_tracks`, newer listings by `model_name` ("random_walk" vs
    "STORM"). Client.get_hazard raises unless exactly one dataset matches, so
    we walk the candidates until one does. The matched properties are recorded
    in the meta sidecar: that is your provenance if ETH re-tags things.
    """
    from climada.util.api_client import Client   # (1) Data API property names
    client = Client()

    base = {"country_iso3alpha": country_iso3}
    if source == "present":
        candidates = [
            {**base, "climate_scenario": "None", "event_type": "synthetic"},
            {**base, "climate_scenario": "None", "event_type": "synthetic",
             "nb_synth_tracks": NB_SYNTH_TRACKS},
            {**base, "climate_scenario": "None", "event_type": "synthetic",
             "model_name": "random_walk"},
            {**base, "climate_scenario": "None", "event_type": "observed"},
        ]
    else:
        rcp, ref_year = source
        stem = {**base, "climate_scenario": rcp, "ref_year": ref_year}
        candidates = [
            {**stem, "event_type": "synthetic", "nb_synth_tracks": NB_SYNTH_TRACKS},
            {**stem, "event_type": "synthetic", "model_name": "random_walk"},
            {**stem, "event_type": "synthetic"},
            {**stem},
        ]

    last_err = None
    for props in candidates:
        tag = {k: v for k, v in props.items() if k != "country_iso3alpha"}
        try:
            LOG.info("Fetching TC wind: %s / %s  %s", country_iso3, source_key(source), tag)
            haz = client.get_hazard("tropical_cyclone", properties=props)
            record = {"data_type": "tropical_cyclone", "properties_matched": props}
            try:    # dataset name is nice-to-have provenance, never fatal
                infos = client.list_dataset_infos("tropical_cyclone", properties=props)
                if infos:
                    record["dataset_name"] = infos[0].name
                    record["dataset_version"] = getattr(infos[0], "version", None)
            except Exception:
                pass
            meta.setdefault("wind_sources", {})[f"{country_iso3}:{source_key(source)}"] = record
            return haz
        except Exception as exc:                  # 0 or >1 dataset matches
            last_err = exc
            LOG.info("  no single match, trying next: %s", str(exc)[:160])
    raise last_err


def as_tropcyclone(haz):
    """Petals' surge constructor expects a TropCyclone; the Data API client may
    hand back the base Hazard class depending on release. TropCyclone only
    extends Hazard, so re-wrapping the same attributes is safe."""
    from climada.hazard import TropCyclone
    if isinstance(haz, TropCyclone):
        return haz
    tc = TropCyclone()
    tc.__dict__.update(haz.__dict__)
    return tc


def compute_surge(wind_haz, slr_m: float):
    """Storm-surge depth (m) from the wind hazard, via Petals' bathtub model.

    Wind speed maps to surge height through a linear fit to SLOSH points; SLR
    is added to the water level BEFORE land elevation (from TOPO_PATH) is
    subtracted, so rising seas flood new ground rather than just deepening old
    water; surge decays moving inland. First run may download NASA's
    distance-to-coast auxiliary data through the CLIMADA client.
    """
    from climada_petals.hazard import TCSurgeBathtub   # (3) Petals surge signature
    return TCSurgeBathtub.from_tc_winds(
        as_tropcyclone(wind_haz),
        str(TOPO_PATH),
        inland_decay_rate=INLAND_DECAY_M_PER_KM,
        add_sea_level_rise=slr_m,
    )


def local_rp_intensity(haz, return_periods):
    """Return array [n_return_periods x n_centroids] of RP intensities.

    Works for wind (m/s) and surge depth (m) alike: both are Hazard objects.
    CLIMADA 6.1's `local_exceedance_intensity` returns a tuple whose first
    element is a GeoDataFrame: one row per centroid, a `geometry` column, and
    one column per return period. We match columns back to the requested
    return periods by numeric value, request extrapolation so high return
    periods are filled rather than NaN, and zero out any residual NaN.
    """
    import re
    rps = list(return_periods)

    try:                                               # (2) exceedance method
        res = haz.local_exceedance_intensity(return_periods=rps, method="extrapolate")
    except TypeError:
        res = haz.local_exceedance_intensity(return_periods=rps)   # older signature
    except AttributeError:
        res = haz.local_exceedance_inten(return_periods=rps)       # pre-6.x name

    if isinstance(res, tuple):          # (gdf, label, column_label)
        res = res[0]

    if hasattr(res, "columns"):         # GeoDataFrame / DataFrame path (6.x)
        def col_num(c):
            m = re.search(r"[-+]?\d*\.?\d+", str(c))
            return float(m.group()) if m else None
        by_rp = {}
        for c in res.columns:
            if c == "geometry":
                continue
            k = col_num(c)
            if k is not None:
                by_rp[k] = c
        selected = []
        for rp in rps:
            c = by_rp.get(float(rp))
            if c is None:
                raise ValueError(f"Return period {rp} not in result columns "
                                 f"{[x for x in res.columns if x != 'geometry']}")
            selected.append(c)
        arr = res[selected].to_numpy(dtype=float).T   # [n_rp, n_centroids]
    else:                               # ndarray path (very old)
        arr = np.asarray(res, dtype=float)
        if arr.shape[0] != len(rps) and arr.shape[-1] == len(rps):
            arr = arr.T

    return np.nan_to_num(arr, nan=0.0)


# ---------------------------------------------------------------------------
# Pure grid operations (no CLIMADA imports: unit-testable anywhere)
# ---------------------------------------------------------------------------

def source_key(source) -> str:
    return source if source == "present" else f"{source[0]}_{source[1]}"


def thin_to_grid(lat, lon, values_by_rp, grid_deg=GRID_DEG):
    """Average centroid RP intensities into grid cells of `grid_deg` spacing.

    Returns a DataFrame with lat, lon (cell centre) and one v{rp} column per
    return period. Averaging within a cell is a mild, defensible smoothing
    for portfolio screening.
    """
    glat = np.round(np.asarray(lat, dtype=float) / grid_deg) * grid_deg
    glon = np.round(np.asarray(lon, dtype=float) / grid_deg) * grid_deg
    df = pd.DataFrame({"glat": glat, "glon": glon})
    for rp, vals in values_by_rp.items():
        df[f"v{rp}"] = vals
    agg = df.groupby(["glat", "glon"], as_index=False).mean(numeric_only=True)
    return agg.rename(columns={"glat": "lat", "glon": "lon"})


def align_to_cells(grid: pd.DataFrame, base: pd.DataFrame,
                   rps=tuple(RETURN_PERIODS)) -> pd.DataFrame:
    """Re-index `grid` onto `base`'s (lat, lon) cell set, filling gaps with 0.

    Used to force the surge layer onto the wind layer's cell coverage: the app
    snaps to the nearest cflood cell within 200 km, so dry inland cells must
    exist as explicit zeros or inland sites would inherit coastal surge.
    """
    vcols = [f"v{rp}" for rp in rps]
    out = base[["lat", "lon"]].merge(grid[["lat", "lon"] + vcols],
                                     on=["lat", "lon"], how="left")
    out[vcols] = out[vcols].fillna(0.0)
    return out


def blend_grids(parts, rps=tuple(RETURN_PERIODS)) -> pd.DataFrame:
    """Weighted per-cell average of grids: parts is a list of (weight, df).

    Cells missing from some members are averaged over the members that have
    them, with weights renormalised: so if one bracketing source failed to
    download, its sibling still carries the scenario rather than sinking it.
    """
    vcols = [f"v{rp}" for rp in rps]
    frames = []
    for w, df in parts:
        d = df[["lat", "lon"] + vcols].copy()
        for c in vcols:
            d[c] = d[c] * w
        d["_w"] = w
        frames.append(d)
    allf = pd.concat(frames, ignore_index=True)
    agg = allf.groupby(["lat", "lon"], as_index=False).sum(numeric_only=True)
    for c in vcols:
        agg[c] = agg[c] / agg["_w"]
    return agg.drop(columns=["_w"])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def rf_props_of(info) -> dict:
    """Property dict of a dataset info, tolerant of both API client shapes."""
    p = getattr(info, "properties", {})
    if isinstance(p, dict):
        return p
    try:
        return {x.name: x.value for x in p}
    except Exception:
        return {}


def rf_year_of(info):
    """Central year of a dataset from ref_year or year_range tagging, else None."""
    import re
    p = rf_props_of(info)
    if "ref_year" in p:
        m = re.search(r"\d{4}", str(p["ref_year"]))
        if m:
            return int(m.group())
    if "year_range" in p:
        ys = re.findall(r"\d{4}", str(p["year_range"]))
        if ys:
            return int(round(sum(map(int, ys)) / len(ys)))
    ys = re.findall(r"(?:19|20)\d{2}", str(getattr(info, "name", "")))
    if ys:
        return int(round(sum(map(int, ys)) / len(ys)))
    return None


def rf_pick(infos, app_key, max_models=RF_MAX_MODELS):
    """Choose the river_flood dataset(s) for one app scenario key.

    Pure and unit-tested: filter `infos` to the first scenario tag the release
    offers in practice (per RF_SCEN_PREF), then to the tagged year nearest the
    horizon, then return up to `max_models` model variants (sorted by name for
    determinism) to be ensemble-averaged. Empty list = layer unavailable.
    """
    family = "present" if app_key == "present" else app_key.split("_")[0]
    horizon = "present" if app_key == "present" else app_key.split("_")[1]
    target = RF_TARGET_YEAR[horizon]

    for scen in RF_SCEN_PREF[family]:
        cand = [i for i in infos
                if str(rf_props_of(i).get("climate_scenario", "")).lower() == scen.lower()]
        if not cand:
            continue
        dated = [(rf_year_of(i), i) for i in cand]
        dated = [(y, i) for y, i in dated if y is not None] or [(target, i) for _, i in dated]
        best = min(abs(y - target) for y, _ in dated)
        group = [i for y, i in dated if abs(y - target) == best]
        group.sort(key=lambda i: str(getattr(i, "name", "")))
        return group[:max_models], scen, (target - best, target + best)
    return [], None, None


def fetch_river_flood_grid(iso3: str, app_key: str, meta: dict, cache=None):
    """Ensemble-mean thinned RP-depth grid for one country + app scenario.

    Discovery-driven (see rf_pick). Returns None when the API has no river
    flood for the country/scenario: the app then keeps its interim model for
    sites there, which the meta sidecar records explicitly.

    `cache` (a dict, one per country) lets the ten app scenarios share a single
    Data API dataset listing instead of re-querying it once per scenario, and
    reuses the thinned grid of any dataset that more than one scenario selects
    (e.g. a country that serves only a historical set). The thinned grids are
    tiny, so caching them costs almost no memory.
    """
    from climada.util.api_client import Client   # (1) Data API property names
    cache = {} if cache is None else cache
    client = cache.get("client")
    if client is None:
        client = cache["client"] = Client()
    infos = cache.get("infos")
    if infos is None:
        infos = cache["infos"] = client.list_dataset_infos(
            "river_flood", properties={"country_iso3alpha": iso3})
    chosen, scen, _yr = rf_pick(infos, app_key)
    if not chosen:
        return None, {"reason": f"no river_flood dataset for {iso3}/{app_key} "
                                f"(scenario prefs {RF_SCEN_PREF['present' if app_key == 'present' else app_key.split('_')[0]]})"}
    grid_cache = cache.setdefault("grids", {})
    grids, members = [], []
    for info in chosen:
        name = getattr(info, "name", None)
        try:
            if name is not None and name in grid_cache:
                g = grid_cache[name]
            else:
                LOG.info("Fetching river flood: %s / %s  dataset=%s",
                         iso3, app_key, name or "?")
                haz = client.get_hazard("river_flood", name=name)
                lat = np.asarray(haz.centroids.lat, dtype=float)
                lon = np.asarray(haz.centroids.lon, dtype=float)
                inten = local_rp_intensity(haz, RETURN_PERIODS)
                g = thin_to_grid(lat, lon,
                                 {rp: inten[i] for i, rp in enumerate(RETURN_PERIODS)})
                if name is not None:
                    grid_cache[name] = g
                del haz
                gc.collect()
            grids.append(g)
            members.append({"dataset_name": name or "?",
                            "properties": rf_props_of(info)})
        except Exception as exc:
            LOG.warning("  member failed, continuing ensemble: %s", str(exc)[:160])
    if not grids:
        return None, {"reason": f"all {len(chosen)} river_flood member fetches failed"}
    grid = blend_grids([(1.0 / len(grids), g) for g in grids])
    return grid, {"climate_scenario_matched": scen, "members": members}


def unique_sources(recipes: dict) -> list:
    seen, out = set(), []
    for recipe in recipes.values():
        for _w, src in recipe:
            k = source_key(src)
            if k not in seen:
                seen.add(k)
                out.append(src)
    return out


def process_country(iso3: str, surge_enabled: bool, river_enabled: bool, meta: dict,
                    workers: int = 1):
    """Fetch every needed wind source (concurrently when workers>1); derive wind
    and surge grids from each while it is in memory; free it; then blend sources
    into app scenarios. Each source's fetch-and-reduce is self-contained (its
    surge is aligned to that source's own wind grid), so parallelism only changes
    the order fetches COMPLETE, never the result: sources are folded back into
    the grids in a fixed order below, so the CSV and meta are byte-for-byte the
    same as the serial run.
    Returns a list of output DataFrames (scenario + hazard columns attached)."""
    sources = unique_sources(APP_SCENARIOS)

    def _wind_task(source):
        """Fetch one wind source and reduce it to a thinned wind grid plus (when
        enabled) its per-scenario surge grids. A per-task meta dict keeps
        concurrent fetches from racing on the shared one; it is merged in source
        order during assembly. Anticipated failures are captured, not raised."""
        skey = source_key(source)
        tmeta = {}
        out = {"skey": skey, "wgrid": None, "surge": {}, "tmeta": tmeta,
               "wind_error": None, "surge_skipped": []}
        try:
            haz = fetch_wind(iso3, source, tmeta)
        except Exception as exc:                  # 0 or >1 dataset matches
            out["wind_error"] = str(exc)[:300]
            return out
        cent = haz.centroids
        lat = np.asarray(cent.lat, dtype=float)
        lon = np.asarray(cent.lon, dtype=float)
        inten = local_rp_intensity(haz, RETURN_PERIODS)
        out["wgrid"] = thin_to_grid(
            lat, lon, {rp: inten[i] for i, rp in enumerate(RETURN_PERIODS)})
        if surge_enabled:
            # Surge is computed per (source, app scenario, SLR REGION): SLR
            # enters BEFORE the elevation subtraction, and relative SLR
            # differs by coastline (Gulf subsidence most of all), so each
            # region's centroids get their own bathtub run at their own SLR
            # table. Centroids outside every region box run once on the full
            # hazard at the global-mean SLR and are trimmed to those cells.
            cen_lat = np.asarray(haz.centroids.lat, dtype=float)
            cen_lon = np.asarray(haz.centroids.lon, dtype=float)
            region_parts = slr_region_partition(cen_lat, cen_lon)
            boxes = {n: (la0, la1, lo0, lo1)
                     for n, la0, la1, lo0, lo1 in SLR_REGION_BOXES}
            for app_key, recipe in APP_SCENARIOS.items():
                if not any(source_key(s) == skey for _w, s in recipe):
                    continue
                try:
                    pt_lat, pt_lon = [], []
                    pt_v = {rp: [] for rp in RETURN_PERIODS}
                    for region, _mask in region_parts:
                        sub = haz if region == "global_mean" else \
                            subset_hazard_extent(haz, boxes[region])
                        if sub is None:
                            continue
                        surge = compute_surge(sub, slr_of(app_key, region))
                        s_lat = np.asarray(surge.centroids.lat, dtype=float)
                        s_lon = np.asarray(surge.centroids.lon, dtype=float)
                        s_int = local_rp_intensity(surge, RETURN_PERIODS)
                        keep = np.ones(len(s_lat), bool)
                        if region == "global_mean":
                            for _n, la0, la1, lo0, lo1 in SLR_REGION_BOXES:
                                keep &= ~((s_lat >= la0) & (s_lat <= la1)
                                          & (s_lon >= lo0) & (s_lon <= lo1))
                        del surge
                        if not keep.any():
                            continue
                        pt_lat.append(s_lat[keep])
                        pt_lon.append(s_lon[keep])
                        for i, rp in enumerate(RETURN_PERIODS):
                            pt_v[rp].append(s_int[i][keep])
                    if not pt_lat:
                        raise RuntimeError("surge produced no centroids")
                    sgrid = thin_to_grid(
                        np.concatenate(pt_lat), np.concatenate(pt_lon),
                        {rp: np.concatenate(pt_v[rp]) for rp in RETURN_PERIODS})
                    # Petals may subset centroids to the coastal band: restore
                    # full coverage with explicit zeros inland (see docstring).
                    out["surge"][app_key] = align_to_cells(sgrid, out["wgrid"])
                except Exception as exc:
                    out["surge_skipped"].append(
                        {"country": iso3, "source": skey, "scenario": app_key,
                         "layer": "cflood", "reason": str(exc)[:300]})
        del haz
        gc.collect()
        return out

    wind_by_source = {}                    # source_key -> thinned wind grid
    surge_by_pair = {}                     # (source_key, app_key) -> grid
    for out in parallel_map(_wind_task, sources, workers):
        skey = out["skey"]
        for k, v in out["tmeta"].get("wind_sources", {}).items():
            meta.setdefault("wind_sources", {})[k] = v
        if out["wind_error"] is not None:
            LOG.warning("Skipping wind source %s / %s: %s", iso3, skey, out["wind_error"])
            meta["skipped"].append({"country": iso3, "source": skey,
                                    "layer": "tc", "reason": out["wind_error"]})
            continue
        wind_by_source[skey] = out["wgrid"]
        LOG.info("  wind %s / %s -> %d cells", iso3, skey, len(out["wgrid"]))
        for app_key, sgrid in out["surge"].items():
            surge_by_pair[(skey, app_key)] = sgrid
            LOG.info("  surge %s / %s @ %s (SLR %.2f m global-mean, regional "
                     "tables per box) -> %d wet cells",
                     iso3, skey, app_key, SLR_M[app_key],
                     int((sgrid["v100"] > 0).sum()))
        for sk in out["surge_skipped"]:
            LOG.warning("Surge failed %s / %s @ %s: %s",
                        iso3, sk["source"], sk["scenario"], sk["reason"])
            meta["skipped"].append(sk)

    frames = []
    for app_key, recipe in APP_SCENARIOS.items():
        wind_parts = [(w, wind_by_source[source_key(s)])
                      for w, s in recipe if source_key(s) in wind_by_source]
        if wind_parts:
            g = blend_grids(wind_parts)
            g["scenario"], g["hazard"] = app_key, "tc"
            frames.append(g)
            meta["layers"].append({"hazard": "tc", "scenario": app_key,
                                   "country": iso3, "cells": len(g),
                                   "sources": [source_key(s) for _w, s in recipe
                                               if source_key(s) in wind_by_source]})
        else:
            meta["skipped"].append({"country": iso3, "scenario": app_key,
                                    "layer": "tc", "reason": "no wind source available"})

        surge_parts = [(w, surge_by_pair[(source_key(s), app_key)])
                       for w, s in recipe if (source_key(s), app_key) in surge_by_pair]
        if surge_parts:
            g = blend_grids(surge_parts)
            g["scenario"], g["hazard"] = app_key, "cflood"
            frames.append(g)
            meta["layers"].append({"hazard": "cflood", "scenario": app_key,
                                   "country": iso3, "cells": len(g),
                                   "slr_m": SLR_M[app_key],
                                   "slr_m_by_region": {
                                       r: slr_of(app_key, r)
                                       for r in assumptions.SLR_TABLES},
                                   "wet_cells_v100": int((g["v100"] > 0).sum())})

    # --- Phase 2: riverine flood, one discovery-driven fetch per app scenario.
    # The ensemble grid is re-indexed onto the country's wind coverage with
    # explicit zeros away from rivers, for the same reason surge is: the app
    # snaps a site to the NEAREST rflood cell within 200 km, so cells the
    # flood model is silent about must exist as zeros, or a dry inland site
    # would inherit a river cell's depth.
    if river_enabled:
        base = wind_by_source.get("present")
        if base is None and wind_by_source:
            base = next(iter(wind_by_source.values()))
        river_cache = {}          # one Data API listing + thinned-grid memo per country
        for app_key in APP_SCENARIOS:
            try:
                grid, info = fetch_river_flood_grid(iso3, app_key, meta, cache=river_cache)
            except Exception as exc:
                grid, info = None, {"reason": str(exc)[:300]}
            if grid is None:
                LOG.warning("River flood unavailable %s / %s: %s",
                            iso3, app_key, info["reason"])
                meta["skipped"].append({"country": iso3, "scenario": app_key,
                                        "layer": "rflood", **info})
                continue
            if base is not None:
                grid = align_to_cells(grid, base)
            grid["scenario"], grid["hazard"] = app_key, "rflood"
            frames.append(grid)
            meta["layers"].append({"hazard": "rflood", "scenario": app_key,
                                   "country": iso3, "cells": len(grid),
                                   "wet_cells_v100": int((grid["v100"] > 0).sum()),
                                   **info})
            LOG.info("  rflood %s / %s -> %d cells (%d wet at v100, %d-member ensemble)",
                     iso3, app_key, len(grid), int((grid["v100"] > 0).sum()),
                     len(info.get("members", [])))
    return frames


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Refresh the multi-peril CLIMADA hazard grid.")
    ap.add_argument("--countries", nargs="*", default=COUNTRIES,
                    help="ISO3 codes to process (default: %(default)s)")
    ap.add_argument("--no-surge", action="store_true",
                    help="Skip the Phase 1 cflood layer even if the DEM is present")
    ap.add_argument("--no-river", action="store_true",
                    help="Skip the Phase 2 rflood layer")
    ap.add_argument("--workers", type=int, default=None,
                    help="concurrent Data API wind fetches per country (default: "
                         "CLAM_WORKERS or 4; pass 1 for the exact serial run)")
    ap.add_argument("--out", default=OUT_CSV)
    args = ap.parse_args(argv)

    workers = resolve_workers(args.workers)
    ensure_cartopy_cache()      # before any CLIMADA build touches cartopy's cache
    surge_enabled = not args.no_surge
    if surge_enabled and not TOPO_PATH.exists():
        LOG.warning("DEM not found at %s: the cflood layer will be SKIPPED this run. "
                    "Download SRTM15+ V2 (or set RTV_TOPO_PATH) to enable it.", TOPO_PATH)
        surge_enabled = False

    meta = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "refresh_hazard.py v3 (Phases 0+1+2)",
        "grid_deg": GRID_DEG,
        "return_periods": RETURN_PERIODS,
        "nb_synth_tracks": NB_SYNTH_TRACKS,
        "fetch_workers": workers,
        "countries": args.countries,
        "scenario_recipes": {k: [[w, source_key(s)] for w, s in v]
                             for k, v in APP_SCENARIOS.items()},
        "units": {"tc": "m/s wind speed", "cflood": "m surge depth",
                  "rflood": "m flood depth"},
        "surge": {"enabled": surge_enabled,
                  "model": "climada_petals TCSurgeBathtub (SLOSH linear wind-surge, "
                           "bathtub DEM, inland decay)",
                  "dem_path": str(TOPO_PATH),
                  "dem_size_bytes": TOPO_PATH.stat().st_size if TOPO_PATH.exists() else None,
                  "inland_decay_m_per_km": INLAND_DECAY_M_PER_KM,
                  "slr_m": SLR_M,
                  "slr_regional": {"tables_m": assumptions.SLR_TABLES,
                                   "factors": {r: f for r, (f, _w)
                                               in assumptions.SLR_REGION_FACTOR.items()},
                                   "boxes": assumptions.SLR_REGION_BOXES,
                                   "source": "assumptions.py v"
                                             + assumptions.ASSUMPTIONS_VERSION}},
        "layers": [], "skipped": [], "wind_sources": {},
    }
    try:
        from importlib.metadata import version
        meta["climada_version"] = version("climada")
        try:
            meta["climada_petals_version"] = version("climada-petals")
        except Exception:
            meta["climada_petals_version"] = version("climada_petals")
    except Exception:
        pass

    frames = []
    for iso3 in args.countries:
        frames.extend(process_country(iso3, surge_enabled, not args.no_river,
                                      meta, workers))

    if not frames:
        LOG.error("No hazard produced. Check network access and the countries list.")
        return 1

    out = pd.concat(frames, ignore_index=True)
    cols = ["lat", "lon", "scenario", "hazard"] + [f"v{rp}" for rp in RETURN_PERIODS]
    out = out[cols].round(2)
    out.to_csv(args.out, index=False)
    # sidecar convention: <csv stem>_meta.json, which merge_grids.py and the
    # app's Phase 4 drop zone both rely on
    meta_path = Path(args.out).with_name(Path(args.out).stem + "_meta.json")
    meta_path.write_text(json.dumps(meta, indent=2))

    LOG.info("Wrote %d rows to %s  (%d tc, %d cflood, %d rflood)",
             len(out), args.out,
             int((out["hazard"] == "tc").sum()), int((out["hazard"] == "cflood").sum()),
             int((out["hazard"] == "rflood").sum()))
    LOG.info("Wrote provenance to %s", meta_path)
    LOG.info("Next: python validate_grid.py %s   then drop the CSV into the app "
             "(Method & data > Load CLIMADA hazard).", args.out)
    if meta["skipped"]:
        LOG.warning("%d layer(s) were skipped; see 'skipped' in %s. The app falls "
                    "back to its interim model for anything missing.",
                    len(meta["skipped"]), meta_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
