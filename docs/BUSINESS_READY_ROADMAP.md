# BUSINESS-READY ROADMAP
## From informational display to decision-grade product

Prepared 6 July 2026. Grounded in a line-level review of the v2.1.0 app
(`app/src/`, deployed as `app/TNL_Resort_Climate_Risk_Explorer_v200.html`), the
pipeline and its validators, every contract test in `tests/`, and external
research into what makes physical-climate-risk analytics decision-grade in
2024-2026 practice (regulatory drivers, commercial-platform feature sets,
insurance renewal usage, and adaptation-finance frameworks; sources cited
inline).

This document complements `MASTER_PLAN.md`; it does not supersede it. The
master plan's Phases A-C are shipped and Phase D lists frontier science
options. This plan answers a different question: the science and the
engineering are strong, so what turns the product from "informational"
(numbers on screen) into "business-ready" (numbers routed to decisions with
owners, thresholds, and exportable artifacts)?

=============================================================================
SECTION 1: THE GAP, PRECISELY
=============================================================================

A feature-by-feature classification of the current app shows the pattern:

Genuinely actionable already (the seeds):
- The site scorecard writes a per-site recommendation with a top-3 measure
  list ranked by BCR (`renderScorecard` and `scorecardNarrative`,
  app/src/60_render.js).
- The Adaptation tab ranks every site by its best in-scope measure BCR
  ("Where to act first"), draws an ECA-style cost curve with a breakeven
  line, and computes full insurance layer economics (`layerStatsCalc`,
  app/src/30_adaptation.js).
- The results pack carries a budget-phased, BCR-ranked capital plan and an
  event-set technical premium benchmark; the Method tab renders both.
- The backtest produces a portfolio bias verdict with suggested next steps,
  and the pack records a fitted wind-curve calibration.

Informational only, despite being decision-shaped:
- The Summary tab names the dominant peril and the most exposed sites but
  attaches no threshold, target, or recommended action.
- The TCFD/ISSB-format disclosure table (`finDisclosure`,
  app/src/20_finance.js) renders on screen but exports nowhere.
- Band migration counts (Scenarios tab), concentration ratios (scorecard
  only), the uncertainty tornado's "largest driver," and the climate-premium
  trajectory are all computed every render and surfaced as descriptions,
  never as flags or work queues.
- The insurance benchmark shows the technical premium next to the modeled
  premium but never states a verdict or takes a broker quote as input.
- The board brief is a print-ready one-pager of figures with no
  recommendations section, no risk-tolerance statement, and no action
  appendix.

The through-line: every actionable computation already exists; almost none of
it crosses the line from "displayed" to "decides something." That is the gap
this roadmap closes. Crucially, closing it is mostly additive rendering and
export work over numbers the parity suite already pins, which is the
lowest-risk kind of change this codebase supports.

Four structural gaps sit behind the display gap:
1. No risk tolerance anywhere in the product. All bands (`bandOf`) are
   descriptive, not policy. Nothing can "breach" until a threshold exists.
2. No decision artifacts. The only exports are the Power BI CSV (frozen
   schema) and the board brief PDF. Nothing an insurance broker, a capital
   committee, or a disclosure preparer can take away as their input.
3. No decision routing. A high number should point at one of four lanes:
   capex, insurance, disclosure, or asset management. Today it points at a
   chart.
4. No decision record. Data files are git-ignored and mutable; there is no
   trail of "these numbers, from this data vintage, drove that decision."

=============================================================================
SECTION 2: WHAT DECISION-GRADE MEANS (RESEARCH BASIS)
=============================================================================

The external evidence converges on seven criteria, and this system already
meets the hard ones:

1. Financial units at asset level, not indices: MET (EAD/AAL in dollars and
   percent of value, per site, per peril).
2. Probabilistic outputs (EP curves, return-period losses), because capex and
   insurance key off tails: MET (app curves plus the pack's event-set joint
   exceedance curve).
