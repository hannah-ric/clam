"""
refresh_prain.py  (adaptation-first increment 3: the sixth peril)
==================================================================

Produces the tropical-cyclone rainfall layer (hazard="prain") of the hazard
grid from CLIMADA Petals' TCRain over IBTrACS-derived track sets: the
Harvey-type peril, damaging inland sites wind and surge never touch.

Encoding: v10..v500 = event-accumulated rainfall in MILLIMETRES at each
return period. The app converts rainfall to ponding depth through documented
site-drainage constants and runs its flood damage curve; conversion lives
app-side so drainage assumptions stay adjustable without a pipeline rerun.

Scenarios by Clausius-Clapeyron scaling: rainfall intensity rises
PRAIN_CC_PER_C (7%) per degree C of warming, applied to the present-day
return-period field using the app's own WARMING table. Screening grade and
stated: no change in storm frequency or track, moisture scaling only.

Honest limits: R-CLIPER-class rainfall is a statistical profile (no
topography unless the Petals release provides the TCR physical model);
drainage conversion is a portfolio screening constant, not a site drainage
study. The layer ranks pluvial exposure across sites; it does not size pumps.

Usage:
    python refresh_prain.py                  # writes prain_grid.csv (+ meta)
    python merge_grids.py hazard_grid.csv prain_grid.csv -o hazard_grid.csv
    python validate_grid.py hazard_grid.csv hazard_grid_meta.json
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import refresh_hazard as rh

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
LOG = logging.getLogger("refresh_prain")

# MIRRORS the app's WARMING table; change both.
WARMING = {
    "present": 0.0,
    "ssp126_2030": 0.6, "ssp126_2050": 1.0, "ssp126_2080": 1.3,
    "ssp245_2030": 0.7, "ssp245_2050": 1.4, "ssp245_2080": 2.3,
    "ssp585_2030": 0.8, "ssp585_2050": 2.0, "ssp585_2080": 3.6,
}
PRAIN_CC_PER_C = 0.07           # Clausius-Clapeyron moisture scaling per deg C
NB_SYNTH_TRACKS = 9             # perturbed trajectories per historical track
COUNTRIES = ["USA", "PRI", "VIR"]
# Rain DOMAINS: each pairs a centroid bbox (lon0, lat0, lon1, lat1) with the
# IBTrACS basin whose storms actually rain there. The coverage audit behind
# this structure: the original per-country BBOXES carried no Hawaii box and
# the track fetch hardcoded basin="NA", so Hawaii resorts (whose cyclones,
# e.g. Iniki and Lane, live in the East/Central Pacific basin) silently
# scored zero TC rainfall. Hawaii is now its own EP-basin domain, and any
# site outside every domain is FLAGGED by the consumers, never zeroed
# silently. A country may span several domains (USA = CONUS + Hawaii).
DOMAINS = [
    {"key": "conus",  "iso3": "USA", "basin": "NA",
     "bbox": (-100.5, 23.5, -74.0, 37.5)},          # TC-relevant CONUS
    {"key": "hawaii", "iso3": "USA", "basin": "EP",
     "bbox": (-161.0, 18.0, -154.0, 23.0)},
    {"key": "pri",    "iso3": "PRI", "basin": "NA",
     "bbox": (-67.5, 17.7, -65.1, 18.7)},
    {"key": "vir",    "iso3": "VIR", "basin": "NA",
     "bbox": (-65.2, 17.6, -64.5, 18.5)},
]
DOMAIN_MARGIN_DEG = 0.5         # a site this close to a box still reads from it


def domains_for(iso3, site_lat=None, site_lon=None, margin=DOMAIN_MARGIN_DEG):
    """The country's rain domains; when site coordinates are given, only the
    domains that actually cover at least one site (so a CONUS-only portfolio
    never fetches Pacific tracks)."""
    doms = [d for d in DOMAINS if d["iso3"] == iso3]
    if site_lat is None:
        return doms
    return [d for d in doms
            if bool(domain_covers(d, site_lat, site_lon, margin).any())]


def domain_covers(domain, lat, lon, margin=DOMAIN_MARGIN_DEG):
    """Boolean array: which sites the domain's bbox (plus margin) speaks for."""
    w, s, e, n = domain["bbox"]
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    return ((lat >= s - margin) & (lat <= n + margin)
            & (lon >= w - margin) & (lon <= e + margin))


# ---------------------------------------------------------------------------
# Pure ops (unit-tested in test_newperils.py)
# ---------------------------------------------------------------------------

def cc_scale(warming_c, per_c=PRAIN_CC_PER_C):
    """Clausius-Clapeyron rainfall multiplier for a warming level."""
    return 1.0 + per_c * warming_c


def prain_rows(present_grid, grid_deg=rh.GRID_DEG):
    """All-scenario rows from the thinned present-day RP rainfall grid.
    One shared cell set; scenarios scale the field (coverage never varies
    by horizon)."""
    frames = []
    vcols = [f"v{rp}" for rp in rh.RETURN_PERIODS]
    for sc, w in WARMING.items():
        df = present_grid.copy()
        for c in vcols:
            df[c] = np.round(df[c].to_numpy(float) * cc_scale(w), 1)
        df["scenario"], df["hazard"] = sc, "prain"
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    return out[["lat", "lon", "scenario", "hazard"] + vcols]


