"""
refresh_impacts.py  (Phase 5 : the results pack, step 1)
=========================================================

Companion to refresh_hazard.py. Where that script ships hazard INTENSITY for
the browser to score, this one runs the impact math over the FULL CLIMADA
event sets and ships the RESULTS: per-site expected annual damage, the
portfolio loss-exceedance curve, a direct-damage adaptation appraisal, and
Monte Carlo uncertainty bands. The browser app labels its own portfolio tail
an upper bound (it combines per-site return-period losses with a fixed
correlation); this pack computes the tail from per-EVENT losses summed across
sites first, which is the joint-tail number that label promises.

Scope, stated honestly
----------------------
* Domain: DIRECT damage to asset value for the acute perils (tc wind, cflood
  surge, rflood river flood, prain TC rainfall, wfire wildfire). Business
  interruption, chronic heat cost, and insurance layering stay in the app's
  financial layer, which reads this pack's direct-damage figures alongside
  its own model.
* Vulnerability: the app's exact curves, encoded here so pack and browser
  are attributable to the same math. Wind: Emanuel-type cubic sigmoid with
  V_THRESH=25.7, V_HALF=74.7 m/s, scaled by the site's construction and age
  factor. Flood: concave 1-exp(-0.6 x depth-over-freeboard) capped at 0.75,
  freeboard FB_COAST=1.1 m / FB_RIVER=0.6 m plus 0.5 m if defended.
* Combination rules (recorded in the meta sidecar):
    - wind + surge share one event catalog (surge is derived from the same
      TC events), so their losses add PER EVENT: truly joint.
    - river flood is an independent catalog; its exceedance losses add to
      the wind+surge curve at equal return periods (comonotonic, an upper
      bound on that pairing only).
    - TC rainfall is an independent catalog per basin domain; wildfire is a
      per-site occurrence process on the WRC point burn probability (Task
      3.5). Both add comonotonically, and wildfire's warming signal scales
      the arrival probability, not the loss given fire.
    - countries are independent catalogs; combined the same comonotonic way.
* Impact arithmetic: per-event site losses = value x damage_fraction(nearest
  centroid intensity), exceedance from event losses and frequencies. For
  point exposures with one asset per site this is the same arithmetic as
  CLIMADA's ImpactCalc/eai_exp/calc_freq_curve, implemented directly so the
  parity tests in tests/ can pin every step without a CLIMADA install.
* Uncertainty: seeded Monte Carlo over hazard intensity (+-8%), damage-curve
  steepness (-30/+40%), and asset values (+-15%): the same three physical
  factors the app's tornado sweeps, sampled jointly instead of one at a
  time. The unsequa Saltelli/Sobol upgrade slots behind run_uncertainty().
* Adaptation: the app's three hazard-touching measures at their default
  settings (wind hardening to 65% residual damage, +0.5 m dry floodproofing,
  0.3 m coastal buffer), appraised as averted direct AAL with a 25-year
  annuity at a 3% discount rate. The ops and cooling measures act on the
  financial layer and remain app-side.

Output
------
    results_pack.json        the pack (schema: pack_version 1, kind
                             "results_pack"; see build_pack())
    results_pack_meta.json   provenance sidecar, same convention as the
                             other producers

Usage
-----
    conda activate climada_env
    python refresh_impacts.py --sites sites.csv
    python validate_pack.py results_pack.json

sites.csv columns (the app's site template): name, latitude, longitude,
asset_value_usd, and optionally brand, country (ISO3, default USA),
construction (frame|masonry|engineered), year_built, defended (true/false).
Keep real site files out of version control; sites_template.csv shows the
schema.
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import assumptions
import refresh_hazard as rh
import refresh_prain as rpn
import refresh_wildfire as rw

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
LOG = logging.getLogger("refresh_impacts")

# ---------------------------------------------------------------------------
# Constants that MIRROR the app. If you change one side, change both.
# ---------------------------------------------------------------------------

RPS = rh.RETURN_PERIODS                      # [10, 25, 50, 100, 250, 500]
V_THRESH, V_HALF = 25.7, 74.7                # m/s, Emanuel-type wind curve
FB_COAST, FB_RIVER = 1.1, 0.6                # m freeboard by flood peril
CONSTR_FACTOR = {"frame": 1.3, "masonry": 1.0, "engineered": 0.75}
MAX_SNAP_KM = 200.0                          # the app's nearest-cell limit
SNAP_TOL_KM = 10.0                           # cell-scale slack for water layers

# BCR appraisal settings (recorded in the pack): the ONE convention shared
# with the app's slider defaults, from the single sourced registry
DISCOUNT_RATE, HORIZON_YEARS = assumptions.appraisal_defaults()

# the app's hazard-touching measures at their default slider settings
MEASURES = [
    {"key": "wind", "name": "Wind hardening (roofs & openings)",
     "dmg_mult": 0.65, "cost_pct_value": 1.0, "scope": "all"},
    {"key": "flood", "name": "Dry floodproofing & utility elevation",
     "fb_bonus": 0.5, "cost_pct_value": 0.6, "scope": "flood"},
    {"key": "buffer", "name": "Coastal buffer (dune & mangrove)",
     "depth_red": 0.3, "cost_pct_value": 0.4, "scope": "coastal"},
]
SCOPE_EAD_USD = 100.0        # a peril is "exposed" above this EAD, as in the app

MC_FACTORS = [               # jointly sampled; bounds mirror the app's tornado
    {"key": "haz", "label": "Hazard intensity +-8%", "lo": 0.92, "hi": 1.08},
    {"key": "dmg", "label": "Damage-curve steepness -30/+40%", "lo": 0.70, "hi": 1.40},
    {"key": "exp", "label": "Asset values +-15%", "lo": 0.85, "hi": 1.15},
]
UNCERTAINTY_SCENARIOS = ["present", "ssp245_2050", "ssp585_2080"]

# increment 3 damage constants. MIRROR the app's values; change both.
# The flat FIRE_MDD=0.6 is RETIRED (Task 3.5): the conditional damage ratio
# now comes per site from the WRC flame-length layer (or the registry's
# capped interim ratio), carried in prep["wfire"]["cond"].
FIRE_COND_INTERIM = assumptions.scalar("fire_cond_interim")
FIRE_ROOF_A = 0.6                 # fire vulnerability factor: Class A roof
FIRE_DEFENSIBLE = 0.7             # fire vulnerability factor: space >= 30 m
# TC-rainfall ponding transform: single sourced in assumptions.py (v3
# recalibration). Mirrors the app's generated 05_assumptions.js constants.
PRAIN_DRAIN_MM = assumptions.scalar("prain_drain_mm")
PRAIN_POND_COEFF = assumptions.scalar("prain_pond_coeff")
PRAIN_FB = assumptions.scalar("prain_fb_m")
# FLOPROS / protection embedding: mirrors the app's RFLOOD_GRID_INCLUDES_PROTECTION.
# Flip BOTH when the served ISIMIP river_flood sets are confirmed to embed
# protection standards (see RUNBOOK). Default false = apply FB_RIVER freeboard.
RFLOOD_GRID_INCLUDES_PROTECTION = False


def fb_river_m():
    """Riverine freeboard used by the pack; 0 when the grid already embeds
    protection, else FB_RIVER. Keeps pack and app from diverging on FLOPROS."""
    return 0.0 if RFLOOD_GRID_INCLUDES_PROTECTION else FB_RIVER


# ---------------------------------------------------------------------------
# Pure impact math (no CLIMADA imports: unit-tested in test_impactops.py)
# ---------------------------------------------------------------------------

def emanuel_mdd(v, dmg_mult=1.0, v_half=V_HALF):
    """Mean damage ratio for wind speed v (m/s), the app's exact curve.
    v_half is exposed for the backtest calibration; the default is the
    app's constant."""
    v = np.asarray(v, dtype=float)
    vt = np.maximum((v - V_THRESH) / (v_half - V_THRESH), 0.0)
    c = vt ** 3
    return np.minimum(c / (1.0 + c) * dmg_mult, 1.0)


def flood_mdd(d, fb, cap=0.75):
    """Mean damage ratio for water depth d (m) over freeboard fb (m), capped
    at `cap` (0.75 published; lower when critical systems are elevated)."""
    e = np.asarray(d, dtype=float) - fb
    return np.where(e <= 0.0, 0.0, np.minimum(cap, 1.0 - np.exp(-0.6 * e)))


def vuln_of(construction=None, year_built=None, defended=False):
    """(wind damage multiplier, freeboard bonus m), the app's vulnOf."""
    w = 1.0
    c = str(construction or "").lower()
    if c in CONSTR_FACTOR:
        w *= CONSTR_FACTOR[c]
    try:
        y = float(year_built)
    except (TypeError, ValueError):
        y = float("nan")
    if np.isfinite(y) and y > 1800:
        w *= 1.15 if y < 1995 else (0.9 if y >= 2010 else 1.0)
    return min(max(w, 0.5), 1.6), (0.5 if defended else 0.0)


# --- profile schema v2: documented factor table ------------------------------
# Screening-grade factors; every value is a named constant so the Method copy
# can cite them. A site with NO v2 fields reproduces vuln_of exactly (pinned
# by tests), so a six-field sites.csv keeps yielding today's numbers.
ROOF_TYPE_FACTOR = {"shingle": 1.1, "metal": 0.85, "tile": 0.95,
                    "membrane": 0.95}
ROOF_AGE_REF_YEAR = 2026          # deterministic reference for roof age bands
ROOF_AGE_FACTOR = ((10, 0.9), (20, 1.0), (10**9, 1.2))   # (age <= N, factor)
OPENING_FACTOR = {"impact": 0.85, "partial": 0.95, "none": 1.05}
FIRST_FLOOR_MAX_M = 3.0           # sanity cap on measured first-floor height
EQUIP_ELEV_FLOOD_CAP = 0.5        # flood MDD cap with elevated critical systems
FLOOD_CAP_DEFAULT = 0.75          # the published curve's cap


def _txt(x):
    """Lowercased text or None for genuinely-missing values. The literal
    string "none" is a REAL value (opening_protection's vocabulary), so only
    the None object, NaN, and empty/nan strings count as missing."""
    if x is None:
        return None
    if isinstance(x, float) and not np.isfinite(x):
        return None
    s = str(x).strip().lower()
    return s if s and s != "nan" else None


def _num(x):
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def vuln_v2(construction=None, year_built=None, defended=False,
            roof_type=None, roof_year=None, opening_protection=None,
            first_floor_elev_m=None, equipment_elevated=False):
    """(wind multiplier, freeboard bonus m, flood MDD cap).

    Wind: construction factor, then EITHER the roof-and-openings factors when
    any of those fields is present (roof detail supersedes the coarse
    year-built proxy, which would double-count roof age) OR the legacy
    year-built factor. Absent fields are neutral (1.0), never penalising.
    Flood: a measured first-floor height (clipped to FIRST_FLOOR_MAX_M)
    supersedes the coarse `defended` 0.5 m proxy; elevated critical systems
    cap the flood damage ratio at EQUIP_ELEV_FLOOD_CAP instead of 0.75.
    """
    rt, op = _txt(roof_type), _txt(opening_protection)
    ry = _num(roof_year)
    roofish = rt is not None or ry is not None or op is not None
    if roofish:
        w = CONSTR_FACTOR.get(str(construction or "").lower(), 1.0)
        if rt in ROOF_TYPE_FACTOR:
            w *= ROOF_TYPE_FACTOR[rt]
        if ry is not None and ry > 1800:
            age = max(ROOF_AGE_REF_YEAR - ry, 0)
            w *= next(f for lim, f in ROOF_AGE_FACTOR if age <= lim)
        if op in OPENING_FACTOR:
            w *= OPENING_FACTOR[op]
        wind_mult = min(max(w, 0.5), 1.6)
    else:
        wind_mult = vuln_of(construction, year_built, defended)[0]

    ffe = _num(first_floor_elev_m)
    if ffe is not None and ffe >= 0:
        fb_bonus = min(ffe, FIRST_FLOOR_MAX_M)
    else:
        fb_bonus = 0.5 if defended else 0.0
    cap = EQUIP_ELEV_FLOOD_CAP if equipment_elevated else FLOOD_CAP_DEFAULT
    return wind_mult, fb_bonus, cap