3. Validation against observed losses: MET and rare among commercial tools
   (backtest tab, v_half calibration). Moody's RMS markets Climate on Demand
   on exactly this property; Bressan et al. (Nature Communications, 2024)
   showed commercial scores cannot proxy asset-level damages, which is the
   academic version of this product's design thesis.
4. Transparency and auditability: MET (provenance sidecars, trust chips,
   plain-language INFO corpus, validator gates).
5. Uncertainty made explicit: MET (tornado, Monte Carlo bands).
6. Every output tied to a decision with an owner and a threshold: NOT MET.
7. User-set materiality thresholds separating "monitor" from "act": NOT MET.

Criteria 6 and 7 are the entire remaining distance, and they are product
work, not science work.

Market and regulatory context that shapes the ranking below:

- Insurance is the burning platform. US hotel property-insurance costs rose
  19.5 percent in 2023 and 17.4 percent in 2024 (CBRE), concentrated in
  coastal and wildfire markets, i.e. exactly this portfolio. Underwriters
  price on submission data quality: documented secondary modifiers (roof
  age, opening protection, first-floor elevation) can swing modeled pricing
  20-30 percent (Archipelago/III). The sites.csv profile schema already
  captures these fields; they are not yet packaged as renewal evidence.
- Disclosure is paused, not dead. California SB 261 (climate-financial-risk
  report, applies to public AND private US entities over $500M revenue doing
  business in CA, TCFD or IFRS S2 format) was enjoined by the Ninth Circuit
  in November 2025; CARB will set an alternate reporting date after appeal.
  The SEC climate rule was formally proposed for rescission in June 2026.
  Net: be report-ready cheaply now, do not build a compliance suite.
- The disclosure metrics that matter map directly onto existing data: IFRS
  S2 paragraph 29(c) wants the amount and percentage of assets vulnerable to
  physical risk (computable from per-site EAD and bands); 29(e) wants capex
  deployed toward climate risks (the capital plan, rolled up).
- Adaptation finance has citable anchors: FEMA BCA cost-effectiveness at
  BCR >= 1.0 with a 3.1 percent discount rate (Policy 206-23-001, 2024);
  NIBS Mitigation Saves multipliers ($6:1 for wind/flood retrofits, up to
  $13:1 overall). Corporate screens, by contrast, use WACC-like hurdle
  rates near 7-10 percent. Decision-grade tools show both.
- Commercial platforms (Jupiter Adaptation Hub, Moody's RMS, XDI, S&P
  Sustainable1) have all converged on: dollar AAL plus damage ratios, EP
  outputs, adaptation ROI modules, validation claims, and
  disclosure-formatted exports. None of them does resort-grade seasonal
  business interruption well; that is this product's open differentiator.

=============================================================================
SECTION 3: THE RANKED OPPORTUNITIES
=============================================================================

Ranked by business value per unit of effort and risk, given what the
codebase already computes. Each item states what it builds on, the
implementation path, key considerations, and its no-breakage guardrails.
Effort tags: S (about a day), M (days), L (a week or two).

-----------------------------------------------------------------------------
R1. RISK TOLERANCE AND DECISION ROUTING (the keystone)          [Effort: S-M]
-----------------------------------------------------------------------------
What: a user-set risk tolerance (defaults suggested, always editable and
documented): portfolio AAL as percent of insured value, site AAL in basis
points of site value, and 1-in-100 loss as percent of value. Every breach
becomes a flag routed to a named lane: capex (adaptation), insurance
(renewal/retention), disclosure, or asset management. The Summary read-out
gains a "Position vs tolerance" line and a short "Recommended next actions"
list; breached sites get a marker in the Sites table and on the map.

Why first: it is the smallest change that converts every existing display
into a decision surface, and every later item (queue, brief, disclosure)
consumes it. IFRS S1/S2 materiality practice expects the entity to set and
document its own threshold, so a slider plus an INFO entry is not a
simplification, it is the standard.

