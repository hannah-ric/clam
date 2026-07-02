#!/usr/bin/env bash
# =============================================================================
# tests/run_all.sh : every quality gate in one command, identical to CI.
#
# Run from the repository root:   bash tests/run_all.sh
#
# Gates, in order:
#   1. contract tests        (three suites, pure pandas/numpy)
#   2. simulations           (two end-to-end runs with CLIMADA mocked,
#                             both validators' accept and reject gates)
#   3. frontend functional   (31 assertions against the v1.7 app, needs node)
#   4. app lineage           (v1.5 -> patcher -> v1.6 -> patcher -> v1.7 must
#                             reproduce the committed files byte for byte)
#   5. style guard           (no em dashes outside the frozen lineage files)
#
# Needs: python3 with pandas + numpy, node. No CLIMADA, no network.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1  contract tests ==============================================="
PYTHONPATH=pipeline python3 tests/test_gridops.py
PYTHONPATH=pipeline python3 tests/test_phase23_ops.py
python3 tests/test_impactops.py

echo
echo "== 2  pipeline + results-pack simulations ==========================="
( cd pipeline && PYTHONPATH=. python3 ../tests/test_pipeline_sim.py )
( cd pipeline && PYTHONPATH=. python3 ../tests/test_impacts_sim.py )
rm -f pipeline/sim_hazard_grid.csv pipeline/sim_hazard_grid_meta.json \
      pipeline/sim_heat_grid.csv pipeline/sim_heat_grid_meta.json \
      pipeline/sim_ghost_meta.json pipeline/sim_v1_grid.csv pipeline/fake_dem.tiff \
      pipeline/sim_sites.csv pipeline/sim_results_pack*.json \
      pipeline/sim_pack_*.json pipeline/sim_backtest.csv

echo
echo "== 3  frontend functional tests (v1.8 surface) ======================"
python3 tests/test_frontend.py app/TNL_Resort_Climate_Risk_Explorer_v18.html

echo
echo "== 4  app lineage reproducibility ==================================="
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
python3 app/patch_frontend.py app/TNL_Resort_Climate_Risk_Explorer.html "$TMP/v16.html"
cmp "$TMP/v16.html" app/TNL_Resort_Climate_Risk_Explorer_v16.html
echo "ok  regenerated v1.6 is byte-identical to the committed v1.6"
python3 app/patch_frontend_p4.py "$TMP/v16.html" "$TMP/v17.html"
cmp "$TMP/v17.html" app/TNL_Resort_Climate_Risk_Explorer_v17.html
echo "ok  regenerated v1.7 is byte-identical to the committed v1.7"
python3 app/patch_frontend_p5.py "$TMP/v17.html" "$TMP/v18.html"
cmp "$TMP/v18.html" app/TNL_Resort_Climate_Risk_Explorer_v18.html
echo "ok  regenerated v1.8 is byte-identical to the committed v1.8"

echo
echo "== 5  style guard ===================================================="
# Frozen lineage files predate the project style sweep and stay verbatim.
ALLOW='^app/TNL_Resort_Climate_Risk_Explorer\.html$|^app/TNL_Resort_Climate_Risk_Explorer_v16\.html$|^docs/climada_petals_integration_plan\.md$'
BAD=$(git ls-files | grep -Ev "$ALLOW" | xargs grep -l "$(printf '\xe2\x80\x94')" 2>/dev/null || true)
if [ -n "$BAD" ]; then
  echo "FAIL: em dash found outside the frozen lineage files:"
  echo "$BAD"
  exit 1
fi
echo "ok  no em dashes outside the frozen lineage files"

echo
echo "======================================================================"
echo "ALL GATES PASSED"
echo "======================================================================"
