"""
assumptions.py : the single sourced scenario-assumptions registry
==================================================================

Every scenario constant the pipeline and the browser app SHARE lives here,
once: the WARMING table, the (now regional) sea-level-rise tables, the
scenario-scaling scalars, and the appraisal convention. Before this module
the WARMING table was hand-mirrored in four files and SLR in two, guarded
only by a parity test; now the producers import this module and the app
embeds a GENERATED module (app/src/05_assumptions.js) written by

    python assumptions.py --write-app      # regenerate after ANY edit here
    python assumptions.py --check          # CI gate: generated file in sync

Every entry carries value, units, baseline period, and a source citation.
Where the effective number deliberately sits above the AR6 central estimate,
the offset is stored as an EXPLICIT conservative_delta with a reason, never
a silently higher number: effective value == ar6_central + conservative_delta
by construction (asserted in tests/test_warming_parity.py).

Sea-level rise is REGIONAL: relative sea level differs materially across the
portfolio's coastlines (Gulf subsidence most of all), so each coastline gets
its own table (AR6 global-mean central + explicit delta, scaled by a NOAA
2022 regional factor). Points outside every region box read the global-mean
table, which equals the legacy single table exactly.

The appraisal convention is unified here at 3% real / 25 years (the results
pack's convention). The app's sliders stay adjustable; only their defaults
read this registry, so pack and app BCRs are comparable out of the box.
"""

from __future__ import annotations

import json

ASSUMPTIONS_VERSION = "1"       # bump when any effective value changes

SCEN_KEYS = ["present"] + [f"{p}_{h}" for h in (2030, 2050, 2080)
                           for p in ("ssp126", "ssp245", "ssp585")]

# ---------------------------------------------------------------------------
# Warming (deg C of global-mean surface temperature above the 1995-2014
# baseline, which the app labels "present"). AR6 central per IPCC AR6 WG1
# Table 4.1 (GSAT change relative to 1995-2014; near-term 2021-2040 read at
# 2030, mid-term 2041-2060 at 2050, long-term 2081-2100 at 2080).
# ---------------------------------------------------------------------------

_WARMING_CITE = ("IPCC AR6 WG1 Table 4.1, GSAT change vs 1995-2014 "
                 "(central estimate; 2021-2040 / 2041-2060 / 2081-2100 "
                 "windows read at the 2030 / 2050 / 2080 horizons)")
_WARMING_DELTA_REASON = (
    "conservative screening margin retained from v1: the app horizons are "
    "point years read against AR6 20-year windows, and the margin covers "
    "within-window trend plus model spread; kept explicit, not silent")

_WARMING_AR6 = {                     # (pathway, horizon) -> AR6 central
    ("ssp126", 2030): 0.6, ("ssp126", 2050): 0.9, ("ssp126", 2080): 0.9,
    ("ssp245", 2030): 0.7, ("ssp245", 2050): 1.1, ("ssp245", 2080): 1.8,
    ("ssp585", 2030): 0.8, ("ssp585", 2050): 1.5, ("ssp585", 2080): 3.5,
}
_WARMING_DELTA = {                   # explicit conservative offsets
    ("ssp126", 2030): 0.0, ("ssp126", 2050): 0.1, ("ssp126", 2080): 0.4,
    ("ssp245", 2030): 0.0, ("ssp245", 2050): 0.3, ("ssp245", 2080): 0.5,
    ("ssp585", 2030): 0.0, ("ssp585", 2050): 0.5, ("ssp585", 2080): 0.1,
}

WARMING = {"present": {
    "value": 0.0, "ar6_central": 0.0, "conservative_delta": 0.0,
    "units": "degC above the 1995-2014 baseline",
    "baseline": "1995-2014", "citation": _WARMING_CITE,
    "delta_reason": "present day is the baseline by definition"}}
for (_p, _h), _c in _WARMING_AR6.items():
    _d = _WARMING_DELTA[(_p, _h)]
    WARMING[f"{_p}_{_h}"] = {
        "value": round(_c + _d, 6), "ar6_central": _c,
        "conservative_delta": _d,
        "units": "degC above the 1995-2014 baseline",
        "baseline": "1995-2014", "citation": _WARMING_CITE,
        "delta_reason": _WARMING_DELTA_REASON,
    }

WARMING_TABLE = {k: v["value"] for k, v in WARMING.items()}


def warming(scenario):
    """Effective warming (deg C above present) for an app scenario key."""
    return WARMING_TABLE.get(scenario, 0.0)


