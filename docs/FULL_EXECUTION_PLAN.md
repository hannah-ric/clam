# FULL EXECUTION PLAN
## One document: how everything relates, what changes in your existing folder, and every step from here to a live four-peril system

This plan supersedes BACKEND_FILES_AND_RUN_GUIDE.md and
MASTER_INSTALL_AND_RUN_PLAN.md, which are retired. The documents that remain
are this plan (the what and the how), RUNBOOK.md (deep operational reference:
FLOPROS, spot checks, known limits), DEM_AND_VSCODE_FOR_DUMMIES.md (the novice
companion for the DEM download and VS Code settings), and
climada_petals_integration_plan.md (the original strategy, kept for the
record and for Phase 5 planning).

=============================================================================
SECTION 1: THE WHOLE SYSTEM ON ONE PAGE
=============================================================================

Five places, four relationships. Nothing else exists.

```
  THE INTERNET (four independent public sources)
  |  ETH Zurich Data API .... TC wind + river flood hazard sets
  |  Scripps (UCSD) ......... SRTM15+ elevation (one-time download)
  |  NOAA PSL ............... CPC daily temperatures (auto, cached)
  |  NASA (via CLIMADA) ..... distance-to-coast file (auto, once)
  |
  |  reached through your existing corporate TLS fix:
  |  REQUESTS_CA_BUNDLE / SSL_CERT_FILE in your zsh profile
  v
  YOUR MAC: the climada_env conda environment
  |  This is where CLIMADA LIVES. Not in your folder: CLIMADA and
  |  Petals are packages inside climada_env (plus a data cache at
  |  ~/climada/data that the API client manages by itself).
  |  setup_env.sh adds Petals + xarray/netcdf4/rasterio to this
  |  SAME environment; there is exactly one environment, ever.
  v
  YOUR MAC: the repository root (the VS Code project)
  |  Python scripts that USE climada_env, plus their outputs.
  |  The pipeline's entire product is two files:
  |      hazard_grid.csv  +  hazard_grid_meta.json
  v
  THE BROWSER: app/Resort_Climate_Risk_Explorer_v210.html
  |  Opened by double-click, runs entirely offline, holds all
  |  vulnerability, financial, adaptation, and insurance logic.
  |  It NEVER talks to CLIMADA or the internet. The CSV + JSON
  |  pair dropped on the Method tab is the ONLY bridge, and the
  |  browser's localStorage keeps them across sessions.
  v
  POWER BI / SHAREPOINT (unchanged by Phases 0-4)
     The app's CSV exports carry the hazard_source column exactly
     as before; your existing SharePoint drop and Power BI refresh
     keep working with zero modification. Grid-fed rows simply
     start reading "grid" instead of "interim".
```

The one-sentence version: the backend turns internet climate science into
two small files; the frontend turns those two files plus your portfolio into
decisions; conda holds the science software; the folder holds your scripts
and outputs; and Power BI keeps drinking from the same export tap it always
has.

=============================================================================
SECTION 2: YOUR EXISTING REPOSITORY, FILE BY FILE
=============================================================================

This is the reconciliation that was missing. Open the repository root
and apply exactly this disposition. Nothing outside this table exists in the
final state.

KEEP UNCHANGED (2 files, your originals):
    check_climada.py          still the Core + Data API preflight
    diagnose_network.py       still the TLS fixer; its cert exports carry over

REPLACE (2 files; keep the old ones in an archive subfolder if you like):
    refresh_hazard.py         v1 (wind only, broken scenario keys) is REPLACED
                              by v3 (wind + surge + river, app-native keys,
                              provenance sidecar). Same filename, drop-in.
    Resort_Climate_Risk_Explorer.html
                              v1.5 is REPLACED as the thing you open by
                              Resort_Climate_Risk_Explorer_v210.html.
                              Keep the v1.5 file itself: it is the patch
                              source that regenerates v1.6 and v1.7.

