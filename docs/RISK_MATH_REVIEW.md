# Risk-Math Review: accuracy audit and remediation plan

*Reviewed: July 2026, at commit `f429e09` (v2.3.0 app, Phase 5 pipeline).*
*Scope: the risk mathematics, the assumptions behind it, and how results are
presented to the small group of TNL leaders using this tool for capital and
coverage decisions. This is an internal-quality review, not a compliance
document.*

The review covered, first-hand: `pipeline/assumptions.py`,
`refresh_hazard.py`, `refresh_heat.py`, `refresh_wildfire.py`,
`refresh_prain.py`, `refresh_impacts.py`, `measures_catalog.py`, both
validators, and the app engine (`10_hazard_engine.js`, `20_finance.js`,
`30_adaptation.js`, `40_uncertainty.js`) plus the presentation surfaces
(`60_render.js`, `65_exec.js`, `50_state_info.js`). The full test gate
(`bash tests/run_all.sh`) was run and passes; the parity claims below were
verified against that run, not taken from the docs.

---

## 1. Verdict in three sentences

The event-set math, the assumptions governance, and the honesty
architecture are genuinely strong - most screening choices are named,
cited, test-pinned, and labeled in the UI, which is rare at this maturity.
Accuracy degrades in specific, identifiable places: the 250/500-year tail
rests on an under-resolved track set, the app's coastal-flood grid dilutes
surge depth by construction, the TC-rainfall peril is mathematically almost
incapable of producing a loss, business interruption is the weakest
financial link and has no independent test, and the conservative warming
margins distort exactly the pathway comparison the scenario timeline
showcases. The executive surface - the one the decision-makers actually
land on - carries the weakest caveat labeling in the app, so the remediation
plan below is as much about presentation parity as about model upgrades.

---

## 2. Where accuracy holds

These are load-bearing strengths, verified rather than assumed:

**Assumptions governance.** Every shared scenario constant lives once in
`pipeline/assumptions.py` with value, units, baseline period, citation, and,
where the effective number sits above the AR6 central, an *explicit*
`conservative_delta` with a reason (`assumptions.py:56-80`, `112-133`). The
AR6 WG1 Table 4.1 warming centrals and Table 9.9 GMSL centrals check out
against the source. The app's copy is a generated module, byte-compared in
CI (`assumptions.py --check`), and `tests/test_warming_parity.py` asserts
`effective == central + delta` for every entry. The registry pattern makes
every criticism in this review fixable in one place.

**Event-set impact math (the results pack).** Per-event losses, EAD as
frequency-weighted expectation, and the exceedance curve built from sorted
event losses with cumulative frequency (`refresh_impacts.py:367-428`) are
correct implementations of the standard math and are pinned by oracle unit
tests (exact at event RPs, log-RP interpolation between, flat tail beyond,
zero-frequency guards; `tests/test_impactops.py`). Wind and surge share one
event catalog and add per event - a *truly joint* treatment
(`refresh_impacts.py:541`), which is the honest way to combine them, and the
pack correctly labels everything else comonotonic.

**App ↔ pipeline parity.** The damage curves, factor tables, and all
mirrored constants are pinned identical on both sides
(`tests/test_warming_parity.py:163-183`, `tests/test_frontend.py:255-268`),
and the v2.0.0 rebuild was proven byte-identical to v1.13 across perils,
finance, adaptation, and exports before it took over. The two codebases
cannot silently drift.

**The honesty architecture.** Per-site-per-peril trust states (a site can
never show green on a peril whose grid didn't reach it,
`10_hazard_engine.js:425-481`), explicit NOT-MODELED chips for hail,
non-TC pluvial, and drought (`10_hazard_engine.js:487-499`), coverage
flags instead of silent zeros throughout the pack
(`refresh_impacts.py:1028-1034`), and a calibration that is recorded but
never silently applied (`build_calibration`, `applied: False`, with a bias
flag outside 0.5–2.0). The wildfire rework (retiring FIRMS cell-occupancy
that produced a ~$731M/yr fire AAL for a beach portfolio, replacing it with
WRC point burn probability plus a unit sanity check that refuses to guess a
rescale, `refresh_wildfire.py:216-221`) shows the process catches
order-of-magnitude errors and documents why.

