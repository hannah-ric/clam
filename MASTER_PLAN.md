# MASTER PLAN
## Research synthesis and forward roadmap for the Resort Climate Risk Explorer

Prepared 2 July 2026. Grounded in a review of CLIMADA Core 6.1 and CLIMADA Petals 6.1
documentation and source, the project's own documents (`docs/FULL_EXECUTION_PLAN.md`,
`docs/RUNBOOK.md`, `docs/climada_petals_integration_plan.md`), a line-level structural
review of the v1.7 application, and the contract tests in `tests/`.

This document complements the integration plan; it does not supersede it. The
integration plan's Phases 0 to 4 are code-complete. This plan covers what comes next.

=============================================================================
SECTION 1: WHAT THE SYSTEM IS, AND WHY IT IS GOOD
=============================================================================

Two tiers, one contract.

The backend is a hazard factory, not a risk engine. It turns internet climate science
(ETH Data API wind and river flood, Petals TCSurgeBathtub surge over an SRTM15+ DEM,
NOAA CPC heat climatology shifted per AR6 warming) into two small files:
`hazard_grid.csv` and `hazard_grid_meta.json`. A validator gates every ship.

The frontend is a zero-install risk engine over static data. One self-contained HTML
file holds all vulnerability, financial, adaptation, insurance, uncertainty, and
backtest logic. Grid rows supersede its interim analytic models per peril; outside
coverage it falls back explicitly, never silently. It never talks to CLIMADA or the
internet, which keeps the GPL boundary clean and the portfolio data private.

Five properties make this system worth extending rather than replacing:

1. The trust surface. Per-peril chips (green: grid-fed, all scenarios; amber: partial,
   named horizons fall back; gray: interim), a provenance sidecar rendered in the app,
   and a validator that cross-checks the sidecar against the data so the display can
   never overstate what was computed.
2. Graceful, explicit degradation. Every peril has an interim model; every fallback is
   surfaced.
3. Offline by default. Nothing leaves the machine; localStorage persists across
   sessions; Power BI drinks from the same CSV export it always has.
4. Plain-language explainability. Every number has an INFO popover; the Method tab
   states limits honestly (bathtub surge has no waves or levees; ISIMIP river flood is
   a 5 km model, not a FEMA study; heat is a delta shift of observed climatology).
5. Independently shippable phases with tests as contracts.

=============================================================================
SECTION 2: WHAT CLIMADA OFFERS THAT THE SYSTEM DOES NOT YET USE
=============================================================================

The app labels three of its own outputs as approximations. CLIMADA Core provides the
canonical version of each.

**The portfolio tail.** `finPortfolio` blends a fully-correlated sum with a
root-sum-square using a fixed correlation of 0.30, and the app labels the result an
upper bound. Core's `ImpactCalc(exposures, impfset, hazard).impact()` runs the real
synthetic event sets against the real site exposures and yields the true joint
exceedance curve via `Impact.calc_freq_curve(return_periods)`, plus `eai_exp` (per-site
expected annual impact) and `aai_agg` (portfolio average annual loss).

