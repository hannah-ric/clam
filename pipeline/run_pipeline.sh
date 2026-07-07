#!/usr/bin/env bash
# =============================================================================
# run_pipeline.sh : the ENTIRE quarterly hazard refresh, gated end to end.
#
# Runs, in order:
#   1. refresh_hazard.py   -> hazard_grid.csv      + hazard_grid_meta.json
#                             (tc wind + cflood surge + rflood river flood)
#   2. refresh_heat.py     -> heat_grid.csv        + heat_grid_meta.json
#   3. merge_grids.py      -> hazard_grid.csv      + hazard_grid_meta.json
#                             (single app-ready CSV + combined provenance)
#   4. validate_grid.py    -> acceptance gate: any hard failure STOPS here
#                             and nothing should be shipped
#
# On success it prints exactly which two files to drop onto the app.
#
# Usage:
#   bash run_pipeline.sh                 # standard run (wind + floods + heat)
#   bash run_pipeline.sh --all           # FULL SIX-PERIL run: adds wildfire and
#                                        # TC rainfall (equivalent to --fire --rain)
#   bash run_pipeline.sh --fire          # opt in the wildfire layer only
#   bash run_pipeline.sh --rain          # opt in the TC-rainfall layer only
#   bash run_pipeline.sh --fast          # iteration run: VIR PRI only, 10yr heat
#   bash run_pipeline.sh --preflight     # run the preflights first, then pipeline
#   bash run_pipeline.sh --no-heat       # skip the heat layer this run
#   bash run_pipeline.sh --workers N     # concurrent Data API wind fetches per
#                                        # country (default CLAM_WORKERS or 4;
#                                        # use 1 for the exact serial fetch)
#   bash run_pipeline.sh --no-overlap    # run heat serially instead of alongside
#                                        # the CLIMADA layers (lower peak memory)
#   bash run_pipeline.sh --dry-run       # print every command without executing
#
# Speed: refresh_hazard fetches its wind sources concurrently (--workers), and
# the non-CLIMADA heat layer runs in the BACKGROUND alongside the CLIMADA layers,
# joined before the merge. Both keep the OUTPUT byte-for-byte identical to the
# serial run; --workers 1 and --no-overlap fall back to fully serial. On a cold
# machine the first run still spends most of its time downloading (the Data API,
# CPC, and DEM caches); parallelism helps most once those caches are warm.
#
# Flags combine, e.g.:  bash run_pipeline.sh --preflight --fast
# Without --all/--fire/--rain the app scores wildfire and TC rainfall zero
# (by design) and shows their trust chips gray; see the Method tab in the app.
# =============================================================================
set -euo pipefail

ENV_NAME="climada_env"
FAST=0; PREFLIGHT=0; NO_HEAT=0; DRY=0; FIRE=0; RAIN=0; OVERLAP=1; WORKERS=""
while [ $# -gt 0 ]; do case "$1" in
  --fast) FAST=1;; --preflight) PREFLIGHT=1;; --no-heat) NO_HEAT=1;; --dry-run) DRY=1;;
  --fire) FIRE=1;; --rain) RAIN=1;; --all) FIRE=1; RAIN=1;;
  --no-overlap) OVERLAP=0;;
  --workers) WORKERS="${2:-}"; shift;;
  --workers=*) WORKERS="${1#*=}";;
  *) echo "Unknown flag: $1"; exit 2;;
esac; shift; done

# refresh_hazard fetches its wind sources concurrently; --workers N tunes how
# many at once and is passed straight through. Left unset, the producer uses its
# own default (CLAM_WORKERS or 4); --workers 1 restores the exact serial fetch.
HZ_EXTRA=""
[ -n "$WORKERS" ] && HZ_EXTRA="--workers $WORKERS"

# heat is the one non-CLIMADA producer (NOAA CPC), so it can run alongside the
# CLIMADA layers with no shared state; joined before the merge (see STEP 2d).
MERGE_IN="hazard_grid.csv"; HEAT_PID=""; HEAT_LOG=""
heat_argv(){ if [ "$FAST" -eq 1 ]; then echo "--years 2015 2024"; fi; }

run(){ echo "+ $*"; if [ "$DRY" -eq 0 ]; then "$@"; fi; }

# --- activate the environment (works for conda and mamba installs) ----------
if [ "$DRY" -eq 0 ]; then
  if [ -z "${CONDA_DEFAULT_ENV:-}" ] || [ "${CONDA_DEFAULT_ENV:-}" != "$ENV_NAME" ]; then
    if command -v conda >/dev/null 2>&1; then
      # shellcheck disable=SC1091
      source "$(conda info --base)/etc/profile.d/conda.sh"
      conda activate "$ENV_NAME" || { echo "ERROR: env '$ENV_NAME' missing. Run: bash setup_env.sh"; exit 1; }
    else
      echo "ERROR: conda not found. Run: bash setup_env.sh"; exit 1
    fi
  fi
  echo "Environment: $CONDA_DEFAULT_ENV"
fi

# --- 0. preflights (opt-in; run them at least once and after env changes) ---
if [ "$PREFLIGHT" -eq 1 ]; then
  echo; echo "== STEP 0a  Core + Data API preflight =============================="
  run python check_climada.py
  echo; echo "== STEP 0b  Petals + DEM + dist-coast preflight ====================="
  run python check_phase1.py
fi