RELIEF_CLAMP_M = 10.0     # sanity clamp on site-vs-cell ground relief (m)


def site_relief(ground_elev_m, cell_ground_elev_m):
    """(relief m, has_elevation mask) per site. Relief = site ground minus
    the hazard cell's mean ground: the number that converts depth AT THE
    CELL into depth AT THE STRUCTURE. Both fields must be present (survey or
    enrich_sites.py --dem); otherwise relief is 0 and the site is flagged
    modeled-coarse rather than silently treated as refined."""
    ge = pd.to_numeric(pd.Series(ground_elev_m), errors="coerce").to_numpy(float)
    ce = pd.to_numeric(pd.Series(cell_ground_elev_m), errors="coerce").to_numpy(float)
    has = np.isfinite(ge) & np.isfinite(ce)
    relief = np.where(has, np.clip(ge - ce, -RELIEF_CLAMP_M, RELIEF_CLAMP_M), 0.0)
    return relief, has


def depth_at_structure(depth, relief):
    """Adjust cell water depth to the structure's ground: wet cells shift by
    the site's relief (positive = site sits above the cell mean = shallower;
    negative = a low spot = deeper). DRY CELLS STAY DRY: a below-cell-mean
    site cannot conjure water the flood model did not put in the cell."""
    d = np.asarray(depth, float)
    r = np.asarray(relief, float)
    return np.where(d > 0, np.maximum(d - r, 0.0), 0.0)


def archetype_arrays(rows):
    """(v_half, fb_add_m, cap_override) per-site arrays from the archetype
    field (profile schema v2). The archetype acts on the CURVES: v_half
    shifts the wind curve, fb_add_m moves the effective flood freeboard,
    cap_override replaces the flood damage cap (site-measured
    equipment_elevated still wins downward). Absent/unknown archetypes are
    the default (the published curve): existing profiles reproduce today's
    numbers exactly."""
    arch = [assumptions.archetype_of(r.get("archetype")) for r in rows]
    v_half = np.array([V_HALF * a["v_half_mult"] for a in arch])
    fb_add = np.array([a["fb_add_m"] for a in arch])
    cap_o = np.array([np.nan if a["flood_cap"] is None else a["flood_cap"]
                      for a in arch])
    return v_half, fb_add, cap_o


def compose_flood_cap(cap_profile, cap_override, equipment_elevated):
    """Effective flood MDD cap: the profile's own cap when the archetype is
    silent; else the archetype's cap, except that a site-measured elevated
    plant (equipment_elevated) still caps DOWNWARD (site data beats
    archetype)."""
    cap_profile = np.asarray(cap_profile, float)
    cap_override = np.asarray(cap_override, float)
    ee = np.asarray(equipment_elevated, bool)
    out = np.where(np.isnan(cap_override), cap_profile,
                   np.where(ee, np.minimum(cap_override, cap_profile),
                            cap_override))
    return out


def fire_vuln_of(roof_class_a=False, defensible_space_m=None):
    """Fire vulnerability multiplier from the wildfire profile fields,
    the app's fireVulnMult mirrored."""
    m = 1.0
    if roof_class_a:
        m *= FIRE_ROOF_A
    ds = _num(defensible_space_m)
    if ds is not None and ds >= 30:
        m *= FIRE_DEFENSIBLE
    return m


def nearest_centroids(site_lat, site_lon, cen_lat, cen_lon, max_km=MAX_SNAP_KM):
    """Nearest-centroid index per site, with the app's distance guard.

    Returns (idx array, dist_km array); sites beyond max_km get idx -1 and
    score zero for that hazard (for wind, the pack also records them as
    skipped; for the water layers, zero IS the intended value, exactly the
    explicit inland zeros align_to_cells writes into the hazard grid).
    """
    sla = np.radians(np.asarray(site_lat, float))[:, None]
    slo = np.radians(np.asarray(site_lon, float))[:, None]
    cla = np.radians(np.asarray(cen_lat, float))[None, :]
    clo = np.radians(np.asarray(cen_lon, float))[None, :]
    dlat = cla - sla
    dlon = clo - slo
    a = np.sin(dlat / 2) ** 2 + np.cos(sla) * np.cos(cla) * np.sin(dlon / 2) ** 2
    d_km = 2 * 6371.0 * np.arcsin(np.sqrt(np.minimum(a, 1.0)))
    idx = d_km.argmin(axis=1)
    dist = d_km[np.arange(len(idx)), idx]
    idx = np.where(dist <= max_km, idx, -1)
    return idx, dist


def water_snap(site_lat, site_lon, cen_lat, cen_lon, wind_dist_km):
    """Snap sites to a WATER layer's centroids (surge or river flood).

    Petals may subset surge centroids to the coastal band, and flood sets
    can be served wet-cells-only, so the 200 km wind guard is far too loose
    here: an inland site 100 km from the coast would inherit the nearest
    coastal cell's depth. The guard the hazard-grid pipeline gets from
    align_to_cells (explicit zeros on the full wind grid) is reproduced by
    accepting the snap only within cell scale of where the site's WIND cell
    is: nearest water centroid no further than the site's wind-centroid
    distance plus SNAP_TOL_KM. Beyond that, the layer is silent about the
    site's cell and the correct depth is zero.
    """
    idx, dist = nearest_centroids(site_lat, site_lon, cen_lat, cen_lon)
    ref = np.asarray(wind_dist_km, float) if wind_dist_km is not None \
        else np.zeros(len(idx))
    limit = np.maximum(ref + SNAP_TOL_KM, SNAP_TOL_KM)
    return np.where(dist <= limit, idx, -1)


def site_intensity(haz, idx):
    """[n_events x n_sites] intensity at each site's nearest centroid.
    Sites with idx -1 (outside coverage) get zero intensity."""
    inten = haz.intensity
    take = np.where(idx < 0, 0, idx)
    cols = inten[:, take]
    arr = cols.toarray() if hasattr(cols, "toarray") else np.asarray(cols, float)
    arr = arr.astype(float, copy=False)
    arr[:, idx < 0] = 0.0
    return arr


def ep_curve(event_losses, freq, rps=tuple(RPS)):
    """Loss exceeded at each return period, from per-event losses.

    Events sorted by loss descending; exceedance frequency is the cumulative
    event frequency; return period is its reciprocal. Requested RPs are
    interpolated linearly in log(RP) and edge-clamped, so the tail beyond
    the largest simulated return period stays flat (conservative-low, and
    recorded as a method note rather than extrapolated silently).
    """
    losses = np.asarray(event_losses, dtype=float)
    freq = np.asarray(freq, dtype=float)
    keep = freq > 0                      # zero-frequency events carry no
    losses, freq = losses[keep], freq[keep]   # exceedance and would poison 1/cum
    if not len(losses):
        return {rp: 0.0 for rp in rps}
    order = np.argsort(losses)[::-1]
    l_desc = losses[order]
    cum = np.cumsum(freq[order])
    pos = l_desc > 0
    if not pos.any():
        return {rp: 0.0 for rp in rps}
    rp_pts = 1.0 / cum[pos]
    l_pts = l_desc[pos]
    asc = np.argsort(rp_pts)
    rp_asc, l_asc = rp_pts[asc], l_pts[asc]
    out = np.interp(np.log(np.asarray(rps, float)), np.log(rp_asc), l_asc)
    lo = np.asarray(rps, float) < rp_asc[0]
    out[lo] = 0.0                       # rarer-than-nothing end: no exceedance yet
    return {rp: float(x) for rp, x in zip(rps, out)}


def site_ead(losses, freq):
    """Frequency-weighted expected annual damage per site (eai_exp)."""
    return (np.asarray(losses, float) * np.asarray(freq, float)[:, None]).sum(axis=0)


SITE_RPS = (100, 250)      # per-site return periods surfaced beside the EAD

# TCOR overhaul Task A (pipeline prerequisite): the pack now carries the
# per-event, per-site loss table for the joint wind+surge catalog (the hard
# dependency for the shared per-occurrence hurricane deductible) plus
# per-site frequent-loss ladders down to 1-in-2, so the app's retained-loss
# and attritional-frequency math consumes event outputs instead of
# re-deriving hazard science.
LADDER_RPS = (2, 5, 10, 25, 50, 100, 250, 500)   # 1/RP = annual exceedance
EVENT_FLOOR_USD = 1000.0   # site-event entries below this are dropped
                           # (recorded; far below the smallest deductible)


def site_rp_losses(losses, freq, rps=SITE_RPS):
    """{rp: per-site loss} at the requested return periods: each site's OWN
    exceedance over the catalog's events. Step lookup (the loss of the
    least-severe event at which the site's cumulative event frequency
    reaches 1/RP; zero when it never does), vectorized across sites; the
    step convention is recorded in the pack meta."""
    L = np.asarray(losses, float)
    f = np.asarray(freq, float)
    keep = f > 0
    L, f = L[keep], f[keep]
    n = L.shape[1] if L.ndim == 2 else 0
    if not L.size:
        return {rp: np.zeros(n) for rp in rps}
    order = np.argsort(-L, axis=0, kind="stable")
    l_desc = np.take_along_axis(L, order, axis=0)
    cum = np.cumsum(f[order], axis=0)
    out = {}
    for rp in rps:
        hit = cum >= (1.0 / rp) - 1e-12
        first = hit.argmax(axis=0)
        vals = np.take_along_axis(l_desc, first[None, :], axis=0)[0]
        out[rp] = np.where(hit.any(axis=0), vals, 0.0)
    return out


def _rp_zero(n, rps=SITE_RPS):
    return {rp: np.zeros(n) for rp in rps}


def _rp_add(a, b):
    return {rp: a[rp] + b[rp] for rp in a}


def _rp_scale(a, k):
    return {rp: a[rp] * k for rp in a}


def blend_results(parts):
    """Weighted mean of per-source result dicts {aal, ep{rp}, ead[site]},
    with weight renormalisation over the members present (the same graceful
    degradation blend_grids applies to the hazard grid)."""
    if not parts:
        return None
    wsum = sum(w for w, _ in parts)
    out = {"aal": 0.0,
           "ep": {rp: 0.0 for rp in RPS},
           "ead": np.zeros_like(np.asarray(parts[0][1]["ead"], float))}
    for w, r in parts:
        f = w / wsum
        out["aal"] += f * r["aal"]
        for rp in RPS:
            out["ep"][rp] += f * r["ep"][rp]
        out["ead"] = out["ead"] + f * np.asarray(r["ead"], float)
    return out


def add_ep(a, b):
    """Comonotonic combination: exceedance losses add at equal return
    periods. An upper bound for independent catalogs; recorded in meta."""
    return {rp: a.get(rp, 0.0) + b.get(rp, 0.0) for rp in RPS}


# ---------------------------------------------------------------------------
# TCOR event outputs (pure; unit-tested in test_impactops.py)
# ---------------------------------------------------------------------------

def sparse_event_rows(losses, freq, event_names, skey,
                      floor_usd=EVENT_FLOOR_USD, site_offset=0):
    """[events x sites] losses -> sparse per-event rows for the pack.

    Each kept event carries a stable id (the catalog's event name when the
    hazard provides one, else "<source>:<index>"), its annual frequency, and
    [site_index, loss_usd] pairs for every site at or above the floor. Events
    with zero frequency or no site above the floor are dropped; the floor is
    recorded pack-side so the validator can bound what the drop cost."""
    L = np.asarray(losses, float)
    f = np.asarray(freq, float)
    rows = []
    for i in range(L.shape[0]):
        if f[i] <= 0:
            continue
        j = np.where(L[i] >= floor_usd)[0]
        if not len(j):
            continue
        name = None
        if event_names is not None and i < len(event_names):
            name = str(event_names[i]).strip() or None
        rows.append({"id": name if name else f"{skey}:{i}",
                     "freq": float(f[i]),
                     "sites": [[int(site_offset + jj), round(float(L[i, jj]), 2)]
                               for jj in j]})
    return rows


