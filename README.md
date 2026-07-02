# CLAM: Resort Climate Risk Explorer

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
# download SRTM15_V2.x.nc from https://topex.ucsd.edu/pub/srtm15_plus/ then:
python pipeline/convert_dem.py SRTM15_V2.7.nc
python pipeline/check_phase1.py --smoke
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

## Repository layout

```
app/        the browser application (v1.7, self-contained HTML)
pipeline/   the hazard factory scripts and preflight/diagnostic tools
tests/      contract tests (pure pandas/numpy, no CLIMADA needed)
docs/       the standing documents: execution plan, runbook, novice guide,
            and the original CLIMADA Petals integration plan
MASTER_PLAN.md   the research synthesis and forward roadmap (start here)
```

## Running the tests

All four suites run without CLIMADA (the last needs node):

```bash
PYTHONPATH=pipeline python3 tests/test_gridops.py
PYTHONPATH=pipeline python3 tests/test_phase23_ops.py
(cd pipeline && PYTHONPATH=. python3 ../tests/test_pipeline_sim.py)
python3 tests/test_frontend.py app/TNL_Resort_Climate_Risk_Explorer_v17.html
```

Run them after any code change; run `test_frontend.py` after any app edit.

## PENDING: files not yet imported

This repository holds 22 of the working system's files. The remaining 2 exist in the
operator's working folder (`rtv/`) and should be committed here verbatim, with no edits,
before any refactor.

| File | Role |
|---|---|
| `patch_frontend.py` | lineage: built v1.6 from the v1.5 app |
| `patch_frontend_p4.py` | lineage: built v1.7 from v1.6 |

## Where this is going

Read `MASTER_PLAN.md`. Short version: consolidate and containerize (Phase A), then the
results pack, which makes the portfolio loss curve, adaptation appraisal, and
uncertainty bands CLIMADA-native (Phase B), then a rebuilt frontend with a parity-first
migration (Phase C), then optional frontier layers (Phase D).
