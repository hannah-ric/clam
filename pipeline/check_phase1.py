"""
check_phase1.py
===============

Run this ONCE before the first refresh_hazard.py run that includes the coastal
flood (surge) layer, and again after any environment or DEM change. It is the
Phase 1 counterpart to check_climada.py: that script proves CLIMADA Core and
the Data API work; this one proves the three NEW dependencies do:

  1. climada_petals imports and its version is compatible with climada Core
     (same major; Petals minor may lead Core, e.g. Petals 6.2 on Core 6.1),
  2. the DEM GeoTIFF exists, opens, and truly covers your countries,
  3. the distance-to-coast auxiliary data (used by the surge inland decay)
     can be obtained, which on first use downloads through the CLIMADA client.

Optionally (--smoke) it runs one real end-to-end surge computation on the
smallest country in the portfolio (VIR), which exercises the full path:
Data API wind -> TCSurgeBathtub -> exceedance intensities. Two-ish minutes.

In VS Code: terminal, prompt showing (climada_env), then:

    python check_phase1.py            # steps 1-3, seconds
    python check_phase1.py --smoke    # plus the real surge smoke test

If every step prints OK you are clear to run refresh_hazard.py with surge.
If anything errors, copy the whole output back and it can be fixed in one edit.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

TOPO_PATH = Path(os.environ.get("RTV_TOPO_PATH", "SRTM15+V2.0.tiff"))

# rough lon/lat boxes the DEM must cover for the current portfolio countries
NEEDED_BOXES = {
    "USA (CONUS+HI)": (-160.5, 18.5, -66.0, 49.5),
    "PRI":            (-67.5, 17.7, -65.1, 18.7),
    "VIR":            (-65.2, 17.6, -64.5, 18.5),
}


def step(n, title):
    print("=" * 60)
    print(f"STEP {n}  {title}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true",
                    help="also run a real surge computation on VIR (slower)")
    args = ap.parse_args()

    step(1, "climada_petals import & version alignment")
    try:
        import climada  # noqa: F401
        import climada_petals  # noqa: F401
        from climada_petals.hazard import TCSurgeBathtub  # noqa: F401
    except Exception as exc:
        print("  FAILED to import climada_petals / TCSurgeBathtub:", exc)
        print("  Fix: mamba install -c conda-forge climada-petals=6.*  "
              "(same major version as climada; Petals minor may lead Core)")
        return 1
    from importlib.metadata import version
    try:
        v_core = version("climada")
        try:
            v_pet = version("climada-petals")
        except Exception:
            v_pet = version("climada_petals")
        print(f"  climada {v_core}  /  climada_petals {v_pet}")
        # The real contract is NOT "matching minor versions": Petals declares an
        # open-ended floor on Core (e.g. Petals 6.2.0 requires `climada>=6.1`) and
        # its own minor can LEAD Core's, because Petals ships releases between Core
        # releases. Petals 6.2.0 on Core 6.1.0 is the intended, supported pairing
        # (there is no Core 6.2.0). So only the MAJOR must agree; a Petals minor
        # ahead of Core is normal, not a misconfiguration.
        core_major, core_minor = (int(x) for x in (v_core.split(".") + ["0", "0"])[:2])
        pet_major, pet_minor = (int(x) for x in (v_pet.split(".") + ["0", "0"])[:2])
        if core_major != pet_major:
            print("  WARNING: Core and Petals MAJOR versions differ "
                  f"({core_major} vs {pet_major}). These are not compatible; "
                  "install a matching major (both 6.*).")
        elif pet_minor < core_minor:
            print("  WARNING: Petals minor is behind Core minor "
                  f"({v_pet} < {v_core}). Petals normally leads or matches Core; "
                  "a Petals older than Core may not support this Core. Upgrade "
                  "Petals (mamba install -c conda-forge climada-petals=6.*).")
        else:
            print("  OK: compatible pair (same major; Petals minor >= Core minor). "
                  "A Petals minor ahead of Core is expected: Petals releases "
                  "between Core releases and declares climada>=<its floor>.")
    except Exception:
        print("  imported OK (version metadata unavailable)")

    step(2, f"DEM at {TOPO_PATH}")
    if not TOPO_PATH.exists():
        print("  FAILED: file not found.")
        print("  Fix: download SRTM15+ V2 (global topo-bathymetry GeoTIFF, free, "
              "Scripps/UCSD SRTM15+ page) and place it at this path, or")
        print("       export RTV_TOPO_PATH=/path/to/your/dem.tiff")
        return 1
    try:
        import rasterio
        with rasterio.open(TOPO_PATH) as src:
            b = src.bounds
            print(f"  opens OK: {src.width}x{src.height}px, "
                  f"res ~{abs(src.res[0])*3600:.0f} arcsec, crs {src.crs}")
            print(f"  bounds: lon [{b.left:.1f}, {b.right:.1f}]  "
                  f"lat [{b.bottom:.1f}, {b.top:.1f}]")
            for name, (w, s, e, n) in NEEDED_BOXES.items():
                ok = b.left <= w and b.right >= e and b.bottom <= s and b.top >= n
                verdict = "OK" if ok else "MISSING - surge for this region will be wrong or empty"
                print(f"  covers {name}: {verdict}")
    except Exception as exc:
        print("  FAILED to open DEM with rasterio:", exc)
        return 1

    step(3, "distance-to-coast auxiliary data (surge inland decay)")
    try:
        import numpy as np
        from climada.hazard import Centroids
        # a handful of points around Miami: onshore, nearshore, inland
        la = np.array([25.79, 25.90, 26.50]); lo = np.array([-80.13, -80.30, -81.00])
        try:
            cen = Centroids.from_lat_lon(la, lo)
        except AttributeError:               # 6.x refactor removed from_lat_lon
            cen = Centroids(lat=la, lon=lo)
        try:
            d = cen.get_dist_coast()          # may download NASA data on first use
        except TypeError:
            d = cen.get_dist_coast(precomputed=True)
        print(f"  OK: dist-to-coast sampled, e.g. {np.round(np.asarray(d)/1000, 1)} km")
    except Exception as exc:
        print("  FAILED:", exc)
        msg = str(exc).lower()
        if "403" in msg or "forbidden" in msg or "loading page" in msg:
            # TLS already succeeded (the request reached the server); a
            # corporate WEB FILTER is refusing this specific file. Cert
            # exports cannot fix a content block: seed the file off-network.
            try:
                from climada.util.constants import SYSTEM_DIR
                from climada.util.config import CONFIG
                tif = CONFIG.util.coordinates.dist_to_coast_nasa_tif.str()
                url = CONFIG.util.coordinates.dist_to_coast_nasa_url.str()
                dest = SYSTEM_DIR
            except Exception:
                tif = "GMT_intermediate_coast_distance_01d.tif"
                url = "the NASA distfromcoast zip"
                dest = "~/climada/data"
            print("  Cause: the download reached the server but was refused "
                  "(HTTP 403 / block page). A corporate web filter, not a "
                  "certificate, is blocking this file, so the cert exports "
                  "cannot help. Seed the ~300 MB file once from OFF the "
                  "corporate network:")
            print(f"    - run this check on a hotspot / home wifi so CLIMADA "
                  f"can fetch {url}, OR")
            print(f"    - download that zip elsewhere and unzip {tif} into {dest}")
            print(f"    Once {dest}/{tif} exists, this step never downloads "
                  "again. refresh_hazard.py --no-surge runs the other layers "
                  "meanwhile.")
        elif "certificate" in msg or "ssl" in msg or "verify" in msg:
            print("  Cause: corporate TLS interception, the same issue "
                  "diagnose_network.py solves for the Data API. Run it, export "
                  "REQUESTS_CA_BUNDLE and SSL_CERT_FILE, and rerun.")
        else:
            print("  This usually means the CLIMADA client cannot reach the "
                  "NASA dist-to-coast file. If it is a TLS error, apply the "
                  "diagnose_network.py cert exports; if it is a 403 / block "
                  "page, seed the file off-network (see docs/RUNBOOK.md).")
        return 1

    if args.smoke:
        step(4, "end-to-end surge smoke test on VIR (real computation)")
        try:
            from climada.util.api_client import Client
            from climada_petals.hazard import TCSurgeBathtub
            from climada.hazard import TropCyclone
            client = Client()
            haz = client.get_hazard("tropical_cyclone", properties={
                "country_iso3alpha": "VIR",
                "climate_scenario": "None", "event_type": "synthetic"})
            if not isinstance(haz, TropCyclone):
                tc = TropCyclone(); tc.__dict__.update(haz.__dict__); haz = tc
            surge = TCSurgeBathtub.from_tc_winds(haz, str(TOPO_PATH),
                                                 add_sea_level_rise=0.0)
            mx = surge.intensity.max()
            wet = (surge.intensity.max(axis=0).toarray().ravel() > 0).sum() \
                if hasattr(surge.intensity, "toarray") else (surge.intensity.max(0) > 0).sum()
            print(f"  OK: surge computed. max depth {float(mx):.2f} m across events, "
                  f"{int(wet)} centroids ever wet.")
            if float(mx) <= 0:
                print("  WARNING: zero surge everywhere. Check the DEM covers VIR "
                      "and contains coastal elevations near sea level.")
            if float(mx) > 15:
                print("  WARNING: max depth above 15 m is implausible for a bathtub "
                      "surge; inspect the DEM (units? sign?) before trusting output.")
        except Exception as exc:
            print("  FAILED:", exc)
            return 1

    print("=" * 60)
    print("All checks passed. You are clear to run: python refresh_hazard.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
