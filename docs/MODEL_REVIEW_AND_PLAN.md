# CLAM Model Review and Improvement Plan

Prepared 7 July 2026 from a full read of the repository at commit `26a5aa2`
(every file in `pipeline/`, `app/src/`, `tests/`, `docs/`, and the CI
workflows). Where something could not be established from the code alone it is
marked **unverified** rather than assumed. Line references are to the files as
they stand at that commit.

Contents:

1. How the model works
2. How risks are calculated (the math, and what is ambiguous or wrong)
3. Alignment to best-in-class models
4. Transparency
5. Front-end simplification

Each section gives findings first, then recommendations, then implementation
steps in priority order.

---

## 1. How the model works

### 1.1 Findings — architecture

CLAM is a two-tier system with a deliberately narrow contract between tiers
(`README.md:19-46`):

- **The pipeline** (`pipeline/`, Python, CLIMADA 6.1 + Petals 6.2 inside a
  conda env) is a *hazard factory*. Its product is two files —
  `hazard_grid.csv` and `hazard_grid_meta.json` — plus an optional third
  artifact, `results_pack.json`, produced by `refresh_impacts.py`. Nothing
  else crosses the boundary.
- **The app** (`app/src/`, assembled by `app/assemble_app.py` into the
  single-file deployable `TNL_Resort_Climate_Risk_Explorer_v200.html`) is a
  zero-install browser risk engine. It holds *all* exposure, vulnerability,
  financial, adaptation, insurance, and uncertainty logic. It reads the two
  (or three) files by drag-and-drop and never talks to CLIMADA or the network
  (except optional Leaflet tiles, geocoding, and web fonts).
- **Gates**: `validate_grid.py` and `validate_pack.py` are acceptance gates
  (exit 0 = shippable). CI (`.github/workflows/ci.yml`) runs
  `tests/run_all.sh` (pure pandas/numpy + node, no CLIMADA) on every push:
  contract tests, end-to-end simulations, 101 frontend assertions, byte-level
  assembly drift checks, and a v1.13-vs-v2.0.0 numerical parity suite
  (`tests/test_app_parity.py`).

This is an unusually disciplined structure for a project of this size. The
weak point is not the plumbing; it is that **the science lives in two places**
(pipeline event math and app RP-grid math) held equal only by manually
mirrored constants, and that many of those constants are screening-grade
values without cited sources.

### 1.2 Findings — data inputs and sources

| Peril | Source | Producer | Key parameters |
|---|---|---|---|
| TC wind (`tc`) | ETH CLIMADA Data API `tropical_cyclone` (synthetic track sets) | `refresh_hazard.py:297-350` | Countries `USA, PRI, VIR` (`:210`); `NB_SYNTH_TRACKS="10"` default, 50 recommended for authoritative runs (`:214-219`); candidate-fallback property matching because API tagging drifts |
| Storm surge (`cflood`) | Derived from the same wind hazards via Petals `TCSurgeBathtub` over an operator-supplied SRTM15+ DEM | `refresh_hazard.py:365-380`; DEM prep in `convert_dem.py` | SLOSH-fitted linear wind→surge; inland decay 0.2 m/km (`:235`, Pielke & Pielke 1997, the Petals default); per-scenario SLR added *before* elevation subtraction (`SLR_M`, `:239-244`) |
| Riverine flood (`rflood`) | Data API `river_flood` (ISIMIP / CaMa-Flood, ~150 arcsec ≈ 5 km) | `refresh_hazard.py:527-607` | Discovery-driven selection; `ssp245 → rcp45` if served, else `rcp60` (`RF_SCEN_PREF`, `:270-276`); ensemble mean of up to 4 model variants (`RF_MAX_MODELS`, `:277`) |
| Extreme heat (`heat`) | NOAA CPC Global Daily Temperature (tmax/tmin, 0.5°, 2005–2024) | `refresh_heat.py` | Delta method: observed climatology shifted by `WARMING × 1.25` land amplification (`:90-98`); four region boxes (`:77-82`); no CLIMADA involvement |
| Wildfire (`wfire`) | NASA FIRMS active-fire archive CSVs (operator downloads), Petals `WildFire` | `refresh_wildfire.py` | Historic fire seasons only by default (`n_proba_seasons=0`, `:298-333`); MODIS confidence floor 50 (`:94`); trimmed to 75 km around sites (`:93`); burn probability `1−exp(−λ)` (`:101-106`); scenarios scale probability by `1 + 0.14·ΔT` (`:75, :109-112`) |
| TC rainfall (`prain`) | IBTrACS North Atlantic tracks 1980–2024 + 9 synthetic per historic track, Petals `TCRain` | `refresh_prain.py:91-116` | Country bounding boxes (`:57-59`); 150-arcsec centroids; scenarios scale rainfall by Clausius–Clapeyron 7 %/°C (`:53`) |

Exposure input is a site CSV (`sites_template.csv`): required `name, latitude,
longitude, asset_value_usd`; optional country, brand, revenue, and a v2
building profile (construction, year_built, defended, roof_type, roof_year,
opening_protection, first_floor_elev_m, equipment_elevated, stories, keys,
renovation_year, wui_class, defensible_space_m, roof_class_a, fema_zone,
named_insured, site_id, site_name). `enrich_sites.py` can draft some fields
from public data (DEM sample, CLIMADA dist-to-coast, FEMA NFHL point query,
OSM building count), always flagged `needs_review`, never overwriting operator
values.

### 1.3 Findings — the hazard grid contract

One CSV, schema `lat, lon, scenario, hazard, v10, v25, v50, v100, v250, v500`
(`refresh_hazard.py:60-67`), values rounded to 2 decimals (`:830`), thinned to
a 0.25° (~25 km) grid by within-cell averaging (`thin_to_grid`, `:441-454`).
Three encodings share the six v-columns:

- **Return-period intensities** (tc: m/s; cflood/rflood: m depth; prain: mm
  rain) from CLIMADA's `local_exceedance_intensity(method="extrapolate")`
  (`:383-430`).
- **Indicator encoding for heat** ("Option A"): v10 = days/yr > 32 °C, v25 =
  days/yr > 35 °C, v50 = cooling degree days, v100–v500 = 0
  (`refresh_heat.py:154-177`).
- **Indicator encoding for wildfire**: v10 = annual burn probability in
  percent, rest 0 (`refresh_wildfire.py:115-131`).