Build on: `finPortfolio`, `aggregatePortfolio` (app/src/20_finance.js),
band-migration math in `renderScenarios`, the `sumReadout` panel, the INFO
popover corpus (app/src/50_state_info.js), and the existing settings-slider
pattern on the Financial tab.

Path:
1. Add a `tolerance` object to app state with defensive-merge restore,
   exactly as `finAssume` merges today (app/src/80_persist_wire.js:11).
2. Pure function `toleranceFlags(sites, scenario, tolerance)` in
   20_finance.js returning `{portfolio:{...}, perSite:[...], lanes:{...}}`.
   New function, touches nothing existing.
3. Render: tolerance card on Summary with edit affordance; breach chips in
   the Sites table; two sentences in `sumReadout`; INFO entries explaining
   each threshold and why the default is the default.
4. Tests: extend `test_frontend.py` with tolerance persistence round-trip,
   breach detection on the standard fixture, and lane assignment.

Key considerations: defaults deserve care; anchor them to observable
practice (e.g. flag a site when AAL exceeds insurer attention levels of
roughly 10-25 bps of value, flag the portfolio when the 1-in-100 exceeds a
set share of annual gross operating profit) and say so in INFO copy rather
than presenting magic numbers.

No-breakage: additive state key (restore already tolerates unknown keys),
no change to any computed number, no export change. Parity suite untouched.

-----------------------------------------------------------------------------
R2. RENEWAL-GRADE INSURANCE WORKBENCH                             [Effort: M]
-----------------------------------------------------------------------------
What: turn the layering panel from "here are the layer economics" into "here
is your renewal position." Three parts:
(a) Quote verdict: an input for the broker's quoted premium; the app states
    "quote is N percent above/below the modeled technical premium (event-set
    benchmark when a pack is loaded)" with the loading assumption visible.
(b) Retention sweep: evaluate `layerStatsCalc` over a grid of attachment
    and limit choices from the EP curve and render the frontier (retained
    expected loss + premium versus transferred), so "raise the attachment,
    keep the limit" becomes a readable conclusion. Include a working-layer
    view (expected annual loss below attachment) as the captive-feasibility
    starter number.
(c) Broker evidence pack: a one-click export (new artifact, not the Power BI
    CSV) of per-site COPE and secondary-modifier data already in sites.csv
    (construction, year_built, roof_type, roof_year, opening_protection,
    first_floor_elev_m, equipment_elevated, stories, defended), completed
    and planned adaptation measures, and modeled per-site loss summaries.
    This is the underwriting submission data-quality lever.

Why second: insurance is the most immediate dollar decision this portfolio
faces every year (premium growth near 20 percent annually per CBRE), the
technical-premium machinery already exists (`layerStatsCalc`,
`packLayerStats`), and brokers/underwriters find AAL and EP outputs with
stated damage functions credible, which this system has and can document.

Build on: `layerStatsCalc` (app/src/30_adaptation.js:129), `packLayerStats`
(app/src/60_render.js:716), the pack's `ep_usd` curve, profile-v2 site
columns, `csvCell` and the download path in 80_persist_wire.js.

Path:
1. Add `adapt.quote` (nullable) to state; verdict line in the layering panel
   and the pack panel; INFO entry on what a technical premium is and is not.
2. Pure `retentionSweep(ep, attachGrid, limitGrid, load)` in
   30_adaptation.js; render as a small table or SVG in the existing panel
   style. Reuse the EP interpolation the app already has.
3. `exportBrokerPack()` producing a separate, clearly named CSV (e.g.
   `rtv_broker_evidence_<date>.csv`). New file, new schema, free to design;
   document it in the Method tab. Do not touch `exportCsv`.
4. Tests: verdict math, sweep monotonicity, evidence-pack column list.

