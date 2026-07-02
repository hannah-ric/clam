"""
measures_catalog.py  (adaptation-first increment 2)
====================================================

The realistic measure catalog: data-as-code, pure, unit-tested. Each measure
declares WHO it applies to (a predicate on the v2 building profile, with a
plain-language reason when it does not), WHAT it changes (per-site knob
arrays for the shared eval_scenario code path, derived where possible from
the vuln_v2 factor table itself so a measure's benefit is exactly the factor
delta it would cause), and WHAT it costs (per key when `keys` is known, else
a value-percent fallback), plus lifecycle attributes for honest BCR math:
lifespan, lead time, guest-disruption downtime, and an insurance
premium-credit hook (0 until a broker quote fills it).

Measures whose benefit the pipeline cannot yet model (wildfire ahead of its
hazard layer, continuity measures that act on the app's financial layer) are
still IDENTIFIED per site: modeled=False entries surface in the pack so the
exposure is visible before it is priceable. Never silently absent.

Screening-grade cost figures; every number is a named constant with a note.
Replace with quoted costs per site as they arrive (operator columns win).
"""

from __future__ import annotations

import numpy as np

import refresh_impacts as ri

RENOV_SYNERGY = 0.85          # cost factor when bundled with a planned
                              # refurbishment (mobilization already paid)
RENOV_WINDOW_YEARS = 3        # renovation_year within this window qualifies
PLAN_YEARS = 3                # the short-term capital plan horizon


def _num(x):
    return ri._num(x)


def _profile_windmult(row, **overrides):
    """vuln_v2 wind multiplier for a profile row with optional overrides:
    the catalog derives retrofit effects from the factor table itself."""
    f = {"construction": row.get("construction"),
         "year_built": row.get("year_built"),
         "defended": bool(row.get("defended")),
         "roof_type": row.get("roof_type"),
         "roof_year": row.get("roof_year"),
         "opening_protection": row.get("opening_protection")}
    f.update(overrides)
    return ri.vuln_v2(f["construction"], f["year_built"], f["defended"],
                      roof_type=f["roof_type"], roof_year=f["roof_year"],
                      opening_protection=f["opening_protection"])[0]


def _cost(row, per_key_usd, pct_value_fallback):
    """Per-key cost when `keys` is known, else the percent-of-value proxy."""
    keys = _num(row.get("keys"))
    if keys and keys > 0:
        return float(keys) * per_key_usd
    return float(row.get("asset_value_usd") or 0.0) * pct_value_fallback / 100.0


# ---------------------------------------------------------------------------
# The catalog. `applies(row, ead)` -> (bool, reason); `effect(row)` -> dict of
# per-site scalar knobs for eval_scenario; `cost(row)` -> usd.
# `ead` is the site's base by-peril EAD dict {"tc","cflood","rflood"}.
# ---------------------------------------------------------------------------

def _reroof_applies(row, ead):
    rt = ri._txt(row.get("roof_type"))
    ry = _num(row.get("roof_year"))
    if rt is None and ry is None:
        return False, "needs roof profile data (roof_type or roof_year)"
    base = _profile_windmult(row)
    new = _profile_windmult(row, roof_type="metal",
                            roof_year=ri.ROOF_AGE_REF_YEAR)
    if new >= base - 1e-9:
        return False, "roof already at or near best practice"
    return True, ""


def _reroof_effect(row):
    base = _profile_windmult(row)
    new = _profile_windmult(row, roof_type="metal",
                            roof_year=ri.ROOF_AGE_REF_YEAR)
    return {"wind_dmg_mult": new / base}


def _openings_applies(row, ead):
    op = ri._txt(row.get("opening_protection"))
    if op is None:
        return False, "needs opening_protection profile data"
    if op == "impact":
        return False, "openings already impact-rated"
    return True, ""


def _openings_effect(row):
    base = _profile_windmult(row)
    new = _profile_windmult(row, opening_protection="impact")
    return {"wind_dmg_mult": new / base}


def _utility_applies(row, ead):
    if bool(row.get("equipment_elevated")):
        return False, "critical systems already elevated"
    if ead["cflood"] + ead["rflood"] <= ri.SCOPE_EAD_USD:
        return False, "no material flood exposure"
    return True, ""


def _floodproof_applies(row, ead):
    if ead["cflood"] + ead["rflood"] <= ri.SCOPE_EAD_USD:
        return False, "no material flood exposure"
    return True, ""


def _elevation_applies(row, ead):
    stories = _num(row.get("stories"))
    if stories is None:
        return False, "needs stories profile data"
    if stories > 2:
        return False, "multi-story structure cannot be elevated"
    if ead["cflood"] + ead["rflood"] <= ri.SCOPE_EAD_USD:
        return False, "no material flood exposure"
    return True, ""


