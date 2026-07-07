"""
refresh_wildfire.py  (v3: the structural fix - point burn probability)
=======================================================================

Produces the wildfire layer (hazard="wfire") of the hazard grid from the
USFS Wildfire Risk to Communities (WRC) burn-probability product, sampled
AT THE SITE POINT (30 m native), with the conditional damage side driven by
the WRC Conditional Flame Length layer where supplied.

Why the rework (the structural defect it fixes)
-----------------------------------------------
The previous producer derived "burn probability" from NASA FIRMS active-fire
detections clustered by CLIMADA Petals into ~20 km centroid cells. A 400 km2
cell in fire-active terrain lights up almost every year, so the quantity
labeled "annual probability this resort burns" was actually "annual
probability a fire of ANY kind (agricultural and prescribed burning
included; the Southeast is the prescribed-burn capital of the country)
occurs within ~10 km of the resort": ~13-18%/yr at many sites, 8-18x the
0.1-2%/yr that real burn-probability products assign even to high-risk WUI.
A flat 60% conditional damage ratio was stacked on top, compounding in the
same direction. The result (a ~$731M/yr portfolio wildfire AAL for a
coastal, not-wildfire-led portfolio) contradicted the original design
judgment, which was the signal the PIPELINE, not the tuning, was wrong.

The fix: burn probability is now the WRC BP value at the site point, which
already means "fire reaches this location" (no spatial buffer may ever be
reapplied on top), and the damage given fire is conditioned on modeled
flame length at the point (FIRE_CFL_DAMAGE in the assumptions registry)
instead of the retired flat FIRE_MDD=0.6. Where the CFL raster is not
supplied, an INTERIM flat conditional ratio applies (fire_cond_interim in
the registry, capped, and labeled interim on the app's trust surface).

Encoding (indicator style, like heat's Option A):
    v10  = annual probability fire reaches the site point, PERCENT (0..100)
    v25  = conditional structure damage ratio given fire, PERCENT (0..100)
    v50..v500 = 0
Rows are written AT THE SITE COORDINATES (point semantics travel through
the existing grid contract: each site's nearest cell is itself). Sites the
rasters do not cover (check WRC coverage for Hawaii and the territories per
release) are FLAGGED in the meta sidecar, never silently zeroed; the app
shows them degraded on wildfire per the per-site trust rules.

Scenarios by a documented uplift: burn probability scales with warming at
FIRE_WARMING_UPLIFT per degree C (fire-weather-day scaling, screening
grade), from the shared assumptions registry.

Input: the WRC GeoTIFFs, downloaded ONCE from wildfirerisk.org / USFS
Research Data Archive (RDS-2020-0016, public domain) - exactly like the
one-time DEM. The source path is CONFIGURATION (--wrc-bp/--wrc-cfl flags,
CLAM_WRC_BP/CLAM_WRC_CFL env vars, or a ./wrc/ folder), so a pre-downloaded
local file always works and corporate-network SSL can never block a
rebuild. Without the BP raster the app keeps wildfire on its wui_class
interim model, by design.

FIRMS historical context (optional, NEVER feeds burn probability)
------------------------------------------------------------------
The NASA FIRMS utilities remain for one purpose: an optional historical
fire-activity CONTEXT export (--firms-context), clearly separated from the
loss calculation. FIRMS observes thermal anomalies of any kind, not
structure-threatening wildfire, and is no longer wired into any hazard or
impact quantity.

Usage (sites.csv and ./wrc/ are auto-discovered):
    python refresh_wildfire.py                          # ./wrc/ + ./sites.csv
    python refresh_wildfire.py --wrc-bp wrc/BP_CONUS.tif --wrc-cfl wrc/CFL_CONUS.tif
    python refresh_wildfire.py --firms-context firms/   # context CSV only
    python merge_grids.py hazard_grid.csv wfire_grid.csv -o hazard_grid.csv
    python validate_grid.py hazard_grid.csv hazard_grid_meta.json
"""