DELETE OR ARCHIVE (retired):
    list_tc_datasets.py       superseded by list_datasets.py (any data type)
    hazard_grid.csv (old)     present-day only; the first Phase 0 run
                              overwrites it, and validate_grid.py rejects the
                              old one by design if it ever resurfaces
    engine.py, app_streamlit.py, run_portfolio.py, environment.yml,
    sample_sites.csv          IF still present from the early two-deliverable
                              Streamlit strategy: that architecture was
                              consolidated away; these are fully superseded

ADD (the 18 new files delivered in this conversation):
    Pipeline:        refresh_heat.py, merge_grids.py, validate_grid.py
    Orchestration:   setup_env.sh, run_pipeline.sh
    Tools:           convert_dem.py, list_datasets.py, check_phase1.py
    App + lineage:   Resort_Climate_Risk_Explorer_v210.html (deployable),
                     Resort_Climate_Risk_Explorer_v16.html (lineage),
                     Resort_Climate_Risk_Explorer_v113.html (lineage),
                     patch_frontend.py through patch_frontend_p10.py
    Tests:           test_gridops.py, test_phase23_ops.py,
                     test_pipeline_sim.py, test_frontend.py
    Docs:            FULL_EXECUTION_PLAN.md (this file), RUNBOOK.md,
                     DEM_AND_VSCODE_FOR_DUMMIES.md,
                     climada_petals_integration_plan.md

APPEARS BY ITSELF (never version these):
    SRTM15+V2.0.tiff, cpc_cache/, hazard_grid.csv (new),
    hazard_grid_meta.json, heat_grid.csv, heat_grid_meta.json

ONE ENVIRONMENT: climada_env stays your only environment. setup_env.sh
detects it and installs the additions INTO it (Petals pins to Core 6.x, so
your CLIMADA 6.1.0 matches). No second environment is created; every script
and doc now says climada_env. Your VS Code interpreter selection does not
change.

ONE BROWSER NOTE: the v1.5 app stored the old present-only grid in your
browser's localStorage. The first time you open v1.7 it will restore that old
grid and the badge will read "CLIMADA x 1/4 perils" with an amber wind chip
(1 of 10 scenarios). That is the new trust surface working correctly on old
data. It disappears the moment you drop the new files in Step 24.

=============================================================================
SECTION 3: EXECUTION, EVERY STEP IN ORDER
=============================================================================
Numbered straight through. Terminal = VS Code terminal in the repository root,
prompt showing (climada_env) from Step 4 onward. Your Mac's zsh runs the .sh
scripts natively with `bash script.sh`.

PART A: RECONCILE AND UPGRADE (Steps 1 to 8, about an hour plus downloads)

Step 1. In the repository root, make an `archive` subfolder and move into it: the
old refresh_hazard.py, the old hazard_grid.csv, and any
Streamlit-era files from the Section 2 delete list.

Step 2. Copy the 18 new files from Section 2's ADD list into the folder,
alongside your unchanged check_climada.py, diagnose_network.py, and the
original v1.5 HTML.

Step 3. Upgrade the environment in place:
    bash setup_env.sh
You should see it find climada_env and install climada-petals, xarray,
netcdf4, requests, rasterio into it, no errors.

Step 4. Activate and confirm nothing regressed:
    conda activate climada_env
    python check_climada.py
Same OK you have seen before. TLS trouble? Your existing cert exports should
carry over; if not, python diagnose_network.py, re-apply, retry.

Step 5. Get the DEM (full novice detail in DEM_AND_VSCODE_FOR_DUMMIES.md):
browser to https://topex.ucsd.edu/pub/srtm15_plus/, download the newest
SRTM15_V2.x.nc (~6 GB), move it into the folder.

Step 6. Convert and crop it:
    python convert_dem.py SRTM15_V2.7.nc
You should see "Wrote SRTM15+V2.0.tiff". The .nc can then be deleted or kept
in archive for future re-crops.

Step 7. Prove the whole new tool chain:
    python check_phase1.py --smoke
You should see matching Core and Petals versions, three "covers ... OK"
lines for the DEM, dist-to-coast fetched, and a real VIR surge with a
single-digit max depth. Ends "All checks passed."

Step 8. Run the code safety net once, as a baseline:
    python test_gridops.py
    python test_phase23_ops.py
    python test_pipeline_sim.py
    python test_frontend.py app/Resort_Climate_Risk_Explorer_v210.html