def _buffer_applies(row, ead):
    if ead["cflood"] <= ri.SCOPE_EAD_USD:
        return False, "no material coastal-flood exposure"
    return True, ""


def _wui(row):
    return ri._txt(row.get("wui_class")) in ("interface", "intermix")


CATALOG = [
    # -- modeled: wind ---------------------------------------------------------
    {"key": "reroof", "name": "Re-roof to rated metal system",
     "peril": "wind", "modeled": True,
     "applies": _reroof_applies, "effect": _reroof_effect,
     "cost": lambda row: _cost(row, per_key_usd=9000, pct_value_fallback=2.0),
     "lifespan_years": 40, "lead_time_months": 9,
     "downtime_room_nights_per_key": 2, "premium_credit_pct": 0.0,
     "note": "effect derived from the vuln_v2 factor table (metal, new)"},
    {"key": "openings", "name": "Impact-rated openings (windows & doors)",
     "peril": "wind", "modeled": True,
     "applies": _openings_applies, "effect": _openings_effect,
     "cost": lambda row: _cost(row, per_key_usd=6500, pct_value_fallback=1.2),
     "lifespan_years": 30, "lead_time_months": 6,
     "downtime_room_nights_per_key": 1, "premium_credit_pct": 0.0,
     "note": "effect derived from the vuln_v2 factor table (impact)"},
    {"key": "tiedown", "name": "Roof-to-wall connection retrofit",
     "peril": "wind", "modeled": True,
     "applies": lambda row, ead: ((True, "") if
        str(row.get("construction") or "").lower() in ("frame", "masonry")
        and (_num(row.get("year_built")) or 0) < 2002
        else (False, "engineered or post-2002 construction")),
     "effect": lambda row: {"wind_dmg_mult": 0.85},
     "cost": lambda row: _cost(row, per_key_usd=2500, pct_value_fallback=0.5),
     "lifespan_years": 50, "lead_time_months": 4,
     "downtime_room_nights_per_key": 1, "premium_credit_pct": 0.0,
     "note": "screening factor 0.85 for pre-2002 frame/masonry"},
    # -- modeled: flood --------------------------------------------------------
    {"key": "floodproof", "name": "Dry floodproofing (barriers & sealing)",
     "peril": "flood", "modeled": True,
     "applies": _floodproof_applies,
     "effect": lambda row: {"fb_bonus": 0.5},
     "cost": lambda row: _cost(row, per_key_usd=1800, pct_value_fallback=0.6),
     "lifespan_years": 25, "lead_time_months": 4,
     "downtime_room_nights_per_key": 0, "premium_credit_pct": 0.0,
     "note": "the legacy flood measure, now scope-priced"},
    {"key": "utility", "name": "Critical systems elevation",
     "peril": "flood", "modeled": True,
     "applies": _utility_applies,
     "effect": lambda row: {"flood_cap": ri.EQUIP_ELEV_FLOOD_CAP},
     "cost": lambda row: _cost(row, per_key_usd=1200, pct_value_fallback=0.35),
     "lifespan_years": 30, "lead_time_months": 6,
     "downtime_room_nights_per_key": 0, "premium_credit_pct": 0.0,
     "note": "caps flood MDD at 0.5: the deep-water tail"},
    {"key": "elevate", "name": "First-floor elevation (low-rise only)",
     "peril": "flood", "modeled": True,
     "applies": _elevation_applies,
     "effect": lambda row: {"fb_bonus": 1.5},
     "cost": lambda row: _cost(row, per_key_usd=25000, pct_value_fallback=6.0),
     "lifespan_years": 50, "lead_time_months": 18,
     "downtime_room_nights_per_key": 30, "premium_credit_pct": 0.0,
     "note": "structures over 2 stories excluded by applicability"},
    {"key": "buffer", "name": "Coastal buffer (dune & mangrove)",
     "peril": "cflood", "modeled": True,
     "applies": _buffer_applies,
     "effect": lambda row: {"cf_depth_red": 0.3},
     "cost": lambda row: _cost(row, per_key_usd=1500, pct_value_fallback=0.4),
     "lifespan_years": 20, "lead_time_months": 12,
     "downtime_room_nights_per_key": 0, "premium_credit_pct": 0.0,
     "note": "the legacy buffer measure, now scope-priced"},
    # -- identified, not yet priced for benefit --------------------------------
    {"key": "defensible", "name": "Defensible space (wildfire)",
     "peril": "wildfire", "modeled": False,
     "applies": lambda row, ead: ((True, "") if _wui(row)
        and (_num(row.get("defensible_space_m")) or 0) < 30
        else (False, "not in the wildland-urban interface, or space adequate")),
     "cost": lambda row: _cost(row, per_key_usd=400, pct_value_fallback=0.1),
     "lifespan_years": 10, "lead_time_months": 3,
     "downtime_room_nights_per_key": 0, "premium_credit_pct": 0.0,
     "note": "appraised live in the app (v1.12 wildfire peril); "
             "pack-side pricing awaits wfire in the results pack"},
    {"key": "roof_class_a", "name": "Class A roof assembly (wildfire)",
     "peril": "wildfire", "modeled": False,
     "applies": lambda row, ead: ((True, "") if _wui(row)
        and not bool(row.get("roof_class_a"))
        else (False, "not in the wildland-urban interface, or already Class A")),
     "cost": lambda row: _cost(row, per_key_usd=3000, pct_value_fallback=0.8),
     "lifespan_years": 40, "lead_time_months": 9,
     "downtime_room_nights_per_key": 2, "premium_credit_pct": 0.0,
     "note": "appraised live in the app (v1.12 wildfire peril); "
             "pack-side pricing awaits wfire in the results pack"},
    {"key": "backup_power", "name": "Backup power (full-site generation)",
     "peril": "continuity", "modeled": False,
     "applies": lambda row, ead: ((True, "") if
        ri._txt(row.get("backup_power")) in (None, "none", "no", "false", "0",
                                             "partial")
        else (False, "full backup power already present")),
     "cost": lambda row: _cost(row, per_key_usd=2200, pct_value_fallback=0.5),
     "lifespan_years": 20, "lead_time_months": 8,
     "downtime_room_nights_per_key": 0, "premium_credit_pct": 0.0,
     "note": "acts on business interruption: appraised in the app's "
             "financial layer, identified here"},
]


