"""
enrich_sites.py  (profile schema v2 enrichment)
================================================

Drafts the v2 building-profile fields from public data so the operator
CONFIRMS instead of researches. Reads a sites CSV, fills only fields the
operator left blank, and writes:

    sites_enriched.csv           the draft (same schema, blanks filled)
    sites_enriched_meta.json     per-field provenance and needs_review flags

Rules, in order of importance:
  1. NEVER overwrite an operator-entered value. Filled fields are drafts.
  2. Every filled field records its source and carries needs_review=true.
  3. Every fetcher degrades gracefully: unreachable source = field left
     blank + a skipped record, never a crash (the rf_pick pattern).

Sources, cheapest first:
  * ground_elev_m       sampled from the DEM already on disk (rh.TOPO_PATH);
                        context for first_floor_elev_m, not a substitute
  * coast_km            distance to coast via the CLIMADA client seam
  * fema_zone           FEMA NFHL public map service, point query
  * buildings           OpenStreetMap building count near the point

Usage:
    python enrich_sites.py sites.csv -o sites_enriched.csv
    python enrich_sites.py sites.csv --no-network     # DEM-only, offline

The enriched CSV is a DRAFT: review the needs_review fields (the meta lists
them) before using it as the pipeline's sites input.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
LOG = logging.getLogger("enrich_sites")

# context columns this script may ADD (never required by the pipeline)
CONTEXT_COLS = ["ground_elev_m", "coast_km"]
# v2 profile columns it may DRAFT when blank
DRAFT_COLS = ["fema_zone", "buildings"]

FEMA_NFHL_URLS = [   # candidate-fallback: the public NFHL map service layers
    "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query",
    "https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer/28/query",
]
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


# ---------------------------------------------------------------------------
# Pure merge logic (unit-tested in test_profileops.py)
# ---------------------------------------------------------------------------

def is_blank(v):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return True
    s = str(v).strip().lower()
    return s in ("", "nan", "none")


def merge_field(df, idx, col, value, source, prov):
    """Fill df[col][idx] ONLY if blank; record provenance either way."""
    key = f"{df.at[idx, 'name']}:{col}"
    if col in df.columns and not is_blank(df.at[idx, col]):
        prov["kept"].append({"field": key, "reason": "operator value kept"})
        return False
    df.at[idx, col] = value
    prov["filled"].append({"field": key, "value": value, "source": source,
                           "needs_review": True})
    return True


# ---------------------------------------------------------------------------
# Fetch seams: each isolated, each skippable
# ---------------------------------------------------------------------------

def sample_dem(lats, lons):
    """Ground elevation (m) per site from the DEM on disk. Returns None when
    the DEM or rasterio is unavailable (recorded, not fatal)."""
    import refresh_hazard as rh
    if not rh.TOPO_PATH.exists():
        return None, f"DEM not found at {rh.TOPO_PATH}"
    try:
        import rasterio
        with rasterio.open(rh.TOPO_PATH) as src:
            vals = [v[0] for v in src.sample(zip(lons, lats))]
        return [round(float(v), 1) for v in vals], None
    except Exception as exc:
        return None, f"DEM sampling failed: {str(exc)[:200]}"


def coast_distance_km(lats, lons):
    """Distance to coast per site via the CLIMADA client (first use may
    download the NASA auxiliary file). None + reason when unavailable."""
    try:
        from climada.hazard import Centroids
        la, lo = np.asarray(lats, float), np.asarray(lons, float)
        try:
            cen = Centroids.from_lat_lon(la, lo)
        except AttributeError:
            cen = Centroids(lat=la, lon=lo)
        try:
            d = cen.get_dist_coast()
        except TypeError:
            d = cen.get_dist_coast(precomputed=True)
        return [round(float(x) / 1000.0, 1) for x in np.asarray(d)], None
    except Exception as exc:
        return None, f"dist-to-coast unavailable: {str(exc)[:200]}"


def fetch_fema_zone(lat, lon):
    """FEMA flood zone at a point from the public NFHL service. None + reason
    on any failure; the zone is screening context, always needs_review."""
    import requests
    params = {"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
              "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
              "outFields": "FLD_ZONE", "returnGeometry": "false", "f": "json"}
    last = None
    for url in FEMA_NFHL_URLS:
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            feats = r.json().get("features", [])
            if feats:
                return str(feats[0]["attributes"].get("FLD_ZONE", "")).strip(), None
            return None, "no NFHL polygon at point"
        except Exception as exc:
            last = str(exc)[:200]
    return None, f"NFHL unreachable: {last}"


def fetch_osm_buildings(lat, lon, radius_m=150):
    """Building count within radius via Overpass. None + reason on failure."""
    import requests
    q = (f"[out:json][timeout:25];"
         f"way[building](around:{radius_m},{lat},{lon});out count;")
    last = None
    for url in OVERPASS_URLS:
        try:
            r = requests.post(url, data={"data": q}, timeout=40)
            r.raise_for_status()
            els = r.json().get("elements", [])
            if els and "tags" in els[0]:
                return int(els[0]["tags"].get("total", 0)), None
            return None, "unexpected Overpass shape"
        except Exception as exc:
            last = str(exc)[:200]
    return None, f"Overpass unreachable: {last}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Draft v2 building-profile fields "
                                             "from public data (operator confirms).")
    ap.add_argument("sites")
    ap.add_argument("-o", "--out", default="sites_enriched.csv")
    ap.add_argument("--no-network", action="store_true",
                    help="DEM sampling only; skip FEMA and OSM lookups")
    args = ap.parse_args(argv)

    df = pd.read_csv(args.sites)
    need = ["name", "latitude", "longitude"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise SystemExit(f"{args.sites}: missing required columns {missing}")
    for c in CONTEXT_COLS + DRAFT_COLS:
        if c not in df.columns:
            df[c] = None

    prov = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "script": "enrich_sites.py v1",
            "sites_file": args.sites,
            "filled": [], "kept": [], "skipped": []}

    lats = df["latitude"].to_numpy(float)
    lons = df["longitude"].to_numpy(float)

    elev, why = sample_dem(lats, lons)
    if elev is None:
        prov["skipped"].append({"source": "dem", "reason": why})
        LOG.warning("DEM: %s", why)
    else:
        for i in df.index:
            merge_field(df, i, "ground_elev_m", elev[i],
                        "SRTM15+ DEM sample (topo-bathymetry; verify on site)",
                        prov)

    dist, why = coast_distance_km(lats, lons)
    if dist is None:
        prov["skipped"].append({"source": "dist_coast", "reason": why})
        LOG.warning("dist-to-coast: %s", why)
    else:
        for i in df.index:
            merge_field(df, i, "coast_km", dist[i],
                        "CLIMADA dist-to-coast (NASA)", prov)

    if not args.no_network:
        for i in df.index:
            z, why = fetch_fema_zone(lats[i], lons[i])
            if z is None:
                prov["skipped"].append({"source": "fema_nfhl",
                                        "site": str(df.at[i, "name"]),
                                        "reason": why})
            else:
                merge_field(df, i, "fema_zone", z, "FEMA NFHL point query", prov)
            b, why = fetch_osm_buildings(lats[i], lons[i])
            if b is None:
                prov["skipped"].append({"source": "osm",
                                        "site": str(df.at[i, "name"]),
                                        "reason": why})
            else:
                merge_field(df, i, "buildings", b,
                            "OpenStreetMap building count within 150 m", prov)

    df.to_csv(args.out, index=False)
    meta_path = Path(args.out).with_name(Path(args.out).stem + "_meta.json")
    meta_path.write_text(json.dumps(prov, indent=2, default=str))
    n_rev = len(prov["filled"])
    LOG.info("Wrote %s (%d field(s) drafted, all needs_review) and %s",
             args.out, n_rev, meta_path)
    if n_rev:
        LOG.info("Review the drafted fields, then use the confirmed file as "
                 "the sites input for refresh_impacts.py.")
    if prov["skipped"]:
        LOG.warning("%d lookup(s) skipped; see the meta sidecar.",
                    len(prov["skipped"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
