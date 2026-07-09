# AGENTS.md

## Cursor Cloud specific instructions

This repo (CLAM: Resort Climate Risk Explorer) has **no long-running services, servers,
databases, or containers**. It is a batch pipeline plus an offline single-file browser app,
bridged only by data files. There is nothing to "start"; the dev loop is the test/quality
gates and opening the app HTML in a browser.

### Dependencies (already installed by the startup update script)
- Python with `pandas` + `numpy` (the only test dependencies), plus Node.js (preinstalled).
- The heavy CLIMADA conda stack (`pipeline/setup_env.sh`) is **optional** and only needed to
  run the real hazard pipeline against live external data. It is not required for the tests or
  to run the app.
- Note: CI pins Python 3.11 to match `climada_env`, but the VM's system Python (3.12) is fine
  for the gate suite since it only uses pandas/numpy.

### Quality gates / primary dev loop
- Run every gate with `bash tests/run_all.sh` (contract tests, mocked end-to-end sims, frontend
  assertions, app-lineage regeneration, assembly drift check, style guard). This is what CI runs
  (`.github/workflows/ci.yml`). No CLIMADA and no network needed.
- Run the gates after any code change; run `tests/test_frontend.py` after any app edit.

### The app
- Deployable: `app/Resort_Climate_Risk_Explorer_v210.html`, opened directly via
  `file://` in a browser (fully offline, zero network calls since v3). It ships with a built-in
  sample portfolio: use the "Load the sample and explore" button (or `loadSample()`), so no
  pipeline output is needed to exercise the risk engine end to end.
- Source of truth is `app/src/` (shell head/tail + numbered JS modules). Edit modules, then
  rebuild the deployable with `python3 app/assemble_app.py`. The CI gate
  `python3 app/assemble_app.py --check` fails if the committed HTML drifts from `app/src/`, so
  always reassemble after editing source.
- Two `app/src/` files are NOT hand-edited: `90_vendor_maplibre.js` (vendored MapLibre GL JS,
  see its header) and `88_basemap_data.js` (generated offline basemap; regenerate with
  `python3 app/make_basemap.py`, which needs the network, then reassemble). The node test
  harness extracts the inline script only up to the end of `restore()`, so anything that must
  stay test-visible lives in modules before `80_persist_wire.js`.

### The pipeline (optional, requires the conda env)
- Pipeline scripts reference each other by bare name, so they **must be run from inside
  `pipeline/`** (running from the repo root silently drops the surge layer / breaks DEM lookup).
- See `README.md` and `docs/RUNBOOK.md` for the quarterly-refresh commands.

### Style guard
- No em dashes are allowed outside the frozen lineage files (enforced by `tests/run_all.sh`).