def build_event_sets(prep, app_key, values, wind_mult, fb_coast,
                     flood_cap=None, v_half=None,
                     floor_usd=EVENT_FLOOR_USD, site_offset=0):
    """Per-event, per-site JOINT wind+surge losses for one scenario.

    The wind sources in the scenario recipe are ALTERNATIVE catalogs blended
    by weight (exactly blend_results' rule), so each source keeps its own
    event list and normalized weight: a consumer computes any event-level
    statistic (per-occurrence retained loss above all) per source and then
    weight-averages. Events are NEVER merged across sources; wind and surge
    inside one source share the catalog, so their losses add per event
    (truly joint), which is what the shared hurricane deductible needs."""
    recipe = rh.APP_SCENARIOS[app_key]
    parts = []
    for w, src in recipe:
        skey = rh.source_key(src)
        wnd = prep["wind"].get(skey)
        if wnd is None:
            continue
        wl = wind_losses(wnd["int"], values, wind_mult,
                         v_half=V_HALF if v_half is None else v_half)
        sg = prep["surge"].get((skey, app_key))
        combined = wl
        if sg is not None:
            combined = wl + flood_losses(sg["int"], values, fb_coast,
                                         cap=flood_cap)
        rows = sparse_event_rows(combined, wnd["freq"], wnd.get("event_name"),
                                 skey, floor_usd, site_offset)
        kept = sum(e["freq"] * sum(l for _j, l in e["sites"]) for e in rows)
        parts.append({"source": skey, "weight": float(w),
                      "aal_usd": round(float(site_ead(combined,
                                                      wnd["freq"]).sum()), 2),
                      "kept_aal_usd": round(float(kept), 2),
                      "events": rows})
    if not parts:
        return None
    wsum = sum(p["weight"] for p in parts)
    for p in parts:
        p["weight"] = round(p["weight"] / wsum, 6)
    return parts


def build_frequent_ladders(prep, app_key, values, wind_mult, fb_coast,
                           fb_river, flood_cap=None, fb_prain=None,
                           fire_vuln=None, v_half=None, haz_warm=None):
    """Per-site loss ladders at LADDER_RPS (down to 1-in-2) per peril.

    The attritional layer lives in events more frequent than 1-in-10, which
    SITE_RPS never reached; these ladders extend each site's own exceedance
    into that band so per-location deductible math (general property, flood)
    can integrate the frequent hits without re-deriving hazard science.
    Combination rules mirror eval_scenario exactly: wind sources blend by
    weight, river members average, rain domains add per site (each site
    belongs to one domain), wildfire is its own arrival process. `tc_joint`
    is the same-catalog wind+surge sum (the hurricane occurrence basis);
    `tc` and `cflood` are the components, kept so a consumer that classes
    surge under the flood deductible instead can do so."""
    vals = values
    recipe = rh.APP_SCENARIOS[app_key]
    zero = lambda: {rp: np.zeros(len(vals)) for rp in LADDER_RPS}
    out = {}

    w_parts, s_parts, j_parts = [], [], []
    for w, src in recipe:
        skey = rh.source_key(src)
        wnd = prep["wind"].get(skey)
        if wnd is None:
            continue
        wl = wind_losses(wnd["int"], vals, wind_mult,
                         v_half=V_HALF if v_half is None else v_half)
        w_parts.append((w, site_rp_losses(wl, wnd["freq"], rps=LADDER_RPS)))
        sg = prep["surge"].get((skey, app_key))
        combined = wl
        if sg is not None:
            sl = flood_losses(sg["int"], vals, fb_coast, cap=flood_cap)
            s_parts.append((w, site_rp_losses(sl, wnd["freq"],
                                              rps=LADDER_RPS)))
            combined = wl + sl
        else:
            s_parts.append((w, zero()))
        j_parts.append((w, site_rp_losses(combined, wnd["freq"],
                                          rps=LADDER_RPS)))

    def _blend(parts):
        if not parts:
            return None
        wsum = sum(w for w, _ in parts)
        acc = zero()
        for w, r in parts:
            acc = _rp_add(acc, _rp_scale(r, w / wsum))
        return acc

    out["tc"] = _blend(w_parts)
    out["cflood"] = _blend(s_parts)
    out["tc_joint"] = _blend(j_parts)

    members = prep["rflood"].get(app_key) or []
    if members:
        acc = zero()
        for m in members:
            rl = flood_losses(m["int"], vals, fb_river, cap=flood_cap)
            acc = _rp_add(acc, _rp_scale(site_rp_losses(rl, m["freq"],
                                                        rps=LADDER_RPS),
                                         1.0 / len(members)))
        out["rflood"] = acc

    pw = prep.get("prain")
    if pw is not None:
        warm = 0.0 if haz_warm is None else haz_warm
        rain_members = [pw] if isinstance(pw, dict) else pw
        acc = zero()
        for pm in rain_members:
            mm = pm["int"] * (1.0 + rpn.PRAIN_CC_PER_C * warm)
            depth = np.maximum(mm - PRAIN_DRAIN_MM, 0.0) / 1000.0 \
                * PRAIN_POND_COEFF
            fbp = (np.full_like(vals, PRAIN_FB) if fb_prain is None
                   else fb_prain)
            pl = flood_losses(depth, vals, fbp, cap=flood_cap)
            acc = _rp_add(acc, site_rp_losses(pl, pm["freq"],
                                              rps=LADDER_RPS))
        out["prain"] = acc

    fw = prep.get("wfire")
    if fw is not None:
        warm = 0.0 if haz_warm is None else haz_warm
        fv = np.ones_like(vals) if fire_vuln is None else np.asarray(fire_vuln)
        p = np.minimum(np.asarray(fw["bp"], float)
                       * (1.0 + rw.FIRE_WARMING_UPLIFT * warm), 1.0)
        frac = np.minimum(np.asarray(fw["cond"], float) * fv, 1.0)
        lgf = frac * vals
        out["wfire"] = {rp: np.where(p >= 1.0 / rp, lgf, 0.0)
                        for rp in LADDER_RPS}

    return {k: v for k, v in out.items() if v is not None} or None


def annuity(years, rate):
    t = np.arange(1, years + 1)
    return float((1.0 / (1.0 + rate) ** t).sum())


def wind_losses(wind_int, values, wind_mult, dmg_scale=1.0, haz_mult=1.0,
                v_half=V_HALF):
    """[events x sites] direct wind losses."""
    frac = emanuel_mdd(wind_int * haz_mult, dmg_mult=1.0, v_half=v_half)
    frac = np.minimum(frac * wind_mult[None, :] * dmg_scale, 1.0)
    return frac * values[None, :]


def flood_losses(depth, values, freeboard, dmg_scale=1.0, haz_mult=1.0,
                 depth_red=0.0, cap=None):
    """[events x sites] direct flood losses (surge or river). `cap` is the
    per-site flood MDD cap array (None means the published 0.75).

    Vectorized over sites: this is exactly flood_mdd applied column by column,
    written as one broadcast so the hot adaptation and Monte-Carlo paths avoid a
    per-site Python loop. Bit-identical to stacking flood_mdd(d[:, j], fb[j],
    cap[j]) across sites; freeboard and caps broadcast over the event axis."""
    d = np.maximum(np.asarray(depth, float) * haz_mult - depth_red, 0.0)
    caps = (np.full(d.shape[1], FLOOD_CAP_DEFAULT) if cap is None
            else np.asarray(cap, float))
    e = d - np.asarray(freeboard, float)
    frac = np.where(e <= 0.0, 0.0, np.minimum(caps, 1.0 - np.exp(-0.6 * e)))
    frac = np.minimum(frac * dmg_scale, 1.0)
    return frac * values[None, :]


# ---------------------------------------------------------------------------
# Scenario evaluation over prepared per-site intensity matrices (pure)
# ---------------------------------------------------------------------------

def eval_scenario(prep, app_key, values, wind_mult, fb_coast, fb_river,
                  dmg_scale=1.0, haz_mult=1.0, exp_mult=1.0,
                  wind_dmg_mult=1.0, fb_bonus=0.0, cf_depth_red=0.0,
                  flood_cap=None, fb_prain=None, fire_vuln=None,
                  fire_mult=1.0, v_half=None, site_rp=False):
    """One scenario's portfolio result from prepared intensities.

    `prep` is the pure data structure build_country_prep() returns:
      wind[skey]   = {"freq", "int"}            events x sites wind speed
      surge[(skey, app_key)] = {"int"}          events x sites depth (same events)
      rflood[app_key] = [{"freq", "int"}, ...]  ensemble members
    Measure and uncertainty knobs enter here so adaptation and Monte Carlo
    reuse one code path (the app's adaptedFinSite does the same).
    """
    vals = values * exp_mult
    recipe = rh.APP_SCENARIOS[app_key]

    ws_parts, w_parts, s_parts, ws_rp_parts = [], [], [], []
    for w, src in recipe:
        skey = rh.source_key(src)
        if skey not in prep["wind"]:
            continue
        wnd = prep["wind"][skey]
        wl = wind_losses(wnd["int"], vals, wind_mult * wind_dmg_mult,
                         dmg_scale, haz_mult,
                         v_half=V_HALF if v_half is None else v_half)
        w_parts.append((w, {"aal": float(site_ead(wl, wnd["freq"]).sum()),
                            "ep": ep_curve(wl.sum(axis=1), wnd["freq"]),
                            "ead": site_ead(wl, wnd["freq"])}))
        combined = wl
        sg = prep["surge"].get((skey, app_key))
        if sg is not None:
            sl = flood_losses(sg["int"], vals, fb_coast + fb_bonus,
                              dmg_scale, haz_mult, depth_red=cf_depth_red,
                              cap=flood_cap)
            s_parts.append((w, {"aal": float(site_ead(sl, wnd["freq"]).sum()),
                                "ep": ep_curve(sl.sum(axis=1), wnd["freq"]),
                                "ead": site_ead(sl, wnd["freq"])}))
            combined = wl + sl          # same event catalog: truly joint
        else:
            # surge failed or is disabled for this source: the joint carries
            # it at zero, so the surge blend must carry an explicit zero part
            # with the SAME weight, or renormalisation would over-weight the
            # surviving member and tc + cflood would no longer reconcile
            # with acute
            s_parts.append((w, {"aal": 0.0, "ep": {rp: 0.0 for rp in RPS},
                                "ead": np.zeros_like(vals)}))
        ws_parts.append((w, {"aal": float(site_ead(combined, wnd["freq"]).sum()),
                             "ep": ep_curve(combined.sum(axis=1), wnd["freq"]),
                             "ead": site_ead(combined, wnd["freq"])}))
        if site_rp:
            ws_rp_parts.append((w, site_rp_losses(combined, wnd["freq"])))

    wind = blend_results(w_parts)
    surge = blend_results(s_parts)
    joint = blend_results(ws_parts)
    joint_rp = None
    if site_rp and ws_rp_parts:
        wsum = sum(w for w, _ in ws_rp_parts)
        joint_rp = _rp_zero(len(vals))
        for w, r_ in ws_rp_parts:
            joint_rp = _rp_add(joint_rp, _rp_scale(r_, w / wsum))

    river = None
    river_rp = None
    members = prep["rflood"].get(app_key) or []
    if members:
        mparts = []
        for m in members:
            rl = flood_losses(m["int"], vals, fb_river + fb_bonus,
                              dmg_scale, haz_mult, cap=flood_cap)
            mparts.append((1.0 / len(members),
                           {"aal": float(site_ead(rl, m["freq"]).sum()),
                            "ep": ep_curve(rl.sum(axis=1), m["freq"]),
                            "ead": site_ead(rl, m["freq"])}))
            if site_rp:
                mr = _rp_scale(site_rp_losses(rl, m["freq"]),
                               1.0 / len(members))
                river_rp = mr if river_rp is None else _rp_add(river_rp, mr)
        river = blend_results(mparts)

    warm = rw.WARMING.get(app_key, 0.0)

    rain = None
    rain_rp = None
    pw = prep.get("prain")
    if pw is not None:
        # one member per basin domain (a lone dict is the legacy one-domain
        # shape). Each site belongs to exactly one domain, so per-site EADs
        # simply add; portfolio exceedance adds comonotonically across the
        # independent domain catalogs, the same rule countries follow.
        rain_members = [pw] if isinstance(pw, dict) else pw
        rain = {"aal": 0.0, "ep": {rp: 0.0 for rp in RPS},
                "ead": np.zeros_like(vals)}
        rain_rp = _rp_zero(len(vals)) if site_rp else None
        for pm in rain_members:
            # scenario scaling by Clausius-Clapeyron on the rain field itself,
            # then the documented drainage conversion (mirrors the app exactly)
            mm = pm["int"] * (1.0 + rpn.PRAIN_CC_PER_C * warm) * haz_mult
            depth = np.maximum(mm - PRAIN_DRAIN_MM, 0.0) / 1000.0 * PRAIN_POND_COEFF
            fbp = (np.full_like(vals, PRAIN_FB) if fb_prain is None else fb_prain)                 + fb_bonus
            pl = flood_losses(depth, vals, fbp, dmg_scale, 1.0, cap=flood_cap)
            rain["aal"] += float(site_ead(pl, pm["freq"]).sum())
            rain["ep"] = add_ep(rain["ep"], ep_curve(pl.sum(axis=1), pm["freq"]))
            rain["ead"] = rain["ead"] + site_ead(pl, pm["freq"])
            if site_rp:
                rain_rp = _rp_add(rain_rp, site_rp_losses(pl, pm["freq"]))

    fire = None
    fw = prep.get("wfire")
    if fw is not None:
        # point-probability math (Task 3.5): each site's fire is its own
        # arrival process at the WRC point burn probability, with loss given
        # fire = value x flame-length-conditioned damage x profile
        # vulnerability. Warming scales the arrival PROBABILITY (capped at
        # 1), not the loss. The portfolio curve is the per-site occurrence
        # exceedance over these independent arrivals (recorded in meta).
        fv = np.ones_like(vals) if fire_vuln is None else np.asarray(fire_vuln)
        p = np.minimum(np.asarray(fw["bp"], float) * haz_mult
                       * (1.0 + rw.FIRE_WARMING_UPLIFT * warm), 1.0)
        frac = np.minimum(np.asarray(fw["cond"], float) * fv * dmg_scale
                          * fire_mult, 1.0)
        loss_given_fire = frac * vals
        fire = {"aal": float((p * loss_given_fire).sum()),
                "ep": ep_curve(loss_given_fire, p),
                "ead": p * loss_given_fire}
        if site_rp:
            fire["_site_rp"] = {rp: np.where(p >= 1.0 / rp, loss_given_fire,
                                             0.0) for rp in SITE_RPS}

    if joint is None and river is None and rain is None and fire is None:
        return None
    zero = lambda: {"aal": 0.0, "ep": {rp: 0.0 for rp in RPS},
                    "ead": np.zeros_like(vals)}
    fire_rp = (fire or {}).pop("_site_rp", None) if fire else None
    joint = joint or zero()
    river = river or zero()
    rain = rain or zero()
    fire = fire or zero()
    acute_ep = add_ep(add_ep(add_ep(joint["ep"], river["ep"]),
                             rain["ep"]), fire["ep"])
    out = {
        "tc": wind or zero(),
        "cflood": surge or zero(),
        "rflood": river,
        "prain": rain,
        "wfire": fire,
        "acute": {"aal": joint["aal"] + river["aal"] + rain["aal"] + fire["aal"],
                  "ep": acute_ep,
                  "ead": np.asarray(joint["ead"]) + np.asarray(river["ead"])
                       + np.asarray(rain["ead"]) + np.asarray(fire["ead"])},
    }
    if site_rp:
        # Task 5: per-site return-period losses beside the EAD. Catalogs add
        # comonotonically per site, the same rule the portfolio curve uses.
        acute_rp = _rp_zero(len(vals))
        for part_rp in (joint_rp, river_rp, rain_rp, fire_rp):
            if part_rp is not None:
                acute_rp = _rp_add(acute_rp, part_rp)
        out["acute"]["site_rp"] = acute_rp
    return out