Key considerations: label the verdict honestly (a technical premium is a
benchmark for negotiation, not a market price; loads vary by capacity
cycle). Keep the load slider assumption in the verdict sentence. The
evidence pack should include per-field provenance where enrich_sites
supplied a value (needs_review flags exist for this).

No-breakage: no change to the frozen Power BI export (new artifact instead);
`adapt` merges defensively; layering math untouched (sweep calls it, does
not modify it).

-----------------------------------------------------------------------------
R3. PORTFOLIO ACTION QUEUE WITH A FUNDING CUTLINE                 [Effort: M]
-----------------------------------------------------------------------------
What: one ranked work queue for the whole portfolio: every (site, measure)
pair in scope, ranked by BCR, with an annual-budget input drawing a visible
funded/deferred cutline, a program roll-up (total cost, total averted AAL,
program BCR, residual position versus the R1 tolerance), and a one-click
action-list export (a new CSV artifact listing site, measure, cost, averted
loss, BCR, phase year, synergy flag, owner column left blank on purpose).
When a results pack is loaded, the pack's canonical `capital_plan` is the
authoritative ranking and the live model fills interactive what-ifs, same
dual-display convention the app already uses elsewhere.

Why third: this is the capex half of "business-ready" and it is nearly free.
The pipeline already phases projects under a budget with renovation-window
synergies and deferral-not-deletion semantics (`phase_projects`,
pipeline/measures_catalog.py:262); the app already ranks sites by best
measure (`rec`, app/src/60_render.js:301). What is missing is the single
merged queue, the in-app budget line, the program roll-up, and the takeaway
artifact a capital committee can hold.