# ---------------------------------------------------------------------------
# Sea-level rise (m above the 1995-2014 baseline), REGIONAL.
# Global-mean central per IPCC AR6 WG1 Table 9.9 (GMSL, median; the 2080
# value interpolated between the 2050 and 2100 medians). The explicit
# conservative delta reproduces the legacy single table exactly, so the
# global-mean effective values are unchanged. Regional relative-SLR factors
# are screening-grade centrals from the NOAA 2022 Interagency Sea Level Rise
# Technical Report regional scenarios: the western/central Gulf runs well
# above GMSL (subsidence), the Southeast Atlantic moderately above, the
# Caribbean slightly above, Hawaii near GMSL.
# ---------------------------------------------------------------------------

_SLR_CITE = ("IPCC AR6 WG1 Table 9.9, GMSL rise vs 1995-2014 (median; 2080 "
             "interpolated between the 2050 and 2100 medians)")
_SLR_DELTA_REASON = (
    "conservative screening margin retained from v1 (roughly the 60-70th "
    "percentile of the AR6 likely range at the late horizons); kept "
    "explicit, not silent")
_SLR_REGION_CITE = ("NOAA 2022 Interagency Sea Level Rise Technical Report, "
                    "regional scenarios (screening-grade central factor on "
                    "the global-mean trajectory)")

_SLR_AR6_GMSL = {                    # (pathway, horizon) -> AR6 GMSL central
    ("ssp126", 2030): 0.09, ("ssp126", 2050): 0.19, ("ssp126", 2080): 0.31,
    ("ssp245", 2030): 0.09, ("ssp245", 2050): 0.20, ("ssp245", 2080): 0.37,
    ("ssp585", 2030): 0.10, ("ssp585", 2050): 0.23, ("ssp585", 2080): 0.48,
}
_SLR_DELTA = {                       # explicit conservative offsets (m)
    ("ssp126", 2030): 0.00, ("ssp126", 2050): 0.00, ("ssp126", 2080): 0.03,
    ("ssp245", 2030): 0.01, ("ssp245", 2050): 0.02, ("ssp245", 2080): 0.07,
    ("ssp585", 2030): 0.01, ("ssp585", 2050): 0.04, ("ssp585", 2080): 0.14,
}

# region -> (relative-SLR factor, one-line basis). global_mean is the
# fallback for any point outside every box and reproduces the legacy table.
SLR_REGION_FACTOR = {
    "gulf":             (1.35, "western/central Gulf subsidence raises "
                               "relative SLR well above GMSL"),
    "florida_atlantic": (1.15, "Southeast Atlantic sterodynamic + "
                               "subsidence moderately above GMSL"),
    "caribbean":        (1.05, "Puerto Rico / USVI slightly above GMSL"),
    "hawaii":           (1.00, "central Pacific near GMSL"),
    "global_mean":      (1.00, "AR6 global-mean trajectory (fallback)"),
}

# (name, lat_min, lat_max, lon_min, lon_max), FIRST MATCH WINS in this order
# (gulf and florida_atlantic share the lon=-82 edge; gulf claims it).
SLR_REGION_BOXES = [
    ("gulf",             24.0, 31.5, -100.5, -82.0),
    ("florida_atlantic", 24.0, 37.5,  -82.0, -74.0),
    ("hawaii",           18.0, 23.0, -161.0, -154.0),
    ("caribbean",        17.0, 19.5,  -68.0, -64.0),
]

SLR = {}
for _region, (_f, _why) in SLR_REGION_FACTOR.items():
    _tab = {"present": {
        "value": 0.0, "ar6_central": 0.0, "conservative_delta": 0.0,
        "regional_factor": _f,
        "units": "m above the 1995-2014 baseline",
        "baseline": "1995-2014",
        "citation": f"{_SLR_CITE}; regional factor: {_SLR_REGION_CITE} ({_why})",
        "delta_reason": "present day is the baseline by definition"}}
    for (_p, _h), _c in _SLR_AR6_GMSL.items():
        _d = _SLR_DELTA[(_p, _h)]
        _tab[f"{_p}_{_h}"] = {
            "value": round((_c + _d) * _f, 2), "ar6_central": _c,
            "conservative_delta": _d, "regional_factor": _f,
            "units": "m above the 1995-2014 baseline",
            "baseline": "1995-2014",
            "citation": f"{_SLR_CITE}; regional factor: {_SLR_REGION_CITE} ({_why})",
            "delta_reason": _SLR_DELTA_REASON,
        }
    SLR[_region] = _tab

SLR_TABLES = {r: {k: v["value"] for k, v in t.items()} for r, t in SLR.items()}


