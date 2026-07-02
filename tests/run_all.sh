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
#   3. frontend functional   (assertions against the deployable app, needs node)
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
python3 tests/test_profileops.py
python3 tests/test_catalogops.py
python3 tests/test_warming_parity.py

echo
echo "== 2  pipeline + results-pack simulations ==========================="
( cd pipeline && PYTHONPATH=. python3 ../tests/test_pipeline_sim.py )
( cd pipeline && PYTHONPATH=. python3 ../tests/test_impacts_sim.py )
( cd pipeline && PYTHONPATH=. python3 ../tests/test_newperils.py )
rm -f pipeline/sim_hazard_grid.csv pipeline/sim_hazard_grid_meta.json \
      pipeline/sim_heat_grid.csv pipeline/sim_heat_grid_meta.json \
      pipeline/sim_ghost_meta.json pipeline/sim_v1_grid.csv pipeline/fake_dem.tiff \
      pipeline/sim_sites.csv pipeline/sim_results_pack*.json \
      pipeline/sim_pack_*.json pipeline/sim_backtest.csv \
      pipeline/sim_wfire_grid* pipeline/sim_prain_grid* \
      pipeline/sim_tc_base.csv pipeline/sim_sixperil_grid.csv \
      pipeline/sim_badfire_grid.csv

echo
echo "== 3  frontend functional tests (v2.0.0 surface) ====================="
python3 tests/test_frontend.py app/TNL_Resort_Climate_Risk_Explorer_v200.html
python3 tests/test_app_parity.py

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
python3 app/patch_frontend_p6.py "$TMP/v18.html" "$TMP/v19.html"
cmp "$TMP/v19.html" app/TNL_Resort_Climate_Risk_Explorer_v19.html
echo "ok  regenerated v1.9 is byte-identical to the committed v1.9"
python3 app/patch_frontend_p7.py "$TMP/v19.html" "$TMP/v110.html"
cmp "$TMP/v110.html" app/TNL_Resort_Climate_Risk_Explorer_v110.html
echo "ok  regenerated v1.10 is byte-identical to the committed v1.10"
python3 app/patch_frontend_p8.py "$TMP/v110.html" "$TMP/v111.html"
cmp "$TMP/v111.html" app/TNL_Resort_Climate_Risk_Explorer_v111.html
echo "ok  regenerated v1.11 is byte-identical to the committed v1.11"
python3 app/patch_frontend_p9.py "$TMP/v111.html" "$TMP/v112.html"
cmp "$TMP/v112.html" app/TNL_Resort_Climate_Risk_Explorer_v112.html
echo "ok  regenerated v1.12 is byte-identical to the committed v1.12"
python3 app/patch_frontend_p10.py "$TMP/v112.html" "$TMP/v113.html"
cmp "$TMP/v113.html" app/TNL_Resort_Climate_Risk_Explorer_v113.html
echo "ok  regenerated v1.13 is byte-identical to the committed v1.13"
python3 app/assemble_app.py --check

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
