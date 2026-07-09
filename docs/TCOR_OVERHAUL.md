# TCOR overhaul: financial spine + calibration (review checkpoint)

CLAM's repositioning from "how badly could each building be damaged" to
"what does climate risk cost TNL per year, all in, and where can we lower
it". This checkpoint delivers the pipeline prerequisite, Task 1 (TCOR
spine + aggregation rule), the Task 2 event-level deductible engine and
attritional layer, and Task 5 (loss-run calibration). It stops, as
instructed, BEFORE interface work for review.

## Prerequisite verification (hazard-layer integrity)

| Prerequisite | Finding |
|---|---|
| Per-event, per-site losses with event IDs in results_pack.json | **WAS ABSENT: blocker.** The [events x sites] matrices existed transiently inside `eval_scenario` but were never emitted. Now emitted (see below). |
| Joint wind+surge as the canonical tail | Confirmed: `combined = wl + sl` on a shared catalog per source; pack meta records `wind_surge: per event (shared catalog, truly joint)`. Untouched. |
| Per-site coverage resolved | Confirmed: `per_site[].coverage` flags per peril; sites outside coverage flagged, never zeroed. Untouched. |
| Wildfire from WRC point burn probability | Confirmed (Task 3.5 lineage): point-sampled BP x conditional damage; FIRMS retired from loss. Untouched. |
| Warming/SLR constants in one sourced registry | Confirmed: `pipeline/assumptions.py` with `--check` parity gate. Untouched. |
| Loss integration includes events more frequent than 1-in-10 | Confirmed pipeline-side (no frequency floor; meta `ead_basis`); app-side `subTenPts` extends the interim integral. The new ladders make the 1-in-2..1-in-10 band an explicit, consumable output. |

## What the pipeline now emits (additive; pack_version stays 1)

`pipeline/refresh_impacts.py` (readers only; no hazard math changed):

- **`event_sets`**: per scenario, per wind source: `{source, weight,
  country, aal_usd, kept_aal_usd, events: [{id, freq, sites: [[site_index,
  loss_usd], ...]}]}`. Event ids are the catalog's `event_name` when the
  hazard carries one, else `source:index`. Sources are ALTERNATIVE
  catalogs blended by weight and never merged; losses are the joint
  wind+surge sum per event (the shared hurricane deductible's basis).
  Site-event entries below `--event-floor` (default $1,000) are dropped
  and the drop is bounded by the validator.
- **`frequent_losses`**: per scenario, per peril (`tc`, `cflood`,
  `tc_joint`, `rflood`, `prain`, `wfire`), a per-site loss ladder at RPs
  [2, 5, 10, 25, 50, 100, 250, 500] (the `site_rp` step convention,
  extended into the attritional band).

`pipeline/validate_pack.py` gates both: id uniqueness per source,
positive frequencies, site indices in range, per-country weight
normalization, event-AAL reconciliation with tc+cflood AAL (2%), floor
drop bounds (warn 2%, fail 10%), ladder shape and monotonicity.

## App: module layout (single-file build preserved)

Two new modules in `app/src/` (MANIFEST order):

- **`22_tcor.js`**: program parameters (`tcorProgram`: deductibles by
  class with basis, aggregate cap, BI terms, premium, admin, indirect
  factor: all parameterized, persisted, never hardcoded facts);
  `eventRetained` (the aggregation rule, pure); ladder math
  (`ladderIntegral`, `ladderRetained`); `retainedPropertyCalc` (event-
  level hurricane, per-location flood/general, explicit attritional
  layer); `simulateRetainedYears` (seeded, deterministic; exact aggregate
  cap + bad-year distribution); `retainedBICalc` (interim chain, waiting
  vs overage split); `premiumCalc` (actual first, technical benchmark
  else); `tcorSite` / `tcorPortfolio` (the five-part spine + flagged
  indirect + per-site quality marks + waterfall data for Task 7).
- **`25_lossrun.js`**: loss-run CSV ingestion (header aliases, money
  parsing, Net Incurred basis check), claimant-to-site and Coverage-
  Major-to-class mapping (unmatched/unmapped flagged WITH dollars),
  claim-to-event grouping (named storms by name, else 3-day same-class
  clusters), actual aggregation by site/class/year/event, and
  `lossrunCalibration` (modeled vs actual per class, attritional hit
  frequency, BI, multi-site validation, body-vs-tail credibility, open-
  claim development flags, prominent disagreement list).

Wiring only (no interface work): loss-run CSVs route through the
existing drop zone by header sniff; `campus_code`, `campus_name`,
`owned_or_leased`, `bi_ee_usd`, `premium_annual_usd`,
`mitigation_annual_usd` load from the site CSV as a documented v3
subset (the full SOV importer is Task 8); `tcorProgram` and `lossRun`
persist and restore; INFO entries (`tcor`, `tcorAgg`, `attritional`,
`biRetained`, `lossrun`) teach the logic.

## The aggregation rule (the correctness core)

- Hurricane (joint wind+surge events): ONE deductible per occurrence per
  campus (SOV Campus Code is the sharing unit; `per-occurrence-program`
  supported), computed at the EVENT level from `event_sets`, allocated
  back to sites pro-rata so rows still sum to the event-level truth.
  **Never the sum of per-site hurricane deductibles.**
- Flood / general property: per-location deductibles integrate each
  site's own ladder and sum across sites.
- Attritional layer: expected annual retained loss and deductible hits
  from the 1-in-10-and-more-frequent band, summed portfolio-wide.
- Degradations, all labeled: no event table -> campus-comonotonic ladder
  approximation; no campus codes -> own-unit sharing (flagged as
  overstating retained hurricane loss); no pack ladder -> interim curves
  with the subTenPts loss-space extension.

Acceptance evidence (tests/test_tcor.py, in CI):
- six sites in one campus hit by one modeled hurricane retain exactly
  ONE shared $1M deductible ($1.0M, not $2.4M);
- two campuses hit by one storm retain two; program basis retains one;
- hand-computed event sums, ladder integrals, and waterfall
  reconciliations match; TCOR is exactly the five-part sum with the
  indirect estimate flagged OUTSIDE the total;
- the loss run groups Hurricane Zeta's three claims at three sites into
  ONE event; calibration flags material disagreement, splits named-cat
  dollars from the body, and reports open-claim development risk.

## Interim placeholders (labeled in every output they touch)

- Retained BI uses the interim damage-to-downtime chain (linear reopen
  model, GOP proxy revenue). Task 3 replaces the transform (archetype/
  peril downtime, amenity partial impairment, seasonality, timeshare
  revenue structure, regional demand shock); the terms math (waiting /
  indemnity / limit, per-event application) stays.
- Premium is actual-where-on-file plus a technical benchmark (load
  factor shared with the existing insurance panel). Task 4 adds the
  technical-vs-actual gap surface.
- Tenure (owned/leased) is ingested and flagged but does not yet adjust
  retained components (Task 8, needs SOV value splits).

## Remaining after review

Task 3 (BI module), Task 4 (premium surfaces), Task 6 (adaptation payoff
in TCOR terms), Task 7 (TCOR front door + waterfall), Task 8 (full SOV
schema v3 importer), Task 9 (demotions). The engine already produces the
waterfall, attritional, bad-year, and calibration data those surfaces
need.