from __future__ import annotations

import argparse
import contextlib
import os
import warnings
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import assumptions
import portfolio_regions
import refresh_hazard as rh

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
LOG = logging.getLogger("refresh_wildfire")

# Both scenario constants read from the single sourced registry
# (assumptions.py: units, baseline period, and citation per entry).
WARMING = assumptions.WARMING_TABLE
FIRE_WARMING_UPLIFT = assumptions.scalar("fire_warming_uplift_per_c")

# The resort footprint. A nationwide FIRMS download is trimmed to these boxes so
# Petals builds centroids over cells that can actually host a site. The boxes
# live in portfolio_regions.py (one source of truth, shared with refresh_heat
# and the coverage audit). Wildfire is portfolio-wide, not only the desert SW.
FIRE_REGIONS = portfolio_regions.REGIONS
# --- WRC burn-probability input (the loss-driving source) -------------------
# Local pre-downloaded GeoTIFFs; the path is configuration so corporate SSL
# never blocks a rebuild. wildfirerisk.org data downloads / USFS RDS-2020-0016.
WRC_BP_ENV = "CLAM_WRC_BP"      # burn probability raster (annual, 0..1, 30 m)
WRC_CFL_ENV = "CLAM_WRC_CFL"    # conditional flame length raster (ft, 30 m)
DEFAULT_WRC_DIR = "wrc"         # ./wrc/*bp*.tif and ./wrc/*cfl*.tif discovery
FIRE_COND_INTERIM = assumptions.scalar("fire_cond_interim")

# --- FIRMS historical-context input (NEVER feeds burn probability) ----------
# Columns climada_petals' WildFire._clean_firms_df reads. MODIS carries
# 'brightness' with a numeric 'confidence'; VIIRS carries 'bright_ti4' with l/n/h.
FIRMS_REQUIRED = ["latitude", "longitude", "acq_date", "instrument", "confidence"]
# Auto-discovered: the FIRMS_CSV env var, then a ./firms/ folder of CSVs,
# then a single firms_us.csv, in the working directory.
DEFAULT_FIRMS = ["firms", "firms_us.csv"]
DEFAULT_SITES = "sites.csv"     # the portfolio the BP raster is sampled at
BUFFER_KM = 75.0                # context export: fire history near a site
MIN_CONFIDENCE = 50             # context export: MODIS confidence floor


# ---------------------------------------------------------------------------
# Pure ops (unit-tested in test_newperils.py)
# ---------------------------------------------------------------------------

def burn_probability(freq, hits):
    """Annual burn probability per centroid from a probabilistic fire event
    set (Poisson rate of arrivals, converted to a probability). CONTEXT
    ONLY: this cell-occupancy quantity is exactly what the structural fix
    retired from the loss path; it survives for the FIRMS historical-context
    export and its unit tests, and must never feed the wfire layer."""
    lam = (np.asarray(freq, float)[:, None] * np.asarray(hits, bool)).sum(axis=0)
    return 1.0 - np.exp(-lam)


def scenario_pburn(p_present, warming_c, uplift=FIRE_WARMING_UPLIFT):
    """Scale present burn probability for a warming level, capped at 1."""
    return np.minimum(np.asarray(p_present, float) * (1.0 + uplift * warming_c),
                      1.0)