Build on: `rec` and scorecard `acts` arrays, pack `capital_plan.projects[]`
(including `budget_annual_usd`, which the app currently ignores), pack
`measures_catalog.identified[]` (the not-yet-priced backlog, rendered as a
"scope next" list at the queue's tail).

Path:
1. Pure `actionQueue(sites, adapt, scenario, budget, pack)` in
   30_adaptation.js merging live and pack rankings with source labels.
2. Render on the Adaptation tab above the existing panels; budget input
   persists in `adapt` (defensive merge).
3. `exportActionList()` as a new CSV artifact; Method-tab documentation.
4. Tests: queue ordering equals BCR order, cutline respects budget,
   deferral never drops items, export column list pinned.

Key considerations: keep the live-model queue visibly labeled as the
interactive estimate and the pack queue as canonical (the app's existing
badge convention). Program BCR should be reported alongside residual risk
versus tolerance, because "fund everything above 1.0x" and "fund until
within tolerance" are different strategies the user should see diverge.

No-breakage: additive rendering plus new pure functions; the pack schema
already carries everything needed (validate_pack tolerates no new fields
being required); no existing export touched.

-----------------------------------------------------------------------------
R4. DISCLOSURE-READY OUTPUT PACK (IFRS S2 / TCFD / SB 261)        [Effort: M]
-----------------------------------------------------------------------------
What: make the app able to emit, on demand, the exact numbers a preparer
needs: (a) count, value, and percent of sites vulnerable per peril, scenario,
and horizon, with the vulnerability threshold documented (uses R1's
tolerance or the band definitions, stated either way); (b) adaptation capex
deployed and planned by year from the action queue (S2 29(e)); (c) the
existing `finDisclosure` acute/chronic/VaR table; (d) portfolio AAL and
1-in-100 under at least two scenarios at 2030/2050 with and without the
funded adaptation program; (e) a methodology-and-uncertainty annex generated
from the meta sidecars and the Monte Carlo bands. Delivered as a
print-formatted section of the board brief plus a machine-readable JSON/CSV
export artifact.

Why fourth: the entire content already exists in state (finDisclosure, per
site bands, capital plan, uncertainty, provenance sidecars); this is mostly
formatting and export plumbing, and it converts the tool from "informs an
eventual filing" to "produces the filing input." SB 261 is enjoined but the
obligation is expected to return with a new date; report-readiness is cheap
insurance, and the same tables serve lender and investor questionnaires
(GRESB resilience indicators) regardless of regulation.

Build on: `finDisclosure` (app/src/20_finance.js:42), `bandOf`, per-site EAD,
R1 tolerance, R3 queue, `metaSources()`, `briefHtml` print CSS.

Path: pure `disclosurePack(sites, scenarios, tolerance, queue)` in
20_finance.js; a Method-tab panel with an export button; a brief section.
Tests pin the vulnerable-percent math on the fixture and the export shape.

Key considerations: never let the disclosure export claim more than the
trust chips do; carry the per-peril authority (grid versus interim) into the
annex verbatim. State the vulnerability threshold in the artifact itself.
Do not build workflow (sign-offs, filing calendars); that is a compliance
suite, out of scope by design.

No-breakage: new export artifact; zero changes to computed numbers.

-----------------------------------------------------------------------------
R5. BOARD BRIEF v2: FROM FIGURES TO RECOMMENDATIONS               [Effort: S]
-----------------------------------------------------------------------------
What: extend the existing one-click brief with (a) a position-versus-
tolerance statement, (b) a "Recommended actions" section: top funded queue
items, the insurance verdict, and any tolerance breaches with their lane,
(c) a per-site action appendix, (d) the disclosure table, and (e) a
validation line ("modeled versus observed losses across N matched events:
bias X; wind curve calibration available"). The brief becomes the artifact
an executive can act on rather than a status page.

Why fifth: it is the stitching layer over R1-R4 and the highest-visibility
surface in the product; effort is small because `briefHtml` and the print
path exist and every input is computed by earlier items.

Build on: `briefHtml`/`openBrief` (app/src/60_render.js:859), R1-R4 outputs,
backtest verdict.

Path: append sections to `briefHtml` gated on data presence (same pattern as
the current capital-plan section, which renders only when a pack is loaded).
Extend the existing brief test assertions.

Key considerations: keep it to two pages; recommendations must carry their
basis inline (BCR, benchmark gap, breach) so the page survives forwarding
without the app. Order recommendations by lane, then magnitude.

No-breakage: render-only; the brief has no export-schema contract.

-----------------------------------------------------------------------------
R6. CAPITAL CASE UPGRADE: CFO-CREDIBLE MEASURE ECONOMICS          [Effort: M]
-----------------------------------------------------------------------------
What: make each measure's card read like an investment memo line: BCR at the
corporate hurdle rate (existing discount slider) AND at the FEMA-comparable
3.1 percent side by side; simple payback; the benefit split into cash-like
components (insurance premium credit, avoided downtime revenue) versus
statistical avoided damage; a NIBS benchmark context line in INFO copy
($6:1 wind/flood retrofit average) so numbers land against an external
anchor. Activate the `premium_credit_pct` hook that the measures catalog
already carries at zero: when a broker quotes a credit for a completed
measure, the operator records it and BCRs update.

Why sixth: capital committees screen at hurdle rates, not social discount
rates, and near-term cash benefits (premium credits, avoided BI) carry
approval while tail-risk benefits justify; showing both rates and the
cash/statistical split is what moves a plan from "interesting" to "approved."
Ranked below R1-R5 because it deepens a lane those items open.

Build on: `MEASURES` and `adaptedFinSite` (app/src/30_adaptation.js),
`premium_credit_pct` (pipeline/measures_catalog.py), downtime_room_nights
metadata, the discount-rate slider, INFO corpus.

Path: pure dual-rate annuity helper (the annuity function exists pipeline-
side and app-side); measure-card render additions; a `premiumCredits` map in
`adapt` state (defensive merge); catalog passes credits through the pack on
the next refresh (additive pack field, validator-safe).

Key considerations: premium credits must be entered, never assumed; keep
the zero default and label estimates versus broker-confirmed. Do not blend
the two discount rates into one number; the divergence is the information.

No-breakage: display plus additive state; existing BCR math (parity-pinned)
remains the default view. New pack field is additive (validate_pack
tolerates unknown fields; add a validation stanza when it ships).

-----------------------------------------------------------------------------
R7. PUT VALIDATION ON THE TRUST SURFACE (AND MAKE CALIBRATION USABLE)
                                                                  [Effort: M]
-----------------------------------------------------------------------------
What: (a) promote the backtest verdict from a Method-tab panel to the trust
surface: a compact "validated against N observed events, bias X" chip near
the hazard badge once a backtest CSV is loaded, carried into the brief and
the disclosure annex; (b) make the recorded-but-never-applied v_half
calibration actionable: an explicit, default-off setting "use calibrated
wind vulnerability (v_half = X, fitted to observed losses)" with the fitted
value, its provenance, and a visible mode indicator everywhere numbers
change.

Why seventh: validation is the single strongest credibility asset with
underwriters, auditors, and boards, and this system has real validation
that commercial competitors mostly lack; it is currently buried. Ranked
here because part (b) is the first item that deliberately changes numbers,
which demands the strictest guardrails.

Build on: `renderBacktest` (app/src/60_render.js:573), pack `calibration`
(fitted_v_half, portfolio_bias, applied:false), `vulnOf` wind curve, score
tracing (which must show the calibrated curve when active).

Path: chip and brief line are render-only (S). The apply-calibration toggle:
a state flag (default off), `vulnOf` reads the override only when the flag
is set AND a pack with calibration is loaded; the score trace and export
gain no new columns but the Method tab states the active curve. Extend
tests: flag off reproduces parity fixture byte-for-byte (this keeps
test_app_parity green because the fixture never sets the flag); flag on
matches the pack's fitted expectation.

Key considerations: never auto-apply; the pipeline's applied:false
discipline carries into the app as opt-in with provenance. Exported CSVs
generated while calibration is active should carry the existing
hazard_source semantics untouched; if a distinction is ever needed, add a
NEW column at the tail per the export discipline, do not repurpose values.

No-breakage: default-off preserves every pinned number; parity fixture
unchanged; the toggle path gets its own assertions.

-----------------------------------------------------------------------------
R8. HOSPITALITY BUSINESS-INTERRUPTION LAYER (the differentiator)  [Effort: L]
-----------------------------------------------------------------------------
What: upgrade BI from "reopenMonths times revenue share" to resort-grade:
(a) optional monthly revenue weights per site (twelve new optional sites.csv
columns, defaulting to uniform, exactly the profile-v2 additive pattern);
(b) seasonality-weighted BI: an event in peak season costs its months, not
the annual average; (c) an indemnity-period adequacy check: given the
modeled downtime distribution and the seasonal curve, does a 12-month
indemnity period span the revenue actually at risk (the classic hospitality
BI trap); (d) a heat revenue-at-risk restated per heat-day threshold (the
data exists: days over 32C/35C are in the grid) rather than a flat
percentage; (e) note post-event market dynamics honestly in INFO copy
(operating survivors can see demand surges while damaged properties lose
their season; the model prices the owned asset, not the market).

Why eighth despite being the differentiator: it changes modeled numbers
(new BI math) and needs new operator data, so it is a bigger, riskier lift
than R1-R7. It is also the item none of the major vendors do well for
resorts, and it feeds the insurance workbench (indemnity adequacy is a
renewal conversation) and the capital case (avoided BI is a cash-like
benefit). Worth doing right after the routing-and-artifact layer exists.

Build on: `finSite` BI composition (app/src/20_finance.js), `reopenMonths`
and `heatDrop` assumptions, profile-v2 optional-column pattern
(pipeline/refresh_impacts.py load_sites, tests/test_profileops.py),
downtime_room_nights in the measures catalog.

Path: additive columns with uniform default proven to reproduce current
numbers exactly (the profile-v2 compatibility test pattern: a sites.csv
without the new columns must produce byte-identical results, pinned in
tests before any UI ships); seasonal BI as a parallel computation shown
next to the flat model until trusted, then promoted behind an explicit
assumption toggle; indemnity check rendered in the insurance workbench.

Key considerations: parity discipline is the whole game here: uniform
weights must reproduce the current BI path exactly, and the parity fixture
(no weights) must stay byte-identical. Seasonal data is sensitive
commercial information; it stays in localStorage like everything else.

No-breakage: the compatibility-pinned additive-column pattern exists and is
tested (six-field CSV reproduces legacy numbers today); replicate it.

-----------------------------------------------------------------------------
R9. DECISION AUDIT TRAIL AND DATA VINTAGES                        [Effort: M]
-----------------------------------------------------------------------------
What: (a) a data-vintage line everywhere decisions render: grid
generated_utc, pack generated_utc, app version (all already in state) shown
on the brief, the disclosure pack, and every export artifact; (b) a
quarterly snapshot convention: run_pipeline.sh gains an optional
`--snapshot` that copies validated artifacts into a dated folder
(`artifacts/2026Q3/`) with their sidecars and a manifest hash; (c) a light
decision log in the app: when an operator exports a brief, action list,
broker pack, or disclosure pack, append `{artifact, date, data vintages,
tolerance settings}` to a persisted log rendered on the Method tab and
included in exports.

Why ninth: assurance-readiness and institutional memory ("which data drove
the 2026 renewal?") are what auditors and future operators need; it is
cheap, but it serves the artifacts created in R2-R5, so it lands after
them.

Build on: sidecar generated_utc fields already parsed (`metaSources`), the
existing gitignore discipline for data files (snapshots are copies, not
commits, unless the operator chooses), the localStorage persistence layer.

Key considerations: keep the log advisory, not a compliance workflow. The
snapshot folder stays out of git by default (size, privacy) with the
manifest hash small enough to commit if desired.

No-breakage: additive persisted key with defensive merge; a new optional
pipeline flag that changes nothing when absent.

-----------------------------------------------------------------------------
R10. OPERATIONAL HARDENING AND ANALYTIC DEPTH (existing plans)  [Effort: M-L]
-----------------------------------------------------------------------------
Not new proposals; sequenced pointers to already-planned items that
business-readiness elevates from nice-to-have to needed:

- One-command container and pinned environment (MASTER_PLAN Phase A item 3,
  still unbuilt): the quarterly ritual currently depends on one machine and
  one person; a Dockerfile plus lockfile is continuity insurance for a
  business process, not developer convenience. The quarterly GitHub-issue
  reminder exists; the runnable target does not.
- Multi-country appraisal completion (refresh_impacts currently appraises
  adaptation/uncertainty/capital plan for the largest country by value
  only): required before the action queue can claim portfolio completeness
  for a portfolio spanning PR/USVI/HI plus CONUS if value distribution
  shifts.
- unsequa Saltelli/Sobol upgrade behind run_uncertainty() and CAT-bond
  pricing off the pack EP curve (MASTER_PLAN Phase D): the analytic
  deepenings that most strengthen R2 (retention/alternative risk transfer)
  when appetite exists.
- Doc refresh: RUNBOOK.md and FULL_EXECUTION_PLAN.md still describe v1.7 as
  the deployable; update to the v2.x lineage so a new operator is not
  misdirected (S, do alongside Wave 1).

=============================================================================
SECTION 4: NO-BREAKAGE RULES (THE CONTRACT MAP)
=============================================================================

Every item above was shaped against these verified contracts. Any
implementer should treat this section as the checklist.

Hard contracts, breakage is a CI failure by design:
1. Power BI export schema (`exportCsv`, app/src/80_persist_wire.js:61):
   column order frozen; legacy peril columns stay mid-row; any new column
   appends at the tail AND registers in EXPORT_ACUTE_APPENDED (or a new
   explicit list); `test_frontend.py` pins the partition and
   `test_app_parity.py` pins the export string byte-for-byte. Default
   stance in this roadmap: new artifacts get NEW files (broker pack, action
   list, disclosure pack), the Power BI export does not change.
2. Parity suite (`tests/test_app_parity.py`): every computed number on the
   standard fixture is pinned. All R1-R6 work is additive rendering and new
   pure functions, which passes untouched. R7's calibration toggle and R8's
   seasonal BI are the only number-changing items; both ship default-off
   with the fixture reproducing current behavior exactly, plus new
   assertions for the opted-in path.
3. Assembly gate (`app/assemble_app.py --check`): all app work edits
   app/src/ modules and reassembles; never hand-edit the deployable; never
   extend the retired patch_frontend chain.
4. localStorage keys (`rtv_state_v1`, `rtv_hazard_v1`, `rtv_hazmeta_v1`,
   `rtv_respack_v1`): never rename; only add fields, merged defensively the
   way restore() already merges finAssume and adapt.
5. Scenario keys are an allow-list in both validators (validate_grid.py,
   validate_pack.py): new scenario keys are rejected on purpose. None of
   R1-R9 adds scenarios.
6. Pack schema: additive fields are validator-safe (unknown fields
   tolerated); required sections are not. New pack fields (R6 premium
   credits) ship with their own validate_pack stanza and test.
7. Pipeline output columns: `test_pipeline_sim.py` asserts the exact grid
   CSV column list; grid schema does not change in this roadmap.
8. Style guard: no em dashes in any committed file outside the frozen
   lineage (tests/run_all.sh section 5); applies to docs, including this
   one.
9. Drop-zone routing (`routeHazFiles`): any future third JSON artifact type
   needs its own kind marker; nothing in this roadmap adds one (all new
   artifacts are exports, not intakes).
10. Trust surface discipline: no new panel or export may claim coverage the
    data lacks; disclosure and brief artifacts carry the per-peril
    authority (grid versus interim) verbatim.

Verification ritual for every increment: `bash tests/run_all.sh` green
locally (CI mirrors it exactly), new behavior gets new assertions in the
same run, and any number-changing toggle proves its default-off path
byte-identical first.

=============================================================================
SECTION 5: SEQUENCING, EFFORT, ACCEPTANCE
=============================================================================

Three waves, each independently shippable, each leaving the product better
if the next never starts (the house style).

WAVE 1: THE DECISION LAYER (R1 tolerance and routing, R2 insurance
workbench, R3 action queue; roughly 1-2 weeks total)
Acceptance: an operator can state the portfolio's position against a
documented tolerance, hand a broker an evidence pack and a quote verdict,
and hand a capital committee a funded, phased action list; all with the
test suite green and the Power BI export byte-identical.

WAVE 2: THE ARTIFACT LAYER (R4 disclosure pack, R5 board brief v2, R6
capital case, R7 validation surface; roughly 1-2 weeks)
Acceptance: the brief carries recommendations with their basis; the
disclosure export contains IFRS S2 29(c)/(e)-shaped tables with the
methodology annex; measure cards show dual-rate BCR and cash/statistical
split; the backtest verdict is visible at the top of the product; the
calibration toggle exists, defaults off, and the parity fixture is
untouched.

WAVE 3: THE DEPTH LAYER (R8 seasonal BI, R9 audit trail, R10 pointers;
2-4 weeks by appetite)
Acceptance: a sites.csv without seasonal columns reproduces today's numbers
byte-for-byte; with them, BI reflects the season an event lands in and the
indemnity-adequacy check renders in the insurance workbench; every exported
artifact names its data vintages; the quarterly ritual has a documented
one-command path.

The one-sentence version: the science is already decision-grade; give every
number a threshold, a lane, and an artifact, and never let a new surface
claim more than the trust chips do.
