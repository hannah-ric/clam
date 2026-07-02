# Runbook: Phases 0-3 (multi-scenario wind, Petals surge, river flood, data-driven heat)

This runbook covers the full hazard pipeline: the v3 refresh_hazard.py (wind +
surge + river flood from CLIMADA/Petals), the new refresh_heat.py (heat
indicators from observed climatology plus AR6 warming shifts), the merge and
validation utilities, and the v1.6 browser app produced by patch_frontend.py.

## The pieces and what each one does

refresh_hazard.py v3 : wind (tc), storm surge (cflood, Petals TCSurgeBathtub),
  and riverine flood (rflood, Data API river_flood, discovery-driven,
  ensemble-mean) -> hazard_grid.csv + hazard_grid_meta.json.
refresh_heat.py : heat layer (hazard=heat) from NOAA CPC daily tmax/tmin
  climatology (0.5 deg, anonymous download, ~2 GB cached once) shifted per
  scenario by the app's own AR6 WARMING table x land amplification 1.25.
  Encoding: v10=days>32C, v25=days>35C, v50=CDD -> heat_grid.csv.
merge_grids.py : concatenates grid CSVs into the ONE file the app consumes
  (the app replaces all grids per drop, so: one file, one drop).
validate_grid.py v2 : acceptance test, now heat- and rflood-aware. Ship only
  on exit 0.
patch_frontend.py : produces the v1.6 app from the v1.5 HTML (5 surgical
  edits; aborts untouched if the source has drifted). Already applied:
  TNL_Resort_Climate_Risk_Explorer_v16.html is the deployable file.
test_frontend.py : functional tests of the patched app logic in node; rerun
  after ANY future HTML edit.

## What changed in the app (v1.6) and what deliberately did not

Changed: heat now reads the grid when heat rows are loaded (falling back to
the latitude formula outside coverage); sites OUTSIDE any grid's coverage
(>200 km from a cell) now fall back to the interim model for tc/cflood/rflood
instead of silently scoring zero, which matters the day a site lands in a
country the grid does not cover; a documented RFLOOD_GRID_INCLUDES_PROTECTION
flag exists for the FLOPROS question below. NOT changed: every formula, every
financial assumption, the measure library, and all behaviour when no grid is
loaded: the no-grid regression is part of test_frontend.py.

## One-time setup

    # your existing climada_env (CLIMADA 6.1.0) is the one environment;
    # setup_env.sh ADDS Petals and the heat/DEM libraries to it:
    bash setup_env.sh
    conda activate climada_env

Corporate network: the diagnose_network.py certificate exports cover the
Data API, the NASA dist-to-coast download, and the NOAA PSL downloads alike.
DEM: download the newest SRTM15_V2.x.nc from the Scripps SRTM15+ page and run
convert_dem.py on it to produce SRTM15+V2.0.tiff (or set RTV_TOPO_PATH);
CoastalDEM is the drop-in upgrade when granted.

## Full refresh, in order

    python check_climada.py                 # Core + Data API preflight
    python check_phase1.py --smoke          # Petals + DEM + dist-coast + VIR surge
    python refresh_hazard.py                # tc + cflood + rflood
    python refresh_heat.py                  # heat (first run downloads ~2 GB, cached)
    python merge_grids.py hazard_grid.csv heat_grid.csv -o hazard_grid.csv
    python validate_grid.py hazard_grid.csv # ship only on RESULT: shippable
    python test_frontend.py TNL_Resort_Climate_Risk_Explorer_v16.html

Then drop hazard_grid.csv into the v1.6 app and commit hazard_grid_meta.json
beside it as the provenance record. Iterating? --countries VIR PRI,
--no-surge, --no-river, and refresh_heat.py --years 2015 2024 all shrink runs.

## The FLOPROS decision (do this once, on first real river flood data)

Open hazard_grid_meta.json and read the rflood members' properties and
dataset names. If the served ISIMIP sets embed flood protection (names or
properties mentioning "flopros" or a protection standard), flip
RFLOOD_GRID_INCLUDES_PROTECTION to true in the app so the interim riverine
freeboard stops double-counting protection the hazard already nets out. If
they are unprotected ("0" protection), leave it false. Record the decision in
the Method tab copy. If the discovery output is ambiguous, run
`python list_datasets.py river_flood USA` and read the tags directly.