def run_adaptation(prep, values, wind_mult, fb_coast, fb_river, base_by_scen,
                   flood_cap=None, fb_prain=None, fire_vuln=None, v_half=None):
    """Averted direct AAL, cost, and BCR per measure per scenario."""
    an = annuity(HORIZON_YEARS, DISCOUNT_RATE)
    out = {}
    for m in MEASURES:
        per_scen = {}
        for app_key, base in base_by_scen.items():
            if m["scope"] == "flood":
                in_scope = (np.asarray(base["cflood"]["ead"]) +
                            np.asarray(base["rflood"]["ead"])) > SCOPE_EAD_USD
            elif m["scope"] == "coastal":
                in_scope = np.asarray(base["cflood"]["ead"]) > SCOPE_EAD_USD
            else:
                in_scope = np.ones(len(values), dtype=bool)
            # the measure acts ONLY on in-scope sites (which are also the
            # only sites costed), so benefit and cost cover the same assets
            kw = {}
            if "dmg_mult" in m:
                kw["wind_dmg_mult"] = np.where(in_scope, m["dmg_mult"], 1.0)
            if "fb_bonus" in m:
                kw["fb_bonus"] = np.where(in_scope, m["fb_bonus"], 0.0)
            if "depth_red" in m:
                kw["cf_depth_red"] = np.where(in_scope, m["depth_red"], 0.0)
            adapted = eval_scenario(prep, app_key, values, wind_mult,
                                    fb_coast, fb_river, flood_cap=flood_cap,
                                    fb_prain=fb_prain, fire_vuln=fire_vuln,
                                    v_half=v_half, **kw)
            if adapted is None:
                continue
            cost = float((values[in_scope] * m["cost_pct_value"] / 100.0).sum())
            averted = max(base["acute"]["aal"] - adapted["acute"]["aal"], 0.0)
            av_site = np.maximum(np.asarray(base["acute"]["ead"], float) -
                                 np.asarray(adapted["acute"]["ead"], float), 0.0)
            cost_site = np.where(in_scope,
                                 values * m["cost_pct_value"] / 100.0, 0.0)
            per_scen[app_key] = {
                "averted_direct_aal_usd": round(averted, 2),
                "sites_in_scope": int(in_scope.sum()),
                "cost_usd": round(cost, 2),
                "npv_benefit_usd": round(averted * an, 2),
                "bcr": round(averted * an / cost, 3) if cost > 0 else None,
                "per_site": {
                    "averted_usd": [round(float(x), 2) for x in av_site],
                    "cost_usd": [round(float(x), 2) for x in cost_site],
                    "in_scope": [bool(b) for b in in_scope]},
            }
        out[m["key"]] = {"name": m["name"], "settings": {
            k: v for k, v in m.items() if k not in ("key", "name", "scope")},
            "scope": m["scope"], "per_scenario": per_scen}
    return out


def run_uncertainty(prep, values, wind_mult, fb_coast, fb_river,
                    scenarios, n_samples, seed, flood_cap=None,
                    fb_prain=None, fire_vuln=None, v_half=None):
    """Seeded joint Monte Carlo over the three physical factors. Returns
    per-scenario quantiles for acute AAL and 1-in-100 loss, plus a
    one-at-a-time driver ranking (the tornado, computed the app's way).
    The unsequa Saltelli/Sobol upgrade replaces the sampler here."""
    rng = np.random.default_rng(seed)
    draws = {f["key"]: rng.uniform(f["lo"], f["hi"], n_samples)
             for f in MC_FACTORS}
    out = {}
    for app_key in scenarios:
        aal = np.empty(n_samples)
        var100 = np.empty(n_samples)
        for i in range(n_samples):
            r = eval_scenario(prep, app_key, values, wind_mult, fb_coast,
                              fb_river, dmg_scale=draws["dmg"][i],
                              haz_mult=draws["haz"][i], exp_mult=draws["exp"][i],
                              flood_cap=flood_cap, fb_prain=fb_prain,
                              fire_vuln=fire_vuln, v_half=v_half)
            aal[i] = r["acute"]["aal"] if r else 0.0
            var100[i] = r["acute"]["ep"][100] if r else 0.0
        central = eval_scenario(prep, app_key, values, wind_mult,
                                fb_coast, fb_river, flood_cap=flood_cap,
                                fb_prain=fb_prain, fire_vuln=fire_vuln,
                                v_half=v_half)
        drivers = []
        for f in MC_FACTORS:
            lo = eval_scenario(prep, app_key, values, wind_mult, fb_coast,
                               fb_river, flood_cap=flood_cap,
                               fb_prain=fb_prain, fire_vuln=fire_vuln,
                               v_half=v_half, **{_MC_KW[f["key"]]: f["lo"]})
            hi = eval_scenario(prep, app_key, values, wind_mult, fb_coast,
                               fb_river, flood_cap=flood_cap,
                               fb_prain=fb_prain, fire_vuln=fire_vuln,
                               v_half=v_half, **{_MC_KW[f["key"]]: f["hi"]})
            swing = abs((hi["acute"]["aal"] if hi else 0.0) -
                        (lo["acute"]["aal"] if lo else 0.0))
            drivers.append({"label": f["label"], "swing_usd": round(swing, 2)})
        drivers.sort(key=lambda d: -d["swing_usd"])
        q = lambda a, p: float(np.percentile(a, p))
        out[app_key] = {
            "acute_aal_usd": {"p5": q(aal, 5), "p50": q(aal, 50), "p95": q(aal, 95),
                              "central": central["acute"]["aal"] if central else 0.0},
            "loss_1in100_usd": {"p5": q(var100, 5), "p50": q(var100, 50),
                                "p95": q(var100, 95),
                                "central": central["acute"]["ep"][100] if central else 0.0},
            "drivers": drivers,
        }
    return out


_MC_KW = {"haz": "haz_mult", "dmg": "dmg_scale", "exp": "exp_mult"}


# ---------------------------------------------------------------------------
# Backtest calibration (pure): fit the wind curve's v_half so the modeled
# present-day acute AAL over the backtested sites matches observed losses.
# Recorded in the pack as an OPTIONAL vulnerability setting, never silently
# applied: the pack's headline figures keep the app's published curve.
# ---------------------------------------------------------------------------