Two structural safeguards matter: water layers are re-indexed onto the wind
grid's cell set with explicit zeros inland (`align_to_cells`,
`refresh_hazard.py:457-469`), because the app snaps a site to the *nearest*
cell within 200 km and absent cells would let an inland site inherit coastal
surge; and scenario blends renormalize weights when a member failed
(`blend_grids`, `:472-491`) so a failed download degrades rather than sinks a
scenario.

**Scenario construction for wind/surge** (`build_recipes`,
`refresh_hazard.py:280-288`): the app's SSP keys map to the Data API's RCP
tags by radiative-forcing equivalence (`ssp126←rcp26, ssp245←rcp45,
ssp585←rcp85`, `:254`), and each horizon is a weighted blend of thinned
RP-intensity fields: 2030 = ½·present + ½·rcp(2040); 2050 = ½·rcp(2040) +
½·rcp(2060); 2080 = rcp(2080).

### 1.4 Findings — how the app scores a site

The dispatch is `hzSite(site, hz, scenario)`
(`app/src/10_hazard_engine.js:330-356`):

1. **Hazard lookup**: if a grid layer for that peril is loaded, nearest cell
   within 200 km (memoized linear scan, `makeGridProvider`, `:52-72`).
   Outside coverage, or with no grid, per-peril **interim models** fill in
   (`:319-328`), with two honest exceptions: wildfire falls back to a
   `wui_class`-based rate or zero, and TC rainfall has *no* interim model
   (zero by design).
2. **Vulnerability**: `vulnOf(site)` (`:296-316`) produces a wind damage
   multiplier (construction × roof/openings *or* year-built factor, clamped
   0.5–1.6), a flood freeboard bonus (measured first-floor elevation up to
   3 m, else 0.5 m if `defended`), and a flood damage cap (0.5 if critical
   equipment elevated, else 0.75).
3. **Damage curves**: Emanuel (2011) cubic sigmoid for wind (`:29`), concave
   exponential stage-damage for the three water perils (`:210`), value ×
   burn-probability × 0.6 conditional damage for fire (`:343-346`), and the
   rainfall→ponding drainage transform for prain (`:280-283`).
4. **EAD integration**: trapezoid over exceedance frequency at the six RPs
   with a closing rectangle at the 1-in-500 frequency (`siteEad`, `:73-82`;
   `floodEad`, `:247-254`).

The financial layer (`20_finance.js`) then adds business interruption
(GOP-based) and chronic heat cost; the adaptation layer (`30_adaptation.js`)
appraises measures as modifiers on that chain; the uncertainty layer
(`40_uncertainty.js`) sweeps five factors one at a time.

### 1.5 Findings — the results pack (event-set math)