## Spot-checks before first ship (record results in the repo)

Wind: Scenarios tab shows monotone growth along SSP5-8.5; present figures
within ~10% of the old grid's. Surge: Galveston/Daytona v100 within the same
order as NOAA SLOSH MOMs (bathtub typically a touch low); New Orleans
materially above the old interim proxy; San Antonio exactly zero. River
flood: San Antonio and Orlando nonzero at long return periods; beach cells
near-zero; if PRI or VIR return "no river_flood dataset" in meta.skipped,
note that their riverine risk stays on the interim model (VIR's is ~nil
anyway). Heat: Palm Springs and San Antonio days>35C should now EXCEED the
coastal-latitude sites, correcting the documented arid-inland understatement;
Hawaii sites fall back to the formula if the 0.5-degree land mask misses
small islands (the app handles that automatically).

## Honest limits to carry into the Method tab (Phase 4 will render these
   from the meta sidecar; until then, keep the copy current by hand)

Surge: bathtub physics (no waves/tides/levees; `defended` still carries site
protection); SRTM biased high on built coasts. River flood: ~5 km ISIMIP
model, not a FEMA study; ssp245 maps to rcp45 when served, else rcp60
(nearest middle pathway). Heat: delta method shifts the observed distribution
uniformly (no variability/humidity change); 0.5-degree CPC grid; upgrade path
is a NEX-GDDP-CMIP6 ensemble behind the same accumulator seam. Scenarios: the
SSP-from-RCP mapping matches radiative forcing, standard for screening; 2030
and 2050 wind/surge are blends of the bracketing Data API ref-years.

## Phase 4: provenance and trust surface (app v1.7)

What it closes: the pipeline has written a provenance sidecar since Phase 0,
but nothing consumed it. Now every producer writes one (<csv stem>_meta.json:
refresh_hazard.py and refresh_heat.py both follow the convention),
merge_grids.py combines them automatically alongside the CSVs, validate_grid.py
cross-checks the sidecar against the CSV so the trust surface can never claim
coverage the data lacks, and the v1.7 app renders it all.

In the app: the hazard drop zone now accepts hazard_grid.csv AND
hazard_grid_meta.json (drag both together, or one at a time, in any order;
click-to-browse allows multi-select). The top bar badge becomes per-peril
("CLIMADA x n/4 perils", pipeline run date on hover). The Method tab's Hazard
source panel shows one chip per peril: green means grid-fed with every app
scenario covered, amber means grid-fed but PARTIAL scenario coverage (missing
horizons silently use that peril's present grid, which is exactly the v1
failure mode, so it is surfaced rather than hidden), gray means interim. Below
the chips: the run record per producer (date, CLIMADA and Petals versions,
synthetic track count, DEM, heat method and climatology window) and a count of
layers skipped in the last run. The hazNote caveat narrows peril by peril
instead of speaking for the whole app. Everything persists across sessions
like the grid does.

Updated run order (only the last two lines changed):

    python refresh_hazard.py
    python refresh_heat.py
    python merge_grids.py hazard_grid.csv heat_grid.csv -o hazard_grid.csv
    python validate_grid.py hazard_grid.csv hazard_grid_meta.json
    python test_frontend.py TNL_Resort_Climate_Risk_Explorer_v17.html

Then drop BOTH hazard_grid.csv and hazard_grid_meta.json onto the app's
hazard zone. The validator's new section H hard-fails if the sidecar claims a
hazard x scenario layer the CSV does not carry, and warns on the reverse, on a
cflood layer with no recorded DEM, and on a heat layer with no recorded
method.

Patching lineage for the HTML: v1.5 (original) -> patch_frontend.py -> v1.6
(Phases 2-3) -> patch_frontend_p4.py -> v1.7 (Phase 4). Both patchers abort
untouched if their anchors no longer match, and test_frontend.py v2 runs 31
functional assertions against whichever file you point it at (it expects the
v1.7 surface).
