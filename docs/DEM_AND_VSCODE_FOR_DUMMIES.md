# The DEM, Your VS Code Project, and What To Do Next
## A For Dummies walkthrough of Manual Step A and everything after it

You have all the code. This guide covers the one thing a script cannot do for
you (getting the elevation map), shows you exactly what your project looks
like in VS Code, and then walks you to your first real run. Plain language,
no assumed knowledge, one step at a time.

---

# PART 1: Manual Step A, the elevation map (the DEM)

## What you are downloading and why (30 seconds of background)

The storm surge model works like filling a bathtub. A hurricane pushes the
sea up to some height; any land LOWER than that water gets wet, and land
higher stays dry. To know which is which, the model needs a map of how high
every patch of ground is. That map is called a DEM (Digital Elevation Model).
It is just one very large image file where every pixel stores an elevation in
meters instead of a color.

Scientists at Scripps (UC San Diego) publish exactly such a map for the whole
planet, for free, called SRTM15+. That is what you are about to fetch.

REMEMBER: without the DEM, nothing breaks. The pipeline runs and simply skips
the coastal flood layer, and the app quietly keeps using its built-in
approximation for that one peril. The DEM is what upgrades coastal flood from
"approximation" to "CLIMADA authoritative."

## Step-by-step

**Step 1. Check your disk space.**
You need about 7 GB free, temporarily. The download is roughly 6 GB, and the
converted file you keep is only a few hundred MB. After conversion you can
delete the big one.

**Step 2. Open the download page in any web browser.**
Go to:

    https://topex.ucsd.edu/pub/srtm15_plus/

It looks like a plain old file listing, because it is one. That is normal.

**Step 3. Click the newest SRTM15_V2.x.nc file.**
As of mid-2026 the newest is SRTM15_V2.7.nc (about 6.1 GB). Any V2.x works;
newer just means more corrections. Click it, and the download starts. This
takes a while on most connections, so go get coffee.

TIP: Ignore the files starting with SID_ (those map data sources, not
elevations) and the .txt, .pdf, and .kmz files. You want exactly one file,
and its name starts with SRTM15_V2.

WARNING: On a locked-down corporate network the download may be blocked.
That is fine: download it at home or on a phone hotspot and carry it in on a
USB stick. The file is public data; there is nothing sensitive about moving
it that way.

**Step 4. Move the downloaded file into your project folder.**
Drag SRTM15_V2.7.nc from your Downloads folder into the rtv folder (your existing project folder)
(the one with all the .py files). It must sit next to convert_dem.py.

**Step 5. Convert and crop it with one command.**
The file you downloaded is in a scientific format (.nc) and covers the whole
planet. The pipeline wants a GeoTIFF covering just your part of the world.
One command does both. In the VS Code terminal (with the environment active,
see Part 2 if you have not set that up yet):

    python convert_dem.py SRTM15_V2.7.nc

You will see it open the file, read only the crop box (CONUS, Hawaii, Puerto
Rico, USVI, with margin), and write:

    SRTM15+V2.0.tiff

That exact filename is what refresh_hazard.py looks for, so do not rename it.

TIP: If your portfolio later grows beyond the US and Caribbean, do not
re-download anything. Keep the .nc file and re-run convert_dem.py with a
wider box, for example:

    python convert_dem.py SRTM15_V2.7.nc --bbox -170 5 -50 55

**Step 6. Prove it worked.**

    python check_phase1.py

Look for these lines and nothing scary:

    opens OK ...
    covers USA (CONUS+HI): OK
    covers PRI: OK
    covers VIR: OK

If all three say OK, you are done with Manual Step A forever. Delete or
archive the 6 GB .nc file if you want the space back.

**If you would rather keep the file somewhere else:** you do not have to keep
the tiff in the project folder. Put it anywhere and tell the pipeline where:

    On Mac or Linux (or Git Bash):   export RTV_TOPO_PATH=/data/dems/SRTM15+V2.0.tiff
    In Windows PowerShell:           $env:RTV_TOPO_PATH="D:\dems\SRTM15+V2.0.tiff"

The PowerShell version lasts for that terminal session; to make it permanent
on Windows, run once:  setx RTV_TOPO_PATH "D:\dems\SRTM15+V2.0.tiff"

---

# PART 2: Your project in VS Code, exactly

## Opening it

1. Open VS Code.
2. File menu, then "Open Folder...", and pick your rtv folder (your existing project folder).
3. The Explorer sidebar (the two-pages icon, top left, or Ctrl+Shift+E) now
   shows every file.

## What the sidebar shows, and what each thing is

Here is the full tree, annotated the way you should think about it. Three
mental buckets: things YOU RUN, things that RUN THEMSELVES when called, and
things you NEVER TOUCH.

