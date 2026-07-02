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

## Quality gates

One command runs every gate, needing only python3 (pandas + numpy) and node,
no CLIMADA and no network:

```bash
bash tests/run_all.sh
```

That is: the two contract suites, the end-to-end pipeline simulation (which
exercises the validator's accept and reject paths), the 31 frontend assertions
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
patch source, `patch_frontend.py` regenerates v1.6 from it, and `patch_frontend_p4.py`
regenerates v1.7 from v1.6, byte-identical to the committed files in both steps. Both
patchers abort with no output if their anchors no longer match. The v1.7 file is the
deployable; the rest is lineage.

The working system is fully consolidated in this repository. Next steps are on the
roadmap in `MASTER_PLAN.md` (Phase A: CI wiring and the one-command container).

## Where this is going

Read `MASTER_PLAN.md`. Short version: consolidate and containerize (Phase A), then the
results pack, which makes the portfolio loss curve, adaptation appraisal, and
uncertainty bands CLIMADA-native (Phase B), then a rebuilt frontend with a parity-first
migration (Phase C), then optional frontier layers (Phase D).