def wfire_rows(lat, lon, p_present, cond):
    """Per-SITE wfire rows for every app scenario: v10 = point burn
    probability (percent), v25 = conditional damage ratio given fire
    (percent). Rows sit AT the site coordinates - point semantics through
    the existing grid contract (each site's nearest cell is itself); there
    is deliberately NO thinning and NO buffering, because the point value
    already means fire reaches the location. Co-located records dedupe."""
    base = pd.DataFrame({
        "lat": np.round(np.asarray(lat, float), 4),
        "lon": np.round(np.asarray(lon, float), 4),
        "p": np.asarray(p_present, float),
        "cond": np.asarray(cond, float),
    }).drop_duplicates(subset=["lat", "lon"], keep="first")
    frames = []
    for sc, w in WARMING.items():
        df = pd.DataFrame({"lat": base["lat"], "lon": base["lon"]})
        df["v10"] = np.round(scenario_pburn(base["p"].to_numpy(), w) * 100.0, 4)
        df["v25"] = np.round(base["cond"].to_numpy() * 100.0, 1)
        for c in ("v50", "v100", "v250", "v500"):
            df[c] = 0.0
        df["scenario"], df["hazard"] = sc, "wfire"
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    cols = ["lat", "lon", "scenario", "hazard"] + [f"v{rp}" for rp in rh.RETURN_PERIODS]
    return out[cols]


# ---------------------------------------------------------------------------
# WRC input: point sampling of the burn-probability / flame-length rasters
# ---------------------------------------------------------------------------

def resolve_wrc(bp_arg=None, cfl_arg=None):
    """(bp_path, cfl_path) from explicit flags, else the env vars, else a
    ./wrc/ folder (filenames containing 'bp' / 'cfl'). Either may be None:
    no BP means the layer is skipped with guidance; no CFL means the interim
    conditional ratio applies (capped, labeled interim)."""
    def _find(needle):
        d = Path(DEFAULT_WRC_DIR)
        if not d.is_dir():
            return None
        hits = sorted(p for p in d.iterdir()
                      if p.suffix.lower() in (".tif", ".tiff")
                      and needle in p.name.lower())
        return str(hits[0]) if hits else None
    bp = bp_arg or os.environ.get(WRC_BP_ENV) or _find("bp")
    cfl = cfl_arg or os.environ.get(WRC_CFL_ENV) or _find("cfl")
    return bp, cfl


def sample_raster_points(path, lat, lon):
    """(values, valid_mask) sampled at points from a GeoTIFF (rasterio seam,
    mocked in tests). Valid = finite and not the raster's nodata."""
    import rasterio
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    with rasterio.open(path) as src:
        vals = np.array([float(v[0]) for v in src.sample(zip(lon, lat))])
        nodata = src.nodata
    valid = np.isfinite(vals)
    if nodata is not None:
        valid &= ~np.isclose(vals, float(nodata))
    return vals, valid


def wrc_at_points(lat, lon, bp_path, cfl_path=None):
    """Point-sampled WRC values for the sites:
      bp           annual probability fire reaches the point (0..1)
      cond         conditional damage ratio given fire (CFL-mapped, or the
                   interim flat ratio where no CFL value exists)
      covered      BP raster has a valid value at the point (False = FLAG
                   the site, never silently zero it)
      cond_interim True where the conditional side is the interim ratio
    Raises ValueError when the BP raster does not look like a probability
    (values above 1), rather than guessing a rescale."""
    bp, cov = sample_raster_points(bp_path, lat, lon)
    if cov.any() and np.nanmax(np.abs(bp[cov])) > 1.0 + 1e-6:
        raise ValueError(
            f"{bp_path}: values exceed 1; expected annual burn probability "
            f"in 0..1 (check the WRC layer; do not rescale blindly)")
    bp = np.where(cov, np.clip(bp, 0.0, 1.0), 0.0)
    n = len(bp)
    if cfl_path:
        cfl, cfl_ok = sample_raster_points(cfl_path, lat, lon)
        cond = np.where(cfl_ok & (cfl >= 0),
                        assumptions.cfl_to_damage(np.maximum(cfl, 0.0)),
                        FIRE_COND_INTERIM)
        cond_interim = ~(cfl_ok & (cfl >= 0))
    else:
        cond = np.full(n, FIRE_COND_INTERIM)
        cond_interim = np.ones(n, dtype=bool)
    return {"bp": bp, "cond": cond, "covered": cov,
            "cond_interim": cond_interim}


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