```
RTV  (your existing project folder)
|
|  THE TWO BUTTONS YOU PRESS
|-- setup_env.sh                 run once (upgrades your existing climada_env)
|-- run_pipeline.sh              run every quarter (does the whole refresh)
|
|  THE MACHINERY (run_pipeline.sh presses these for you)
|-- refresh_hazard.py            wind + surge + river flood from CLIMADA
|-- refresh_heat.py              heat from NOAA temperature records
|-- merge_grids.py               folds everything into one file
|-- validate_grid.py             the quality gate; it decides if you ship
|
|  THE FLASHLIGHTS (only when something is dark)
|-- check_climada.py             "is CLIMADA and its data server reachable?"
|-- check_phase1.py              "is the DEM good? does surge work?"
|-- diagnose_network.py          "is the corporate firewall in the way?"
|-- list_datasets.py             "what does the data server offer?"
|-- convert_dem.py               one-time DEM converter (Part 1, Step 5)
|
|  THE APP AND ITS BUILD CHAIN
|-- TNL_Resort_Climate_Risk_Explorer_v17.html    THE app; open in a browser
|-- patch_frontend.py            history: built v1.6 from the original
|-- patch_frontend_p4.py         history: built v1.7 from v1.6
|
|  THE SAFETY NET (run after any code change; otherwise ignore)
|-- test_gridops.py
|-- test_phase23_ops.py
|-- test_pipeline_sim.py
|-- test_frontend.py
|
|  THE PAPERWORK (read, never run)
|-- FULL_EXECUTION_PLAN.md
|-- RUNBOOK.md
|-- DEM_AND_VSCODE_FOR_DUMMIES.md      this file
|-- climada_petals_integration_plan.md
|
|  DATA THAT APPEARS BY ITSELF (never version-control these)
|-- SRTM15+V2.0.tiff             you made this in Part 1
|-- cpc_cache/                   NOAA files, downloads itself on first run
|-- hazard_grid.csv              THE OUTPUT: hazard for the app
|-- hazard_grid_meta.json        THE OUTPUT: its provenance record
|-- heat_grid.csv                intermediate; merged into the above
`-- heat_grid_meta.json          intermediate; merged into the above
```

REMEMBER: day to day you interact with exactly three things. run_pipeline.sh
to make the data, the two hazard_grid files to drop into the app, and the
v17 HTML file, which you open in a browser like any web page.

## Three one-time VS Code settings

**1. Tell VS Code which Python to use.**
Press Ctrl+Shift+P (Cmd+Shift+P on Mac), type "Python: Select Interpreter",
press Enter, and pick the one that says **climada_env**. If nothing like that
appears, install the "Python" extension from the Extensions sidebar first,
or run setup_env.sh because the environment does not exist yet.

**2. Open the built-in terminal.**
Menu: Terminal, then "New Terminal" (or Ctrl+backtick). Every command in
these guides gets typed there. Before running anything, make sure the prompt
shows (climada_env) at the start. If it does not, type:

    conda activate climada_env

**3. Windows users only: pick your shell.**
The two .sh scripts are bash scripts. Windows PowerShell does not speak bash.
You have two equally fine options:

Option A (nicer): in the terminal panel, click the little dropdown arrow next
to the plus sign and choose "Git Bash" (installed with Git for Windows). Then
`bash run_pipeline.sh` works exactly as written.

Option B (no installs): skip the .sh scripts and type the five commands they
wrap, one at a time, in PowerShell:

    python refresh_hazard.py
    python refresh_heat.py
    python merge_grids.py hazard_grid.csv heat_grid.csv -o hazard_grid.csv
    python validate_grid.py hazard_grid.csv hazard_grid_meta.json

(The fifth "command" is just: stop and read what the validator said.)

---

# PART 3: Next steps, in order

Do these in sequence. Each one has a clear "you know it worked when" moment.

**Next step 1. Run the two preflights.**

    python check_climada.py
    python check_phase1.py --smoke

Worked when: both end with OK, and the smoke test prints a surge depth for
the Virgin Islands. The smoke test takes about two minutes and proves the
entire wind-to-surge chain on a tiny country before you commit hours to the
big one. If either fails, copy the WHOLE output and bring it back; these are
built to be fixed in one edit.

**Next step 2. Rehearse with the fast run.**

    bash run_pipeline.sh --fast

This does the real pipeline on just the two small territories with a shorter
heat window. Worked when: the last lines say "RESULT: grid is shippable" and
"PIPELINE COMPLETE." Minutes, not hours.

**Next step 3. Do the real thing.**

    bash run_pipeline.sh

The first full run is download-heavy (the USA wind sets plus about 2 GB of
NOAA files), so start it and walk away; think an afternoon. Every later run
reuses the caches and is far shorter. Worked when: same two closing lines as
the rehearsal.

**Next step 4. Load the app.**
Double-click TNL_Resort_Climate_Risk_Explorer_v17.html (it opens in your
browser; nothing installs, nothing leaves your machine). Click the Method &
data tab. Drag BOTH hazard_grid.csv and hazard_grid_meta.json onto the
hazard drop zone at the same time. Worked when: the badge in the top bar
reads "CLIMADA x 4/4 perils" and hovering it shows the run date, and the
Hazard source panel shows four green chips.

TIP: an amber chip is not an error. It means that peril has hazard data but
not for every future scenario, and the panel tells you which horizons fall
back. A gray chip means that peril stayed on the built-in model this run.

**Next step 5. First-run homework (once, 30 minutes).**
Two things the RUNBOOK spells out in full. First, open hazard_grid_meta.json
in VS Code (it is readable text) and check whether the river flood datasets
mention flood protection; that decides one true/false flag in the app so
protection is never counted twice. Second, spot-check four sites against
public references: Galveston and Daytona surge in the right ballpark, New
Orleans clearly higher than the old approximation, San Antonio surge exactly
zero.

**Next step 6. Put it on the calendar.**
Quarterly is plenty; climate hazard does not change week to week. The
quarterly ritual is: `bash run_pipeline.sh`, drop the two files, commit them
plus the console log to the repo. Ten minutes of your attention.

**Next step 7. When you are ready for more.**
The plan's Phase 5 is the results pack: exact portfolio loss curves from the
real event sets, CLIMADA-native cost-benefit for the adaptation tab, and
Monte Carlo uncertainty bands. Everything you just set up is the foundation
it builds on. Say the word when the first real run is in and validated.