def run_catalog(prep, sites_c, values, wind_mult, fb_coast, fb_river, fcap,
                base_by_scen, fb_prain=None, fire_vuln=None, v_half=None,
                plan_scenario_pref=("ssp245_2050", "present")):
    """Appraise every catalog measure per site (increment 2). Returns
    (measures_catalog section, projects list ready for phasing, scenario).
    Modeled measures get event-set averted AAL over exactly the sites they
    apply to (and are costed on); identified-but-unmodeled measures (wildfire
    ahead of its layer, continuity) surface with sites and costs but no BCR."""
    import measures_catalog as mc          # lazy: mc imports this module
    sc = next((s for s in plan_scenario_pref if s in base_by_scen), None)
    if sc is None:
        return None, [], None
    base = base_by_scen[sc]
    ead_by_peril = {p: np.asarray(base.get(p, {"ead": np.zeros(len(values))})
                                  ["ead"], float)
                    for p in ("tc", "cflood", "rflood", "prain", "wfire")}
    names = [str(n) for n in sites_c["name"]]
    modeled, identified, projects = {}, [], []
    for m in mc.CATALOG:
        mask, knobs, costs, reasons = mc.catalog_effects(sites_c, ead_by_peril, m)
        entry = {"name": m["name"], "peril": m["peril"],
                 "lifespan_years": m["lifespan_years"],
                 "lead_time_months": m["lead_time_months"],
                 "downtime_room_nights_per_key": m["downtime_room_nights_per_key"],
                 "premium_credit_pct": m["premium_credit_pct"],
                 "note": m["note"],
                 "sites_in_scope": int(mask.sum()),
                 "excluded": [{"site": names[i], "reason": reasons[i]}
                              for i in range(len(names)) if not mask[i]]}
        if not m["modeled"]:
            entry["cost_usd"] = round(float(costs.sum()), 2)
            entry["sites"] = [names[i] for i in range(len(names)) if mask[i]]
            identified.append({"key": m["key"], **entry})
            continue
        cap_knob = knobs["flood_cap"]
        cap_eff = np.where(np.isnan(cap_knob), fcap,
                           np.minimum(fcap, cap_knob))
        fv_eff = (np.ones(len(values)) if fire_vuln is None
                  else np.asarray(fire_vuln, float)) * knobs["fire_mult"]
        adapted = eval_scenario(prep, sc, values, wind_mult, fb_coast,
                                fb_river, flood_cap=cap_eff,
                                fb_prain=fb_prain, fire_vuln=fv_eff,
                                v_half=v_half,
                                wind_dmg_mult=knobs["wind_dmg_mult"],
                                fb_bonus=knobs["fb_bonus"],
                                cf_depth_red=knobs["cf_depth_red"])
        if adapted is None:
            continue
        av_site = np.maximum(np.asarray(base["acute"]["ead"], float) -
                             np.asarray(adapted["acute"]["ead"], float), 0.0)
        an_years = min(m["lifespan_years"], HORIZON_YEARS)
        an = annuity(an_years, DISCOUNT_RATE)
        entry["averted_direct_aal_usd"] = round(float(av_site.sum()), 2)
        entry["cost_usd"] = round(float(costs.sum()), 2)
        entry["annuity_years"] = an_years
        modeled[m["key"]] = entry
        for i in range(len(names)):
            # zero-benefit pairs stay out of the plan (a wildfire measure
            # with no wfire event data would otherwise rank at BCR 0.0)
            if mask[i] and costs[i] > 0 and av_site[i] > 0:
                projects.append({"site": names[i], "measure": m["name"],
                                 "measure_key": m["key"], "peril": m["peril"],
                                 "averted_direct_aal_usd": round(float(av_site[i]), 2),
                                 "cost_usd": round(float(costs[i]), 2),
                                 "annuity_years": an_years,
                                 "bcr": round(float(av_site[i]) * an
                                              / float(costs[i]), 3)})
    projects.sort(key=lambda p: (-p["bcr"], p["site"], p["measure_key"]))
    return ({"modeled": modeled, "identified": identified}, projects, sc)


def build_capital_plan_v2(projects, sites_c, scenario, budget_annual_usd=None,
                          max_projects=40):
    """Phase the BCR-ranked catalog projects into the short-term plan."""
    import measures_catalog as mc
    if not projects:
        return None
    phased = mc.phase_projects(projects[:max_projects], sites_c,
                               budget_annual_usd)
    return {"scenario": scenario, "discount_rate": DISCOUNT_RATE,
            "horizon_years": HORIZON_YEARS, "plan_years": mc.PLAN_YEARS,
            "budget_annual_usd": budget_annual_usd,
            "renovation_synergy_factor": mc.RENOV_SYNERGY,
            "projects": phased}


def build_capital_plan(adaptation, names, max_projects=20,
                       scenario_pref=("ssp245_2050", "present")):
    """Rank every (site, measure) pair by benefit-cost ratio: the canonical
    capital plan. Pure: consumes run_adaptation's output plus the site
    names it was computed over. Appraised on the first scenario every
    measure carries (the middle pathway at 2050 by default, since capital
    decisions are about the future), which is recorded in the result.
    Only in-scope, positively-costed pairs qualify; ties break by site name
    for determinism.
    """
    an = annuity(HORIZON_YEARS, DISCOUNT_RATE)
    sc = next((s for s in scenario_pref
               if all(s in m.get("per_scenario", {})
                      for m in adaptation.values())), None)
    if sc is None or not adaptation:
        return None
    projects = []
    for mk, m in adaptation.items():
        rec = m["per_scenario"][sc]
        ps = rec.get("per_site")
        if not ps:
            continue
        for i, name in enumerate(names):
            if not ps["in_scope"][i] or ps["cost_usd"][i] <= 0:
                continue
            averted = ps["averted_usd"][i]
            cost = ps["cost_usd"][i]
            projects.append({"site": str(name), "measure": m["name"],
                             "measure_key": mk,
                             "averted_direct_aal_usd": averted,
                             "cost_usd": cost,
                             "bcr": round(averted * an / cost, 3)})
    projects.sort(key=lambda p: (-p["bcr"], p["site"], p["measure_key"]))
    return {"scenario": sc, "discount_rate": DISCOUNT_RATE,
            "horizon_years": HORIZON_YEARS,
            "projects": projects[:max_projects]}


VHALF_LO, VHALF_HI = 40.0, 150.0

def fit_v_half(calib_parts, observed_total, lo=VHALF_LO, hi=VHALF_HI,
               iters=60):
    """Bisection on v_half. calib_parts is a list of per-country dicts:
    {"wind": {"freq", "int"} for the present source restricted to matched
    sites, "values", "wind_mult", "flood_fixed"} where flood_fixed is the
    matched sites' present cflood+rflood AAL (independent of v_half).
    Modeled acute AAL is strictly decreasing in v_half, so the root is
    unique when reachable; otherwise the bound is returned with clipped=True.
    """
    def modeled(vh):
        total = 0.0
        for p in calib_parts:
            w = p.get("wind")
            if w is not None and w["int"].size:
                wl = wind_losses(w["int"], p["values"], p["wind_mult"],
                                 v_half=vh)
                total += float(site_ead(wl, w["freq"]).sum())
            total += p["flood_fixed"]
        return total
    m_lo, m_hi = modeled(lo), modeled(hi)      # AAL(lo) >= AAL(hi)
    if observed_total >= m_lo:
        return lo, m_lo, True
    if observed_total <= m_hi:
        return hi, m_hi, True
    a, b = lo, hi
    for _ in range(iters):
        mid = 0.5 * (a + b)
        if modeled(mid) > observed_total:
            a = mid                            # too much damage: raise v_half
        else:
            b = mid
    vh = 0.5 * (a + b)
    return vh, modeled(vh), False


def build_calibration(calib_parts, observed_total, matched):
    vh, modeled_at_fit, clipped = fit_v_half(calib_parts, observed_total)
    base = None
    for p in calib_parts:      # bias uses the model AS RUN (archetype curves)
        base = (base or 0.0)
        w = p.get("wind")
        if w is not None and w["int"].size:
            wl = wind_losses(w["int"], p["values"], p["wind_mult"],
                             v_half=p.get("v_half", V_HALF))
            base += float(site_ead(wl, w["freq"]).sum())
        base += p["flood_fixed"]
    bias = round(observed_total / base, 3) if base else None
    out = {
        "method": "bisection on Emanuel v_half; modeled present-day acute "
                  "AAL (wind at v_half + fixed flood) matched to observed "
                  "annual losses over the backtested sites",
        "matched_sites": int(matched),
        "observed_total_usd": round(observed_total, 2),
        "modeled_present_acute_usd": round(base, 2) if base is not None else None,
        "portfolio_bias_obs_over_model": bias,
        "fitted_v_half": round(vh, 1),
        "published_v_half": V_HALF,
        "clipped_at_bound": clipped,
        "applied": False,
        "note": "recorded as an optional vulnerability setting; pack figures "
                "use the published curve",
    }
    if bias is not None and not 0.5 <= bias <= 2.0:
        out["flag"] = "bias outside 0.5..2.0, review before adopting"
    return out


# ---------------------------------------------------------------------------
# CLIMADA seams. Everything version-sensitive is delegated to refresh_hazard,
# which already carries the candidate-fallback and API-shape tolerance.
# ---------------------------------------------------------------------------

def fetch_river_flood_hazards(iso3, app_key, meta, cache=None):
    """Ensemble of river_flood Hazard OBJECTS (not grids) for one scenario.

    `cache` (one dict per country) shares the Data API dataset listing and the
    Client across the ten app scenarios instead of re-querying once per scenario.
    """
    from climada.util.api_client import Client
    cache = {} if cache is None else cache
    client = cache.get("client")
    if client is None:
        client = cache["client"] = Client()
    infos = cache.get("infos")
    if infos is None:
        infos = cache["infos"] = client.list_dataset_infos(
            "river_flood", properties={"country_iso3alpha": iso3})
    chosen, scen, _yr = rh.rf_pick(infos, app_key)
    members = []
    for info in chosen:
        try:
            members.append(client.get_hazard("river_flood",
                                             name=getattr(info, "name", None)))
        except Exception as exc:
            LOG.warning("  rflood member failed, continuing: %s", str(exc)[:160])
    if members:
        meta.setdefault("rflood_sources", {})[f"{iso3}:{app_key}"] = {
            "climate_scenario_matched": scen, "n_members": len(members)}
    return members