def filter_firms_confidence(df, min_conf=MIN_CONFIDENCE):
    """Drop low-confidence detections before clustering: MODIS numeric confidence
    below min_conf, and VIIRS 'low' ('l'). Petals also cleans internally at
    confidence 30; this earlier, stronger cut removes agricultural-burn noise and
    speeds the fire-season clustering. Rows of unknown instrument are kept."""
    if "confidence" not in df.columns or "instrument" not in df.columns:
        return df
    inst = df["instrument"].astype(str).str.strip().str.upper()
    conf = df["confidence"]
    is_modis = (inst == "MODIS").to_numpy()
    c_num = pd.to_numeric(conf, errors="coerce").to_numpy()
    is_viirs = (inst == "VIIRS").to_numpy()
    c_low = conf.astype(str).str.strip().str.lower().eq("l").to_numpy()
    keep = ~((is_modis & (c_num < min_conf)) | (is_viirs & c_low))
    return df.loc[keep].reset_index(drop=True)


def filter_firms_near_sites(df, site_lat, site_lon, buffer_km=BUFFER_KM):
    """Keep detections within buffer_km of any portfolio site. Burn probability is
    only read at site locations (the app snaps a site to the nearest cell), so
    trimming to a buffer around the resorts gives the same answer at the sites,
    keeps Petals' clustering tractable, and drops fire regimes far from any resort
    (for example Southeast agricultural burning). A generous per-site lat/lon box
    union, vectorized."""
    lat = df["latitude"].to_numpy(float)
    lon = df["longitude"].to_numpy(float)
    keep = np.zeros(len(df), bool)
    dlat = buffer_km / 111.0
    for la, lo in zip(np.asarray(site_lat, float), np.asarray(site_lon, float)):
        dlon = buffer_km / (111.0 * max(np.cos(np.radians(la)), 0.1))
        keep |= (np.abs(lat - la) <= dlat) & (np.abs(lon - lo) <= dlon)
    return df.loc[keep].reset_index(drop=True)


def load_site_points(path):
    """(lat, lon) arrays from a sites CSV (needs latitude, longitude columns)."""
    s = pd.read_csv(path)
    s.columns = [str(c).strip().lower() for c in s.columns]
    if "latitude" not in s.columns or "longitude" not in s.columns:
        raise ValueError(f"{path}: needs latitude, longitude columns")
    la = pd.to_numeric(s["latitude"], errors="coerce")
    lo = pd.to_numeric(s["longitude"], errors="coerce")
    m = la.notna() & lo.notna()
    return la[m].to_numpy(), lo[m].to_numpy()


def load_sites_min(path):
    """(names, lat, lon) from a sites CSV; names fall back to row numbers."""
    s = pd.read_csv(path)
    s.columns = [str(c).strip().lower() for c in s.columns]
    if "latitude" not in s.columns or "longitude" not in s.columns:
        raise ValueError(f"{path}: needs latitude, longitude columns")
    la = pd.to_numeric(s["latitude"], errors="coerce")
    lo = pd.to_numeric(s["longitude"], errors="coerce")
    m = (la.notna() & lo.notna()).to_numpy()
    names = (s["name"].astype(str).to_numpy() if "name" in s.columns
             else np.array([f"row {i}" for i in range(len(s))]))
    return names[m], la.to_numpy()[m], lo.to_numpy()[m]


def resolve_sites(path):
    """Explicit --sites if given, else ./sites.csv when present, else None."""
    if path:
        return path
    return DEFAULT_SITES if Path(DEFAULT_SITES).exists() else None


# ---------------------------------------------------------------------------
# CLIMADA Petals seam (version-sensitive, mocked in tests)
# ---------------------------------------------------------------------------

# The cartopy-cache guard lives in refresh_hazard (shared by every producer that
# builds a hazard from local data). Kept here under its original name so the
# WildFire seam and its test call the same shorthand.
_ensure_cartopy_cache = rh.ensure_cartopy_cache