def slr_region_of(lat, lon):
    """SLR region name for one point; 'global_mean' outside every box."""
    for name, la0, la1, lo0, lo1 in SLR_REGION_BOXES:
        if la0 <= lat <= la1 and lo0 <= lon <= lo1:
            return name
    return "global_mean"


def slr_m(scenario, region="global_mean"):
    """Effective sea-level rise (m) for a scenario and region."""
    return SLR_TABLES.get(region, SLR_TABLES["global_mean"]).get(scenario, 0.0)


# ---------------------------------------------------------------------------
# Scenario-scaling scalars shared across producers and/or the app.
# ---------------------------------------------------------------------------

SCALARS = {
    "fire_warming_uplift_per_c": {
        "value": 0.14, "units": "fractional burn-probability increase per degC",
        "baseline": "present-day fire climatology",
        "citation": "fire-weather-day scaling, screening grade (cf. Jolly et "
                    "al. 2015; Abatzoglou & Williams 2016)"},
    "prain_cc_per_c": {
        "value": 0.07, "units": "fractional rainfall-intensity increase per degC",
        "baseline": "present-day TC rainfall climatology",
        "citation": "Clausius-Clapeyron moisture scaling, ~7%/degC (IPCC AR6 "
                    "WG1 Ch.11)"},
    "heat_land_amplification": {
        "value": 1.25, "units": "local land warming per unit GSAT warming",
        "baseline": "1995-2014",
        "citation": "AR6-consistent central land-amplification for the "
                    "portfolio latitudes (land warms faster than the global "
                    "mean; IPCC AR6 WG1 Ch.4)"},
    "tc_intensity_uplift_per_c": {
        "value": 0.02, "units": "fractional wind-intensity increase per degC "
                                "(the app's INTERIM TC field only)",
        "baseline": "present-day interim wind field",
        "citation": "screening scalar consistent with AR6 assessed TC "
                    "intensity trends (~+5% per 2-3 degC)"},
    "fire_cond_interim": {
        "value": 0.35, "units": "conditional structure damage ratio GIVEN "
                                "fire reaches the site point (interim flat "
                                "ratio, capped)",
        "baseline": "n/a",
        "citation": "interim cap pending a conditional-flame-length layer; "
                    "consistent with the expectation of the FIRE_CFL_DAMAGE "
                    "mapping at moderate flame lengths (USFS Wildfire Risk "
                    "to Communities, RDS-2020-0016). LABELED interim on the "
                    "trust surface; replaced per site wherever the CFL "
                    "raster is supplied"},
}

# Conditional flame length (ft, upper band edge) -> conditional structure
# damage ratio given fire reaches the point. Screening-grade step mapping on
# the standard fireline-intensity / suppression classes (Scott & Reinhardt
# 2001; home-ignition-zone literature): surface fire barely threatens a
# code-built resort structure, crowning fire mostly destroys it. This is the
# intensity-conditioned replacement for the retired flat FIRE_MDD=0.6, which
# stacked a near-total-loss assumption on top of cell-occupancy frequency.
FIRE_CFL_DAMAGE = {
    "bands_ft": [2.0, 4.0, 8.0, 12.0],
    "ratios": [0.02, 0.10, 0.30, 0.55, 0.80],
    "units": "conditional structure damage ratio by flame-length band (ft)",
    "baseline": "n/a",
    "citation": "flame-length suppression/intensity classes (Scott & "
                "Reinhardt 2001) mapped to screening structure-loss ratios; "
                "driven by the USFS WRC Conditional Flame Length layer "
                "(RDS-2020-0016)",
}


def cfl_to_damage(cfl_ft):
    """Conditional damage ratio(s) for flame length(s) in feet (vectorized).
    Values at or below a band edge take that band's ratio; beyond the last
    edge takes the top ratio."""
    import numpy as np
    cfl = np.asarray(cfl_ft, float)
    idx = np.searchsorted(np.asarray(FIRE_CFL_DAMAGE["bands_ft"], float),
                          cfl, side="left")
    return np.asarray(FIRE_CFL_DAMAGE["ratios"], float)[idx]


def scalar(key):
    return SCALARS[key]["value"]