def build_country_prep(iso3, sites_c, surge_enabled, river_enabled, meta,
                       fire_enabled=True, rain_enabled=True,
                       workers=1, wrc_bp=None, wrc_cfl=None):
    """Fetch hazards once per country and reduce them to per-site intensity
    matrices (the pure structure eval_scenario consumes).

    Wind sources fetch concurrently when workers>1. Each source's surge snap
    depends on `wind_dist` (the first successful source's per-site distance to
    the wind grid), which is a cross-source value, so the tasks compute the
    surge intensity at every site's nearest surge centroid UNGUARDED and the
    fixed-order assembly below applies the wind_dist guard once it is known.
    That keeps the result byte-for-byte identical to the serial run whatever
    order the fetches complete in."""
    lat = sites_c["latitude"].to_numpy(float)
    lon = sites_c["longitude"].to_numpy(float)
    # Task 4: per-site ground relief converts flood/surge depth at the CELL
    # into depth at the STRUCTURE. Sites without both elevation fields keep
    # the cell value and are flagged modeled-coarse (prep["_flood_basis"]).
    relief, has_elev = site_relief(sites_c["ground_elev_m"],
                                   sites_c["cell_ground_elev_m"])
    prep = {"wind": {}, "surge": {}, "rflood": {}, "_outside": set(),
            "_flood_basis": has_elev,     # True = depth read at the structure
            # per-site structural coverage per peril (bool arrays): did this
            # peril's model speak for the site's location at all? False means
            # the site is FLAGGED as outside coverage, never silently zeroed.
            "_cov": {p: np.zeros(len(sites_c), dtype=bool)
                     for p in ("tc", "cflood", "rflood", "prain", "wfire")}}

    def _wind_task(source):
        """Fetch one wind source, reduce it to per-site intensity, and (when
        enabled) reduce each scenario's surge to per-site intensity plus the
        per-site surge-centroid distance the deferred guard needs. A per-task
        meta keeps concurrent fetches from racing on the shared dict."""
        skey = rh.source_key(source)
        tmeta = {}
        out = {"skey": skey, "tmeta": tmeta, "wind_error": None,
               "idx": None, "dist": None, "wind": None,
               "surge": {}, "surge_skipped": []}
        try:
            haz = rh.fetch_wind(iso3, source, tmeta)
        except Exception as exc:
            out["wind_error"] = str(exc)[:300]
            return out
        idx, dist = nearest_centroids(lat, lon, haz.centroids.lat,
                                      haz.centroids.lon)
        out["idx"], out["dist"] = idx, dist
        # event identity for the pack's per-event table (TCOR Task A): the
        # catalog's own event names when the hazard carries them; absent
        # (older caches, mocks), sparse_event_rows falls back to source:index
        enames = getattr(haz, "event_name", None)
        out["wind"] = {"freq": np.asarray(haz.frequency, float),
                       "int": site_intensity(haz, idx),
                       "event_name": ([str(x) for x in enames]
                                      if enames is not None else None)}
        if surge_enabled:
            # Surge is REGIONAL: each site's depth comes from a bathtub run
            # over its own coastline's wind cells at that coastline's SLR
            # table (Gulf subsidence most of all); sites outside every region
            # box read the global-mean run, which equals the legacy table.
            site_regions = rh.slr_region_partition(lat, lon)
            boxes = {n: (la0, la1, lo0, lo1)
                     for n, la0, la1, lo0, lo1 in rh.SLR_REGION_BOXES}
            subs = {region: (haz if region == "global_mean" else
                             rh.subset_hazard_extent(haz, boxes[region]))
                    for region, _m in site_regions}
            n_ev = out["wind"]["int"].shape[0]
            for app_key, recipe in rh.APP_SCENARIOS.items():
                if not any(rh.source_key(s) == skey for _w, s in recipe):
                    continue
                try:
                    s_int = np.zeros((n_ev, len(lat)))
                    s_dist = np.full(len(lat), np.inf)
                    for region, m in site_regions:
                        sub = subs[region]
                        if sub is None:
                            continue    # no wind cells in this region: its
                                        # sites stay zero at infinite distance
                                        # (they are outside wind coverage too)
                        surge = rh.compute_surge(sub,
                                                 rh.slr_of(app_key, region))
                        idx_r, dist_r = nearest_centroids(
                            lat[m], lon[m], surge.centroids.lat,
                            surge.centroids.lon)
                        s_int[:, m] = site_intensity(surge, idx_r)
                        s_dist[m] = dist_r
                        del surge
                    out["surge"][app_key] = {"int": s_int, "dist": s_dist}
                except Exception as exc:
                    out["surge_skipped"].append(
                        {"country": iso3, "source": skey, "scenario": app_key,
                         "layer": "cflood", "reason": str(exc)[:300]})
        del haz
        gc.collect()
        return out

    wind_dist = None                 # per-site km to the wind grid, the
                                     # reference the water-layer snap guards on
    for out in rh.parallel_map(_wind_task, rh.unique_sources(rh.APP_SCENARIOS),
                               workers):
        skey = out["skey"]
        for k, v in out["tmeta"].get("wind_sources", {}).items():
            meta.setdefault("wind_sources", {})[k] = v
        if out["wind_error"] is not None:
            LOG.warning("Skipping wind source %s / %s: %s", iso3, skey,
                        out["wind_error"])
            meta["skipped"].append({"country": iso3, "source": skey,
                                    "layer": "tc", "reason": out["wind_error"]})
            continue
        idx, dist = out["idx"], out["dist"]
        if wind_dist is None:
            wind_dist = dist
        for j in np.where(idx < 0)[0]:
            site = str(sites_c.iloc[j]["name"])
            if site not in prep["_outside"]:      # once per site, not per source
                prep["_outside"].add(site)
                meta["skipped"].append({"country": iso3, "layer": "tc",
                                        "site": site,
                                        "reason": f"outside coverage "
                                                  f"({dist[j]:.0f} km to nearest cell)"})
        prep["wind"][skey] = out["wind"]
        prep["_cov"]["tc"] |= idx >= 0
        LOG.info("  wind %s / %s -> %d events x %d sites", iso3, skey,
                 *out["wind"]["int"].shape)
        # deferred water-snap guard: a surge centroid counts for a site only
        # within cell scale of that site's wind cell (water_snap's rule), now
        # that wind_dist is fixed. Equivalent to snapping with the guard inline.
        limit = np.maximum(wind_dist + SNAP_TOL_KM, SNAP_TOL_KM)
        for app_key, sg in out["surge"].items():
            sint = np.asarray(sg["int"], float).copy()
            sint[:, ~(sg["dist"] <= limit)] = 0.0
            # Task 4: depth at the structure where site elevation is known
            sint = depth_at_structure(sint, relief[None, :])
            prep["surge"][(skey, app_key)] = {"int": sint}
        for sk in out["surge_skipped"]:
            LOG.warning("Surge failed %s / %s @ %s: %s",
                        iso3, sk["source"], sk["scenario"], sk["reason"])
            meta["skipped"].append(sk)

    if river_enabled:
        river_cache = {}          # one Data API listing per country, shared here
        for app_key in rh.APP_SCENARIOS:
            fetch_failed = False
            try:
                members = fetch_river_flood_hazards(iso3, app_key, meta,
                                                    cache=river_cache)
            except Exception as exc:
                members, fetch_failed = [], True
                meta["skipped"].append({"country": iso3, "scenario": app_key,
                                        "layer": "rflood",
                                        "reason": str(exc)[:300]})
            packed = []
            for mhaz in members:
                midx = water_snap(lat, lon, mhaz.centroids.lat,
                                  mhaz.centroids.lon, wind_dist)
                packed.append({"freq": np.asarray(mhaz.frequency, float),
                               # Task 4: depth at the structure where known
                               "int": depth_at_structure(
                                   site_intensity(mhaz, midx),
                                   relief[None, :])})
            if packed:
                prep["rflood"][app_key] = packed
            elif not fetch_failed:      # empty result; failure already recorded
                meta["skipped"].append({"country": iso3, "scenario": app_key,
                                        "layer": "rflood",
                                        "reason": "no river_flood dataset"})

    # Water layers re-index onto the wind grid (explicit zeros inland), so a
    # site is COVERED by them exactly when the wind grid covers it and the
    # layer was produced at all; a modeled zero there is an honest zero.
    if prep["surge"]:
        prep["_cov"]["cflood"] = prep["_cov"]["tc"].copy()
    if prep["rflood"]:
        prep["_cov"]["rflood"] = prep["_cov"]["tc"].copy()

    if fire_enabled:
        # Task 3.5: wildfire is the USFS WRC burn probability sampled AT the
        # site point (30 m native), with the damage side conditioned on the
        # WRC flame-length layer (or the capped interim ratio). No FIRMS, no
        # cell occupancy, no spatial buffer. Sites the raster does not cover
        # (confirm WRC coverage for Hawaii and the territories per release)
        # are FLAGGED, never silently zeroed.
        if wrc_bp is None:
            LOG.warning("Wildfire skipped %s: no WRC burn-probability raster "
                        "(--wrc-bp / %s / ./%s/); download once from "
                        "wildfirerisk.org (USFS RDS-2020-0016).",
                        iso3, rw.WRC_BP_ENV, rw.DEFAULT_WRC_DIR)
            meta["skipped"].append({"country": iso3, "layer": "wfire",
                                    "reason": "no WRC BP raster (--wrc-bp / "
                                              f"{rw.WRC_BP_ENV} / "
                                              f"./{rw.DEFAULT_WRC_DIR}/)"})
        else:
            try:
                w = rw.wrc_at_points(lat, lon, wrc_bp, wrc_cfl)
                prep["wfire"] = {"bp": w["bp"], "cond": w["cond"],
                                 "cond_interim": w["cond_interim"]}
                prep["_cov"]["wfire"] = w["covered"]
                for j in np.where(~w["covered"])[0]:
                    meta["skipped"].append(
                        {"country": iso3, "layer": "wfire",
                         "site": str(sites_c.iloc[j]["name"]),
                         "reason": "outside WRC burn-probability raster "
                                   "coverage (no valid value at the site "
                                   "point)"})
                LOG.info("  wfire %s -> %d of %d sites point-sampled "
                         "(mean p %.3f%%)", iso3, int(w["covered"].sum()),
                         len(sites_c), float(w["bp"].mean()) * 100)
            except Exception as exc:
                LOG.warning("Wildfire unavailable %s: %s", iso3, str(exc)[:200])
                meta["skipped"].append({"country": iso3, "layer": "wfire",
                                        "reason": str(exc)[:300]})
    if rain_enabled:
        # Rain is built per basin DOMAIN (a country can span several: USA is
        # CONUS + Hawaii). Each domain speaks only for the sites inside its
        # box; a site no domain covers is flagged, never silently zeroed.
        members, any_built = [], False
        doms = rpn.domains_for(iso3, lat, lon)
        if not doms:
            meta["skipped"].append({"country": iso3, "layer": "prain",
                                    "reason": "no rain domain covers any site "
                                              "in this country"})
        for dom in doms:
            try:
                rhz = rpn.rain_hazard(rpn.fetch_tracks(dom), dom)
            except Exception as exc:
                LOG.warning("Rainfall unavailable %s/%s: %s", iso3,
                            dom["key"], str(exc)[:200])
                meta["skipped"].append({"country": iso3, "layer": "prain",
                                        "domain": dom["key"],
                                        "reason": str(exc)[:300]})
                continue
            in_dom = rpn.domain_covers(dom, lat, lon)
            ridx, _rd = nearest_centroids(lat, lon, rhz.centroids.lat,
                                          rhz.centroids.lon)
            ridx = np.where(in_dom, ridx, -1)
            members.append({"freq": np.asarray(rhz.frequency, float),
                            "int": site_intensity(rhz, ridx),
                            "domain": dom["key"]})
            prep["_cov"]["prain"] |= in_dom & (np.asarray(ridx) >= 0)
            any_built = True
            LOG.info("  prain %s/%s -> %d events x %d sites (%d covered)",
                     iso3, dom["key"], *members[-1]["int"].shape,
                     int((in_dom & (np.asarray(ridx) >= 0)).sum()))
        if members:
            prep["prain"] = members
        if any_built:       # only flag sites when the layer itself exists
            for j in np.where(~prep["_cov"]["prain"])[0]:
                meta["skipped"].append(
                    {"country": iso3, "layer": "prain",
                     "site": str(sites_c.iloc[j]["name"]),
                     "reason": "outside every rain domain (no basin models "
                               "TC rainfall at this location yet)"})
    return prep


# ---------------------------------------------------------------------------
# Pack assembly (pure)
# ---------------------------------------------------------------------------

def combine_countries(results, site_counts, countries=None, meta=None):
    """AALs and per-site EADs concatenate exactly; exceedance curves add at
    equal return periods (comonotonic across independent country catalogs).

    `site_counts[i]` is the number of sites in `results[i]`. A country whose
    hazards all failed for a scenario contributes explicit ZEROS for its
    sites (keeping every per-site array aligned with the full site list) and
    the gap is recorded in meta.skipped rather than silently dropped: the
    same rule align_to_cells applies to the hazard grid."""
    out = {}
    countries = countries or ["?"] * len(results)
    for app_key in rh.APP_SCENARIOS:
        if not any(r.get(app_key) for r in results):
            continue
        combined = {}
        for peril in ("tc", "cflood", "rflood", "prain", "wfire", "acute"):
            aal, ep, eads = 0.0, {rp: 0.0 for rp in RPS}, []
            rp_parts = {rp: [] for rp in SITE_RPS}
            for r, n, iso3 in zip(results, site_counts, countries):
                p = r.get(app_key)
                if p is not None and peril not in p:      # legacy 3-peril dict
                    p = None if peril in ("prain", "wfire") else p
                if p is None:
                    eads.append(np.zeros(n))
                    for rp in SITE_RPS:
                        rp_parts[rp].append(np.zeros(n))
                    if meta is not None and peril == "acute":
                        meta["skipped"].append(
                            {"country": iso3, "scenario": app_key,
                             "layer": "pack",
                             "reason": "scenario absent for this country; "
                                       "its sites carry zero in the pack here"})
                    continue
                aal += p[peril]["aal"]
                ep = add_ep(ep, p[peril]["ep"])
                eads.append(np.asarray(p[peril]["ead"], float))
                srp = p[peril].get("site_rp")
                for rp in SITE_RPS:
                    rp_parts[rp].append(np.asarray(srp[rp], float)
                                        if srp is not None else np.zeros(n))
            combined[peril] = {"aal": aal, "ep": ep,
                               "ead": np.concatenate(eads)}
            if peril == "acute":
                combined[peril]["site_rp"] = {
                    rp: np.concatenate(rp_parts[rp]) for rp in SITE_RPS}
        out[app_key] = combined
    return out


def combine_event_sets(per_country_sets):
    """[(iso3, {app_key: [source parts]})] -> {app_key: [tagged parts]}.

    Country catalogs are independent and their sites disjoint, so each
    country's source parts keep their own per-country-normalized weights and
    gain a country tag: a consumer computes any event statistic per part,
    weight-averages within a country, and SUMS across countries (equivalent:
    sum weight x statistic over all parts). One physical storm crossing a
    country boundary appears as separate per-country events; that limit is
    recorded in meta, and campuses never span countries."""
    out = {}
    for iso3, ev in per_country_sets:
        for app_key, parts in (ev or {}).items():
            for p in parts:
                q = dict(p)
                q["country"] = iso3
                out.setdefault(app_key, []).append(q)
    return out


