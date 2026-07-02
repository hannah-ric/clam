# CLAM: Resort Climate Risk Explorer

[![CI](https://github.com/hannah-ric/clam/actions/workflows/ci.yml/badge.svg)](https://github.com/hannah-ric/clam/actions/workflows/ci.yml)

A physical-climate-risk platform for a resort portfolio (US CONUS + Hawaii, Puerto Rico,
US Virgin Islands). Four perils: tropical-cyclone wind, storm surge, riverine flood, and
heat, scored across present + SSP1-2.6 / SSP2-4.5 / SSP5-8.5 at 2030 / 2050 / 2080 and
return periods from 10 to 500 years, with financial translation, adaptation appraisal,
insurance layering, uncertainty screening, and an observed-loss backtest.

Built on [CLIMADA](https://github.com/CLIMADA-project/climada_python) 6.1 and
[CLIMADA Petals](https://github.com/CLIMADA-project/climada_petals) 6.1 (ETH Zurich).

## The whole system on one page

```
  THE INTERNET (four independent public sources)
  |  ETH Zurich Data API .... TC wind + river flood hazard sets
  |  Scripps (UCSD) ......... SRTM15+ elevation (one-time download)
  |  NOAA PSL ............... CPC daily temperatures (auto, cached)
  |  NASA (via CLIMADA) ..... distance-to-coast file (auto, once)
  v
  THE PIPELINE (pipeline/, runs inside the climada_env conda environment)
  |  Headless hazard factory. Its entire product is two files:
  |      hazard_grid.csv  +  hazard_grid_meta.json
  |  gated by validate_grid.py (ship only on exit 0)
  v
  THE APP (app/TNL_Resort_Climate_Risk_Explorer_v17.html)
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
bash run_pipeline.sh                # full run; --fast / --preflight / --no-heat / --dry-run
```

Or the four steps it wraps, individually:

```bash
cd pipeline
python refresh_hazard.py            # tc + cflood + rflood
python refresh_heat.py              # heat
python merge_grids.py hazard_grid.csv heat_grid.csv -o hazard_grid.csv
python validate_grid.py hazard_grid.csv hazard_grid_meta.json
```

Then open the app and drop both `hazard_grid.csv` and `hazard_grid_meta.json` onto the
hazard zone on the Method & data tab. The badge should read "CLIMADA x 4/4 perils".

The results pack (Phase 5, step 1) runs the impact math over the full event sets and
ships per-site expected annual damage, the joint portfolio loss-exceedance curve, a
direct-damage adaptation appraisal, and Monte Carlo uncertainty bands:

```bash
cd pipeline
python refresh_impacts.py --sites sites.csv     # schema: sites_template.csv
python validate_pack.py results_pack.json results_pack_meta.json
```

Drop `results_pack.json` onto the app's hazard zone (v1.8) alongside the grid
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
dropped. Wildfire and continuity measures the pipeline cannot yet price are
still identified per site in the pack.

## Repository layout

```
app/        the browser application (v1.7, self-contained HTML)
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

That is: the three contract suites, the two end-to-end simulations (which
exercise both validators' accept and reject paths), the 31 frontend assertions
against the v1.7 app, byte-for-byte regeneration of the app lineage
(v1.5 through both patchers to v1.7), and the project style guard.

CI runs the same script on every push and pull request
(`.github/workflows/ci.yml`), so the badge above is the live answer to "is the
system intact?". A second workflow opens a pre-filled runbook issue on the
first of January, April, July, and October so the quarterly refresh never
silently lapses (it skips itself if the previous quarter's issue is still open).

Run the gates after any code change; `test_frontend.py` after any app edit.

## App lineage

`app/` carries the full patch chain, verified reproducible: the v1.5 original is the
patch source; `patch_frontend.py` regenerates v1.6, `patch_frontend_p4.py` v1.7,
`patch_frontend_p5.py` v1.8, and `patch_frontend_p6.py` v1.9, each byte-identical to
the committed files. Every patcher aborts with no output if its anchors no longer
match. The v1.9 file is the deployable; the rest is lineage. v1.9 adds, when a pack
is loaded: the event-set technical premium benchmark in the risk layering panel (the
number to judge renewal quotes against) and the pack's canonical capital plan, every
(site, measure) pair ranked by benefit-cost ratio.

The working system is fully consolidated in this repository. Next steps are on the
roadmap in `MASTER_PLAN.md` (Phase A: CI wiring and the one-command container).

## Where this is going

Read `MASTER_PLAN.md`. Short version: consolidate and containerize (Phase A), then the
results pack, which makes the portfolio loss curve, adaptation appraisal, and
uncertainty bands CLIMADA-native (Phase B), then a rebuilt frontend with a parity-first
migration (Phase C), then optional frontier layers (Phase D).
