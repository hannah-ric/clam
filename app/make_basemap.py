"""
make_basemap.py : regenerates app/src/88_basemap_data.js, the bundled
offline basemap behind the v3 climate map (Surface 3).

WHY THIS EXISTS. The overhaul's ground rules forbid a paid or online
basemap dependency: the map must work from bundled local data, offline,
inside the single self-contained HTML file. Full offline vector tiles
would add megabytes and a tile pipeline, so the chosen approach is a
clean minimal-geometry basemap (land, coastlines by implication, country
and state boundaries, major lakes) generated from public-domain Natural
Earth 1:50m geodata, clipped to the region the portfolio occupies
(Americas: CONUS + Hawaii + Gulf + Caribbean) and quantized to ~1 km.
That is plenty for orientation; the DATA on top (CLAM's own hazard
fields and TCOR-encoded sites) is the point of the map.

Source: Natural Earth (public domain, https://www.naturalearthdata.com),
fetched from the naturalearth/naturalearth-vector GitHub mirror at 1:50m.

Usage:
    python3 app/make_basemap.py            # regenerates 88_basemap_data.js
    python3 app/make_basemap.py --check    # verifies the committed file parses
                                           # and matches the schema (no network)

The generated file is committed (the app build must never need the
network); rerun this script only to refresh the geometry or change the
clip region, then reassemble the app.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "src" / "88_basemap_data.js"
NE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
LAYERS = {
    "land": "ne_50m_land.geojson",
    "countries": "ne_50m_admin_0_boundary_lines_land.geojson",
    "states": "ne_50m_admin_1_states_provinces_lines.geojson",
    "lakes": "ne_50m_lakes.geojson",
}
# lon0, lat0, lon1, lat1 : CONUS + Hawaii + Gulf + Caribbean, with margin
BBOX = (-180.0, 5.0, -50.0, 55.0)
Q = 100.0  # quantization: 2 decimals ~ 1.1 km


def fetch(name: str) -> dict:
    url = NE + name
    print(f"  fetching {url}")
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def inside(p, b):
    return b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3]


def clip_ring(ring, b):
    """Sutherland-Hodgman: clip one polygon ring to the bbox."""
    def clip_edge(pts, keep, intersect):
        out = []
        n = len(pts)
        for i in range(n):
            a, c = pts[i], pts[(i + 1) % n]
            ka, kc = keep(a), keep(c)
            if ka:
                out.append(a)
                if not kc:
                    out.append(intersect(a, c))
            elif kc:
                out.append(intersect(a, c))
        return out

    def x_at(a, c, x):
        t = (x - a[0]) / (c[0] - a[0])
        return [x, a[1] + t * (c[1] - a[1])]

    def y_at(a, c, y):
        t = (y - a[1]) / (c[1] - a[1])
        return [a[0] + t * (c[0] - a[0]), y]

    pts = ring
    pts = clip_edge(pts, lambda p: p[0] >= b[0], lambda a, c: x_at(a, c, b[0]))
    if not pts:
        return []
    pts = clip_edge(pts, lambda p: p[0] <= b[2], lambda a, c: x_at(a, c, b[2]))
    if not pts:
        return []
    pts = clip_edge(pts, lambda p: p[1] >= b[1], lambda a, c: y_at(a, c, b[1]))
    if not pts:
        return []
    pts = clip_edge(pts, lambda p: p[1] <= b[3], lambda a, c: y_at(a, c, b[3]))
    return pts


def clip_line(line, b):
    """Split a polyline into the pieces inside the bbox (with edge
    intersection points so borders meet the frame cleanly)."""
    def isect(a, c):
        # walk the segment toward the box one boundary at a time
        p, q = list(a), list(c)
        for _ in range(4):
            if inside(p, b):
                break
            if p[0] < b[0] and q[0] >= b[0]:
                t = (b[0] - p[0]) / (q[0] - p[0]); p = [b[0], p[1] + t * (q[1] - p[1])]
            elif p[0] > b[2] and q[0] <= b[2]:
                t = (b[2] - p[0]) / (q[0] - p[0]); p = [b[2], p[1] + t * (q[1] - p[1])]
            elif p[1] < b[1] and q[1] >= b[1]:
                t = (b[1] - p[1]) / (q[1] - p[1]); p = [p[0] + t * (q[0] - p[0]), b[1]]
            elif p[1] > b[3] and q[1] <= b[3]:
                t = (b[3] - p[1]) / (q[1] - p[1]); p = [p[0] + t * (q[0] - p[0]), b[3]]
            else:
                break
        return p
    pieces, cur = [], []
    for i, p in enumerate(line):
        if inside(p, b):
            if not cur and i > 0:
                cur.append(isect(line[i - 1], p))
            cur.append(p)
        else:
            if cur:
                cur.append(isect(p, cur[-1]))
                pieces.append(cur)
                cur = []
    if cur:
        pieces.append(cur)
    return pieces


def quantize(pts):
    out = []
    for p in pts:
        q = [round(p[0] * Q) / Q, round(p[1] * Q) / Q]
        if not out or q != out[-1]:
            out.append(q)
    return out


def poly_area(ring):
    s = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def process_polygons(gj, b):
    polys = []
    for f in gj["features"]:
        g = f["geometry"]
        if g is None:
            continue
        rings = []
        if g["type"] == "Polygon":
            rings = [g["coordinates"]]
        elif g["type"] == "MultiPolygon":
            rings = g["coordinates"]
        for poly in rings:
            outer = clip_ring(poly[0], b)
            if len(outer) < 4:
                continue
            outer = quantize(outer)
            if len(outer) < 4 or poly_area(outer) < 0.005:  # ~ (7 km)^2, drops islets
                continue
            holes = []
            for hole in poly[1:]:
                h = quantize(clip_ring(hole, b))
                if len(h) >= 4 and poly_area(h) >= 0.02:
                    holes.append(h + [h[0]])
            polys.append([outer + [outer[0]]] + holes)
    return polys


def process_lines(gj, b):
    lines = []
    for f in gj["features"]:
        g = f["geometry"]
        if g is None:
            continue
        coords = []
        if g["type"] == "LineString":
            coords = [g["coordinates"]]
        elif g["type"] == "MultiLineString":
            coords = g["coordinates"]
        for line in coords:
            for piece in clip_line(line, b):
                q = quantize(piece)
                if len(q) >= 2:
                    lines.append(q)
    return lines


def build() -> str:
    print("Building the offline basemap from Natural Earth 1:50m ...")
    land = process_polygons(fetch(LAYERS["land"]), BBOX)
    lakes = process_polygons(fetch(LAYERS["lakes"]), BBOX)
    countries = process_lines(fetch(LAYERS["countries"]), BBOX)
    states_raw = fetch(LAYERS["states"])
    # keep only the region's states/provinces (adm0 within the bbox anyway)
    states = process_lines(states_raw, BBOX)
    data = {
        "bbox": list(BBOX),
        "source": "Natural Earth 1:50m (public domain), naturalearth-vector GitHub mirror",
        "layers": {
            "land": {"type": "polygons", "coords": land},
            "lakes": {"type": "polygons", "coords": lakes},
            "countries": {"type": "lines", "coords": countries},
            "states": {"type": "lines", "coords": states},
        },
    }
    payload = json.dumps(data, separators=(",", ":"))
    assert "</scr" not in payload.lower()
    header = (
        "/* ============================================================\n"
        "   GENERATED FILE - DO NOT EDIT. Regenerate: python3 app/make_basemap.py\n"
        "   Offline basemap geometry for the climate map (Surface 3):\n"
        "   Natural Earth 1:50m land / lakes / country / state boundaries\n"
        "   (PUBLIC DOMAIN, naturalearthdata.com), clipped to the portfolio\n"
        "   region (lon %s..%s, lat %s..%s), quantized to 0.01 degrees.\n"
        "   Bundled so the map never depends on a tile service or any\n"
        "   network call: the basemap is orientation, CLAM's own hazard\n"
        "   and TCOR layers are the content.\n"
        "   ============================================================ */\n"
        % (BBOX[0], BBOX[2], BBOX[1], BBOX[3])
    )
    return header + "const CLAM_BASEMAP=" + payload + ";\n"


def main() -> int:
    if "--check" in sys.argv:
        if not OUT.exists():
            print(f"MISSING: {OUT}")
            return 1
        txt = OUT.read_text()
        payload = txt[txt.index("const CLAM_BASEMAP=") + len("const CLAM_BASEMAP="):].rstrip().rstrip(";")
        d = json.loads(payload)
        ok = all(k in d.get("layers", {}) for k in ("land", "lakes", "countries", "states"))
        print("ok  88_basemap_data.js parses" if ok else "FAIL: schema mismatch")
        return 0 if ok else 1
    OUT.write_text(build())
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