**Internal consistency of the decision layer.** Measure benefits are
derived from the same vulnerability factor table the base model uses
(`measures_catalog.py:42-54`), so a retrofit's modeled benefit is exactly
the factor delta it would cause; the plan phasing never silently drops
projects; the validators gate EP monotonicity, AAL reconciliation, and
BCR arithmetic before anything ships.

---

## 3. Where accuracy degrades

Ranked by likely impact on the two decisions this tool informs (capital
allocation and insurance coverage). "Acknowledged" means the limitation is
already stated somewhere in the repo's docs; several of the items below are
acknowledged in principle but have consequences the docs do not draw out.

### 3.1 The tail the insurance decisions price against is the least-resolved part of the model - *partly acknowledged*

- The authoritative hazard run defaults to `NB_SYNTH_TRACKS = "10"`
  (`refresh_hazard.py:221`). The docs themselves say 10 under-resolves the
  250/500-year tail and recommend 50 (`docs/FULL_EXECUTION_PLAN.md` step 29),
  but nothing enforces or even warns about it: `validate_grid.py` does not
  check it, and the app never surfaces it.
- The grid path fills high return periods by **extrapolation**
  (`local_rp_intensity(..., method="extrapolate")`,
  `refresh_hazard.py:465`), while the pack clamps its tail **flat** beyond
  the largest simulated RP (`ep_curve`, `refresh_impacts.py:374`). Two
  different tail conventions coexist; neither surface says which one a given
  number used.
- The default insurance layer (attach 1-in-25, exhaust 1-in-250,
  `30_adaptation.js:8-14`) is priced by trapezoid integration over just six
  RP points, of which the top two are precisely the under-resolved or
  extrapolated ones. The "indicative premium" label is honest, but the
  premium's sensitivity to track count is invisible to the reader.

### 3.2 The app's coastal-flood grid dilutes surge depth by construction - *not acknowledged*

`thin_to_grid` cell-averages centroid values into 0.25° (~25 km) cells and
calls this "a mild, defensible smoothing" (`refresh_hazard.py:509-515`).
For wind - a smooth field - that is true. For surge depth - a sparse field
that is nonzero only in a narrow coastal strip - averaging the wet shoreline
centroids with the dry inland majority of the cell systematically
understates depth at the shore, before the 1.1 m freeboard is subtracted.
The pack does *not* have this problem (it samples the native ~150-arcsec
centroids per site, `refresh_impacts.py:1080-1088`), so app-grid and pack
cflood figures for the same beachfront site can diverge materially, and the
app side is biased low. The Task-4 relief adjustment shifts depth by the
site-vs-cell *mean ground* offset; it cannot recover the sub-cell depth
distribution that the averaging destroyed. Given the portfolio is
beach-heavy, this is probably the largest *unlabeled* quantitative bias in
the tool, and its direction (low) is opposite to the general conservative
lean, so it does not net out - it silently reshuffles the site ranking away
from surge-driven sites.

### 3.3 TC rainfall is a modeled peril that almost cannot produce a loss - *not acknowledged*

The drainage transform stacks three conservative-low constants: the first
150 mm of an event is absorbed, only 40% of the excess ponds, and 0.3 m of
freeboard applies before any damage (`refresh_impacts.py:132-134`,
mirrored at `10_hazard_engine.js:353`). Working backwards: **an event must
drop more than 900 mm of rain before the damage fraction exceeds zero**, and
1,200 mm - beyond Harvey at most locations - produces a 7% damage fraction.
Any site with a measured first-floor elevation pushes the threshold higher
still. The peril will read "modeled" (green chip) with ≈$0 EAD essentially
everywhere, which is worse than absent: it affirmatively tells the reader
that Harvey-type pluvial exposure has been priced and found negligible. The
constants have never been checked against a single observed rain-driven
loss. (Non-TC pluvial is separately and honestly chip-labeled NOT MODELED  - 
the problem is specifically that the modeled TC-rain peril presents a
near-structural zero as a finding.)