`refresh_impacts.py` re-implements CLIMADA's `ImpactCalc` arithmetic directly
("identical math to ImpactCalc for point exposures, chosen so the parity tests
run without CLIMADA", `MASTER_PLAN.md:148-151`): per-event site losses = value
× damage_fraction(nearest-centroid intensity); `eai_exp` as frequency-weighted
sums (`site_ead`, `:336-338`); the portfolio exceedance curve from per-event
losses summed across sites *before* the curve (`ep_curve`, `:305-333`). This
gives the genuinely joint wind+surge tail the app's own portfolio tail cannot.

Combination rules (recorded in the pack meta, `:1154-1162`): wind+surge add
per event (shared catalog — truly joint); river flood, TC rainfall, wildfire,
and countries are independent catalogs whose exceedance losses add at equal
return periods (**comonotonic — an upper bound**); the EP tail is flat beyond
the largest simulated return period (conservative-low).

The pack also carries: a three-measure adaptation appraisal (`run_adaptation`,
`:520-570`), a ten-measure catalog with applicability predicates and a phased
capital plan (`measures_catalog.py`), seeded joint Monte Carlo uncertainty
(300 uniform samples over 3 factors, `run_uncertainty`, `:573-624`), an
optional v_half backtest calibration (bisection, recorded but never silently
applied, `:757-822`), and a named-insured rollup.

### 1.6 Findings — inventory of assumptions, hardcoded values, stubs, and shortcuts

**Mirrored constant tables (change-both-sides pattern).** The WARMING table
exists in **four** copies (`app/src/10_hazard_engine.js:13-16`,
`refresh_heat.py:90-95`, `refresh_wildfire.py:69-74`, `refresh_prain.py:47-52`)
and the SLR table in two (`10_hazard_engine.js:17-20`,
`refresh_hazard.py:239-244`). `tests/test_warming_parity.py` pins the mirrors,
which prevents drift but does not remove the pattern. V_THRESH/V_HALF,
CONSTR_FACTOR, the v2 factor table, FIRE_*, and PRAIN_* constants are likewise
mirrored between `refresh_impacts.py` and the app.

**Hardcoded scientific parameters, with no cited source in code or UI:**

- `WARMING` (°C "above present" — baseline period never stated) and `SLR` (m
  — global-mean, no regional adjustment; baseline never stated).
- Wind interim uplift 2 %/°C (`10_hazard_engine.js:26-27`); riverine interim
  uplift 5 %/°C (`:224`); fire uplift 14 %/°C (`refresh_wildfire.py:75`);
  rainfall CC 7 %/°C (`refresh_prain.py:53`); land amplification 1.25
  (`refresh_heat.py:98`).
- Flood curve steepness 0.6 /m and cap 0.75; freeboards 1.1 m coastal / 0.6 m
  riverine / 0.3 m rainfall; `defended` = +0.5 m (`refresh_impacts.py:95-96,
  145-149`; app `:203, :264`).
- Fire conditional damage 0.6; Class-A roof ×0.6; defensible space ×0.7
  (`refresh_impacts.py:123-125`).
- Drainage: 150 mm absorbed, 0.4 ponding coefficient
  (`refresh_impacts.py:126-128`).
- The entire interim hazard layer: 28 wind anchors with per-anchor (v100,
  log-slope) values and IDW scale 380 km (`10_hazard_engine.js:33-42`); the
  coastal-surge proxy `1.8·exp(−coastKm/40)·(0.5+0.5·v100/74.7)` with a fixed
  RP shape table (`:212-219`); the riverine proxy `0.8·(0.3+0.7·continentality)`
  (`:220-226`); the latitude heat formula (`:241-244`); WUI burn rates 0.3 %
  and 0.6 %/yr (`:262`). The Method tab admits the calibration basis is
  "Tuned so per-peril AAL lands in published screening ranges"
  (`00_shell_head.html:791`) without naming the publications.
- Financial defaults: revenue = 35 % of value, GOP margin 30 %, reopen 12
  months, heat-day profit loss 12 %, correlation 0.30, premium load 1.5×
  (`20_finance.js:3`, `30_adaptation.js:8`); heat comfort baseline 15
  days > 35 °C (`20_finance.js:2`).
- Risk bands at 0.25 / 0.75 / 1.5 % EAD-to-value (`10_hazard_engine.js:83`);
  heat bands at 10/45/100/160 days (`:255`); tolerance defaults 75 bps / 1 % /
  10 % (`20_finance.js:16`).
- Measure library costs and effects (both the app's slider defaults,
  `30_adaptation.js:23-60`, and the catalog's per-key costs,
  `measures_catalog.py:139-233`) — labeled "planning-grade defaults drawn
  from published mitigation studies" (`00_shell_head.html:803`), studies not
  named.
- Appraisal settings: pack = 3 % discount / 25-year horizon
  (`refresh_impacts.py:101-102`); app defaults = 2 % / 20 years
  (`00_shell_head.html:521-526`). **These differ** — see §2.6.

**Stubs and deferred items (explicitly marked in code/docs):**

- `RFLOOD_GRID_INCLUDES_PROTECTION = false` — the FLOPROS
  protection-embedding question is unresolved; a wrong setting double-counts
  or ignores flood protection (`10_hazard_engine.js:206-209`,
  `docs/RUNBOOK.md:74-83`).
- `premium_credit_pct: 0.0` on every catalog measure ("hook at 0 until broker
  quotes arrive", `measures_catalog.py`).
- The unsequa Saltelli/Sobol upgrade "slots behind run_uncertainty()"
  (`refresh_impacts.py:41-44`) — not implemented.
- Multi-country packs report adaptation/uncertainty/capital-plan for the
  largest country by value only (`refresh_impacts.py:1367-1378`).
- The planned "pack-versus-browser divergence report" (MASTER_PLAN Phase B
  step 3) is **not implemented** in `validate_pack.py`.
- Wildfire event tail: at screening probabilities wildfire contributes to EAD
  but not to the app's 1-in-100 figures (acknowledged in the INFO copy,
  `50_state_info.js:121-124`).

### 1.7 Recommendations (Section 1)

1. **Create a single assumptions registry.** One versioned JSON
   (`pipeline/assumptions.json`) holding every mirrored table and scientific
   constant, each entry with value, units, baseline period, source citation,
   and last-review date. Pipeline producers import it; `assemble_app.py`
   injects it into the app at build time (replacing the four hand-mirrored
   WARMING copies); the app renders it on the Method tab. The parity tests
   then pin registry→app injection instead of hand mirroring.
2. **Document the provenance of every screening constant** (or replace it):
   the 28 wind anchors, the flood-curve parameters, the WUI burn rates, the
   drainage constants, and the measure costs are the highest-priority items
   because money decisions read them directly.
3. **Resolve the FLOPROS question** on the next real river-flood fetch (the
   runbook already describes exactly how) and record the decision in the
   meta sidecar so the app can set `RFLOOD_GRID_INCLUDES_PROTECTION`
   automatically instead of by hand-edit.
4. **Close the marked stubs in priority order**: unsequa sampling (§3), the
   pack-vs-browser divergence report (§4), per-country adaptation sections.

### 1.8 Implementation steps (priority order)

1. Build `assumptions.json` + build-time injection + registry rendering on
   the Method tab (removes the mirror pattern; ~2–4 days; touches
   `assemble_app.py`, all four producers, `test_warming_parity.py`).
2. Add a `sources` field to each registry entry and write the citation for
   each constant (research task, ~2–3 days; several will be found to be
   uncited judgment calls — mark them as such explicitly).
3. Implement the validator divergence report (§4.3, step 2).
4. FLOPROS resolution at the next quarterly refresh (already runbooked).

---

## 2. How risks are calculated

### 2.1 The math, peril by peril

Notation: `v_RP` = hazard intensity at return period RP; `V` = site asset
value (USD); `f = 1/RP` = annual exceedance frequency.

**Tropical-cyclone wind.** Intensity: m/s (1-min sustained per the ETH sets)
at RP ∈ {10, 25, 50, 100, 250, 500}. Damage fraction (Emanuel 2011, identical
to CLIMADA `ImpfTropCyclone.from_emanuel_usa` defaults):

```
vt  = max((v − 25.7) / (74.7 − 25.7), 0)
MDR = vt³ / (1 + vt³)                       # then × windMult ∈ [0.5, 1.6], clamped ≤ 1
```

(`10_hazard_engine.js:29`; `refresh_impacts.py:135-142`.)

**Coastal / riverine flood and TC-rainfall ponding.** Depth d in metres over
freeboard fb:

```
e   = d − fb                                # fb: 1.1 m coastal, 0.6 m river, 0.3 m rain (+site bonus)
MDR = 0 if e ≤ 0, else min(cap, 1 − exp(−0.6·e))    # cap 0.75, or 0.5 if equipment elevated
```

(`10_hazard_engine.js:210`; `refresh_impacts.py:145-149`.) For prain, the mm
field first passes the drainage transform `depth = max(0, mm − 150)/1000 ×
0.4` (`:280-283`; `refresh_impacts.py:475-478`).

**Wildfire.** Not return-period based. Expected damage = `V × p_burn ×
0.6 × fireVuln` where `p_burn` is the annual burn probability (grid v10 % or
WUI-class interim) and fireVuln = 0.6 if Class-A roof × 0.7 if ≥ 30 m
defensible space (`10_hazard_engine.js:342-347`). In the pack, wildfire is a
true event set: per-event loss = `V × 0.6 × fireVuln` where the site's cell
burned, with warming scaling the event *frequency*, not the loss
(`refresh_impacts.py:484-495`).

**Extreme heat.** Indicators only (days > 32 °C, days > 35 °C, CDD base
18 °C). Monetized on the Financial tab as
`heatCost = (GOP/365) × max(0, d35 − 15) × 0.12` (`20_finance.js:31-33`).
CDD is computed and displayed but never monetized.

**EAD integration (app).** Sort the six points by frequency descending;
trapezoid between adjacent points; close the tail with a rectangle at the
rarest frequency:

```
EADfrac = Σ ½(MDRᵢ + MDRᵢ₊₁)(fᵢ − fᵢ₊₁)  +  MDR₅₀₀ × (1/500)
```

(`siteEad`, `10_hazard_engine.js:73-82`.) Two truncations follow: losses from
events *more frequent than 1-in-10* are counted as zero (the integral stops at
f = 0.1), and losses *rarer than 1-in-500* are held at the 500-year level.
Both bias EAD low; only the tail side is documented (`ep_curve` docstring,
`refresh_impacts.py:305-313`).

**EAD (pack, event-true).** `EAD_site = Σ_events loss × freq` — identical to
CLIMADA `eai_exp` for point exposures (`site_ead`,
`refresh_impacts.py:336-338`). Portfolio EP: events sorted by loss descending,
exceedance frequency = cumulative frequency, RP = 1/cum, interpolated linearly
in log(RP), edge-clamped (`ep_curve`, `:305-333`).

**Business interruption (app only).**
`BI_EAD = GOP × (reopenMonths/12) × damageEADfraction` per acute peril, i.e.
downtime is assumed proportional to the damage fraction with a 12-month
ceiling at total loss (`20_finance.js:24-28`).

**Portfolio tail (app).** Per-RP diversified loss:

```
VaR_RP = sqrt((1−ρ)·Σxᵢ² + ρ·(Σxᵢ)²),   ρ = 0.30
```

— a heuristic interpolation between independence (root-sum-square) and full
comonotonicity (sum) (`finPortfolio`, `20_finance.js:44-48`). Labeled a
screening stand-in; the pack's event-set curve is the corrective.

**Insurance layering.** Transferred fraction = (trapezoid integral of the
layered slice of the diversified curve) / (integral of the full curve),
applied to acute AAL; premium = transferred × load (default 1.5×)
(`layerStatsCalc`, `30_adaptation.js:130-142`).

**Adaptation.** Measures are modifiers (damage multiplier, freeboard bonus,
depth reduction, reopen multiplier, heat multiplier, fire multiplier) composed
into one adapted run so overlaps never double count (`adaptedFinSite`,
`30_adaptation.js:67-98`). `BCR = averted_AAL × annuity(H, r) / cost`.

**Uncertainty (app).** One-at-a-time sweeps: hazard ±8 %, damage-curve
steepness −30/+40 %, asset values ±15 %, revenue ±20 %, reopen −25/+50 %;
deltas combined by root-sum-square assuming independence
(`40_uncertainty.js:1-25`). Pack: joint Monte Carlo, 300 **uniform** draws
over the first three factors, seed 42 (`refresh_impacts.py:115-120, 573-624`).

**Scenario deltas.** Grid-fed perils carry their climate signal in the data
(RCP-tagged event sets; SLR entering the bathtub; shifted climatology;
scaled burn probability / rainfall). Interim models apply scalar uplifts
(wind 2 %/°C; river 5 %/°C; SLR added to the coastal proxy). Grid always
supersedes interim per peril, so no double counting.

### 2.2 Confirmed defect

**`measures_catalog.phase_projects` off-by-one → crash or out-of-plan year.**
The renovation-window predicate (`measures_catalog.py:275`,
`0 < ry − REF + 1 <= RENOV_WINDOW_YEARS + 1`) admits `renovation_year =
REF + 3` (e.g. 2029 with REF 2026), mapping it to plan year 4. With
`--budget`, `spent[4]` raises `KeyError: 4` (`:294`) and the whole
`refresh_impacts.py --budget` run dies; without a budget the project is
silently assigned year 4, outside the stated 3-year plan and without the
synergy discount guard. **Reproduced during this review.** Fix: the predicate
should be `<= RENOV_WINDOW_YEARS` (years 1..3), and the budget branch should
guard `spent.get(y)` for out-of-range years. `tests/test_catalogops.py` only
covers `REF + 1`; add `REF + 3` and `REF + 4` cases.

### 2.3 Ambiguous or undocumented items (highest impact first)

1. **The WARMING and SLR tables have no stated baseline period and no
   citation.** "°C above present" is undefined — present relative to what
   (1995–2014? 2005–2024, the heat climatology window? today)? Checked
   against AR6 WGI SPM central estimates (relative to 1850–1900 minus ~1.1 °C
   observed): the table's mid-century and late-century values run ~0.3–0.7 °C
   **above** AR6 central for SSP2-4.5 and SSP5-8.5 (e.g. `ssp245_2050: 1.4`
   vs an AR6-implied ~0.9 above present). They sit inside AR6 *very likely*
   ranges, so "consistent with AR6 ranges" (`10_hazard_engine.js:8-9`) is
   defensible but leans high, and nothing in the repo says which percentile
   or baseline was chosen, or why. The same applies to SLR (values resemble
   AR6 medium-confidence GMSL medians shifted toward later decades). Every
   scenario number in the system inherits this ambiguity.
2. **TC-rainfall coverage silently excludes Hawaii and the northern
   seaboard.** `refresh_prain.py` fetches only North Atlantic basin tracks
   (`basin="NA"`, `:96`) and builds centroids only inside three boxes: a
   CONUS box capped at 37.5° N and −74° E, PRI, and VIR (`BBOXES`, `:57-59`).
   The sample portfolio includes three Hawaii resorts; they will score
   rainfall zero *with a "grid loaded" trust chip showing green* (a site
   > 200 km from a cell scores an honest zero, but the peril-level chip
   reflects the file, not per-site coverage). Heat's `REGIONS` and wildfire's
   `FIRE_REGIONS` include Hawaii; prain does not. Whether the ETH wind sets
   for country USA include Hawaii is **unverified** from the code — verify at
   the next refresh and record it in the meta sidecar.
3. **Comonotonic addition of independent catalogs.** Adding exceedance losses
   at equal RP across river flood, rain, fire, and countries
   (`add_ep`, `refresh_impacts.py:360-363`) is an upper bound (documented),
   but it is presented in the pack as *the* portfolio EP curve. For a
   portfolio spanning Gulf, Caribbean, and Hawaii the overstatement at
   1-in-100 can be material. The correct treatment (Poisson year-simulation
   across catalogs, or a single merged event set) is well within reach of the
   existing event data.
4. **Frequent-loss truncation in the app's EAD.** Integration stops at
   1-in-10; a peril with meaningful sub-decadal losses (riverine flood,
   rainfall ponding) has that loss counted as zero. The pack does not share
   this truncation (its event sets include frequent events), so pack and app
   EADs differ by construction — another reason the divergence report
   matters.
5. **Wind scenario blending averages RP fields, not event sets**
   (`build_recipes` + `blend_grids`). Averaging two RP-intensity surfaces is
   not the RP surface of a blended climate; for convex damage curves the
   error propagates nonlinearly. Acceptable for screening, but nowhere
   stated.
6. **Wildfire's event set is ~25 historical fire seasons** (default
   `n_proba_seasons=0`). Burn probability at any cell is estimated from ~25
   Bernoulli trials — a cell that happened not to burn since 2000 scores 0 %.
   The probabilistic-season augmentation exists behind a flag but defaults
   off ("robust screening default") without a sensitivity check recorded.