def combine_ladders(per_country_ladders, site_counts):
    """[(iso3, {app_key: {peril: {rp: arr}}})] + per-country site counts ->
    {app_key: {peril: [[loss per LADDER_RPS] per site]}} in pack site order,
    zero-filling countries that lack a peril or scenario so rows stay
    aligned with per_site (the same padding rule combine_countries uses)."""
    keys, perils = [], {}
    for _iso3, ld in per_country_ladders:
        for k, by_peril in (ld or {}).items():
            if k not in keys:
                keys.append(k)
            for p in by_peril:
                perils.setdefault(k, [])
                if p not in perils[k]:
                    perils[k].append(p)
    out = {}
    for k in keys:
        out[k] = {}
        for p in perils[k]:
            rows = []
            for (_iso3, ld), n in zip(per_country_ladders, site_counts):
                lad = (ld or {}).get(k, {}).get(p)
                if lad is None:
                    rows.extend([[0.0] * len(LADDER_RPS)] * n)
                else:
                    for j in range(n):
                        rows.append([round(float(lad[rp][j]), 2)
                                     for rp in LADDER_RPS])
            out[k][p] = rows
    return out


def _norm_insured(x):
    """Display name for a site's named-insured group; missing -> Unspecified,
    mirroring the app's insuredOf so pack and browser roll up the same way."""
    s = _txt(x)
    return str(x).strip() if (s is not None) else "Unspecified"


def named_insured_rollup(acute_ead, named_insured):
    """Direct-damage AAL grouped by named-insured party (pure; testable).

    A single physical site can carry several named insureds (an HOA and the
    operating company, say). This decomposes the per-site acute EAD by that
    party so the pack answers 'who is impacted, and to what degree' alongside
    the by-peril split. Sums to the same portfolio direct AAL, in first-seen
    order for determinism."""
    out = {}
    for ead, party in zip(acute_ead, named_insured):
        key = _norm_insured(party)
        out[key] = out.get(key, 0.0) + float(ead)
    return {k: round(v, 2) for k, v in out.items()}


def build_pack(scen_results, site_names, site_values, adaptation, uncertainty,
               sites_file, site_named_insured=None, site_ids=None,
               site_coverage=None, site_flood_basis=None,
               event_sets=None, ladders=None,
               event_floor_usd=EVENT_FLOOR_USD):
    n = len(site_names)
    site_named_insured = (list(site_named_insured)
                          if site_named_insured is not None else [None] * n)
    site_ids = list(site_ids) if site_ids is not None else [None] * n
    scenarios = {}
    for app_key, r in scen_results.items():
        site_rp = r["acute"].get("site_rp")
        per_site = [{"name": n_,
                     "named_insured": _norm_insured(site_named_insured[i]),
                     "site_id": (_txt(site_ids[i]) and str(site_ids[i]).strip())
                                or None,
                     "direct_ead_usd": round(float(r["acute"]["ead"][i]), 2),
                     # Task 5: per-site return-period losses beside the EAD
                     **({"loss_rp100_usd": round(float(site_rp[100][i]), 2),
                         "loss_rp250_usd": round(float(site_rp[250][i]), 2)}
                        if site_rp is not None else {}),
                     "by_peril": {p: round(float(r[p]["ead"][i]), 2)
                                  for p in ("tc", "cflood", "rflood",
                                            "prain", "wfire") if p in r},
                     # Task 4: whether flood/surge depth was read at the
                     # structure (site + cell ground known) or is the cell
                     # average (modeled-coarse, flagged on the trust surface)
                     **({"flood_depth_basis": ("structure"
                                               if site_flood_basis[i]
                                               else "cell")}
                        if site_flood_basis is not None else {}),
                     # per-site-per-peril coverage: false = this peril's model
                     # did not speak for this site (flagged, not zeroed)
                     **({"coverage": {p: bool(site_coverage[p][i])
                                      for p in site_coverage}}
                        if site_coverage is not None else {})}
                    for i, n_ in enumerate(site_names)]
        scenarios[app_key] = {
            "portfolio": {
                "direct_aal_usd": round(r["acute"]["aal"], 2),
                "by_peril_aal_usd": {p: round(r[p]["aal"], 2)
                                     for p in ("tc", "cflood", "rflood",
                                               "prain", "wfire") if p in r},
                "by_named_insured_aal_usd": named_insured_rollup(
                    r["acute"]["ead"], site_named_insured),
                "ep_usd": {str(rp): round(r["acute"]["ep"][rp], 2)
                           for rp in RPS},
            },
            "per_site": per_site,
        }
    pack = {
        "pack_version": 1,
        "kind": "results_pack",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "refresh_impacts.py v1 (Phase 5 results pack, step 1)",
        "domain": "direct damage to asset value, acute perils "
                  "(tc, cflood, rflood, prain, wfire)",
        "sites": {"file": sites_file, "count": len(site_names),
                  "total_value_usd": round(float(site_values.sum()), 2)},
        "return_periods": RPS,
        "scenarios": scenarios,
        "adaptation": adaptation,
        "uncertainty": uncertainty,
    }
    # TCOR Task A: event-level outputs. Additive sections; pack_version
    # stays 1 so older app builds keep loading the pack unchanged.
    if event_sets:
        pack["event_sets"] = {
            "floor_usd": event_floor_usd,
            "basis": "joint wind+surge losses per event (shared catalog per "
                     "source, truly joint); sources are ALTERNATIVE catalogs "
                     "blended by weight, never merged; site indices refer to "
                     "per_site order; the per-occurrence shared hurricane "
                     "deductible must be computed on these events, never on "
                     "per-site sums",
            "scenarios": event_sets,
        }
    if ladders:
        pack["frequent_losses"] = {
            "ladder_rps": list(LADDER_RPS),
            "basis": "per-site loss at each return period (step exceedance "
                     "over the site's own events, the site_rp convention), "
                     "extended into the 1-in-2..1-in-10 attritional band; "
                     "tc_joint is same-catalog wind+surge, tc and cflood are "
                     "its components; per-location deductible math "
                     "integrates these ladders",
            "scenarios": ladders,
        }
    return pack