# --- heat: launch in the BACKGROUND to overlap the CLIMADA producers ----------
# Heat (NOAA CPC) shares no data source or process with CLIMADA and often
# dominates wall clock (a ~2 GB first-time download), so running it alongside the
# CLIMADA layers is free wall clock. It writes heat_grid.csv, joined at STEP 2d.
# --no-overlap (and --dry-run) keep it in a plain serial slot. The heavier
# CLIMADA producers stay serial with EACH OTHER to keep peak memory bounded.
if [ "$NO_HEAT" -eq 0 ] && [ "$OVERLAP" -eq 1 ] && [ "$DRY" -eq 0 ]; then
  echo; echo "== Heat layer launched in background (overlaps CLIMADA; joined 2d) ==="
  HEAT_LOG="$(mktemp)"
  # shellcheck disable=SC2046
  python refresh_heat.py $(heat_argv) > "$HEAT_LOG" 2>&1 &
  HEAT_PID=$!
  # never leave the background job orphaned if a CLIMADA step aborts under set -e
  trap 'if [ -n "$HEAT_PID" ]; then kill "$HEAT_PID" 2>/dev/null || true; fi' EXIT
  echo "  heat running as PID $HEAT_PID; its log is shown when joined at STEP 2d"
fi

# --- 1. CLIMADA layers: wind + surge + river flood ---------------------------
echo; echo "== STEP 1  CLIMADA layers (tc, cflood, rflood) ======================"
# shellcheck disable=SC2086
if [ "$FAST" -eq 1 ]; then
  run python refresh_hazard.py --countries VIR PRI $HZ_EXTRA
else
  run python refresh_hazard.py $HZ_EXTRA
fi

# --- 2b. optional fifth and sixth perils (opt-in: --fire, --rain) --------------
if [ "$FIRE" -eq 1 ]; then
  echo; echo "== STEP 2b  Wildfire layer (Petals WildFire burn probability) ======="
  # Petals builds the fire hazard from a NASA FIRMS archive CSV, not a country
  # code. refresh_wildfire auto-discovers the source (FIRMS_CSV env, ./firms/, or
  # firms_us.csv) and exits cleanly with guidance when none is present, so guard
  # the exit status: a graceful skip must not abort the whole run under set -e.
  if run python refresh_wildfire.py; then
    MERGE_IN="$MERGE_IN wfire_grid.csv"
  else
    echo "  wildfire skipped: no FIRMS data found. Put MODIS/VIIRS CSVs from"
    echo "  https://firms.modaps.eosdis.nasa.gov/download/ in pipeline/firms/ (or"
    echo "  set FIRMS_CSV=...), then re-run. The app keeps wildfire on its"
    echo "  wui_class interim model until then."
  fi
fi
if [ "$RAIN" -eq 1 ]; then
  echo; echo "== STEP 2c  TC rainfall layer (Petals TCRain, mm at RPs) ============"
  run python refresh_prain.py
  MERGE_IN="$MERGE_IN prain_grid.csv"
fi

# --- 2d. heat layer: join the background job (or run it now if not overlapped) -
if [ "$NO_HEAT" -eq 0 ]; then
  if [ -n "$HEAT_PID" ]; then
    echo; echo "== STEP 2d  Heat layer (joining background PID $HEAT_PID) ==========="
    set +e; wait "$HEAT_PID"; HEAT_RC=$?; set -e
    [ -n "$HEAT_LOG" ] && { cat "$HEAT_LOG"; rm -f "$HEAT_LOG"; }
    HEAT_PID=""
    if [ "$HEAT_RC" -ne 0 ]; then
      echo "ERROR: the background heat layer failed (exit $HEAT_RC); see its log above."
      exit "$HEAT_RC"
    fi
  else
    echo; echo "== STEP 2d  Heat layer (CPC climatology + AR6 deltas) =============="
    # shellcheck disable=SC2046
    run python refresh_heat.py $(heat_argv)
  fi
  MERGE_IN="$MERGE_IN heat_grid.csv"
else
  echo; echo "== STEP 2d  Heat layer skipped (--no-heat) ========================="
fi

# --- 3. merge everything into the single app-ready file -------------------------
if [ "$MERGE_IN" != "hazard_grid.csv" ]; then
  echo; echo "== STEP 3  Merge into the single app-ready file ====================="
  # shellcheck disable=SC2086
  run python merge_grids.py $MERGE_IN -o hazard_grid.csv
else
  echo; echo "== STEP 3  Nothing to merge (single producer this run) =============="
fi

# --- 4. acceptance gate --------------------------------------------------------
# When a sites.csv sits next to the pipeline, the gate also audits per-site
# coverage: any site outside a peril's coverage is listed (never silently
# zeroed; the app shows those sites as degraded on that peril).
echo; echo "== STEP 4  Validation gate (ship ONLY if this passes) ==============="
if [ -f sites.csv ]; then
  run python validate_grid.py hazard_grid.csv hazard_grid_meta.json --sites sites.csv
else
  run python validate_grid.py hazard_grid.csv hazard_grid_meta.json
fi

echo
echo "=============================================================="
echo "PIPELINE COMPLETE. Ship these TWO files to the app:"
echo "    hazard_grid.csv"
echo "    hazard_grid_meta.json"
echo "Open the deployable app (highest version in app/), go to the Method"
echo "tab, and drop BOTH files on the hazard zone (together is fine)."
echo "Then commit both files plus this run's log to the repo as the"
echo "provenance record for the quarter."
echo "=============================================================="