### 3.4 The conservative warming margins distort the pathway comparison - *partly acknowledged*

The deltas are explicit and cited, which is exactly right. But their
magnitudes are wildly asymmetric across pathways with no stated rule:
+0.4 °C on a 0.9 °C central for SSP1-2.6 at 2080 (a 44% margin) versus
+0.1 °C on 3.5 °C for SSP5-8.5 (a 3% margin) (`assumptions.py:61-65`). Two
consequences:

- The effective 2080 spread between pathways compresses from 2.6 °C (AR6
  central) to 2.3 °C, and SSP1-2.6 *keeps warming* from 2050 to 2080
  (1.0 → 1.3 °C effective) where AR6's central is flat (0.9 → 0.9). Every
  surface built to answer "what does the pathway choice buy us" - the
  scenario timeline, the climate-premium KPI, the disclosure table  - 
  inherits a pessimistic bias on the low-emissions branch specifically.
- The same asymmetry propagates into SLR (`assumptions.py:117-121`) and
  therefore surge at 2080.

A margin policy stated as a rule (e.g. "the 60th percentile of the AR6
likely range, every cell") would keep the conservatism and remove the
distortion.

### 3.5 Business interruption is the weakest financial link - *partly acknowledged*

BI is modeled as `GOP × (reopen months / 12) × damage-EAD fraction`
(`20_finance.js:27`): downtime strictly linear in the damage ratio, with a
12-month full-loss reopen default. Reality is convex (a resort with 30%
damage is often 100% closed for a season), seasonal (the roadmap's R8 item
acknowledges this), and includes contingent exposure (utilities, access,
destination demand) that no term here represents. BI routinely exceeds
property loss in hospitality events, and here it:

- has **no independent test oracle** (regression parity only - the docs
  agent's inventory confirms the heat formula is pinned but BI is not);
- rides defaults with no cited basis (`revRatio 0.35`, `gopMargin 0.30`,
  `reopenMonths 12`, `heatDrop 0.12`, `20_finance.js:3`) - adjustable, but
  nothing tells the operator what evidence would justify a change;
- is excluded from the pack's joint event tail, so the *canonical* tail is
  direct-damage-only and there is **no joint tail anywhere that includes
  BI** - the figure closest to what a coverage decision actually needs.

### 3.6 The live portfolio tail is a heuristic, and its uncertainty band describes a different quantity - *acknowledged, with one unacknowledged wrinkle*

`sqrt((1-ρ)·Σv² + ρ·(Σv)²)` at fixed ρ=0.30 (`20_finance.js:66-70`) is a
labeled screening stand-in and the pack supersedes it - all fine and
documented. Two wrinkles are not:

- The tornado band multipliers are derived from acute ratios and then
  applied to whichever tail figure is displayed; when a pack is loaded, the
  band under the tail card is computed from the *blend incl. BI* while the
  card shows the *joint direct-only* tail (`60_render.js:925` vs `:946`).
- The INFO copy attributes the band's upward skew to damage-curve convexity
  (`50_state_info.js:233-235`); it is at least as much a mechanical artifact
  of asymmetric input ranges (−30/+40%, −25/+50%,
  `40_uncertainty.js:1-7`). Similarly, the pipeline's MC factor is labeled
  "damage-curve steepness" but implemented as a linear scale on the damage
  fraction (`refresh_impacts.py:118-122`, `wind_losses`). Neither band
  includes hazard-model structural uncertainty (track count, bathtub, the
  4-member river ensemble), so the displayed ranges are likely too narrow
  even while individual point estimates lean conservative.

### 3.7 Comonotonic stacking and the conservative lean do not have a stated net direction - *partly acknowledged*

Independent catalogs (river flood, rainfall, wildfire, countries) add at
equal return period - a documented upper bound. Warming/SLR margins lean
high. Meanwhile surge dilution (3.2) and the rainfall transform (3.3) lean
low, SRTM overstates coastal ground elevation (surge low), and the flat
pack tail leans low beyond RP500. The docs describe each lean individually
but nowhere states the *net* posture of a headline number, and no
reconciliation exercise (pack vs app vs any external benchmark, e.g. a
broker CAT model output for the same portfolio) has been run. For a tool
feeding coverage decisions, "conservative" needs to be a demonstrated
property of the output, not of individual inputs.

### 3.8 The interim wind field is uncited - *not acknowledged*

The IDW anchor table (`ANCHORS`, `10_hazard_engine.js:69-77`) hardcodes
v100 and log-slope values for ~28 locations with no provenance anywhere in
code or docs. A Miami-type site scores ≈2.3%/yr wind EAD from it
(verified numerically) - plausibly high, band "Severe". The interim layer
is honestly *labeled* interim everywhere, so this is contained; but these
numbers steer real screening until a grid loads, and no one can audit where
they came from.

### 3.9 The backtest calibration is statistically fragile - *partly acknowledged*

Fitting `v_half` so modeled AAL matches summed `observed_annual_loss_usd`
(`refresh_impacts.py:905-971`) treats a short observed window as an AAL
estimate. For tail-driven wind risk, a decade of losses is an extremely
noisy AAL estimator (one Ian-type hit or miss swings it several-fold);
the fit also attributes the *entire* residual to the wind curve while
holding all other perils fixed. The recorded-never-applied discipline and
the 0.5–2.0 bias flag are the right guardrails, but the pack should also
record the number of loss-years and warn below a minimum, or the "fitted
v_half" will look more authoritative than it is.

### 3.10 Smaller items

- **FLOPROS ambiguity, both paths.** The app has
  `RFLOOD_GRID_INCLUDES_PROTECTION=false` with a documented decision
  procedure (`10_hazard_engine.js:250-253`, RUNBOOK) - good - but the
  pipeline pack path applies `FB_RIVER=0.6` unconditionally with no
  equivalent flag (`refresh_impacts.py:98`). If the served ISIMIP sets
  embed protection, both paths double-count it and understate river risk;
  the decision has apparently not yet been executed for the datasets in use.
- **Scenario blending averages quantiles.** 2050 wind = the mean of the
  2040 and 2060 curves' RP intensities (`refresh_hazard.py:348-358`) - the
  mean of quantiles, not the quantile of the mixture. Acceptable screening;
  worth one sentence in the method copy.
- **Wildfire portfolio curve ignores co-occurrence.** Sites are treated as
  mutually exclusive arrivals in `ep_curve(loss_given_fire, p)`
  (`refresh_impacts.py:626-628`); fire years are regionally correlated
  (drought), so the portfolio fire tail is mildly understated. Documented
  as per-site occurrence exceedance; the correlation caveat is not stated.
- **Heat cost basis.** Chronic heat cost uses dry-bulb `daysOver35` with an
  uncited 12% GOP drop and 15-day comfort baseline; the humid-heat lens is
  computed and displayed but deliberately not costed. Consistent and
  labeled, but the single most judgment-heavy chronic number rests on two
  unreferenced constants.
- **Exposure model.** One point, one `asset_value_usd` per site: no
  contents/structure split, no demand surge, no loss-adjustment expense.
  Standard for screening; should appear in the honest-limits list, which
  currently frames exposure limits as "point values until OSM footprints"
  (a geometry point, not a valuation one).

### 3.11 Presentation: the executive surface has the weakest labels in the app - *not acknowledged*

The analyst tabs and the Method/INFO copy are unusually candid (explicit
"upper bound", "blend approximation, not the joint tail", "screening",
per-figure bases). The exec home - the landing view for the actual
decision-makers - is the exception:

- The hero all-in AAL (`65_exec.js:239`) and its delta chip carry **no
  uncertainty band** (the analyst equivalent shows low–high) and no inline
  basis; caveats live in a basis button and a footer note.
- The tail tile's basis strings are the least specific in the app:
  "upper-bound blend" omits that the blend *includes BI*; "joint event
  tail" omits *direct damage only* (`65_exec.js:219,246`). Three different
  scopes (all-in AAL, tail, per-measure dollars) stack in one panel with
  the weakest labels anywhere.
- Precision theater: `fmt$` renders millions to two decimals (~$10k
  resolution) on screening-grade inputs; payback to 0.1 years; BCR to two
  decimals; "each year of delay forfeits $X" presents an expected value as
  a certain annual forfeiture (`65_exec.js:261-269`).
- Terminology collisions: "climate premium" (warming delta) vs "indicative
  premium" (insurance); "rare extreme year" meaning per-site RP100 damage
  in one column and the portfolio tail in another.
- Literature BCR ranges ("2 to 6×", "above 3.5 in Gulf Coast studies",
  `50_state_info.js:194,209`) sit next to the model's own computed BCRs,
  transferring external credibility onto screening outputs.

### 3.12 Validation gaps (what the strong test suite does *not* cover)

The suite pins app↔pipeline *mirroring* exhaustively - but both sides
implement the same equations, so mirroring is not validation. Missing:

- any cross-check of the direct impact math against CLIMADA's own
  `ImpactCalc` (CLIMADA is never imported in tests; the stated acceptance
  criterion in MASTER_PLAN has no automated form);
- an oracle for the correlation blend and for BI (regression-parity only);
- any test of the surge chain's physics (Petals is mocked with a linear
  fake), or of the grid-vs-pack per-site consistency for water perils
  (which would have caught 3.2);
- statistical validity of the uncertainty bands (only determinism and
  ordering are pinned).

---

## 4. What a remediation plan should cover

Sequenced by decision impact per unit effort. Phases 1–2 are the substance;
Phase 3 keeps the already-planned frontier items in view.

### Phase 1 - before the next capital/coverage decision cycle (low effort, high leverage)

1. **Make the authoritative run authoritative.** Run the quarterly refresh
   at `NB_SYNTH_TRACKS=50`; have `validate_grid.py` and `validate_pack.py`
   emit a hard warning when the meta says 10; surface track count and the
   tail convention (extrapolated vs flat) on the Method tab next to the
   250/500-year figures.
2. **Fix or label the surge dilution.** Preferred: publish water-peril
   cells from wet-centroid statistics (e.g. mean-of-wet plus a wet-fraction
   column) instead of all-centroid means, and have the app damage the wet
   fraction of value; cheaper stopgap: rename the depth basis
   "cell average (biased low at the shore)" and add a validator
   cross-check of grid-vs-pack per-site cflood EAD whenever both artifacts
   exist for the same sites.
3. **Execute the FLOPROS decision** per the runbook for the datasets
   actually served, and add the pipeline-side equivalent of
   `RFLOOD_GRID_INCLUDES_PROTECTION` so pack and app cannot diverge on it.
4. **Confront the rainfall transform with one observed event.** Reproduce a
   Harvey/Ian rain-only loss at any comparable property; recalibrate
   (drainage 150 mm, ponding 0.4, freeboard 0.3 m) or downgrade the peril's
   chip from "modeled" to an explicit "screening floor - understates
   pluvial" state. Do not leave a structurally-zero peril reading green.
5. **Presentation parity for the exec surface.** Carry the low–high band
   onto the hero figure; use the full `TAIL_JOINT_LABEL` / `TAIL_BOUND_LABEL`
   strings on the tail tile; round exec-facing dollars to 2 significant
   figures and paybacks to whole years; rephrase cost-of-delay as expected
   value ("forfeits an expected $X/yr"); rename one of the two "premium"s.
   Fix the band-under-joint-tail mismatch (compute the band from the same
   quantity the card displays, or drop it there).
6. **State a margin rule.** Re-derive `conservative_delta` for warming and
   SLR from a single stated rule (a fixed AR6 percentile), so pathway
   comparisons are undistorted. The registry structure makes this a
   one-file change plus regeneration.
7. **Cite or replace the interim anchors**; record their derivation in the
   repo, or precompute a small bundled grid from one authoritative run so
   the interim field inherits real provenance.

### Phase 2 - model upgrades with acceptance criteria (the roadmap items, sharpened)

1. **CLIMADA cross-check in CI.** One job in a `climada_env` container:
   pack math vs `ImpactCalc`/`calc_freq_curve` on a fixture portfolio,
   within a documented tolerance. This converts "identical math by
   construction" into "verified against the reference engine".
2. **BI model v2.** Convex damage→downtime curve (even two-segment),
   seasonal revenue weighting (roadmap R8), and a per-event BI term carried
   into the pack so a **joint tail including BI** exists - that number, not
   the direct-only tail, is what layer pricing needs. Ship default-off with
   a parity fixture, per the R8 pattern.
3. **unsequa/Sobol upgrade** behind `run_uncertainty()` as planned, but
   scope it to add hazard-catalog resampling (bootstrap over events) so the
   band finally reflects tail sampling error - the current dominant
   unquantified uncertainty. Correct the "convexity" explanation in INFO
   copy when the bands change.
4. **Backtest hardening.** Record loss-window years and exposure basis in
   the calibration block; refuse (or flag) fits on fewer than ~10
   site-years; report a v_half interval (e.g. from jackknifing years), not
   a point.
5. **Wildfire co-occurrence note or fix**: either a stated caveat that the
   portfolio fire curve assumes independent site arrivals, or a simple
   shared-year correlation factor.
6. **Reconciliation memo per quarterly refresh** (one page, generated):
   pack vs app per-site EADs by peril, grid trust coverage, tail convention,
   track count, and - when available - one external benchmark (broker CAT
   model or market technical premium) against the same portfolio. This is
   the artifact that lets a leader ask "which way does this number lean?"
   and get a written answer.

### Phase 3 - keep from the existing roadmap (unchanged, correctly scoped there)

CoastalDEM swap-in (raises surge, counteracting SRTM's high ground bias);
hazard emulator for warming-level scenarios and a true 2030; NEX-GDDP-CMIP6
heat ensemble; per-country adaptation/uncertainty expansion for
multi-country packs; CAT-bond pricing off the pack EP curve; OSM footprints.

### Governance thread through all phases

Maintain a one-page **model-risk register** (each material assumption, its
lean, its owner, its review date) seeded from §3 of this document; keep the
existing disciplines that already work (registry + generated constants,
recorded-never-applied calibration, validators as ship gates, parity
fixtures for any change that moves numbers).

---

## 5. Summary table

| # | Finding | Direction of bias | Acknowledged today? | Remediation |
|---|---------|-------------------|---------------------|-------------|
| 3.1 | 10-track tail + dual tail conventions | tail unstable / grid high, pack low | partly (docs only) | P1-1 |
| 3.2 | Surge depth diluted by 0.25° cell-averaging | low (coastal sites) | no | P1-2 |
| 3.3 | TC rain structurally ≈ zero (>900 mm to register) | low (severe) | no | P1-4 |
| 3.4 | Asymmetric warming margins distort pathway spread | SSP1-2.6 pessimistic | partly (deltas explicit, rule absent) | P1-6 |
| 3.5 | BI linear, unseasonal, untested, absent from joint tail | plausibly low | partly (R8) | P2-2 |
| 3.6 | Band/label mismatches on tail uncertainty | bands too narrow | partly | P1-5, P2-3 |
| 3.7 | No stated net posture; no external reconciliation | unknown | no | P2-6 |
| 3.8 | Interim wind anchors uncited | unknown (screening-high) | no | P1-7 |
| 3.9 | Backtest AAL-matching statistically fragile | n/a (guardrailed) | partly | P2-4 |
| 3.10 | FLOPROS unresolved; blend-of-quantiles; fire co-occurrence; heat constants; exposure model | mixed | mixed | P1-3, P2-5 |
| 3.11 | Exec surface: weakest labels, point estimates, precision theater | overconfidence | no | P1-5 |
| 3.12 | Mirroring ≠ validation; no CLIMADA/oracle cross-checks | n/a | partly | P2-1 |