def pack_meta(pack, args, meta):
    meta.update({
        "generated_utc": pack["generated_utc"],
        "script": pack["script"],
        "sites_file": args.sites,
        "countries": sorted(meta.pop("_countries", [])),
        "mc": {"n_samples": args.mc, "seed": args.seed,
               "factors": [f["label"] for f in MC_FACTORS]},
        "discount_rate": DISCOUNT_RATE,
        "horizon_years": HORIZON_YEARS,
        "vulnerability": {"wind": f"Emanuel cubic sigmoid, V_THRESH={V_THRESH}, "
                                  f"V_HALF={V_HALF} m/s (archetype-shifted per "
                                  f"site), x construction/age factor",
                          "flood": "1-exp(-0.6 x depth over freeboard), cap 0.75; "
                                   f"freeboard cflood {FB_COAST} m / rflood "
                                   f"{FB_RIVER} m, +0.5 m if defended",
                          "wildfire": "WRC point burn probability x flame-"
                                      "length-conditioned damage (or the "
                                      f"capped interim ratio "
                                      f"{FIRE_COND_INTERIM}, labeled interim)"},
        "combination_rules": {
            "wind_surge": "per event (shared catalog, truly joint)",
            "river_flood": "comonotonic (exceedance losses add at equal RP)",
            "tc_rainfall": "comonotonic (own track catalog per basin domain; "
                           "domains add comonotonically; Clausius-Clapeyron "
                           "scenario scaling)",
            "wildfire": "comonotonic (per-site occurrence exceedance over "
                        "independent WRC point burn probabilities; warming "
                        "scales the arrival probability, not the loss)",
            "countries": "comonotonic (exceedance losses add at equal RP)",
            "ep_tail": "flat beyond the largest simulated return period"},
        "per_site_return_periods": {
            "rps": list(SITE_RPS),
            "basis": "step exceedance over each site's own events (the loss "
                     "of the least-severe event whose cumulative frequency "
                     "reaches 1/RP); catalogs add comonotonically per site"},
        "ead_basis": "full event-frequency range: the event math never had a "
                     "1-in-10 floor, and the app's interim integral now "
                     "extends below 1-in-10 to match",
        "event_sets": {
            "present": "event_sets" in pack,
            "floor_usd": pack.get("event_sets", {}).get("floor_usd"),
            "ids": "catalog event_name when the hazard carries one, else "
                   "source:index",
            "sources": "alternative catalogs blended by weight; events are "
                       "never merged across sources",
            "cross_country": "catalogs are per country; one storm crossing a "
                             "border appears as separate events (shared-"
                             "deductible sharing never spans countries)"},
        "frequent_losses": {
            "present": "frequent_losses" in pack,
            "ladder_rps": list(LADDER_RPS),
            "basis": "site_rp step-exceedance convention extended into the "
                     "1-in-2..1-in-10 attritional band"},
        "layers": [{"scenario": k,
                    "sites": len(v["per_site"]),
                    "direct_aal_usd": v["portfolio"]["direct_aal_usd"]}
                   for k, v in pack["scenarios"].items()],
    })
    try:
        from importlib.metadata import version
        meta["climada_version"] = version("climada")
    except Exception:
        pass
    return meta


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_sites(path):
    df = pd.read_csv(path)
    need = ["name", "latitude", "longitude", "asset_value_usd"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise SystemExit(f"{path}: missing required columns {missing}")
    if "country" not in df.columns:
        df["country"] = "USA"
    df["country"] = df["country"].fillna("USA").astype(str).str.upper()
    # profile schema v2: every column optional; absent columns reproduce the
    # six-field behavior exactly (pinned by tests). named_insured / site_id /
    # site_name carry the named-insured aggregation: several named-insured
    # groups (e.g. an HOA and the operating company) can share one physical
    # site, grouped by site_id for the portfolio's single-site rollups.
    for c in ("construction", "year_built", "roof_type", "roof_year",
              "opening_protection", "first_floor_elev_m", "stories", "keys",
              "buildings", "fema_zone", "backup_power", "renovation_year",
              "wui_class", "defensible_space_m", "archetype",
              "ground_elev_m", "cell_ground_elev_m",
              "named_insured", "site_id", "site_name"):
        if c not in df.columns:
            df[c] = None
    for c in ("defended", "equipment_elevated", "roof_class_a"):
        if c not in df.columns:
            df[c] = False
        # accept pandas' float-coerced truthy cells ("1.0") too, not just "1"
        df[c] = df[c].map(
            lambda x: str(x).strip().lower() in ("true", "1", "1.0", "yes", "y"))
    return df


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Build the CLIMADA results pack (portfolio EP curves, "
                    "per-site EAD, adaptation appraisal, uncertainty bands).")
    ap.add_argument("--sites", default="sites.csv")
    ap.add_argument("--out", default="results_pack.json")
    ap.add_argument("--no-surge", action="store_true")
    ap.add_argument("--no-river", action="store_true")
    ap.add_argument("--mc", type=int, default=300,
                    help="Monte Carlo samples (default %(default)s)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=None,
                    help="concurrent Data API wind fetches per country (default: "
                         "CLAM_WORKERS or 4; pass 1 for the exact serial run)")
    ap.add_argument("--wrc-bp", default=None, metavar="TIF",
                    help="USFS WRC burn-probability GeoTIFF for the wildfire "
                         f"layer (or {rw.WRC_BP_ENV}, or ./{rw.DEFAULT_WRC_DIR}/); "
                         "local pre-downloaded file, wildfirerisk.org")
    ap.add_argument("--wrc-cfl", default=None, metavar="TIF",
                    help="USFS WRC conditional flame length GeoTIFF (absent: "
                         "the capped interim conditional ratio, labeled)")
    ap.add_argument("--firms", nargs="+", default=None,
                    help="DEPRECATED for loss: FIRMS no longer feeds burn "
                         "probability (Task 3.5 structural fix). Use "
                         "refresh_wildfire.py --firms-context for the "
                         "historical-context export.")
    ap.add_argument("--no-fire", action="store_true",
                    help="skip the wildfire layer in the pack")
    ap.add_argument("--no-rain", action="store_true",
                    help="skip the TC rainfall event layer in the pack")
    ap.add_argument("--budget", type=float, default=None, metavar="USD",
                    help="annual capex budget for the phased capital plan")
    ap.add_argument("--backtest", default=None, metavar="CSV",
                    help="observed-loss CSV (name, observed_annual_loss_usd): "
                         "fits v_half and records it in the pack, not applied")
    ap.add_argument("--no-events", action="store_true",
                    help="skip the per-event joint loss table and the "
                         "frequent-loss ladders (TCOR consumers then degrade "
                         "to labeled approximations)")
    ap.add_argument("--event-floor", type=float, default=EVENT_FLOOR_USD,
                    metavar="USD",
                    help="drop site-event loss entries below this from the "
                         "event table (default %(default)s; recorded in the "
                         "pack and bounded by the validator)")
    args = ap.parse_args(argv)

    backtest = None
    if args.backtest:
        backtest = pd.read_csv(args.backtest)
        need_bt = ["name", "observed_annual_loss_usd"]
        if any(c not in backtest.columns for c in need_bt):
            raise SystemExit(f"{args.backtest}: needs columns {need_bt}")
        backtest = (backtest.drop_duplicates("name")
                    .astype({"name": str}).set_index("name"))

    surge_enabled = not args.no_surge
    if surge_enabled and not rh.TOPO_PATH.exists():
        LOG.warning("DEM not found at %s: surge EXCLUDED from the pack this "
                    "run.", rh.TOPO_PATH)
        surge_enabled = False

    workers = rh.resolve_workers(args.workers)
    sites = load_sites(args.sites)
    LOG.info("Loaded %d sites from %s", len(sites), args.sites)
    meta = {"skipped": [], "wind_sources": {}, "_countries": set(),
            "fetch_workers": workers}

    # Task 3.5: wildfire reads the USFS WRC rasters (local pre-downloaded
    # files; the path is configuration so corporate SSL never blocks a
    # rebuild). FIRMS no longer feeds burn probability anywhere.
    if args.firms:
        LOG.warning("--firms is DEPRECATED for the loss calculation and is "
                    "ignored: burn probability now comes from the WRC point "
                    "raster (--wrc-bp). FIRMS remains available as a "
                    "historical-context export via refresh_wildfire.py "
                    "--firms-context.")
    wrc_bp, wrc_cfl = (None, None) if args.no_fire else \
        rw.resolve_wrc(args.wrc_bp, args.wrc_cfl)
    if wrc_bp and not wrc_cfl:
        LOG.warning("No WRC CFL raster: the wildfire conditional damage side "
                    "uses the INTERIM flat ratio %.2f (capped); the app "
                    "labels it interim on the trust surface.",
                    FIRE_COND_INTERIM)

    per_country, order = [], []
    calib_parts, matched_names = [], set()
    for iso3, sites_c in sites.groupby("country", sort=True):
        meta["_countries"].add(iso3)
        LOG.info("Country %s: %d site(s)", iso3, len(sites_c))
        prep = build_country_prep(iso3, sites_c, surge_enabled,
                                  not args.no_river, meta,
                                  fire_enabled=not args.no_fire,
                                  rain_enabled=not args.no_rain,
                                  workers=workers,
                                  wrc_bp=wrc_bp, wrc_cfl=wrc_cfl)
        values = sites_c["asset_value_usd"].to_numpy(float)
        vulns = [vuln_v2(r.construction, r.year_built, r.defended,
                         roof_type=r.roof_type, roof_year=r.roof_year,
                         opening_protection=r.opening_protection,
                         first_floor_elev_m=r.first_floor_elev_m,
                         equipment_elevated=r.equipment_elevated)
                 for r in sites_c.itertuples()]
        wm = np.array([v[0] for v in vulns])
        fbb = np.array([v[1] for v in vulns])
        fcap_p = np.array([v[2] for v in vulns])
        # archetype layer (profile schema v2): curve-level differentiation;
        # the factor table above stays the mapping layer on top of it
        vh, fb_add, cap_o = archetype_arrays(sites_c.to_dict("records"))
        fbb = fbb + fb_add
        fcap = compose_flood_cap(fcap_p, cap_o,
                                 sites_c["equipment_elevated"].to_numpy(bool))
        fvuln = np.array([fire_vuln_of(r.roof_class_a, r.defensible_space_m)
                          for r in sites_c.itertuples()])
        fb_coast = np.maximum(FB_COAST + fbb, 0.0)
        fbp = np.maximum(np.full(len(sites_c), PRAIN_FB) + fbb, 0.0)
        fb_river = np.maximum(fb_river_m() + fbb, 0.0)
        scen = {}
        for app_key in rh.APP_SCENARIOS:
            r = eval_scenario(prep, app_key, values, wm, fb_coast, fb_river,
                              flood_cap=fcap, fb_prain=fbp, fire_vuln=fvuln,
                              v_half=vh, site_rp=True)
            if r is not None:
                scen[app_key] = r
        base_keys = {"present"} | set(UNCERTAINTY_SCENARIOS)
        adaptation = run_adaptation(prep, values, wm, fb_coast, fb_river,
                                    {k: v for k, v in scen.items()
                                     if k in base_keys}, flood_cap=fcap,
                                    fb_prain=fbp, fire_vuln=fvuln, v_half=vh)
        uncertainty = run_uncertainty(prep, values, wm, fb_coast, fb_river,
                                      [k for k in UNCERTAINTY_SCENARIOS
                                       if k in scen],
                                      args.mc, args.seed, flood_cap=fcap,
                                      fb_prain=fbp, fire_vuln=fvuln,
                                      v_half=vh)
        if backtest is not None and "present" in scen:
            mask = sites_c["name"].astype(str).isin(backtest.index).to_numpy()
            if mask.any():
                wp = prep["wind"].get("present")
                calib_parts.append({
                    "wind": None if wp is None else
                        {"freq": wp["freq"], "int": wp["int"][:, mask]},
                    "values": values[mask], "wind_mult": wm[mask],
                    "v_half": vh[mask],
                    "flood_fixed": float(sum(
                        np.asarray(scen["present"][z]["ead"])[mask].sum()
                        for z in ("cflood", "rflood", "prain", "wfire")
                        if z in scen["present"]))})
                matched_names.update(sites_c.loc[mask, "name"].astype(str))
        cat_section, cat_projects, cat_sc = run_catalog(
            prep, sites_c, values, wm, fb_coast, fb_river, fcap,
            {k: v for k, v in scen.items() if k in base_keys},
            fb_prain=fbp, fire_vuln=fvuln, v_half=vh)
        # TCOR Task A: the per-event, per-site joint wind+surge table (the
        # shared hurricane deductible's hard dependency) and the per-site
        # frequent-loss ladders (the attritional layer's 1-in-2..1-in-10
        # band). Site indices are GLOBAL pack indices via the offset.
        ev_sets, ladders = {}, {}
        if not args.no_events:
            offset = len(order)
            for app_key in scen:
                es = build_event_sets(prep, app_key, values, wm, fb_coast,
                                      flood_cap=fcap, v_half=vh,
                                      floor_usd=args.event_floor,
                                      site_offset=offset)
                if es:
                    ev_sets[app_key] = es
                ld = build_frequent_ladders(
                    prep, app_key, values, wm, fb_coast, fb_river,
                    flood_cap=fcap, fb_prain=fbp, fire_vuln=fvuln, v_half=vh,
                    haz_warm=rw.WARMING.get(app_key, 0.0))
                if ld:
                    ladders[app_key] = ld
        per_country.append({"scen": scen, "adaptation": adaptation,
                            "event_sets": ev_sets, "ladders": ladders,
                            "catalog": cat_section,
                            "cat_projects": cat_projects, "cat_sc": cat_sc,
                            "sites_df": sites_c,
                            "uncertainty": uncertainty, "iso3": iso3,
                            "names": list(sites_c["name"]), "values": values,
                            "named_insured": list(sites_c["named_insured"]),
                            "site_id": list(sites_c["site_id"]),
                            "coverage": prep["_cov"],
                            "flood_basis": prep["_flood_basis"]})
        order.extend(sites_c["name"])

    if not per_country or not any(c["scen"] for c in per_country):
        LOG.error("No impacts produced. Check network access and the sites file.")
        return 1

    combined = combine_countries([c["scen"] for c in per_country],
                                 [len(c["names"]) for c in per_country],
                                 [c["iso3"] for c in per_country], meta)
    # single-country portfolios keep their exact adaptation and uncertainty;
    # multi-country runs report the value-weighted country with a meta note.
    # Only countries that actually produced hazards can lead: otherwise the
    # highest-value country whose fetches all failed would empty these
    # sections while other countries still feed the portfolio numbers.
    lead_pool = [c for c in per_country if c["scen"]] or per_country
    lead = max(lead_pool, key=lambda c: float(c["values"].sum()))
    if len(per_country) > 1:
        meta["note_adaptation_uncertainty"] = (
            "adaptation, uncertainty, capital plan, and measure catalog "
            "sections reflect the largest country by value; per-country "
            "expansion is a step-2 item")
    coverage = {p: np.concatenate([c["coverage"][p] for c in per_country])
                for p in ("tc", "cflood", "rflood", "prain", "wfire")}
    flood_basis = np.concatenate([c["flood_basis"] for c in per_country])
    meta["flood_depth_basis"] = {
        "at_structure_sites": int(flood_basis.sum()),
        "cell_average_sites": int((~flood_basis).sum()),
        "note": "at-structure sites carry ground_elev_m + cell_ground_elev_m "
                "(survey or enrich_sites.py); cell-average sites are flagged "
                "modeled-coarse on the app's trust surface"}
    event_sets = combine_event_sets([(c["iso3"], c["event_sets"])
                                     for c in per_country])
    ladders = combine_ladders([(c["iso3"], c["ladders"])
                               for c in per_country],
                              [len(c["names"]) for c in per_country])
    if event_sets:
        n_entries = sum(len(e["sites"]) for parts in event_sets.values()
                        for p in parts for e in p["events"])
        LOG.info("Event sets: %d scenario(s), %d site-event entries "
                 "(floor %.0f USD)", len(event_sets), n_entries,
                 args.event_floor)
    pack = build_pack(combined, order,
                      np.concatenate([c["values"] for c in per_country]),
                      lead["adaptation"], lead["uncertainty"], args.sites,
                      site_named_insured=[ni for c in per_country
                                          for ni in c["named_insured"]],
                      site_ids=[sid for c in per_country
                                for sid in c["site_id"]],
                      site_coverage=coverage, site_flood_basis=flood_basis,
                      event_sets=event_sets or None, ladders=ladders or None,
                      event_floor_usd=args.event_floor)
    if lead.get("catalog"):
        pack["measures_catalog"] = lead["catalog"]
    plan = build_capital_plan_v2(lead.get("cat_projects") or [],
                                 lead["sites_df"], lead.get("cat_sc"),
                                 budget_annual_usd=args.budget)
    if plan is None:                       # catalog empty: legacy fallback
        plan = build_capital_plan(lead["adaptation"], lead["names"])
    if plan:
        pack["capital_plan"] = plan
    if backtest is not None:
        if calib_parts:
            observed_total = float(
                backtest.loc[sorted(matched_names),
                             "observed_annual_loss_usd"].sum())
            pack["calibration"] = build_calibration(calib_parts,
                                                    observed_total,
                                                    len(matched_names))
            LOG.info("Calibration: %d matched site(s), fitted v_half %.1f "
                     "(published %.1f)", len(matched_names),
                     pack["calibration"]["fitted_v_half"], V_HALF)
        else:
            meta["skipped"].append({"layer": "calibration",
                                    "reason": "no backtest names matched the "
                                              "sites file"})
    Path(args.out).write_text(json.dumps(pack, indent=2))
    meta_path = Path(args.out).with_name(Path(args.out).stem + "_meta.json")
    meta_path.write_text(json.dumps(pack_meta(pack, args, meta), indent=2,
                                    default=str))

    LOG.info("Wrote %s (%d scenarios) and %s", args.out,
             len(pack["scenarios"]), meta_path)
    LOG.info("Next: python validate_pack.py %s %s", args.out, meta_path)
    if meta["skipped"]:
        LOG.warning("%d item(s) skipped; see the meta sidecar.",
                    len(meta["skipped"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