All four must pass (they need no CLIMADA; the last needs node, which comes
with your system or via `brew install node`; skip it if node is absent and
rely on the shipped verification).

PART B: PHASE 0, WIND WITH REAL SCENARIOS (Steps 9 to 12)

Step 9. Small rehearsal:
    python refresh_hazard.py --countries VIR --no-surge --no-river
You should see ten wind fetches (a "no single match, trying next" that then
succeeds is the fallback working), then rows written and "Wrote provenance".

Step 10. Gate it:
    python validate_grid.py hazard_grid.csv hazard_grid_meta.json
You should see all 10 scenario keys covered for tc, a rising climate signal,
"meta layers and CSV layers agree", and RESULT: grid is shippable. This gate
is the proof both v1 silent failures (present-only data, unmatchable keys)
are gone.

Step 11. Full wind run (USA download-heavy the first time; hours, cached
afterwards):
    python refresh_hazard.py --no-surge --no-river

Step 12. Gate again (Step 10's command). Shippable = Phase 0 done.

PART C: PHASE 1, ADD SURGE (Steps 13 to 15)

Step 13.    python refresh_hazard.py --no-river
Wind comes from cache; you should see 16 "surge ... wet cells" lines per
country.

Step 14. Gate (same command). The cflood section appears, including the
check that inland cells carry explicit zeros.

Step 15. Spot checks per RUNBOOK: Galveston and Daytona plausible, New
Orleans clearly above the old proxy, San Antonio exactly zero. Phase 1 done.

PART D: PHASE 2, ADD RIVER FLOOD (Steps 16 to 18)

Step 16.    python refresh_hazard.py
New "Fetching river flood" lines with dataset names and ensemble sizes; an
unavailable country or scenario is recorded and skipped, not fatal.

Step 17. Gate (same command). rflood section appears.

Step 18. The FLOPROS decision, once: open hazard_grid_meta.json, read the
rflood members. Protection mentioned (flopros or a standard)? Set
RFLOOD_GRID_INCLUDES_PROTECTION to true in app/src/05_assumptions.js (then reassemble). No protection?
Change nothing. Ambiguous? python list_datasets.py river_flood USA and bring
me the output. Phase 2 done.

PART E: PHASE 3, ADD HEAT AND MERGE (Steps 19 to 22)

Step 19.    python refresh_heat.py
First run downloads ~2 GB of NOAA files (cached forever), then writes
heat_grid.csv and its sidecar.

Step 20.    python merge_grids.py hazard_grid.csv heat_grid.csv -o hazard_grid.csv
You should see "wrote combined provenance (2 sources, ...)".

Step 21. The full gate:
    python validate_grid.py hazard_grid.csv hazard_grid_meta.json
All four hazards in the coverage table, heat day counts sane, everything
agreeing. Shippable = Phase 3 done.

Step 22. Taste the fix: in hazard_grid.csv, heat rows near Palm Springs
(33.75, -116.5) should show more days over 35C than coastal Florida rows.
The old latitude formula had that backwards; the data does not.

PART F: PHASE 4, SHIP TO THE APP (Steps 23 to 26)

Step 23. Double-click app/Resort_Climate_Risk_Explorer_v210.html. Expect the
localStorage note from Section 2: an amber 1/4 badge from the old grid is
normal at this moment.

Step 24. Method & data tab: drag hazard_grid.csv AND hazard_grid_meta.json
onto the hazard zone together (any order also works).

Step 25. Read the trust surface: badge "CLIMADA x 4/4 perils" with the run
date on hover; four green chips; the run record showing date, CLIMADA and
Petals versions, track count, DEM name, heat method; any skipped layers
counted. Amber = partial scenarios for that peril (the panel says which
horizons fall back); gray = still interim.

Step 26. Commit hazard_grid.csv, hazard_grid_meta.json, and the console log
to SharePoint or the repo as the quarter's provenance record. Phase 4 done;
the system is live end to end, and Power BI needs nothing from you.

PART G: FROM NOW ON (Steps 27 to 31)

Step 27. The quarterly ritual is one command, then Steps 24 to 26:
    bash run_pipeline.sh
(It wraps Steps 16, 19, 20, 21 with stop-on-failure. Useful flags: --fast
for a minutes-long rehearsal, --preflight, --no-heat, --dry-run.) To
schedule it on the Mac, a launchd agent or cron entry that runs it inside
climada_env works with your existing scheduled-Python pattern.

Step 28. Growing the portfolio: add ISO3 codes to COUNTRIES in
refresh_hazard.py; widen REGIONS in refresh_heat.py; re-crop the DEM with
convert_dem.py --bbox if the new country falls outside the box; rerun.

Step 29. Sharper 250/500-year tails: NB_SYNTH_TRACKS = "50" in
refresh_hazard.py when you can give the USA run 32+ GB and a long first
pass.

Step 30. After ANY code change: the four test files from Step 8, all green,
before the next real run. After ANY app edit: test_frontend.py against the
edited file.

Step 31. Phase 5 when ready: the results pack (event-true portfolio EP
curves from the real synthetic sets, CLIMADA-native CostBenefit for the
adaptation tab, unsequa Monte Carlo bands). Bring the first real
hazard_grid_meta.json and console log and we start there, plus the FLOPROS
call from Step 18 if it was ambiguous.

=============================================================================
SECTION 4: INCONSISTENCIES FOUND IN THIS REVIEW, AND THEIR FIXES
=============================================================================

Reviewing everything against the original conversations surfaced five
inconsistencies, all fixed in the files shipped with this plan:

1. Two environments. Earlier docs and scripts invented a second, differently named
   environment alongside your existing climada_env. Fixed: setup_env.sh now
   upgrades climada_env in place (or creates it only if missing), and every
   script and doc references climada_env. One environment, as it always was.
2. Two folders. Earlier docs said to create a brand-new backend folder,
   ignoring your existing rtv VS Code folder. Fixed: Section 2 is the
   in-place, file-by-file reconciliation; no new folder.
3. A stale constant. refresh_hazard.py still declared OUT_META from before
   the sidecar path became derived from --out. Removed.
4. Undisclosed originals in the manifest. The plan referenced your two
   original scripts without bundling them; they are now in the delivered set,
   unchanged, and marked as yours.
5. Style drift. A standing instruction from the frontend sessions (no em
   dashes, and avoid three specific filler adverbs) was violated in eight
   places across six files. All swept and verified clean programmatically.

Also documented rather than fixed, because it is correct behavior: the first
open of v1.7 shows the OLD grid from browser storage as an amber 1/4 badge
(Section 2's browser note). The trust surface is doing its job on stale data.

=============================================================================
SECTION 5: FINAL FILE MANIFEST (single source of truth)
=============================================================================

Changed or new in this final pass (download these fresh):
    FULL_EXECUTION_PLAN.md          new, this document
    setup_env.sh                    rewritten: upgrades climada_env in place
    refresh_hazard.py               stale constant removed, wording swept,
                                    env instructions corrected
    refresh_heat.py                 wording swept, install line corrected
    validate_grid.py                wording swept
    check_phase1.py                 wording swept, env name corrected
    run_pipeline.sh                 environment name corrected
    RUNBOOK.md                      env section rewritten, wording swept
    DEM_AND_VSCODE_FOR_DUMMIES.md   folder and env naming aligned

Unchanged from earlier in this conversation (already in your downloads and
in this conversation's output list; no new copies needed):
    app/Resort_Climate_Risk_Explorer_v210.html    the deployable (v2.3.0)
    Resort_Climate_Risk_Explorer_v16.html    patch lineage
    Resort_Climate_Risk_Explorer_v113.html   patch lineage
    patch_frontend.py through patch_frontend_p10.py patch lineage
    merge_grids.py, convert_dem.py, list_datasets.py
    test_gridops.py, test_phase23_ops.py, test_pipeline_sim.py,
    test_frontend.py
    climada_petals_integration_plan.md
    check_climada.py, diagnose_network.py        your originals, unchanged

Retired by this plan (delete if downloaded earlier):
    BACKEND_FILES_AND_RUN_GUIDE.md
    MASTER_INSTALL_AND_RUN_PLAN.md