# ---------------------------------------------------------------------------
# CLIMADA seams (version-sensitive, mocked in tests)
# ---------------------------------------------------------------------------

def fetch_tracks(domain):
    """IBTrACS historical tracks for the domain's basin near its box,
    densified and perturbed into a synthetic set (the standard CLIMADA track
    recipe)."""
    from climada.hazard import TCTracks
    w, s, e, n = domain["bbox"]
    tr = TCTracks.from_ibtracs_netcdf(basin=domain["basin"],
                                      year_range=(1980, 2024))
    try:
        tr = tr.tracks_in_exp_bbox(w, e, s, n)     # not in every release
    except Exception:
        pass
    tr.equal_timestep(1.0)
    tr.calc_perturbed_trajectories(nb_synth_tracks=NB_SYNTH_TRACKS)
    return tr


def rain_hazard(tracks, domain):
    """TCRain accumulated rainfall (mm) on the domain's centroid grid."""
    from climada.hazard import Centroids
    from climada_petals.hazard import TCRain
    w, s, e, n = domain["bbox"]
    res_deg = 150 / 3600.0
    try:
        cen = Centroids.from_pnt_bounds((w, s, e, n), res=res_deg)
    except TypeError:
        cen = Centroids.from_pnt_bounds((w, s, e, n), res_deg)
    return TCRain.from_tracks(tracks, centroids=cen)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the TC rainfall layer of "
                                             "the hazard grid (mm at RPs).")
    ap.add_argument("--countries", nargs="*", default=COUNTRIES)
    ap.add_argument("--out", default="prain_grid.csv")
    args = ap.parse_args(argv)

    # calc_perturbed_trajectories and TCRain resolve land geometry through
    # cartopy; redirect its cache before the first fetch so a non-writable
    # default (~/.local/share/cartopy) does not skip every country.
    rh.ensure_cartopy_cache()

    meta = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "script": "refresh_prain.py v2 (basin-aware rain domains)",
            "method": "Petals TCRain over IBTrACS-derived synthetic tracks per "
                      "basin domain; scenarios scale by Clausius-Clapeyron per "
                      "WARMING",
            "prain_cc_per_c": PRAIN_CC_PER_C,
            "nb_synth_tracks": NB_SYNTH_TRACKS,
            "domains": [{"key": d["key"], "iso3": d["iso3"],
                         "basin": d["basin"], "bbox": list(d["bbox"])}
                        for d in DOMAINS],
            "units": {"prain": "mm event-accumulated rainfall"},
            "layers": [], "skipped": []}
    frames = []
    domains = [d for d in DOMAINS if d["iso3"] in args.countries]
    for dom in domains:
        label = f"{dom['iso3']}/{dom['key']}"
        try:
            tracks = fetch_tracks(dom)
            haz = rain_hazard(tracks, dom)
        except Exception as exc:
            LOG.warning("Skipping %s: %s", label, exc)
            meta["skipped"].append({"country": dom["iso3"], "layer": "prain",
                                    "domain": dom["key"],
                                    "reason": str(exc)[:300]})
            continue
        lat = np.asarray(haz.centroids.lat, float)
        lon = np.asarray(haz.centroids.lon, float)
        inten = rh.local_rp_intensity(haz, rh.RETURN_PERIODS)
        present = rh.thin_to_grid(lat, lon,
                                  {rp: inten[i] for i, rp
                                   in enumerate(rh.RETURN_PERIODS)})
        # keep only cells inside the domain box: a stray centroid must not
        # let one domain speak for another's territory
        inside = domain_covers(dom, present["lat"].to_numpy(),
                               present["lon"].to_numpy(), margin=0.0)
        present = present.loc[inside].reset_index(drop=True)
        if not len(present):
            LOG.warning("Skipping %s: no cells inside the domain box", label)
            meta["skipped"].append({"country": dom["iso3"], "layer": "prain",
                                    "domain": dom["key"],
                                    "reason": "no cells inside the domain box"})
            continue
        rows = prain_rows(present)
        frames.append(rows)
        for sc in WARMING:
            meta["layers"].append({"hazard": "prain", "scenario": sc,
                                   "country": dom["iso3"], "domain": dom["key"],
                                   "basin": dom["basin"],
                                   "cells": int(len(rows) / len(WARMING))})
        LOG.info("  prain %s -> %d cells x %d scenarios (max v100 %.0f mm)",
                 label, len(rows) // len(WARMING), len(WARMING),
                 float(rows["v100"].max()))
    if not frames:
        LOG.error("No rainfall layer produced.")
        return 1
    out = pd.concat(frames, ignore_index=True)
    out.to_csv(args.out, index=False)
    meta_path = Path(args.out).with_name(Path(args.out).stem + "_meta.json")
    meta_path.write_text(json.dumps(meta, indent=2))
    LOG.info("Wrote %d rows to %s and provenance to %s",
             len(out), args.out, meta_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
