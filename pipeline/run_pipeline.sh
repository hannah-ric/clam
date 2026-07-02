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
#   bash run_pipeline.sh                 # full run (all countries, 20yr heat)
#   bash run_pipeline.sh --fast          # iteration run: VIR PRI only, 10yr heat
#   bash run_pipeline.sh --preflight     # run the preflights first, then pipeline
#   bash run_pipeline.sh --no-heat       # skip the heat layer this run
#   bash run_pipeline.sh --dry-run       # print every command without executing
#
# Flags combine, e.g.:  bash run_pipeline.sh --preflight --fast
# =============================================================================
set -euo pipefail

ENV_NAME="climada_env"
FAST=0; PREFLIGHT=0; NO_HEAT=0; DRY=0; FIRE=0; RAIN=0
for a in "$@"; do case "$a" in
  --fast) FAST=1;; --preflight) PREFLIGHT=1;; --no-heat) NO_HEAT=1;; --dry-run) DRY=1;;
  --fire) FIRE=1;; --rain) RAIN=1;;
  *) echo "Unknown flag: $a"; exit 2;;
esac; done

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

# --- 1. CLIMADA layers: wind + surge + river flood ---------------------------
echo; echo "== STEP 1  CLIMADA layers (tc, cflood, rflood) ======================"
if [ "$FAST" -eq 1 ]; then
  run python refresh_hazard.py --countries VIR PRI
else
  run python refresh_hazard.py
fi

# --- 2. heat layer ------------------------------------------------------------
MERGE_IN="hazard_grid.csv"
if [ "$NO_HEAT" -eq 0 ]; then
  echo; echo "== STEP 2  Heat layer (CPC climatology + AR6 deltas) ================"
  if [ "$FAST" -eq 1 ]; then
    run python refresh_heat.py --years 2015 2024
  else
    run python refresh_heat.py
  fi
  MERGE_IN="$MERGE_IN heat_grid.csv"
else
  echo; echo "== STEP 2  Heat layer skipped (--no-heat) ==========================="
fi

# --- 2b. optional fifth and sixth perils (opt-in: --fire, --rain) --------------
if [ "$FIRE" -eq 1 ]; then
  echo; echo "== STEP 2b  Wildfire layer (Petals WildFire burn probability) ======="
  run python refresh_wildfire.py
  MERGE_IN="$MERGE_IN wfire_grid.csv"
fi
if [ "$RAIN" -eq 1 ]; then
  echo; echo "== STEP 2c  TC rainfall layer (Petals TCRain, mm at RPs) ============"
  run python refresh_prain.py
  MERGE_IN="$MERGE_IN prain_grid.csv"
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
echo; echo "== STEP 4  Validation gate (ship ONLY if this passes) ==============="
run python validate_grid.py hazard_grid.csv hazard_grid_meta.json

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