7. **BI proportional to damage fraction** with one global reopen ceiling
   ignores downtime nonlinearity (a 20 % damaged resort is often 100 %
   closed) and seasonality (a hurricane in high season ≠ low season). This
   is the single most consequential financial simplification for a
   hospitality portfolio — the roadmap's R8 already recognizes it.
8. **The ρ = 0.30 correlation** is a single global dial with no empirical
   anchor; the blend formula is a variance interpolation, not a copula or
   event model. Fine as labeled — but the *app* tail drives the tolerance
   flags and layering panel even when a pack (with a real joint curve) is
   loaded; only the benchmark row uses the pack.
9. **Appraisal settings mismatch**: pack BCRs use 3 %/25 y
   (`refresh_impacts.py:101-102`), the app's live BCRs default to 2 %/20 y
   (`00_shell_head.html:521-526`). The two are shown side by side ("canonical"
   vs "live") — a user comparing them sees differences caused partly by
   settings, not model. Neither surface states the other's settings.
10. **Uniform Monte Carlo distributions** (`run_uncertainty`) are an
    undocumented choice; the tornado bounds double as distribution bounds.
    P5/P95 from uniforms are materially narrower than from, say, lognormals
    with the same bounds at 90 % coverage.
11. **The v_half calibration absorbs *all* model bias into the wind curve**
    (flood/fire AALs held fixed, `fit_v_half`, `refresh_impacts.py:757-791`).
    With a flood-driven loss history the fitted v_half is biased; the code
    flags bias outside 0.5–2.0 but does not decompose it by peril.
