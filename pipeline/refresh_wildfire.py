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

Usage:
    python refresh_wildfire.py                # writes wfire_grid.csv (+ meta)
    python merge_grids.py hazard_grid.csv wfire_grid.csv -o hazard_grid.csv
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
LOG = logging.getLogger("refresh_wildfire")

# MIRRORS the WARMING table in the app and refresh_heat.py; change all three.
WARMING = {
    "present": 0.0,
    "ssp126_2030": 0.6, "ssp126_2050": 1.0, "ssp126_2080": 1.3,
    "ssp245_2030": 0.7, "ssp245_2050": 1.4, "ssp245_2080": 2.3,
    "ssp585_2030": 0.8, "ssp585_2050": 2.0, "ssp585_2080": 3.6,
}
FIRE_WARMING_UPLIFT = 0.14      # fractional burn-probability increase per deg C
COUNTRIES = ["USA"]             # FIRMS coverage worth fetching; extend as needed


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
# CLIMADA Petals seam (version-sensitive, mocked in tests)
# ---------------------------------------------------------------------------

def fetch_wildfire_hazard(iso3):
    """Probabilistic wildfire Hazard for a country via Petals' WildFire.
    Kept behind one seam because the module's constructors have shifted
    across releases; walk the candidates until one works."""
    from climada_petals.hazard import WildFire
    wf = WildFire()
    for name in ("from_hist_fire_seasons_FIRMS", "set_hist_fire_seasons_FIRMS"):
        fn = getattr(wf, name, None) or getattr(WildFire, name, None)
        if fn is None:
            continue
        try:
            haz = fn(iso3) if name.startswith("from_") else (fn(iso3) or wf)
            try:                       # probabilistic seasons when offered
                haz.set_proba_fire_seasons()
            except Exception:
                pass
            return haz
        except Exception as exc:
            LOG.info("  %s failed, trying next: %s", name, str(exc)[:160])
    raise RuntimeError("no WildFire constructor variant worked; check the "
                       "climada-petals release notes")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the wildfire layer of the "
                                             "hazard grid (burn probability).")
    ap.add_argument("--countries", nargs="*", default=COUNTRIES)
    ap.add_argument("--out", default="wfire_grid.csv")
    args = ap.parse_args(argv)

    meta = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "script": "refresh_wildfire.py v1 (increment 3)",
            "method": "Petals WildFire (FIRMS) burn probability; scenarios "
                      "scale by WARMING x FIRE_WARMING_UPLIFT",
            "fire_warming_uplift_per_c": FIRE_WARMING_UPLIFT,
            "encoding": {"v10": "annual burn probability, percent",
                         "v25": 0, "v50": 0, "v100": 0, "v250": 0, "v500": 0},
            "units": {"wfire": "indicator encoding, see 'encoding'"},
            "layers": [], "skipped": []}
    frames = []
    for iso3 in args.countries:
        try:
            haz = fetch_wildfire_hazard(iso3)
        except Exception as exc:
            LOG.warning("Skipping %s: %s", iso3, exc)
            meta["skipped"].append({"country": iso3, "layer": "wfire",
                                    "reason": str(exc)[:300]})
            continue
        inten = haz.intensity
        hits = (inten.toarray() if hasattr(inten, "toarray")
                else np.asarray(inten)) > 0
        p = burn_probability(haz.frequency, hits)
        rows = wfire_rows(np.asarray(haz.centroids.lat, float),
                          np.asarray(haz.centroids.lon, float), p)
        frames.append(rows)
        for sc in WARMING:
            meta["layers"].append({"hazard": "wfire", "scenario": sc,
                                   "country": iso3,
                                   "cells": int(len(rows) / len(WARMING))})
        LOG.info("  wfire %s -> %d cells x %d scenarios (max p %.2f%%)",
                 iso3, len(rows) // len(WARMING), len(WARMING),
                 float(rows["v10"].max()))
    if not frames:
        LOG.error("No wildfire layer produced.")
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