# ---------------------------------------------------------------------------
# Resort structural ARCHETYPES: differentiated vulnerability-curve settings.
# The archetype describes structural FORM and siting and acts on the CURVES
# (the wind curve's half-damage speed, the flood freeboard, the flood damage
# cap); the existing profile factor table (construction, roof, openings,
# first-floor height, equipment elevation) stays the mapping layer for
# envelope CONDITION and keeps multiplying on top, so the two compose
# without either replacing the other.
#
# The default is the low-rise timber archetype, which IS the published
# emanuel_usa-parameter curve: an absent or unknown archetype reproduces
# today's numbers exactly (pinned by tests), so existing profiles do not
# break. Screening-grade values; the wind shifts follow the ordering of the
# HAZUS-MH hurricane building classes (wood frame worst, engineered concrete
# towers best), the flood adjustments are siting/plant-location judgments.
#
#   v_half_mult : multiplies the Emanuel curve's half-damage speed V_HALF
#                 (>1 = stronger structure, curve shifts right)
#   fb_add_m    : metres added to the effective flood/surge/rain freeboard
#                 (negative = beachfront wave exposure defeats freeboard)
#   flood_cap   : overrides the max flood damage ratio (None = profile's own
#                 cap; site-measured equipment_elevated still wins downward)
# ---------------------------------------------------------------------------

_ARCH_CITE = ("HAZUS-MH hurricane model building classes (relative wind "
              "fragility ordering) and USACE/FEMA depth-damage practice for "
              "the flood-side siting adjustments; screening grade")

ARCHETYPES = {
    "lowrise_timber": {
        "v_half_mult": 1.0, "fb_add_m": 0.0, "flood_cap": None,
        "label": "Low-rise timber frame",
        "basis": "the published emanuel_usa-parameter curve IS this "
                 "archetype; absent/unknown archetypes reproduce it exactly"},
    "lowrise_masonry": {
        "v_half_mult": 1.08, "fb_add_m": 0.0, "flood_cap": None,
        "label": "Low-rise masonry",
        "basis": "masonry envelope survives higher winds than timber "
                 "(HAZUS class ordering)"},
    "midrise_concrete": {
        "v_half_mult": 1.18, "fb_add_m": 0.0, "flood_cap": None,
        "label": "Mid-rise concrete frame (4-7 stories)",
        "basis": "engineered concrete frame; wind loss driven by envelope, "
                 "not structure"},
    "tower_concrete": {
        "v_half_mult": 1.30, "fb_add_m": 0.0, "flood_cap": 0.5,
        "label": "High-rise concrete tower",
        "basis": "cladding/glazing-dominated wind loss well below timber; "
                 "flood reaches only the podium and ground-floor systems, "
                 "capping the damageable share"},
    "beachfront_lowrise": {
        "v_half_mult": 0.95, "fb_add_m": -0.3, "flood_cap": None,
        "label": "Beachfront low-rise",
        "basis": "open-coast exposure and salt fatigue lower the wind "
                 "threshold; wave setup and run-up defeat part of the "
                 "nominal freeboard"},
    "setback_elevated": {
        "v_half_mult": 1.0, "fb_add_m": 0.5, "flood_cap": None,
        "label": "Set-back / elevated siting",
        "basis": "siting above base flood elevation and back from the "
                 "water adds effective freeboard"},
    "mep_basement": {
        "v_half_mult": 1.0, "fb_add_m": -0.2, "flood_cap": 0.9,
        "label": "Critical plant in basement",
        "basis": "water reaches MEP early (lower effective freeboard) and "
                 "basement plant drives near-total service loss in deep "
                 "water (higher cap)"},
    "mep_elevated_plant": {
        "v_half_mult": 1.0, "fb_add_m": 0.0, "flood_cap": 0.5,
        "label": "Critical plant elevated",
        "basis": "elevated MEP caps the flood damage ratio, mirroring the "
                 "equipment_elevated profile field at archetype level"},
}
for _k, _a in ARCHETYPES.items():
    _a["citation"] = _ARCH_CITE
DEFAULT_ARCHETYPE = "lowrise_timber"


def archetype_of(value):
    """The archetype entry for a raw field value; absent/unknown values map
    to the default (current behavior), so existing profiles never break."""
    key = str(value).strip().lower() if value is not None else ""
    return ARCHETYPES.get(key, ARCHETYPES[DEFAULT_ARCHETYPE])


# ---------------------------------------------------------------------------
# Appraisal convention (unified: the results pack's 3% real / 25 years).
# The app's sliders stay adjustable; their DEFAULTS read this registry.
# ---------------------------------------------------------------------------

APPRAISAL = {
    "discount_rate": {
        "value": 0.03, "units": "real annual discount rate (fraction)",
        "baseline": "n/a",
        "citation": "screening convention aligned with the results pack; 3% "
                    "real is conservative for benefit annuities (higher than "
                    "OMB Circular A-4 2023's 2.0% central), so BCRs are not "
                    "flattered"},
    "horizon_years": {
        "value": 25, "units": "years of averted loss counted",
        "baseline": "n/a",
        "citation": "matches the pack's annuity cap min(measure lifespan, "
                    "25): benefits beyond 25 years are not credited"},
}