**Adaptation appraisal.** The adaptation tab re-implements CostBenefit: mechanism
modifiers, averted AAL annuitised at a discount rate, a waterfall of today + growth +
climate change. Core's `CostBenefit.calc(hazard, entity, haz_future, ent_future,
future_year)` is the canonical implementation, where `Entity` bundles Exposures,
ImpactFuncSet, DiscRates, and MeasureSet. The app's five measures map onto Measure
parameters: wind hardening to `mdd_impact`, floodproofing and coastal buffer to
`hazard_inten_imp` shifts, and the insurance layering tab to `risk_transf_attach` and
`risk_transf_cover`.

**Uncertainty.** The tornado panel sweeps five factors one at a time and combines by
root sum square, labelled a screening. Core's `unsequa` module wraps uncertain inputs
as `InputVar` objects with scipy distributions, propagates them through `CalcImpact`
and `CalcCostBenefit` with Saltelli sampling (N x (2D+2) model runs; the docs use
N=128), and returns real quantiles plus Sobol first-order and total-order sensitivity
indices.

One more Core capability closes the backtest loop: the impact-function calibration
module can fit the wind vulnerability curve (v_half) to the observed-loss CSV the
backtest tab already ingests.

Petals modules beyond the three already integrated, in rough order of future fit:
TCRain (pluvial rainfall from the same track sets), TCForecast plus the Warn module
(a live storm-watch product surface on the same map and site chassis), the CAT bond
engine (prices risk transfer off the loss exceedance curve the results pack will
produce), OSM footprint exposures (upgrades top coastal sites from a point to a
footprint), and the Hazard Emulator (warming-level scenarios and a true 2030).

Version and operational facts that bound the design: core and petals must share a
major version, but the petals minor may lead core's (petals releases between core
releases and declares an open floor on core; petals 6.2.0 requires climada>=6.1
and there is no core 6.2.0, so conda-forge resolves core 6.1.x + petals 6.2.x); the
Data API property vocabulary drifts
between releases, so the candidate-fallback fetch pattern and `list_datasets.py` stay;
impact runs keep `save_mat=False` unless per-event detail is needed; the API caches
under `~/climada/data`, so re-runs are cheap.

=============================================================================
SECTION 3: THE ROADMAP
=============================================================================

Four phases. Each ships on its own and leaves the system better even if the next never
starts. Contracts that never break: the grid CSV + meta sidecar schema, the app's CSV
export schema (Power BI), localStorage keys, and validator exit-0 gating every artifact.

-----------------------------------------------------------------------------
PHASE A: CONSOLIDATE AND DE-FRICTION
-----------------------------------------------------------------------------

Goal: the working system lives in this repository, tested on every push, and the
quarterly ritual runs with one command on any machine.

1. DONE: the working system's complete file set is imported verbatim and the app
   lineage is verified reproducible (v1.5 through both patchers to v1.7, byte for
   byte). The tests in `tests/` pin the contracts.
2. CI (GitHub Actions): run `test_gridops.py`, `test_phase23_ops.py`,
   `test_pipeline_sim.py` (pandas/numpy only) and `test_frontend.py` (node only) on
   every push. Green CI becomes the merge gate.
3. One-command container: a Dockerfile on a conda-forge base with climada and
   climada-petals pinned at 6.* (resolving core 6.1.x + petals 6.2.x today),
   certificate handling baked in, wrapping
   `run_pipeline.sh`. DEM handling automated: fetch, then `convert_dem.py` crop, into
   a cache mount; the manual USB-carry fallback stays documented for locked-down
   networks. `docker run ... --fast` reproduces the runbook rehearsal with zero setup.
   The Mac-native conda path remains first-class; the container is the friction-free
   alternative and the future scheduler target.
4. If grid size ever bites the drag-and-drop, gzip the CSV and add a pako inflate in
   the loader (two lines, per the integration plan).

Acceptance: a fresh machine goes from clone to a validator-exit-0 `--fast` bundle with
one command; the v1.7 app loads it and shows the expected chips; CI is green.

-----------------------------------------------------------------------------
PHASE B: THE RESULTS PACK (the integration plan's Phase 5; the credibility leap)
-----------------------------------------------------------------------------

Goal: the portfolio loss curve, adaptation appraisal, and uncertainty bands become
CLIMADA-native, delivered as a second artifact the app displays alongside (not instead
of) its live interactive model.

STATUS: shipped (steps 1 and 2). pipeline/refresh_impacts.py produces
results_pack.json (+ meta sidecar) gated by pipeline/validate_pack.py; contracts
pinned by tests/test_impactops.py and tests/test_impacts_sim.py. The v1.8 app
(patch_frontend_p5.py from v1.7) ingests the pack on the same drop zone (JSON
kind sniffing), persists it, and renders a Method-tab pack panel showing the
event-set figures for the selected scenario beside the live model's equivalents.
The backtest CSV can now drive a v_half calibration (--backtest): bisection fits
the wind curve so modeled present-day acute AAL over the matched sites equals
observed losses; the fit is recorded in the pack as an optional setting, never
silently applied. Deliberate scoping, revisit when needed: impact arithmetic
implemented directly (identical math to ImpactCalc for point exposures, chosen
so the parity tests run without CLIMADA); uncertainty is seeded joint Monte
Carlo over the tornado's three physical factors (the unsequa Saltelli/Sobol
upgrade slots behind run_uncertainty()); adaptation covers the three
hazard-touching measures in the direct-damage domain (ops and cooling stay
app-side); multi-country packs report adaptation and uncertainty for the
largest country by value.

DECISION WORKFLOWS (post-Phase-B increment, shipped): v1.9
(patch_frontend_p6.py) turns the pack into two decisions. Insurance renewal:
the risk layering panel and the pack panel both show the event-set technical
premium for the configured layer (expected annual loss to the layer on the
pack's joint exceedance curve, times the load slider), the benchmark to judge
broker quotes against. Capital prioritisation: refresh_impacts.py emits
per-site adaptation detail and a capital_plan section, every in-scope
(site, measure) pair ranked by canonical BCR at the middle-pathway 2050
appraisal; the app renders the top of that list. Both are gated by
validate_pack (plan sorted, BCRs reconcile with averted x annuity / cost).

The original step-1 design notes, kept for the record:

1. New `pipeline/refresh_impacts.py`:
   - Reads the site CSV; builds a point `Exposures` GeoDataFrame (asset values,
     `impf_` id per construction class).
   - Encodes the app's exact curves as an `ImpactFuncSet` first: the Emanuel wind
     curve with the app's V_THRESH=25.7 and V_HALF=74.7, and the concave `floodMdd`
     stage-damage shape as explicit ImpactFunc objects. Parity before improvement, so
     every divergence between pack and browser is attributable to the event-set math,
     not to curve drift.
   - Runs `ImpactCalc` per peril per scenario over the full cached synthetic event
     sets; emits per-site EAD and the true portfolio exceedance curve at the six
     return periods.
   - Runs `CostBenefit` for the five measures via their Measure-parameter mappings,
     with DiscRates from the app's adaptation sliders.
   - Runs `unsequa` with the five factors the tornado already sweeps as InputVar
     distributions; emits P5/P50/P95 on AAL, VaR, and BCR plus Sobol driver ranking.
     Modest Saltelli N by default; `--fast` reduced-N mode for rehearsals.
2. Output: `results_pack.json` plus a meta sidecar following the existing convention.
3. Validator grows a pack section: exceedance curve monotone, AAL non-negative, pack
   and grid provenance cross-check, and a pack-versus-browser divergence report.
4. Frontend (surgical edits, single-file pattern preserved): one more drop route in
   `routeHaz`; when a pack is loaded, the EP curve, VaR, adaptation, and uncertainty
   panels show the authoritative figures badge-labelled next to the live model, and
   the footer's disclosure caveats narrow peril by peril.
5. Calibration loop: feed the backtest observed-loss CSV into Core's impact-function
   calibration to fit v_half regionally; surface the fitted curve as an optional
   vulnerability setting.

Acceptance: pack VaR at 1-in-100 sits at or below the app's labelled upper bound; the
browser CostBenefit agrees with the canonical run within a documented tolerance;
`test_frontend.py` extended and green; the runbook spot-checks still pass.

-----------------------------------------------------------------------------
ADAPTATION-FIRST PROGRAM (three increments; #1 shipped)
-----------------------------------------------------------------------------

Gap analysis: risk measurement is strong, but short-term adaptation planning
needs (1) building profiles rich enough to price measures against a real
baseline, (2) a realistic per-peril measure catalog with applicability rules,
unit costs, downtime, and insurance co-benefits, (3) wildfire and pluvial rain
in the peril set, (4) budget and refurbishment-cycle phasing lenses.

Increment 1 (SHIPPED): profile schema v2. Optional site columns (roof_type,
roof_year, opening_protection, first_floor_elev_m, equipment_elevated,
stories, keys, renovation_year, wui_class, defensible_space_m, roof_class_a,
fema_zone) drive a documented vulnerability factor table (vuln_v2, mirrored
exactly between refresh_impacts.py and the v1.10 app): roof detail supersedes
the year-built proxy, a measured first-floor height supersedes the defended
0.5 m proxy, elevated critical systems cap flood MDD at 0.5. A six-field
sites.csv reproduces today's numbers exactly (compatibility pinned by tests).
pipeline/enrich_sites.py drafts profile fields from public data (DEM sample,
dist-to-coast, FEMA NFHL zone, OSM building count) with per-field provenance,
needs_review flags, never overwriting operator values, every source skippable.

Increment 2 (SHIPPED): pipeline/measures_catalog.py, a ten-measure catalog
across wind, flood, wildfire, and continuity. Applicability predicates on the
profile with plain-language exclusion reasons; retrofit effects DERIVED from
the vuln_v2 factor table itself (re-roofing benefit is exactly the factor
delta it causes, so an already-new metal roof correctly gains nothing);
per-key costs with value-percent fallbacks; lifecycle BCR over min(lifespan,
horizon); premium-credit hook at 0 until broker quotes arrive. Capital plan
v2: refurbishment-cycle phasing (renovation_year within 3 years shares
mobilization at a 0.85 cost factor), --budget fills years 1..3 greedily by
BCR and DEFERS what does not fit (never drops it), wildfire and continuity
measures surface as identified-not-yet-priced. The v1.11 app renders phase
years, deferral, synergy tags, the budget, and the identified list.
validate_pack gates funded-project ordering, per-year budget, and per-project
annuity reconciliation.

Increment 3 (SHIPPED): wildfire and TC rainfall as the fifth and sixth perils.
refresh_wildfire.py encodes annual burn probability (percent, indicator style
like heat) from Petals WildFire behind a candidate-fallback seam, scenarios
scaled by WARMING x FIRE_WARMING_UPLIFT (0.14/C). refresh_prain.py encodes
event rainfall (mm at return periods) from TCRain over IBTrACS-derived
synthetic tracks, scenarios by Clausius-Clapeyron (7%/C). validate_grid gained
wfire and prain sections (burn probability bounded 0..100, indicator rows
excluded from monotonicity, per-hazard signal columns). The v1.12 app
(patch_frontend_p9.py, fifteen anchored edits) registers both perils
everywhere: selector, chips (n/6), ratings, combined score, risk drivers,
by-peril split, business interruption, scorecards, and a new
wildfire-hardening measure in the adaptation engine. MIGRATION SAFETY is the
design center: no wfire grid + no wui_class = zero wildfire; no prain grid =
zero rainfall (deliberately NO interim model, rain cannot be proxied honestly
from regional anchors), so v1.12 with no new data reproduces v1.11's numbers
exactly, pinned by tests. Wildfire damage: value x burn probability x
conditional damage ratio (0.6) x profile modifiers (Class A roof 0.6,
defensible space 0.7). Rainfall damage: mm to ponding depth via documented
drainage constants (150 mm capacity, 0.4 ponding, 0.3 m freeboard), then the
flood curve. The follow-ups shipped in the coherence pass: wfire and prain
now flow through the results pack's event math (wildfire as a frequency-scaled
event set, rainfall through the drainage transform, both honoring warming
uplifts), catalog wildfire measures price pack-side, run_pipeline.sh
orchestrates the new producers behind --fire/--rain opt-in flags, and a
holistic review pass (v1.13) fixed every misleading data trail found: the
by-peril split, export columns, chip counts, and INFO copy all agree on six
perils.

-----------------------------------------------------------------------------
PHASE C: THE EXPERIENCE LEAP (frontend v2)
-----------------------------------------------------------------------------

Goal: retire the patch-anchor build chain and give the product the interface its
science deserves, without changing a single answer until the parity gate passes.

STATUS (C1 SHIPPED): the structural rebuild is done. The app's source of truth
is now app/src/: a shell head, eight readable JS domain modules (hazard engine,
finance, adaptation, uncertainty, state and INFO copy, render, intake, persist
and wiring), and a shell tail, concatenated in MANIFEST order by
app/assemble_app.py into the same zero-install single-file deployable
(Resort_Climate_Risk_Explorer_v210.html). The split from v1.13 was proven
lossless byte for byte before any edit. The refactor inside the source made the
peril set registry-driven: scorePhysTotal, the financial by-peril split, and
the Power BI export all iterate the ACUTE registry, with the export column
order frozen by explicit EXPORT_ACUTE_LEGACY and EXPORT_ACUTE_APPENDED lists
so the contract cannot drift. The executable spec demanded below exists:
tests/test_app_parity.py runs an identical six-peril fixture through v1.13 and
v2.0.0 and requires exact equality across per-site per-peril EAD, the
financial layer, adaptation with and without modifiers, waterfall, insurance
layering, uncertainty bands, and the export CSV string byte for byte. CI gates
both directions: assemble_app.py --check catches a deployable that drifted
from source, and the parity test catches a refactor that changed an answer.
The patchers remain as verified history (v1.5 through v1.13 regenerate byte
identically); new work edits app/src/ and reassembles.

STATUS (C2 SHIPPED, v2.1.0): the experience layer landed on that foundation,
render-only so the parity-pinned math is untouched. Shipped: a scenario
timeline on the Summary tab (Present / 2030 / 2050 / 2080 under the top-bar
pathway, with Play animating the walk and the top-bar selects kept in sync);
"why these numbers" score tracing on every site scorecard (each peril walks
from its data source, grid cell distance and dataset name, or the named
interim model, or an honest zero with the reason, through the intensities and
the building's named factors to the EAD, with a test pinning the wind factor
trail's product to vulnOf so the trace cannot diverge from the math); a
one-click board brief (print-optimized one-pager with headline figures, cost
by peril, most exposed sites, trajectory, capital plan when a pack is loaded,
and a data-basis line, delivered as PDF through the browser's print dialog,
zero dependencies); map popups that open scorecards directly; and a top-bar
brand filter for the map. Every C2 item on the list below is now live, the
CSV export schema is unchanged (partition-tested), and the suite grew to 101
frontend assertions plus a real-browser smoke pass.

1. Parity first. Every constant, formula, measure, fallback, and the no-grid
   regression from v1.7 becomes an executable spec (the successor to
   `test_frontend.py`'s 31 assertions) before any visual work begins.
2. Rebuild the structure. Original sketch said Vite + TypeScript + MapLibre; the
   shipped C1 deliberately kept the zero-toolchain constraint instead (readable
   source modules + a dependency-free Python assembler), because "opens from
   file://, nothing to install" is the product's distribution model and a node
   build chain would break it for the exact operators it serves. Zero-install
   (file:// or any static host), no backend, same localStorage privacy, same
   drop UX for grid, meta, and pack. The prior deployable stays authoritative
   until the parity suite passes against the new app (it has: v2.0.0 == v1.13).
3. The experience, realistically scoped:
   - Map-first home: per-site risk halos, peril toggles, brand filters.
   - Site scorecards with "why is this red?" drilldowns that trace a score to the
     grid cells and the dataset that produced it.
   - A scenario scrubber that animates the portfolio across pathways and horizons.
   - Adaptation what-if with live BCR, waterfall, and layering, now with the pack's
     canonical figures beside the interactive ones.
   - Uncertainty bands drawn on every headline number.
   - The Method and trust surface as a first-class page, rendered from the manifest.
   - One-click board-ready PDF export.
   - The INFO popover corpus carries over intact as the plain-language layer.
4. The CSV export schema does not change (Power BI).

Acceptance: parity suite green against the prior deployable's outputs (met:
v2.0.0 matches v1.13 exactly, export string byte for byte); grid and pack
drops behave identically; trust chips behave identically; export
byte-compatible. C2 acceptance: every new surface (map drilldowns, scrubber,
PDF) reads from the same functions the parity suite pins, so the numbers on
screen are the numbers under test.

-----------------------------------------------------------------------------
PHASE D: FRONTIER OPTIONS (choose by appetite after C)
-----------------------------------------------------------------------------

- TCRain as a pluvial layer (Harvey-type losses neither wind nor surge captures).
- TCForecast + Warn: a live storm-watch mode over the same map and site model.
- CAT bond pricing behind the insurance layering tab, off the pack's loss curve.
- OSM footprints for the highest-value coastal sites (surge cares about 200 m).
- CoastalDEM swap-in when granted (corrects SRTM's high bias on built coasts).
- Hazard Emulator for warming-level scenarios and a true 2030 horizon.
- NEX-GDDP-CMIP6 heat ensemble behind the existing HeatAccumulator seam.

=============================================================================
SECTION 4: PRINCIPLES, RISKS, AND EFFORT
=============================================================================

Principles carried through every phase:
1. Trust surface first: validator exit 0 gates every artifact.
2. Graceful, explicit degradation.
3. Offline by default; CLIMADA stays pipeline-side (the GPL boundary).
4. Behavior-preserving migration: parity tests before any answer changes; deliberate
   upgrades documented in the Method tab copy.
5. Plain-language explainability is a feature, not copy.
6. Contracts are stable: grid schema, export schema, localStorage keys.

Risks and mitigations:
- Import completeness: RESOLVED; the full working set is committed and the lineage
  regenerates byte for byte in CI. The tests define the contracts if a copy is lost.
- Data API drift: keep the candidate-fallback pattern and `list_datasets.py`; record
  matched properties in the meta sidecar.
- unsequa compute cost: modest Saltelli N, `--fast` mode, parallelize when needed.
- Frontend rewrite regression: the parity suite is the gate; the current
  deployable stays deployable
  until C passes it.
- Scope creep: A, B, C ship independently; B is the single highest-value increment.

Effort, honestly: Phase A is days of work spread over setup and CI plumbing. Phase B
is one to two weeks including validation against the browser model (the integration
plan's own estimate for Phase 5, which this is). Phase C is two to four weeks, with
the parity suite consuming the first chunk deliberately. Phase D items range from
days (CoastalDEM swap) to weeks (storm-watch mode).

The one-sentence version: keep the two-tier soul, make the science canonical, make
the ritual one command, and only then make it beautiful.