12. **Heat monetization counts only days > 35 °C** and ignores humidity
    (wet-bulb), which for Gulf/Caribbean resorts is the binding comfort
    variable; CDD is collected but unused in the money path.
13. **Rounding to 2 decimals in the grid CSV** (`refresh_hazard.py:830`)
    quantizes burn probability (stored ×100, so 3 decimals there — fine) and
    surge depths to 1 cm — harmless, but validator monotonicity tolerance
    (−0.011, `validate_grid.py:111`) exists to absorb it; worth a comment
    linking the two.
14. **`heatIndicators`' effective-temperature inversion**
    (`10_hazard_engine.js:236-239`) back-solves a logistic from day counts to
    display "effT" — a synthetic number presented alongside measured
    indicators with no marker that it is synthetic.

### 2.4 Recommendations (Section 2)

1. Fix the `phase_projects` window defect and add the missing edge-case
   tests (confirmed bug; small, isolated).
2. Extend `refresh_prain.py` to cover Hawaii (Eastern/Central Pacific basins
   `EP`/`CP` in IBTrACS) and the full portfolio footprint; add a
   per-peril × per-site coverage check to `refresh_impacts.py` and the app
   (site > 200 km from every cell of a loaded peril should surface in the
   trust UI, not just in the score trace).
3. Replace comonotonic catalog addition in the pack with an annual
   simulation: sample a year of events per catalog (Poisson by frequency),
   sum losses, repeat ~10k× — the existing per-event matrices make this a
   ~100-line change; keep the comonotonic curve as a reported bound.
4. Document (or fix) the EAD truncation: either state "losses below 1-in-10
   are excluded" in the INFO copy for EAD, or extend the grid schema with a
   v5/v2 column and integrate to f = 0.5.
5. Pin the WARMING/SLR tables to citable AR6 values with an explicit
   baseline (see §3), and record percentile choice.
6. Unify appraisal settings: have the app read horizon/discount defaults
   from the pack when one is loaded (or at minimum print the pack's settings
   next to the "canonical" plan).
7. Backtest v2: report per-peril observed/modeled decomposition where the
   loss history has cause-of-loss tags; keep single-lever v_half fitting
   only for wind-tagged losses.
8. Swap uniform MC draws for documented distributions (triangular or
   lognormal), and state the choice in the pack meta.

### 2.5 Implementation steps (priority order)

1. `phase_projects` fix + tests (hours). — *correctness*
2. Coverage audit: prain Hawaii boxes + basin, wind-set Hawaii verification,
   per-site coverage surfacing (1–2 days). — *silent-zero risk*
3. Pack year-simulation aggregation (2–3 days incl. validator + tests). —
   *credibility of the joint tail*
4. Appraisal-setting unification (half day).
5. WARMING/SLR re-derivation with citations (1–2 days, coordinated with the
   assumptions registry from §1).
6. EAD frequent-loss documentation or schema extension (choose; ½–3 days).
7. MC distribution upgrade + meta documentation (1 day).
8. Backtest per-peril decomposition (2 days, needs loss-cause data).

---

## 3. Alignment to best-in-class models

### 3.1 Findings — where CLAM matches the field

- **Peril coverage** (TC wind, surge, riverine flood, heat, wildfire, TC
  rain) matches the acute set of most commercial physical-risk screeners,
  and exceeds several on TC rainfall.
- **Scenario framework** (SSP1-2.6/2-4.5/5-8.5 × 2030/2050/2080) is the IPCC
  AR6 / TCFD-conventional grid; the acute/chronic disclosure split
  (`finDisclosure`) mirrors IFRS S2 expectations.
- **CLIMADA lineage**: the wind vulnerability is exactly CLIMADA's
  `emanuel_usa`; the pack reproduces `ImpactCalc`/`eai_exp`/`calc_freq_curve`
  arithmetic; surge is Petals `TCSurgeBathtub`; wildfire and rain are Petals
  modules. Where the code re-implements rather than calls CLIMADA
  (`refresh_impacts.py`), it does so deliberately for testability, with
  parity as the stated design goal — a legitimate trade, but it must be
  *demonstrated* (see divergence report) rather than asserted.
- **Provenance and validation gating** (meta sidecars cross-checked against
  data, exit-0 shipping, CI parity suites) exceed what most commercial
  vendors expose to their customers.
- **Adaptation cost-benefit with applicability predicates and phased capital
  planning** is genuinely differentiated — most commercial risk scores stop
  at the diagnosis.

### 3.2 Findings — where CLAM lags

**Versus CLIMADA best practice:**