class _DropPetalsDeprecation(logging.Filter):
    """Drop Petals' internal 'X is deprecated' log notices, nothing else.

    from_hist_fire_seasons_FIRMS (the non-deprecated classmethod build_wildfire_
    hazard calls) loops over fire seasons and, inside Petals, calls the
    DEPRECATED WildFire.set_hist_fire_FIRMS once per year. Each call logs a
    WARNING on the Petals wildfire logger, so a ~25-year FIRMS archive prints
    ~25 identical 'is deprecated' lines. We already use the recommended
    classmethod; the deprecated call is Petals' own, so there is nothing to fix
    on our side but the noise. Crucially these are logging records
    (LOGGER.warning), NOT Python warnings, so warnings.simplefilter cannot touch
    them -- a logging filter can. Match only the deprecation text so genuine
    progress (INFO) and real warnings/errors from the same logger still show."""

    def filter(self, record):   # noqa: A003 (this IS the logging.Filter API)
        return "is deprecated" not in record.getMessage()


@contextlib.contextmanager
def _quiet_petals_deprecation(logger_name):
    """Attach _DropPetalsDeprecation to the named logger for the duration, then
    remove it. Scoped to the Petals wildfire logger and to the build call, so it
    silences the deprecation flood without hiding anything elsewhere or after."""
    logger = logging.getLogger(logger_name)
    filt = _DropPetalsDeprecation()
    logger.addFilter(filt)
    try:
        yield
    finally:
        logger.removeFilter(filt)


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
    # Two independent noise sources are silenced around the build:
    #  - warnings.catch_warnings(): Petals sets values via chained assignment
    #    internally (wildfire.py), which pandas >= 2.2 flags once per fire event
    #    with a FutureWarning -- a Python warning, silenced by the filter below.
    #  - _quiet_petals_deprecation(): from_hist_fire_seasons_FIRMS itself calls
    #    the deprecated set_hist_fire_FIRMS once per year, each a LOGGER.warning
    #    (a logging record, which the warnings filter CANNOT reach). Scoped to
    #    the exact Petals wildfire logger; real progress and errors stay visible.
    with warnings.catch_warnings(), _quiet_petals_deprecation(WildFire.__module__):
        warnings.simplefilter("ignore", FutureWarning)
        if ctor is not None:
            wf = ctor(df_firms, centr_res_factor=centr_res_factor,
                      year_start=year_start, year_end=year_end)
        else:                               # pre-classmethod releases
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


