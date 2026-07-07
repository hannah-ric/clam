"""
portfolio_regions.py
====================

The ONE definition of the portfolio's regional footprint, shared by every
producer that trims or grids by region (refresh_heat.py, refresh_wildfire.py)
and by the coverage audit in validate_grid.py. Before this module the same
box list was hand-mirrored in two producers, which is exactly the drift the
WARMING parity test exists to prevent; boxes get the same treatment.

Audit note (per-site trust increment)
-------------------------------------
The boxes were audited against the portfolio extent the app itself encodes
(the sample portfolio and the intake docs): Southeast US + Gulf + Atlantic
coast, the desert Southwest (Palm Springs), Hawaii, and the Caribbean
territories (Puerto Rico, US Virgin Islands). All four boxes cover that
extent. The boxes are a PROCESSING extent, not a guarantee: any site falling
outside every box, or outside a peril's centroid coverage, must be FLAGGED
(validate_grid --sites, the results pack's per-site coverage records, and
the app's per-site trust chips), never silently zeroed.

Box format: (name, lat_min, lat_max, lon_min, lon_max), lon in -180..180.
Add boxes as the portfolio grows; every consumer picks the change up at once.
"""

from __future__ import annotations

import numpy as np

REGIONS = [
    ("conus_se_gulf", 24.0, 37.5, -100.5, -74.0),   # FL, Gulf, Carolinas, TX triangle
    ("southwest",     32.0, 38.0, -120.0, -110.0),  # Palm Springs, desert SW
    ("hawaii",        18.0, 23.0, -161.0, -154.0),
    ("caribbean",     17.0, 19.5, -68.0, -64.0),    # PR, USVI
]


def in_regions(lat, lon, regions=REGIONS):
    """Boolean array: which points fall inside the union of the region boxes."""
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    keep = np.zeros(lat.shape, bool)
    for _name, la0, la1, lo0, lo1 in regions:
        keep |= (lat >= la0) & (lat <= la1) & (lon >= lo0) & (lon <= lo1)
    return keep


def region_of(lat, lon, regions=REGIONS):
    """Name of the first region box containing each point, else None."""
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    out = np.full(lat.shape, None, dtype=object)
    for name, la0, la1, lo0, lo1 in regions:
        hit = (lat >= la0) & (lat <= la1) & (lon >= lo0) & (lon <= lo1)
        out[hit & (out == None)] = name          # noqa: E711 (array comparison)
    return out


def sites_outside_regions(names, lat, lon, regions=REGIONS):
    """[(name, lat, lon), ...] for every site outside all region boxes.
    The caller decides how loudly to flag them; silence is not an option."""
    inside = in_regions(lat, lon, regions)
    return [(str(n), float(la), float(lo))
            for n, la, lo, ok in zip(names, lat, lon, inside) if not ok]