- No `unsequa` (Saltelli sampling, Sobol indices) — the app's OAT/RSS and the
  pack's 3-factor uniform MC are both labeled placeholders.
- No `CostBenefit`/`Entity` canonical run to cross-check the re-implemented
  appraisal (MASTER_PLAN §2 maps the measures to `Measure` parameters; never
  executed).
- Impact-function calibration module unused; the bespoke bisection fits one
  scalar.
- `Exposures` are single points with one value; CLIMADA supports LitPop
  scaling, OSM footprints, and multiple value columns (structure/content/BI).

**Versus IPCC AR6 conventions:**

- Warming values lack baseline definition and citation (§2.3.1); best
  practice is to state assessment-report table, baseline period, and
  percentile (e.g. "AR6 WGI Table 4.5, 50th percentile, re-baselined to
  1995–2014").
- SLR is global-mean; AR6 (and NOAA/NASA regional tools) provide *relative*
  sea-level projections including vertical land motion — Gulf Coast
  subsidence alone makes local SLR materially higher than GMSL, and the
  Caribbean differs again.
- The SSP↔RCP forcing-equivalence mapping and the rcp45→rcp60 substitution
  are standard screening choices but should be user-visible caveats, not just
  code comments (they are recorded in meta; not surfaced in the UI).

**Versus leading commercial models (Moody's RMS, Verisk, Jupiter, XDI,
S&P Climanomics, Fathom/JBA for flood):**

- **Hazard resolution.** CLAM's 0.25° (~25 km) grid with nearest-cell snap is
  2–3 orders of magnitude coarser than commercial flood (10–90 m) and
  wildfire (30–270 m) products. For surge and riverine flood — where risk
  gradients are hundreds of metres — a 25 km cell mean is a screening
  quantity only. The DEM (SRTM15+, ~450 m, known high bias on built coasts)
  compounds this for surge.
- **Flood physics.** Bathtub surge (no waves, tides, or defenses) and ISIMIP
  ~5 km riverine (no pluvial except TC rain, no urban drainage) versus
  hydrodynamic modeling with defense databases. Non-TC pluvial flooding is
  entirely absent from the peril set, as are hail/SCS, tornado, winter storm,
  and drought/water stress — hail and non-TC convective storm are material
  for TX/inland sites.
- **Vulnerability granularity.** One wind curve and one flood shape with
  scalar modifiers, versus occupancy/construction/height-specific engineering
  curve libraries. No secondary-peril damage (wind-driven rain ingress), no
  contents vs structure vs time-element split, no demand surge/post-event
  inflation.
- **Dependence.** Commercial models aggregate on full event sets with spatial
  correlation everywhere; CLAM has this only for wind+surge within the pack,
  with heuristics elsewhere (§2.3.3, §2.3.8).
- **Wildfire.** FIRMS history clustering vs calibrated burn-probability
  products (e.g. USFS *Wildfire Risk to Communities*, published 30–270 m
  burn probability and flame-length exposure — public domain) plus
  structure-hardening models (ember exposure).
- **Heat.** Dry-bulb only; leading treatments use wet-bulb/WBGT and energy
  cost coupling.
- **Governance artifacts.** Vendors ship model methodology documents,
  validation studies against claims data, and version change logs. CLAM's
  equivalents (README/MASTER_PLAN/RUNBOOK + backtest tab) are strong for an
  internal tool but there is no single citable methodology document with
  versioned assumptions.

### 3.3 Recommendations (Section 3) — specific changes to close each gap

1. **Flood realism first** (largest gap × largest exposure): keep the bathtub
   for the quarterly grid, but (a) swap in CoastalDEM when granted (already
   planned, drop-in), (b) resolve FLOPROS, (c) add the missing pluvial
   (non-TC) component or explicitly retitle `prain` coverage as "TC rainfall
   only" everywhere BI/flood totals appear, and (d) for the top-10 value
   coastal sites, commission or ingest one high-resolution reference (FEMA
   BFE / NOAA SLOSH MOMs) as a per-site sanity anchor recorded beside the
   grid value.
2. **Wildfire: replace or corroborate FIRMS clustering with USFS Wildfire
   Risk to Communities burn probability** (public, calibrated, ~30× finer).
   The grid contract already supports it (indicator encoding unchanged);
   FIRMS stays as the event set for the pack.
3. **Regional SLR**: replace the scalar SLR table with per-site relative SLR
   from the AR6/NASA sea-level projection tool (medium confidence, median,
   stated baseline), keyed by coordinate — a lookup file, not a model change.
4. **Dependence**: implement the pack year-simulation (§2.5.3). This is the
   single cheapest step toward commercial-grade aggregation.
5. **unsequa**: swap the seeded MC for `CalcImpact`-based Saltelli sampling
   with Sobol indices at modest N (the seam exists); report first-order
   indices in the pack and render the driver ranking from them.
6. **Canonical CostBenefit cross-check**: run CLIMADA `CostBenefit` once per
   quarter for the three measures and record agreement with the
   re-implemented appraisal in the pack meta (tolerance test, not a
   replacement).
7. **Exposure v3**: OSM footprints for the top coastal sites (planned Phase D
   item), and a structure/contents/BI value split in the sites schema
   (columns optional, defaulting to today's single value).
8. **Peril-set honesty**: add a "perils not modeled" line (hail, tornado,
   non-TC pluvial, drought, winter storm) to the Method tab, the board brief,
   and the disclosure table footnote. Absence of a peril is an assumption
   too.
9. **Write MODEL_CARD.md** (see §4) as the citable methodology + validation
   document, versioned with the assumptions registry.

### 3.4 Implementation steps (priority order)

1. Pack year-simulation (shared with §2). — days
2. USFS burn-probability ingestion behind the existing wfire encoding. — 2–4
   days incl. validation
3. Regional SLR lookup table + registry entry. — 1–2 days
4. "Perils not modeled" surfacing (copy + brief + export footnote). — hours
5. unsequa integration behind `run_uncertainty()`. — 3–5 days
6. Quarterly CostBenefit cross-check + tolerance record. — 2 days
7. CoastalDEM swap and FEMA/SLOSH per-site anchors. — days, gated on data
   access
8. Exposure v3 (footprints, value split). — 1–2 weeks, schedule after the
   above

---

## 4. Transparency

### 4.1 Findings — what already works

This codebase is well ahead of most on transparency *mechanisms*: per-peril
trust chips (green/amber/gray) that cannot overstate coverage because the
validator cross-checks the sidecar against the data (`validate_grid.py`
section H); INFO popovers on essentially every figure (`50_state_info.js`
carries ~60 entries); per-site score tracing that walks every number to its
source, factors, and curve (`explainPeril`, pinned to the live math by test);
honest zeros with stated reasons; a data-basis line on the board brief; and a
plain-language glossary on the Method tab.

### 4.2 Findings — where it still behaves as a black box for a non-technical user

1. **Constants without sources** (§1.6). The INFO layer explains *what* a
   number means, rarely *where its parameters came from*. "Tuned so per-peril
   AAL lands in published screening ranges" names no publication; "drawn from
   published mitigation studies" names no study. A skeptical CFO cannot
   audit any of the ~40 scientific constants from inside the product.
2. **The interim model is invisible in substance.** The user is told "interim
   screening model" but cannot see the 28 anchors, the IDW kernel, or the
   proxy formulas that generated their numbers. The trace names the model but
   not its data.
3. **Per-site coverage gaps hide behind per-peril chips.** A green prain chip
   with a Hawaii site at zero (§2.3.2) is technically honest (the trace says
   "beyond 200 km") but the summary surfaces — banner, chips, brief — say
   "grid-fed". Coverage is a per-site × per-peril property presented as
   per-peril.
4. **Staleness is silent.** Grids, meta, and packs persist in localStorage
   and restore forever (`80_persist_wire.js:11-36`). The load date is shown
   on the Method tab, but nothing warns when the loaded grid is three
   quarters old, or when grid and pack came from different runs
   (`generated_utc` of grid meta and pack are never compared).
5. **No pack-vs-app divergence number.** The two engines are shown side by
   side, but the product never says "the live model is X % above the
   event-set figure for this scenario" — the user must eyeball it. The
   validator hook for this was planned and not built.
6. **Uncertainty communication is partial.** The Summary KPI carries a range,
   but per-site figures, the matrix, the map, and the export are
   point-estimates only; nothing grades *data confidence* (e.g. grid-fed +
   profiled site vs interim + bare site) even though the inputs to such a
   grade all exist.
7. **Validator output never reaches the user.** `validate_grid.py` prints a
   rich report (coverage pivot, climate-signal table, wet-cell stats,
   skipped layers) to a terminal the app user never sees. The meta sidecar
   carries `skipped` (rendered as a count) but not the validation verdict.
8. **Assumption edits are unlogged.** Sliders (financial assumptions,
   tolerance, measure settings) persist silently; two users with the same
   files can see different numbers with no visible marker of which
   assumptions were touched (the brief prints three of them; the export
   carries none except implicitly).
9. **Methodology has no single citable artifact.** The truth is spread
   across README, MASTER_PLAN, RUNBOOK, docstrings, and INFO copy. For
   disclosure or broker use, there is nothing to attach.

### 4.3 Recommendations (Section 4)

1. **Assumptions registry with citations rendered in-product** (§1.7.1) — the
   single highest-leverage transparency move; every INFO popover gains a
   "Source:" line generated from the registry.
2. **Ship the validation verdict with the data.** Have
   `validate_grid.py`/`validate_pack.py` write a small `*_validation.json`
   (result, warnings, per-layer stats) beside the meta; app renders a
   "Validated ✓ (date, N warnings)" line under the trust chips and refuses
   the word "disclosure-grade" without it.
3. **Implement the divergence report.** `validate_pack.py` (or a new
   `compare_pack.py`) recomputes the app-side portfolio figures from the grid
   for matching scenarios and writes per-peril divergence percentages into
   the pack meta; app shows "live model runs +X % vs event set" on the pack
   panel.
4. **Per-site data-confidence grade.** A/B/C per site × peril from: source
   (grid vs interim vs zero), cell distance, scenario coverage, profile
   completeness. Show it in the matrix tooltip, scorecard header, and as an
   export column. All inputs already exist in `explainPeril`.
5. **Staleness and mismatch warnings.** Amber banner when
   `generated_utc` > 120 days old (quarterly cadence + grace) or when grid
   and pack run dates differ; both are one-line checks at render time.
6. **Assumption-drift chip.** When any slider differs from the documented
   default, show "N assumptions changed — review" linking to a diff view;
   include a `assumptions_changed` column in exports and the brief.
7. **Interim model disclosure page.** Render the anchors table and proxy
   formulas (from the registry) on the Method tab under "The interim model,
   in full."
8. **MODEL_CARD.md** (versioned, ~6 pages): scope, data sources and vintages,
   methods per peril, validation results (backtest + spot checks from the
   runbook), limitations, and change log. Link it from the app footer and
   attach it to the board brief.

### 4.4 Implementation steps (priority order)

1. Validation-verdict sidecar + in-app rendering (1–2 days).
2. Staleness/mismatch banners (half day).
3. Divergence report (2 days; requires a small Python re-implementation of
   the app's RP-grid EAD, which `tests/test_app_parity.py` fixtures already
   approximate).
4. Data-confidence grades (2–3 days).
5. Registry-driven source lines in INFO popovers (after §1 step 1).
6. Assumption-drift chip + export column (1 day).
7. MODEL_CARD.md (2–3 days writing; ongoing maintenance rule: no constant
   changes without a card entry).

---

## 5. Front-end simplification

### 5.1 Findings

The app is information-rich and honest, but it is an analyst's cockpit, not a
non-technical user's tool:

- **Seven tabs** (`00_shell_head.html:335-343`): Summary, By peril, Sites,
  Adaptation, Scenarios, Financial impact, Method & data — plus a top bar
  with **five selects** (Peril, Pathway, Horizon, Brand, Map colour) and
  **six buttons** (Guide, Simple view, Load sample, Export CSV, Board brief,
  plus info buttons). First-run cognitive load is high before any data
  question is answered.
- **Duplication across tabs.** "Most exposed sites" appears on Summary and
  Financial impact; cost-by-peril/cost-by-type appear on Summary and
  Financial impact; trajectory appears on Summary, Scenarios, and in every
  scorecard; the Scenarios tab is almost entirely redundant with the Summary
  timeline + trajectory panel and the band-mix panel.
- **Three different "1-in-100" numbers** can be on screen: the By-peril
  co-occurrence bound (`renderOverview`), the Financial-impact diversified
  VaR (`finPortfolio`), and the pack's event-set loss (pack panel). Each is
  correct with its own caveat; a non-technical reader cannot arbitrate.
- **Three names for near-identical quantities**: "expected annual damage"
  (physical EAD), "expected annual cost" (AAL incl. BI + heat), "climate
  cost". The distinction is real but unlabeled at the point of use.
- **The Adaptation tab is the densest surface in the product**: measure
  library with 12+ sliders, appraisal settings, cost curve, waterfall,
  insurance layering with broker quote and retention sweep, per-site
  recommendations, and the action queue with budget cutline — five distinct
  jobs (harden? insure? how much? where first? what to tell the committee?)
  on one page.
- **The peril selector governs distant state.** Selecting "Wildfire" in the
  top bar changes the map, the By-peril tab, and the Sites table metric —
  including turning the "Annual damage" column into day counts when Heat is
  selected — surprising action-at-a-distance for a casual user.
- **"Simple view" exists but is shallow** (`applySimpleView`,
  `80_persist_wire.js:107-110`): it hides only four `pro-only` panels
  (retention sweep, uncertainty, model definition, backtest). The remaining
  surface is still the full cockpit.
- **Data loading lives at the end.** The empty state points to the sample or
  CSV, but the hazard-grid drop zone — the single action that makes numbers
  "disclosure-grade" — is on the last tab. The strong onboarding modal
  (welcome, one-minute overview) does not mention loading climate data at
  all.
- Genuinely good and worth preserving as-is: the risk matrix, the
  risk-vs-value quadrant, the scenario timeline, score tracing, the INFO
  layer, the board brief, the tolerance panel's plain-language routing, and
  the executive read-out sentence.

### 5.2 Recommendations — target structure

Reorganize around the user's four questions, not the model's layers:

| New tab | Contents (from today) | What changes |
|---|---|---|
| **1. Portfolio** | Map + Summary tab (timeline, KPIs, read-out, tolerance, matrix, quadrant, cost-by-peril/type, trajectory, top sites, brands) | Absorbs the Scenarios tab (delete it: timeline + trajectory + band-mix already cover it) and the By-peril tab (peril deep-dive becomes a drill-in from the matrix column header or a peril chip, carrying the EP curve and per-peril narrative) |
| **2. Sites** | Sites table + detail + scorecards | Keep; make the scorecard the only deep-dive surface (it already traces) |
| **3. Decisions** | Adaptation + insurance, re-staged | Stage 1 "Where to act" (recommendations + action queue + budget); Stage 2 "Harden" (measure library, cost curve, waterfall); Stage 3 "Insure" (layering, quote, retention — retention behind Analyst mode). One shared appraisal-settings strip |
| **4. Data & method** | Method tab + backtest + financial assumptions | Add the load-status checklist (below); move the five financial sliders here under "Assumptions" (they are set-and-forget, not daily controls) |

Top bar reduced to: **one climate-future control** (a single select combining
pathway × horizon, defaulting to "Present day", with the timeline as the
primary affordance), the trust badge, Guide, Export, Brief. Peril, Brand, and
Map colour move onto the map itself as a compact layer control (they are map
lenses; `brandFilter` is already map-only). "Simple view" inverts: **simple is
the default**, and an "Analyst" toggle reveals the pro panels (retention
sweep, uncertainty tornado, backtest, model definition, brand overrides).

Other specific changes:

- **One tail number policy**: when a pack is loaded, the event-set 1-in-100
  is *the* headline VaR everywhere, with the live blend demoted to a detail
  row; without a pack, the diversified VaR is headline and the co-occurrence
  bound appears only in the By-peril drill-in, renamed "if one event struck
  every site (upper bound)".
- **Rename for consistency**: use "Expected annual loss (physical damage)"
  and "Expected annual cost (damage + downtime + heat)" as the only two
  terms, defined once, used verbatim in KPIs, tables, exports, and the
  brief.
- **First-run checklist replaces the passive empty state**: ① Load sites
  (sample/CSV/search) ② Load climate data (grid + meta; shows chip status
  and "estimated → disclosure-grade" language) ③ Review assumptions (one
  screen, registry-driven) — with progress persisted, and the drop zone
  reachable from the checklist, not only the last tab.
- **Cut or park** (Analyst mode): per-brand assumption overrides, retention
  sweep, backtest, model-definition panel, broker-quote gap wording. None of
  these should confront a first-time executive.
- **Keep the export contracts untouched** (Power BI schema is frozen by
  design and partition-tested; all reorganization is presentational, which
  the parity suite already protects).

### 5.3 Implementation steps (priority order)

All of this is render-layer work; the parity suite
(`tests/test_app_parity.py`, `test_frontend.py`) is the safety net, and the
`app/src/` module split makes it tractable.

1. **Default-simple + Analyst toggle** — extend the existing `pro-only`
   mechanism to the full pro list; flip the default; persist. (Half day; no
   layout change yet, immediate load reduction.)
2. **One tail number policy + terminology rename** — copy and KPI-routing
   changes in `60_render.js`; update INFO entries. (1 day.)
3. **First-run checklist** — extend the onboarding modal into a persistent
   3-step status card on the Portfolio tab empty/partial states; wire to the
   existing drop-zone handlers. (1–2 days.)
4. **Top-bar consolidation** — single climate-future select (the scenario
   composition logic in `wire()` already treats pathway+horizon as one key);
   move Peril/Brand/Map-colour into a Leaflet control. (1–2 days.)
5. **Tab merge** — retire Scenarios into Summary; fold By-peril into a
   drill-in; re-stage Adaptation into the three-step Decisions flow; move
   financial sliders to Data & method. (3–5 days, staged one tab per PR with
   frontend assertions updated alongside.)
6. **Data-confidence + staleness surfaces** land here too (§4 steps 2 and 4)
   so the simplified UI carries the trust information forward rather than
   hiding it.

---

## Closing summary — the ten most important actions across all sections

1. Fix the confirmed `phase_projects` off-by-one (crash under `--budget`).
2. Close the TC-rainfall Hawaii coverage hole and surface per-site coverage.
3. Build the assumptions registry (one sourced, versioned copy of every
   constant; kills the four-way mirror pattern).
4. Replace comonotonic catalog addition with year-simulation in the pack.
5. Ship the validation verdict and a pack-vs-app divergence number into the
   product.
6. Cite or re-derive the WARMING/SLR tables with explicit baselines; move to
   regional SLR.
7. Unify appraisal settings between pack and app.
8. Adopt USFS burn probability for the wildfire grid; keep FIRMS for the
   event set.
9. Write MODEL_CARD.md and put "perils not modeled" on every summary
   surface.
10. Flip the app to simple-by-default, one tail number, four tabs, and a
    first-run data checklist.