def write_firms_context(paths, out_csv, sites_path=None,
                        buffer_km=BUFFER_KM, min_confidence=MIN_CONFIDENCE):
    """The OPTIONAL historical fire-activity context export: FIRMS detection
    counts per 0.25-degree cell near the portfolio. Clearly separated from
    the loss calculation (its own file, its own columns, no hazard
    vocabulary) and never merged into the hazard grid."""
    df = filter_firms_confidence(load_firms(paths), min_confidence)
    scope = "within the portfolio region boxes"
    if sites_path:
        try:
            slat, slon = load_site_points(sites_path)
            df = filter_firms_near_sites(df, slat, slon, buffer_km)
            scope = "within %g km of %d site(s)" % (buffer_km, len(slat))
        except Exception as exc:
            LOG.warning("Context: could not use sites (%s); region boxes.", exc)
            df = filter_firms_to_regions(df)
    else:
        df = filter_firms_to_regions(df)
    g = pd.DataFrame({
        "cell_lat": np.round(df["latitude"].to_numpy(float) / rh.GRID_DEG)
        * rh.GRID_DEG,
        "cell_lon": np.round(df["longitude"].to_numpy(float) / rh.GRID_DEG)
        * rh.GRID_DEG,
        "year": pd.to_datetime(df["acq_date"], errors="coerce").dt.year,
    })
    out = (g.groupby(["cell_lat", "cell_lon"])
           .agg(detections=("year", "size"), first_year=("year", "min"),
                last_year=("year", "max")).reset_index())
    out.insert(0, "kind", "firms_historical_context")
    out.to_csv(out_csv, index=False)
    LOG.info("Context: %d detections -> %d cells (%s) -> %s. This layer is "
             "historical CONTEXT only and never feeds burn probability.",
             len(df), len(out), scope, out_csv)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Build the wildfire layer of the hazard grid: USFS WRC "
                    "burn probability point-sampled at the portfolio sites, "
                    "with flame-length-conditioned damage.")
    ap.add_argument("--wrc-bp", default=None, metavar="TIF",
                    help=f"WRC annual burn-probability GeoTIFF (or "
                         f"{WRC_BP_ENV}, or ./{DEFAULT_WRC_DIR}/*bp*.tif); "
                         "wildfirerisk.org / USFS RDS-2020-0016, downloaded "
                         "once like the DEM")
    ap.add_argument("--wrc-cfl", default=None, metavar="TIF",
                    help=f"WRC conditional flame length GeoTIFF (or "
                         f"{WRC_CFL_ENV}, or ./{DEFAULT_WRC_DIR}/*cfl*.tif); "
                         "absent -> the interim flat conditional ratio, "
                         "capped and labeled interim")
    ap.add_argument("--sites", default=None,
                    help="sites CSV to sample at (auto-uses ./sites.csv)")
    ap.add_argument("--out", default="wfire_grid.csv")
    ap.add_argument("--firms-context", nargs="+", default=None, metavar="CSV",
                    help="OPTIONAL: also write a historical fire-activity "
                         "context CSV from NASA FIRMS archives (never feeds "
                         "burn probability)")
    ap.add_argument("--context-out", default="firms_context.csv")
    ap.add_argument("--buffer-km", type=float, default=BUFFER_KM,
                    help="context export: keep fire history within this "
                         "radius of a site (default %(default)s)")
    ap.add_argument("--min-confidence", type=int, default=MIN_CONFIDENCE,
                    help="context export: MODIS confidence floor "
                         "(default %(default)s)")
    ap.add_argument("--country", default="USA", help="provenance label only")
    args = ap.parse_args(argv)

    meta = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "script": "refresh_wildfire.py v3 (WRC point burn probability)",
            "method": "USFS Wildfire Risk to Communities burn probability "
                      "sampled at the site point; conditional damage from "
                      "the WRC flame-length layer (FIRE_CFL_DAMAGE bands) "
                      "or the interim flat ratio; scenarios scale by "
                      "WARMING x FIRE_WARMING_UPLIFT",
            "fire_warming_uplift_per_c": FIRE_WARMING_UPLIFT,
            "fire_cond_interim": FIRE_COND_INTERIM,
            "encoding": {"v10": "annual probability fire reaches the site "
                                "point, percent",
                         "v25": "conditional structure damage ratio given "
                                "fire, percent",
                         "v50": 0, "v100": 0, "v250": 0, "v500": 0},
            "units": {"wfire": "indicator encoding, see 'encoding'"},
            "layers": [], "skipped": []}

    if args.firms_context:
        try:
            write_firms_context(args.firms_context, args.context_out,
                                resolve_sites(args.sites),
                                args.buffer_km, args.min_confidence)
        except Exception as exc:
            LOG.warning("FIRMS context export failed (%s); continuing to "
                        "the hazard layer.", exc)

    sites_path = resolve_sites(args.sites)
    if not sites_path:
        LOG.error("No sites CSV found (--sites or ./sites.csv). The wfire "
                  "layer is point-sampled AT the portfolio sites, so it "
                  "needs them.")
        meta["skipped"].append({"country": args.country, "layer": "wfire",
                                "reason": "no sites CSV (--sites / ./sites.csv)"})
        _write_meta(args.out, meta)
        return 1
    bp_path, cfl_path = resolve_wrc(args.wrc_bp, args.wrc_cfl)
    if not bp_path:
        LOG.error("No WRC burn-probability raster found. Download the "
                  "public-domain Burn Probability (and ideally Conditional "
                  "Flame Length) GeoTIFFs ONCE from wildfirerisk.org (USFS "
                  "RDS-2020-0016) and pass --wrc-bp/--wrc-cfl, set "
                  f"{WRC_BP_ENV}/{WRC_CFL_ENV}, or drop them in "
                  f"./{DEFAULT_WRC_DIR}/. The path is configuration, so a "
                  "pre-downloaded local file always works (corporate SSL "
                  "never blocks a rebuild). The app keeps wildfire on its "
                  "wui_class interim model until then.")
        meta["skipped"].append({"country": args.country, "layer": "wfire",
                                "reason": f"no WRC BP raster (--wrc-bp / "
                                          f"{WRC_BP_ENV} / ./{DEFAULT_WRC_DIR}/)"})
        _write_meta(args.out, meta)
        return 1

    try:
        names, slat, slon = load_sites_min(sites_path)
        w = wrc_at_points(slat, slon, bp_path, cfl_path)
    except Exception as exc:
        LOG.error("WRC sampling failed: %s", exc)
        meta["skipped"].append({"country": args.country, "layer": "wfire",
                                "reason": str(exc)[:300]})
        _write_meta(args.out, meta)
        return 1

    cov = w["covered"]
    for j in np.where(~cov)[0]:
        # flagged, never silently zeroed: WRC coverage must be confirmed
        # for Hawaii and the territories per release
        meta["skipped"].append({"country": args.country, "layer": "wfire",
                                "site": str(names[j]),
                                "reason": "outside WRC burn-probability "
                                          "raster coverage (no valid value "
                                          "at the site point)"})
    if not cov.any():
        LOG.error("No site has a valid WRC value; check the raster extent.")
        _write_meta(args.out, meta)
        return 1

    rows = wfire_rows(slat[cov], slon[cov], w["bp"][cov], w["cond"][cov])
    n_sites = int(len(rows) / len(WARMING))
    for sc in WARMING:
        meta["layers"].append({"hazard": "wfire", "scenario": sc,
                               "country": args.country, "cells": n_sites})
    meta["wrc"] = {"bp_raster": Path(bp_path).name,
                   "cfl_raster": Path(cfl_path).name if cfl_path else None,
                   "sites_file": Path(sites_path).name,
                   "sites_sampled": int(cov.sum()),
                   "sites_outside_coverage": int((~cov).sum()),
                   "cond_interim_sites": int(w["cond_interim"][cov].sum()),
                   "source": "USFS Wildfire Risk to Communities "
                             "(wildfirerisk.org; RDS-2020-0016), public "
                             "domain; local pre-downloaded file"}
    if cfl_path is None:
        LOG.warning("No CFL raster: the conditional damage side uses the "
                    "INTERIM flat ratio %.2f (capped); the app labels it "
                    "interim on the trust surface.", FIRE_COND_INTERIM)
    p_now = w["bp"][cov]
    if p_now.size and float(p_now.max()) > 0.05:
        LOG.warning("Max point burn probability %.1f%%/yr: plausible only "
                    "in extreme WUI; inspect the raster and the site "
                    "coordinates before shipping.", p_now.max() * 100)
    LOG.info("  wfire %s -> %d site-point cells x %d scenarios "
             "(mean p %.3f%%, max p %.3f%%)", args.country, n_sites,
             len(WARMING), float(p_now.mean()) * 100, float(p_now.max()) * 100)
    rows.to_csv(args.out, index=False)
    meta_path = _write_meta(args.out, meta)
    LOG.info("Wrote %d rows to %s and provenance to %s",
             len(rows), args.out, meta_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