def appraisal_defaults():
    """(discount_rate fraction, horizon_years) for both pack and app."""
    return APPRAISAL["discount_rate"]["value"], APPRAISAL["horizon_years"]["value"]


# ---------------------------------------------------------------------------
# App code generation. The offline single-file app cannot import Python, so
# the shared constants are emitted as a generated JS module the assembler
# embeds (app/src/05_assumptions.js). Deterministic output (no timestamps),
# byte-compared in CI so the app can never drift from this registry.
# ---------------------------------------------------------------------------

def _js(obj):
    return json.dumps(obj, separators=(",", ":"), sort_keys=False)


def to_app_js():
    warming_js = {k: WARMING[k]["value"] for k in SCEN_KEYS}
    slr_regions_js = {r: {k: SLR_TABLES[r][k] for k in SCEN_KEYS}
                      for r in SLR_TABLES}
    boxes_js = [[n, la0, la1, lo0, lo1]
                for n, la0, la1, lo0, lo1 in SLR_REGION_BOXES]
    disc, horizon = APPRAISAL["discount_rate"]["value"], \
        APPRAISAL["horizon_years"]["value"]
    return (
        "\n/* ============================================================\n"
        "   GENERATED FILE - DO NOT EDIT.\n"
        "   Source: pipeline/assumptions.py (the single sourced scenario-\n"
        "   assumptions registry: every value there carries units, baseline\n"
        "   period, citation, and any explicit conservative delta vs the\n"
        "   AR6 central estimate). Regenerate with:\n"
        "       python pipeline/assumptions.py --write-app\n"
        "   ============================================================ */\n"
        f"const ASSUMPTIONS_VERSION={_js(ASSUMPTIONS_VERSION)};\n"
        "// degC above the 1995-2014 baseline; AR6 WG1 Table 4.1 central +\n"
        "// explicit conservative delta (see the registry for per-entry detail)\n"
        f"const WARMING={_js(warming_js)};\n"
        "// m above the 1995-2014 baseline, REGIONAL: AR6 Table 9.9 GMSL\n"
        "// central + explicit delta, x NOAA 2022 regional factor. First\n"
        "// matching box wins; outside every box the global-mean table\n"
        "// (identical to the legacy single table) applies.\n"
        f"const SLR_REGIONS={_js(slr_regions_js)};\n"
        f"const SLR=SLR_REGIONS.global_mean;\n"
        f"const SLR_REGION_BOXES={_js(boxes_js)};\n"
        "// appraisal convention, unified with the results pack (3% real, 25y)\n"
        f"const APPRAISAL_DEFAULTS="
        f"{_js({'discountPct': round(disc * 100, 4), 'horizonYears': horizon})};\n"
        "// structural archetypes: curve-level vulnerability differentiation;\n"
        "// the profile factor table stays the mapping layer on top. The\n"
        "// default reproduces the published curve exactly.\n"
        f"const ARCHETYPES={_js({k: {f: v[f] for f in ('v_half_mult', 'fb_add_m', 'flood_cap', 'label')} for k, v in ARCHETYPES.items()})};\n"
        f"const DEFAULT_ARCHETYPE={_js(DEFAULT_ARCHETYPE)};\n"
        f"const FIRE_WARMING_UPLIFT={_js(scalar('fire_warming_uplift_per_c'))};"
        "   // burn-probability uplift per deg C\n"
        f"const TC_UPLIFT_PER_C={_js(scalar('tc_intensity_uplift_per_c'))};"
        "     // interim TC field intensity uplift per deg C\n"
        "// interim flat conditional damage ratio given fire reaches the\n"
        "// site (capped; LABELED interim); a grid carrying flame-length-\n"
        "// conditioned ratios in v25 supersedes it per site\n"
        f"const FIRE_COND_INTERIM={_js(scalar('fire_cond_interim'))};\n"
    )


def main(argv=None) -> int:
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser(description="Regenerate or check the app's "
                                             "generated assumptions module.")
    ap.add_argument("--write-app", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    out = Path(__file__).resolve().parent.parent / "app/src/05_assumptions.js"
    if args.check:
        if not out.exists() or out.read_text() != to_app_js():
            print(f"DRIFT: {out} does not match assumptions.py. "
                  f"Run: python pipeline/assumptions.py --write-app")
            return 1
        print(f"ok  {out.name} matches assumptions.py byte for byte")
        return 0
    if args.write_app:
        out.write_text(to_app_js())
        print(f"wrote {out}")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