def catalog_effects(sites_df, ead_by_peril, measure):
    """Per-site knob arrays + in-scope mask + exclusion reasons for one
    modeled measure. Neutral knobs outside scope (benefit and cost always
    cover the same sites)."""
    n = len(sites_df)
    mask = np.zeros(n, dtype=bool)
    reasons = []
    knobs = {"wind_dmg_mult": np.ones(n), "fb_bonus": np.zeros(n),
             "cf_depth_red": np.zeros(n),
             "flood_cap": np.full(n, np.nan)}       # nan = keep site's own cap
    costs = np.zeros(n)
    for i, (_, row) in enumerate(sites_df.iterrows()):
        r = row.to_dict()
        ead = {p: float(ead_by_peril[p][i]) for p in ("tc", "cflood", "rflood")}
        okay, reason = measure["applies"](r, ead)
        reasons.append(reason)
        if not okay:
            continue
        mask[i] = True
        costs[i] = measure["cost"](r)
        if "effect" in measure:            # identified-only measures have none
            for k, val in measure["effect"](r).items():
                knobs[k][i] = val
    return mask, knobs, costs, reasons


def phase_projects(projects, sites_df, budget_annual_usd=None):
    """Assign each funded project a year 1..PLAN_YEARS.

    Rules, in order: a project whose site has renovation_year inside the
    window gets that year and the RENOV_SYNERGY cost discount (mobilization
    shared with the refurbishment); remaining projects fill years greedily by
    BCR under the annual budget when one is given (else year 1); projects
    that fit no year are kept with year null and deferred=true, never
    silently dropped. Returns the projects list (mutated copies) sorted by
    (year nulls last, then BCR desc)."""
    renov = {}
    for _, row in sites_df.iterrows():
        ry = _num(row.get("renovation_year"))
        if ry and 0 < ry - ri.ROOF_AGE_REF_YEAR + 1 <= RENOV_WINDOW_YEARS + 1:
            renov[str(row["name"])] = int(ry - ri.ROOF_AGE_REF_YEAR + 1)
    spent = {y: 0.0 for y in range(1, PLAN_YEARS + 1)}
    out = []
    for p in projects:                     # already BCR-descending
        q = dict(p)
        year = renov.get(q["site"])
        if year is not None and 1 <= year <= PLAN_YEARS:
            q["cost_usd"] = round(q["cost_usd"] * RENOV_SYNERGY, 2)
            q["renovation_synergy"] = True
        cost = q["cost_usd"]
        if budget_annual_usd is None:
            q["year"] = year if year is not None else 1
            spent[q["year"]] = spent.get(q["year"], 0.0) + cost
        else:
            candidates = ([year] if year is not None
                          else list(range(1, PLAN_YEARS + 1)))
            placed = None
            for y in candidates:
                if spent[y] + cost <= budget_annual_usd:
                    placed = y
                    break
            if placed is None and year is not None:
                for y in range(1, PLAN_YEARS + 1):   # renovation year full:
                    if spent[y] + cost <= budget_annual_usd:
                        placed = y                   # any year beats deferred
                        break
            if placed is None:
                q["year"] = None
                q["deferred"] = True
            else:
                q["year"] = placed
                spent[placed] += cost
        out.append(q)
    out.sort(key=lambda q: (q["year"] is None, -q["bcr"]))
    return out
