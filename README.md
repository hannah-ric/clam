# CLAM: Resort Climate Risk Explorer

[![CI](https://github.com/hannah-ric/clam/actions/workflows/ci.yml/badge.svg)](https://github.com/hannah-ric/clam/actions/workflows/ci.yml)

A physical-climate-risk platform for a resort portfolio (US CONUS + Hawaii, Puerto Rico,
US Virgin Islands). Six perils: tropical-cyclone wind, storm surge, riverine flood,
extreme heat, wildfire, and TC rainfall, scored across present + SSP1-2.6 / SSP2-4.5 /
SSP5-8.5 at 2030 / 2050 / 2080 and return periods from 10 to 500 years, with financial
translation, a profile-driven measure catalog and phased capital plan, insurance
layering with an event-set technical premium benchmark, uncertainty bands, and an
observed-loss backtest with wind-curve calibration.

Built on [CLIMADA](https://github.com/CLIMADA-project/climada_python) 6.1 and
[CLIMADA Petals](https://github.com/CLIMADA-project/climada_petals) 6.2 (ETH Zurich).
Petals releases between Core releases and declares an open floor on Core
(Petals 6.2.0 requires `climada>=6.1`, and there is no Core 6.2.0), so Core 6.1.0
with Petals 6.2.0 is the current intended pairing: same major, Petals minor ahead.

## The whole system on one page

```
  THE INTERNET (independent public sources)
  |  ETH Zurich Data API .... TC wind + river flood hazard sets
  |  Scripps (UCSD) ......... SRTM15+ elevation (one-time download)
  |  NOAA PSL ............... CPC daily temperatures (auto, cached)
  |  NASA (via CLIMADA) ..... distance-to-coast file (auto, once)
  |  NASA FIRMS / IBTrACS ... fire history and TC tracks (via Petals)
  v
  THE PIPELINE (pipeline/, runs inside the climada_env conda environment)
  |  Headless hazard factory. Its entire product is two files:
  |      hazard_grid.csv  +  hazard_grid_meta.json
  |  gated by validate_grid.py (ship only on exit 0)
  v
  THE APP (app/TNL_Resort_Climate_Risk_Explorer_v200.html, the deployable)
  |  Opened by double-click, runs entirely offline. Holds all
  |  vulnerability, financial, adaptation, and insurance logic.
  |  The CSV + JSON pair dropped on its Method tab is the only bridge.
  v
  POWER BI / SHAREPOINT
     Consumes the app's CSV export (hazard_source column contract).
```

Design principles that everything here preserves: a trust surface that never claims
coverage the data lacks, graceful and explicit degradation, offline by default,
plain-language explainability, and a strict GPL boundary (CLIMADA code stays in the
pipeline; the app consumes data files only).

## Quickstart

One-time setup (full novice walkthrough in `docs/DEM_AND_VSCODE_FOR_DUMMIES.md`):

```bash
bash pipeline/setup_env.sh          # upgrades or creates the climada_env conda env
conda activate climada_env
cd pipeline                         # the pipeline reads and writes HERE:
                                    # running these from the repo root would put the
                                    # DEM where refresh_hazard.py cannot find it and
                                    # the surge layer would silently drop out
# download SRTM15_V2.x.nc from https://topex.ucsd.edu/pub/srtm15_plus/ then:
python convert_dem.py SRTM15_V2.7.nc
python check_phase1.py --smoke
```

The quarterly refresh is one command, run from `pipeline/` (details in `docs/RUNBOOK.md`;
the scripts reference each other by bare name, so run them from that directory):

```bash
cd pipeline
bash run_pipeline.sh                # standard run: wind + both floods + heat
bash run_pipeline.sh --all          # FULL SIX-PERIL run: adds wildfire + TC rainfall
bash run_pipeline.sh --fire --rain  # or opt the extra layers in individually
# other flags: --fast / --preflight / --no-heat / --dry-run
```

The wildfire layer needs a one-time NASA FIRMS download: CLIMADA Petals builds
its fire hazard from a FIRMS active-fire CSV, not a country code (passing a
country string raised `'str' object has no attribute 'columns'`). Download the
MODIS and/or VIIRS archive CSV(s) for the US from
https://firms.modaps.eosdis.nasa.gov/download/ and drop them in `pipeline/firms/`.
`bash run_pipeline.sh --fire` picks them up automatically, as do the producers run
directly (`python refresh_wildfire.py`, `python refresh_impacts.py --sites sites.csv`);
override the location with `--firms PATH` or `FIRMS_CSV=...`. The detections are
trimmed to a buffer around the portfolio sites (auto-uses `sites.csv`) after a
confidence floor, so only fire history near the resorts is clustered: the same
answer at each site, but fast, and free of far-away regimes such as Southeast
agricultural burning. Without any FIRMS data the wildfire step is skipped with a
clear note and the app keeps wildfire on its `wui_class` interim model, by design.

Migration safety: without these layers (and without wui_class profile data),
the v1.12 app scores both new perils zero and every number matches the
five-peril app exactly; the trust chips show wildfire and rainfall gray until
data arrives. Rainfall deliberately has no interim model.

Or the four steps it wraps, individually:

```bash
cd pipeline
python refresh_hazard.py            # tc + cflood + rflood
python refresh_heat.py              # heat
python merge_grids.py hazard_grid.csv heat_grid.csv -o hazard_grid.csv
python validate_grid.py hazard_grid.csv hazard_grid_meta.json
```

Then open the app and drop both `hazard_grid.csv` and `hazard_grid_meta.json` onto the
hazard zone on the Method & data tab. The badge counts every grid-fed peril
(n/6); gray chips mean that peril awaits data, by design.

The results pack (Phase 5, step 1) runs the impact math over the full event sets and
ships per-site expected annual damage, the joint portfolio loss-exceedance curve, a
direct-damage adaptation appraisal, and Monte Carlo uncertainty bands:

```bash
cd pipeline
python refresh_impacts.py --sites sites.csv     # schema: sites_template.csv
python validate_pack.py results_pack.json results_pack_meta.json
```

Drop `results_pack.json` onto the app's hazard zone alongside the grid
and sidecar: the Method tab gains a pack panel showing the event-set figures
beside the live model's. Add `--backtest backtest.csv` (columns: name,
observed_annual_loss_usd) to fit the wind curve's v_half to observed losses;
the fit is recorded in the pack as an optional setting, never silently applied.

Keep real site files out of version control (`sites.csv` is gitignored);
`sites_template.csv` documents the schema.

Building profiles (schema v2, all columns optional): roof_type, roof_year,
opening_protection, first_floor_elev_m, equipment_elevated, stories, keys,
renovation_year, wui_class, defensible_space_m, roof_class_a, fema_zone.
Present fields sharpen the damage math through a documented factor table
(mirrored exactly between pipeline and app); absent fields reproduce the
six-field behavior, pinned by tests. To draft profiles from public data:

Named-insured aggregation (also optional): `named_insured`, `site_id`, and
`site_name`. One physical site can carry several named-insured parties (an
owners' association and the operating company, say), each insuring different
buildings on the same land. Records sharing a `site_id` (or, absent that,
exact coordinates) aggregate into a single site: the map draws one marker per
physical site, while the scorecard, the risk matrix (a "by named insured"
view), the summary, and the results pack (`by_named_insured_aal_usd` plus
`named_insured` / `site_id` on each per-site row) break the exposure out by
party, so you can still see who is impacted and to what degree. A portfolio
with none of these columns is unchanged: one marker per record, as before.

```bash
cd pipeline
python enrich_sites.py sites.csv -o sites_enriched.csv   # or --no-network
```

Enrichment fills only blank fields, marks every draft needs_review in the
meta sidecar, and never overwrites an operator value. Review, confirm, then
use the confirmed file as the pipeline's sites input.

The measure catalog (`pipeline/measures_catalog.py`) turns the profile into a
short-term capital plan: per-measure applicability with plain-language
exclusion reasons (a high-rise cannot be elevated; a new metal roof has
nothing to gain from re-roofing), per-key costs with value-percent fallbacks,
lifecycle BCR over min(lifespan, horizon), refurbishment-cycle phasing via
`renovation_year` (shared mobilization discounts the cost), and an annual
budget lens: `python refresh_impacts.py --sites sites.csv --budget 5000000`
phases funded projects into years 1..3 and marks the rest deferred, never
dropped. Wildfire measures price against the wildfire event layer; continuity
measures (appraised in the app's financial model) stay identified per site.

## Repository layout

```
app/        the browser application: readable source in app/src/, assembled by
            assemble_app.py into the self-contained HTML deployable
pipeline/   the hazard factory scripts and preflight/diagnostic tools
tests/      contract tests (pure pandas/numpy, no CLIMADA needed)
docs/       the standing documents: execution plan, runbook, novice guide,
            and the original CLIMADA Petals integration plan
MASTER_PLAN.md   the research synthesis and forward roadmap (start here)
```

## Quality gates

One command runs every gate, needing only python3 (pandas + numpy) and node,
no CLIMADA and no network:

```bash
bash tests/run_all.sh
```

That is: the contract suites, the end-to-end simulations (which
exercise the validators' accept and reject paths), the frontend assertions
against the deployable app plus the v1.13-vs-v2.0.0 parity suite,
byte-for-byte regeneration of the historical app lineage from the v1.5 patch
source, the assembly drift check (deployable matches app/src/ exactly), and
the project style guard.

CI runs the same script on every push and pull request
(`.github/workflows/ci.yml`), so the badge above is the live answer to "is the
system intact?". A second workflow opens a pre-filled runbook issue on the
first of January, April, July, and October so the quarterly refresh never
silently lapses (it skips itself if the previous quarter's issue is still open).

Run the gates after any code change; `test_frontend.py` after any app edit.

## App source and lineage

The app's source of truth is `app/src/`: a shell head, eight readable JS domain
modules (hazard engine, finance, adaptation, uncertainty, state and INFO copy,
render, intake, persist and wiring), and a shell tail, concatenated in MANIFEST
order. `python3 app/assemble_app.py` joins them into the deployable
(`TNL_Resort_Climate_Risk_Explorer_v200.html`), still a single self-contained
file that opens from file:// with nothing to install. To change the app: edit
the module, reassemble, run the gates. `assemble_app.py --check` (a CI gate)
fails if the committed deployable ever drifts from the source, and
`tests/test_app_parity.py` proved v2.0.0 numerically identical to v1.13 across
every peril, the financial layer, adaptation, and the export string before
v2.0.0 took over as the deployable.

`app/` also carries the historical patch chain, verified reproducible on every
push: the v1.5 original is the patch source, and patch_frontend.py through
_p10 regenerate v1.6 through v1.13 byte-identically to the committed files.
Every patcher aborts with no output if its anchors no longer match. That chain
is closed history now; new work happens in `app/src/`. Additions by version:
v1.8 results-pack intake, v1.9 renewal benchmark and capital plan, v1.10
building profiles, v1.11 phased catalog plan, v1.12 the wildfire and
TC-rainfall perils, v1.13 the coherence pass, v2.0.0 the source-split
rebuild, v2.1.0 the experience layer: a scenario timeline that animates the
portfolio from Present to 2080, per-peril score tracing on every scorecard
(each figure walked back to its grid cell or interim model and the named
factors applied), a one-click print-ready board brief, and a map brand
filter; v2.2.0 named-insured aggregation, which groups several named-insured
parties on one physical site into a single map marker while breaking their
exposure out everywhere the split matters.

The working system is fully consolidated in this repository, with CI green on
every push. The roadmap lives in `MASTER_PLAN.md`; Phases A (CI), B (results
pack), and C (parity-first rebuild plus the experience layer) are shipped.

## Where this is going

Read `MASTER_PLAN.md`. Short version: consolidation and CI shipped (Phase A,
container still open), the CLIMADA-native results pack with appraisal and
uncertainty shipped (Phase B), the parity-first structural rebuild and the
experience layer shipped (Phase C: scenario timeline, score tracing, board
brief), leaving optional frontier layers (Phase D: storm-watch mode, CAT bond
pricing, CoastalDEM, the hazard emulator).
