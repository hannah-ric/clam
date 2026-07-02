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
    - TC rainfall and wildfire are independent catalogs (their own track
      set and fire seasons); both add comonotonically, and wildfire's
      warming signal scales the fire FREQUENCY, not the per-event loss.
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

DISCOUNT_RATE = 0.03                         # BCR appraisal settings
HORIZON_YEARS = 25                           # (recorded in the pack)

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

# increment 3 damage constants. MIRROR the app's v1.12 values; change both.
FIRE_MDD = 0.6                    # conditional damage ratio when a site burns
FIRE_ROOF_A = 0.6                 # fire vulnerability factor: Class A roof
FIRE_DEFENSIBLE = 0.7             # fire vulnerability factor: space >= 30 m
PRAIN_DRAIN_MM = 150.0            # site drainage capacity per event
PRAIN_POND_COEFF = 0.4            # ponding share of excess rain
PRAIN_FB = 0.3                    # rainfall freeboard (grading and drains)


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
    per-site flood MDD cap array (None means the published 0.75)."""
    d = np.maximum(np.asarray(depth, float) * haz_mult - depth_red, 0.0)
    caps = np.full(d.shape[1], FLOOD_CAP_DEFAULT) if cap is None \
        else np.asarray(cap, float)
    frac = np.stack([flood_mdd(d[:, j], freeboard[j], caps[j])
                     for j in range(d.shape[1])], axis=1)
    frac = np.minimum(frac * dmg_scale, 1.0)
    return frac * values[None, :]


# ---------------------------------------------------------------------------
# Scenario evaluation over prepared per-site intensity matrices (pure)
# ---------------------------------------------------------------------------

def eval_scenario(prep, app_key, values, wind_mult, fb_coast, fb_river,
                  dmg_scale=1.0, haz_mult=1.0, exp_mult=1.0,
                  wind_dmg_mult=1.0, fb_bonus=0.0, cf_depth_red=0.0,
                  flood_cap=None, fb_prain=None, fire_vuln=None,
                  fire_mult=1.0):
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

    ws_parts, w_parts, s_parts = [], [], []
    for w, src in recipe:
        skey = rh.source_key(src)
        if skey not in prep["wind"]:
            continue
        wnd = prep["wind"][skey]
        wl = wind_losses(wnd["int"], vals, wind_mult * wind_dmg_mult,
                         dmg_scale, haz_mult)
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

    wind = blend_results(w_parts)
    surge = blend_results(s_parts)
    joint = blend_results(ws_parts)

    river = None
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
        river = blend_results(mparts)

    warm = rw.WARMING.get(app_key, 0.0)

    rain = None
    pw = prep.get("prain")
    if pw is not None:
        # scenario scaling by Clausius-Clapeyron on the rain field itself,
        # then the documented drainage conversion (mirrors the app exactly)
        mm = pw["int"] * (1.0 + rpn.PRAIN_CC_PER_C * warm) * haz_mult
        depth = np.maximum(mm - PRAIN_DRAIN_MM, 0.0) / 1000.0 * PRAIN_POND_COEFF
        fbp = (np.full_like(vals, PRAIN_FB) if fb_prain is None else fb_prain)             + fb_bonus
        pl = flood_losses(depth, vals, fbp, dmg_scale, 1.0, cap=flood_cap)
        rain = {"aal": float(site_ead(pl, pw["freq"]).sum()),
                "ep": ep_curve(pl.sum(axis=1), pw["freq"]),
                "ead": site_ead(pl, pw["freq"])}

    fire = None
    fw = prep.get("wfire")
    if fw is not None:
        # true event math over the probabilistic fire seasons: per-event site
        # losses are value x conditional damage x profile vulnerability, and
        # warming scales the fire FREQUENCY (arrival rate), not the loss
        fv = np.ones_like(vals) if fire_vuln is None else np.asarray(fire_vuln)
        frac = np.minimum(FIRE_MDD * fv * dmg_scale * fire_mult, 1.0)
        fl = fw["hits"].astype(float) * (frac * vals)[None, :]
        freq_f = np.asarray(fw["freq"], float) * haz_mult             * (1.0 + rw.FIRE_WARMING_UPLIFT * warm)
        fire = {"aal": float(site_ead(fl, freq_f).sum()),
                "ep": ep_curve(fl.sum(axis=1), freq_f),
                "ead": site_ead(fl, freq_f)}

    if joint is None and river is None and rain is None and fire is None:
        return None
    zero = lambda: {"aal": 0.0, "ep": {rp: 0.0 for rp in RPS},
                    "ead": np.zeros_like(vals)}
    joint = joint or zero()
    river = river or zero()
    rain = rain or zero()
    fire = fire or zero()
    acute_ep = add_ep(add_ep(add_ep(joint["ep"], river["ep"]),
                             rain["ep"]), fire["ep"])
    return {
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


def run_adaptation(prep, values, wind_mult, fb_coast, fb_river, base_by_scen,
                   flood_cap=None, fb_prain=None, fire_vuln=None):
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
                                    **kw)
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
                    fb_prain=None, fire_vuln=None):
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
                              fire_vuln=fire_vuln)
            aal[i] = r["acute"]["aal"] if r else 0.0
            var100[i] = r["acute"]["ep"][100] if r else 0.0
        central = eval_scenario(prep, app_key, values, wind_mult,
                                fb_coast, fb_river, flood_cap=flood_cap,
                                fb_prain=fb_prain, fire_vuln=fire_vuln)
        drivers = []
        for f in MC_FACTORS:
            lo = eval_scenario(prep, app_key, values, wind_mult, fb_coast,
                               fb_river, flood_cap=flood_cap,
                               fb_prain=fb_prain, fire_vuln=fire_vuln,
                               **{_MC_KW[f["key"]]: f["lo"]})
            hi = eval_scenario(prep, app_key, values, wind_mult, fb_coast,
                               fb_river, flood_cap=flood_cap,
                               fb_prain=fb_prain, fire_vuln=fire_vuln,
                               **{_MC_KW[f["key"]]: f["hi"]})
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
                base_by_scen, fb_prain=None, fire_vuln=None,
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
    for p in calib_parts:                      # bias uses the PUBLISHED curve
        base = (base or 0.0)
        w = p.get("wind")
        if w is not None and w["int"].size:
            wl = wind_losses(w["int"], p["values"], p["wind_mult"])
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

def fetch_river_flood_hazards(iso3, app_key, meta):
    """Ensemble of river_flood Hazard OBJECTS (not grids) for one scenario."""
    from climada.util.api_client import Client
    client = Client()
    infos = client.list_dataset_infos("river_flood",
                                      properties={"country_iso3alpha": iso3})
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
                       fire_enabled=True, rain_enabled=True):
    """Fetch hazards once per country and reduce them to per-site intensity
    matrices (the pure structure eval_scenario consumes)."""
    lat = sites_c["latitude"].to_numpy(float)
    lon = sites_c["longitude"].to_numpy(float)
    prep = {"wind": {}, "surge": {}, "rflood": {}, "_outside": set()}
    wind_dist = None                 # per-site km to the wind grid, the
                                     # reference the water-layer snap guards on

    for source in rh.unique_sources(rh.APP_SCENARIOS):
        skey = rh.source_key(source)
        try:
            haz = rh.fetch_wind(iso3, source, meta)
        except Exception as exc:
            LOG.warning("Skipping wind source %s / %s: %s", iso3, skey, exc)
            meta["skipped"].append({"country": iso3, "source": skey,
                                    "layer": "tc", "reason": str(exc)[:300]})
            continue
        idx, dist = nearest_centroids(lat, lon, haz.centroids.lat,
                                      haz.centroids.lon)
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
        prep["wind"][skey] = {"freq": np.asarray(haz.frequency, float),
                              "int": site_intensity(haz, idx)}
        LOG.info("  wind %s / %s -> %d events x %d sites", iso3, skey,
                 *prep["wind"][skey]["int"].shape)

        if surge_enabled:
            for app_key, recipe in rh.APP_SCENARIOS.items():
                if not any(rh.source_key(s) == skey for _w, s in recipe):
                    continue
                try:
                    surge = rh.compute_surge(haz, rh.SLR_M[app_key])
                    sidx = water_snap(lat, lon, surge.centroids.lat,
                                      surge.centroids.lon, wind_dist)
                    prep["surge"][(skey, app_key)] = {
                        "int": site_intensity(surge, sidx)}
                    del surge
                except Exception as exc:
                    LOG.warning("Surge failed %s / %s @ %s: %s",
                                iso3, skey, app_key, exc)
                    meta["skipped"].append({"country": iso3, "source": skey,
                                            "scenario": app_key,
                                            "layer": "cflood",
                                            "reason": str(exc)[:300]})
        del haz
        gc.collect()

    if river_enabled:
        for app_key in rh.APP_SCENARIOS:
            fetch_failed = False
            try:
                members = fetch_river_flood_hazards(iso3, app_key, meta)
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
                               "int": site_intensity(mhaz, midx)})
            if packed:
                prep["rflood"][app_key] = packed
            elif not fetch_failed:      # empty result; failure already recorded
                meta["skipped"].append({"country": iso3, "scenario": app_key,
                                        "layer": "rflood",
                                        "reason": "no river_flood dataset"})

    if fire_enabled:
        try:
            fhaz = rw.fetch_wildfire_hazard(iso3)
            fidx, _fd = nearest_centroids(lat, lon, fhaz.centroids.lat,
                                          fhaz.centroids.lon)
            prep["wfire"] = {"freq": np.asarray(fhaz.frequency, float),
                             "hits": site_intensity(fhaz, fidx) > 0}
            LOG.info("  wfire %s -> %d events x %d sites", iso3,
                     *prep["wfire"]["hits"].shape)
        except Exception as exc:
            LOG.warning("Wildfire unavailable %s: %s", iso3, str(exc)[:200])
            meta["skipped"].append({"country": iso3, "layer": "wfire",
                                    "reason": str(exc)[:300]})
    if rain_enabled:
        try:
            rhz = rpn.rain_hazard(rpn.fetch_tracks(iso3), iso3)
            ridx, _rd = nearest_centroids(lat, lon, rhz.centroids.lat,
                                          rhz.centroids.lon)
            prep["prain"] = {"freq": np.asarray(rhz.frequency, float),
                             "int": site_intensity(rhz, ridx)}
            LOG.info("  prain %s -> %d events x %d sites", iso3,
                     *prep["prain"]["int"].shape)
        except Exception as exc:
            LOG.warning("Rainfall unavailable %s: %s", iso3, str(exc)[:200])
            meta["skipped"].append({"country": iso3, "layer": "prain",
                                    "reason": str(exc)[:300]})
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
            for r, n, iso3 in zip(results, site_counts, countries):
                p = r.get(app_key)
                if p is not None and peril not in p:      # legacy 3-peril dict
                    p = None if peril in ("prain", "wfire") else p
                if p is None:
                    eads.append(np.zeros(n))
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
            combined[peril] = {"aal": aal, "ep": ep,
                               "ead": np.concatenate(eads)}
        out[app_key] = combined
    return out


def build_pack(scen_results, site_names, site_values, adaptation, uncertainty,
               sites_file):
    scenarios = {}
    for app_key, r in scen_results.items():
        per_site = [{"name": n,
                     "direct_ead_usd": round(float(r["acute"]["ead"][i]), 2),
                     "by_peril": {p: round(float(r[p]["ead"][i]), 2)
                                  for p in ("tc", "cflood", "rflood",
                                            "prain", "wfire") if p in r}}
                    for i, n in enumerate(site_names)]
        scenarios[app_key] = {
            "portfolio": {
                "direct_aal_usd": round(r["acute"]["aal"], 2),
                "by_peril_aal_usd": {p: round(r[p]["aal"], 2)
                                     for p in ("tc", "cflood", "rflood",
                                               "prain", "wfire") if p in r},
                "ep_usd": {str(rp): round(r["acute"]["ep"][rp], 2)
                           for rp in RPS},
            },
            "per_site": per_site,
        }
    return {
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
                                  f"V_HALF={V_HALF} m/s, x construction/age factor",
                          "flood": "1-exp(-0.6 x depth over freeboard), cap 0.75; "
                                   f"freeboard cflood {FB_COAST} m / rflood "
                                   f"{FB_RIVER} m, +0.5 m if defended"},
        "combination_rules": {
            "wind_surge": "per event (shared catalog, truly joint)",
            "river_flood": "comonotonic (exceedance losses add at equal RP)",
            "tc_rainfall": "comonotonic (own track catalog; Clausius-"
                           "Clapeyron scenario scaling)",
            "wildfire": "comonotonic (own fire seasons; warming scales the "
                        "fire frequency, not the loss)",
            "countries": "comonotonic (exceedance losses add at equal RP)",
            "ep_tail": "flat beyond the largest simulated return period"},
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
    # six-field behavior exactly (pinned by tests)
    for c in ("construction", "year_built", "roof_type", "roof_year",
              "opening_protection", "first_floor_elev_m", "stories", "keys",
              "buildings", "fema_zone", "backup_power", "renovation_year",
              "wui_class", "defensible_space_m"):
        if c not in df.columns:
            df[c] = None
    for c in ("defended", "equipment_elevated", "roof_class_a"):
        if c not in df.columns:
            df[c] = False
        df[c] = df[c].map(
            lambda x: str(x).strip().lower() in ("true", "1", "yes", "y"))
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
    ap.add_argument("--no-fire", action="store_true",
                    help="skip the wildfire event layer in the pack")
    ap.add_argument("--no-rain", action="store_true",
                    help="skip the TC rainfall event layer in the pack")
    ap.add_argument("--budget", type=float, default=None, metavar="USD",
                    help="annual capex budget for the phased capital plan")
    ap.add_argument("--backtest", default=None, metavar="CSV",
                    help="observed-loss CSV (name, observed_annual_loss_usd): "
                         "fits v_half and records it in the pack, not applied")
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

    sites = load_sites(args.sites)
    LOG.info("Loaded %d sites from %s", len(sites), args.sites)
    meta = {"skipped": [], "wind_sources": {}, "_countries": set()}

    per_country, order = [], []
    calib_parts, matched_names = [], set()
    for iso3, sites_c in sites.groupby("country", sort=True):
        meta["_countries"].add(iso3)
        LOG.info("Country %s: %d site(s)", iso3, len(sites_c))
        prep = build_country_prep(iso3, sites_c, surge_enabled,
                                  not args.no_river, meta,
                                  fire_enabled=not args.no_fire,
                                  rain_enabled=not args.no_rain)
        values = sites_c["asset_value_usd"].to_numpy(float)
        vulns = [vuln_v2(r.construction, r.year_built, r.defended,
                         roof_type=r.roof_type, roof_year=r.roof_year,
                         opening_protection=r.opening_protection,
                         first_floor_elev_m=r.first_floor_elev_m,
                         equipment_elevated=r.equipment_elevated)
                 for r in sites_c.itertuples()]
        wm = np.array([v[0] for v in vulns])
        fbb = np.array([v[1] for v in vulns])
        fcap = np.array([v[2] for v in vulns])
        fvuln = np.array([fire_vuln_of(r.roof_class_a, r.defensible_space_m)
                          for r in sites_c.itertuples()])
        fb_coast = FB_COAST + fbb
        fbp = np.full(len(sites_c), PRAIN_FB) + fbb
        fb_river = FB_RIVER + fbb
        scen = {}
        for app_key in rh.APP_SCENARIOS:
            r = eval_scenario(prep, app_key, values, wm, fb_coast, fb_river,
                              flood_cap=fcap, fb_prain=fbp, fire_vuln=fvuln)
            if r is not None:
                scen[app_key] = r
        base_keys = {"present"} | set(UNCERTAINTY_SCENARIOS)
        adaptation = run_adaptation(prep, values, wm, fb_coast, fb_river,
                                    {k: v for k, v in scen.items()
                                     if k in base_keys}, flood_cap=fcap,
                                    fb_prain=fbp, fire_vuln=fvuln)
        uncertainty = run_uncertainty(prep, values, wm, fb_coast, fb_river,
                                      [k for k in UNCERTAINTY_SCENARIOS
                                       if k in scen],
                                      args.mc, args.seed, flood_cap=fcap,
                                      fb_prain=fbp, fire_vuln=fvuln)
        if backtest is not None and "present" in scen:
            mask = sites_c["name"].astype(str).isin(backtest.index).to_numpy()
            if mask.any():
                wp = prep["wind"].get("present")
                calib_parts.append({
                    "wind": None if wp is None else
                        {"freq": wp["freq"], "int": wp["int"][:, mask]},
                    "values": values[mask], "wind_mult": wm[mask],
                    "flood_fixed": float(sum(
                        np.asarray(scen["present"][z]["ead"])[mask].sum()
                        for z in ("cflood", "rflood", "prain", "wfire")
                        if z in scen["present"]))})
                matched_names.update(sites_c.loc[mask, "name"].astype(str))
        cat_section, cat_projects, cat_sc = run_catalog(
            prep, sites_c, values, wm, fb_coast, fb_river, fcap,
            {k: v for k, v in scen.items() if k in base_keys},
            fb_prain=fbp, fire_vuln=fvuln)
        per_country.append({"scen": scen, "adaptation": adaptation,
                            "catalog": cat_section,
                            "cat_projects": cat_projects, "cat_sc": cat_sc,
                            "sites_df": sites_c,
                            "uncertainty": uncertainty, "iso3": iso3,
                            "names": list(sites_c["name"]), "values": values})
        order.extend(sites_c["name"])

    if not per_country or not any(c["scen"] for c in per_country):
        LOG.error("No impacts produced. Check network access and the sites file.")
        return 1

    combined = combine_countries([c["scen"] for c in per_country],
                                 [len(c["names"]) for c in per_country],
                                 [c["iso3"] for c in per_country], meta)
    # single-country portfolios keep their exact adaptation and uncertainty;
    # multi-country runs report the value-weighted country with a meta note
    lead = max(per_country, key=lambda c: float(c["values"].sum()))
    if len(per_country) > 1:
        meta["note_adaptation_uncertainty"] = (
            "adaptation and uncertainty sections reflect the largest country "
            "by value; per-country expansion is a step-2 item")
    pack = build_pack(combined, order,
                      np.concatenate([c["values"] for c in per_country]),
                      lead["adaptation"], lead["uncertainty"], args.sites)
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
