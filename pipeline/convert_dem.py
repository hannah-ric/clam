"""
convert_dem.py
==============

Turns the SRTM15+ file you download from Scripps (a .nc netCDF, about 6 GB)
into the GeoTIFF the surge pipeline expects, cropped to the portfolio's part
of the world so the result is a few hundred MB instead of six thousand.

You run this ONCE, right after downloading the .nc file:

    python convert_dem.py SRTM15_V2.6.nc

That writes SRTM15+V2.0.tiff into the current folder, which is exactly the
name refresh_hazard.py looks for. Done. You can delete the .nc afterwards,
or keep it in case the portfolio grows beyond the default crop box.

Options:
    python convert_dem.py SRTM15_V2.6.nc --out mydem.tiff
    python convert_dem.py SRTM15_V2.6.nc --bbox -161 16 -63 51
                                          (lon_min lat_min lon_max lat_max)

The default box covers CONUS, Hawaii, Puerto Rico, and the USVI with margin.
If you add countries like MEX or BHS later, widen the box and re-run; the
pipeline itself never needs the whole globe.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

# default crop: everything the current portfolio can need, with margin
DEFAULT_BBOX = (-161.0, 16.0, -63.0, 51.0)   # lon_min, lat_min, lon_max, lat_max
DEFAULT_OUT = "SRTM15+V2.0.tiff"


def prepare_grid(lat: np.ndarray, lon: np.ndarray, values: np.ndarray):
    """Pure and unit-tested: orient a (lat, lon) grid north-up and west-east,
    and return the georeferencing numbers a GeoTIFF needs.

    Returns (values_north_up, info) where info has west/north EDGES (the
    coordinates are cell centers, so edges sit half a cell outward) and the
    cell sizes dx, dy (dy positive, meaning size, not direction).
    """
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    v = np.asarray(values)
    if lon.size > 1 and lon[1] < lon[0]:          # ensure west -> east
        lon = lon[::-1]
        v = v[:, ::-1]
    if lat.size > 1 and lat[1] > lat[0]:          # ensure north-up rows
        lat = lat[::-1]
        v = v[::-1, :]
    dx = float(abs(lon[1] - lon[0])) if lon.size > 1 else 1.0
    dy = float(abs(lat[0] - lat[1])) if lat.size > 1 else 1.0
    info = {"west": float(lon[0] - dx / 2), "north": float(lat[0] + dy / 2),
            "dx": dx, "dy": dy, "height": v.shape[0], "width": v.shape[1]}
    return v, info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Convert SRTM15+ .nc to the cropped "
                                             "GeoTIFF the surge pipeline expects.")
    ap.add_argument("nc_file", help="the SRTM15_V2.x.nc you downloaded from Scripps")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--bbox", nargs=4, type=float, default=list(DEFAULT_BBOX),
                    metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"))
    args = ap.parse_args(argv)
    lon_min, lat_min, lon_max, lat_max = args.bbox

    import xarray as xr
    import rasterio
    from rasterio.transform import from_origin

    print(f"Opening {args.nc_file} (reading only the crop box, not all 6 GB)...")
    ds = xr.open_dataset(args.nc_file)
    var = "z" if "z" in ds else next(v for v in ds.data_vars
                                     if ds[v].ndim == 2)
    lat_name = "lat" if "lat" in ds[var].dims else "y"
    lon_name = "lon" if "lon" in ds[var].dims else "x"
    da = ds[var]

    # slice respecting whichever direction the coordinates run in
    lat_asc = bool(da[lat_name][1] > da[lat_name][0])
    lat_sl = slice(lat_min, lat_max) if lat_asc else slice(lat_max, lat_min)
    da = da.sel({lat_name: lat_sl, lon_name: slice(lon_min, lon_max)})
    print(f"Crop: {da.sizes[lat_name]} x {da.sizes[lon_name]} cells "
          f"(lat {lat_min}..{lat_max}, lon {lon_min}..{lon_max}). Loading...")
    values = da.values.astype("float32")
    v, info = prepare_grid(da[lat_name].values, da[lon_name].values, values)

    transform = from_origin(info["west"], info["north"], info["dx"], info["dy"])
    with rasterio.open(args.out, "w", driver="GTiff", height=info["height"],
                       width=info["width"], count=1, dtype="float32",
                       crs="EPSG:4326", transform=transform,
                       compress="lzw", tiled=True) as dst:
        dst.write(v, 1)

    mb = Path(args.out).stat().st_size / 1e6
    print(f"Wrote {args.out} ({mb:.0f} MB).")
    print("Next: python check_phase1.py   (it should now say the DEM opens and")
    print("covers your regions). The big .nc file can be deleted or archived.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
