#!/usr/bin/env bash
# =============================================================================
# setup_env.sh : brings your EXISTING climada_env up to Phase 0-4 spec.
#
# You built climada_env during the original setup (Miniforge, conda-forge,
# CLIMADA 6.1.0). This script does not replace it; it ADDS what the new
# layers need: CLIMADA Petals (surge), xarray + netcdf4 (heat and DEM),
# requests and rasterio (downloads and GeoTIFFs). If climada_env somehow does
# not exist, it creates the whole thing from scratch. Safe to re-run.
#
# Usage:   bash setup_env.sh
# =============================================================================
set -euo pipefail

ENV_NAME="${RTV_ENV:-climada_env}"

if command -v mamba >/dev/null 2>&1; then PKG=mamba
elif command -v conda >/dev/null 2>&1; then PKG=conda
else
  echo "ERROR: neither mamba nor conda found on PATH."
  echo "Install Miniforge from https://conda-forge.org/download/ (the same"
  echo "installer used in the original setup)."
  exit 1
fi
echo "Using package manager: $PKG"

if $PKG env list | grep -qE "(^|/)${ENV_NAME}([[:space:]]|$)"; then
  echo "Found existing '$ENV_NAME'. Adding Petals and the Phase 1-3 libraries..."
  $PKG install -y -n "$ENV_NAME" -c conda-forge \
      "climada-petals=6.*" xarray netcdf4 requests rasterio
else
  echo "No '$ENV_NAME' found. Creating it fresh (several minutes)..."
  $PKG create -y -n "$ENV_NAME" -c conda-forge python=3.11 \
      "climada=6.*" "climada-petals=6.*" pandas numpy xarray netcdf4 requests rasterio
fi

echo
echo "=============================================================="
echo "Environment ready. TWO manual steps remain (skip any already done):"
echo
echo "1. DEM (needed for the coastal-flood surge layer):"
echo "   a. In a browser, open https://topex.ucsd.edu/pub/srtm15_plus/"
echo "   b. Download the newest SRTM15_V2.x.nc (about 6 GB, free)"
echo "   c. Move it into this folder, then convert and crop it:"
echo "        python convert_dem.py SRTM15_V2.7.nc"
echo "      (writes SRTM15+V2.0.tiff, a few hundred MB; the .nc can then go)"
echo "   Without it, refresh_hazard.py still runs and skips the cflood layer."
echo
echo "2. Corporate network: your existing certificate exports from the"
echo "   original setup (REQUESTS_CA_BUNDLE and SSL_CERT_FILE in your zsh"
echo "   profile) carry over unchanged and also cover the NASA, NOAA, and"
echo "   Scripps downloads. If a download fails with a TLS error anyway,"
echo "   run  python diagnose_network.py  and re-apply what it prints."
echo
echo "Then verify, once:"
echo "   conda activate $ENV_NAME"
echo "   python check_climada.py"
echo "   python check_phase1.py --smoke"
echo
echo "After that, every refresh is just:  bash run_pipeline.sh"
echo "=============================================================="
