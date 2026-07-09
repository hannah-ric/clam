# CLIMADA Petals Integration Plan
## Resort Portfolio Risk-to-Value: extending from single-peril CLIMADA Core to multi-peril Petals

Prepared 1 July 2026. Reviewed against CLIMADA Core 6.1.x and CLIMADA Petals 6.x documentation and source, and against the current project codebase (refresh_hazard.py, check_climada.py, list_datasets.py, diagnose_network.py, Resort_Climate_Risk_Explorer.html v1.5, hazard_grid.csv).

---

## 1. Where the system stands today

The architecture is a deliberate two-piece split, and it is worth naming because the whole integration plan preserves it.

**The backend is a hazard factory, not a risk engine.** refresh_hazard.py runs CLIMADA Core headless, pulls country-level tropical-cyclone wind hazard from the ETH Data API (USA, PRI, VIR), computes local exceedance intensities at six return periods (10 to 500 years), thins the ~150 arcsec centroids onto a 0.25 degree grid, and writes one long-format CSV. It does no impact modelling. All vulnerability (the Emanuel 2011 wind curve, the concave stage-damage flood curves), exposure, financial translation (direct damage, business interruption, heat revenue at risk), adaptation appraisal, insurance layering, uncertainty screening, and backtesting live in the browser.

**The frontend is a zero-install risk engine over static hazard data.** The single-file HTML app carries four perils. TC wind is fed by the CLIMADA grid when loaded, otherwise by an IDW interim model over regional anchors. Coastal flood, riverine flood, and heat currently always run on interim proxies (coastal proximity plus a surge scaled from the wind field plus scenario SLR; a continentality-based riverine depth; a latitude-based heat index). The app already anticipates the multi-peril future: the grid loader accepts an optional `hazard` column, routes rows into `gridByHazard`, and any peril present in the grid supersedes its interim model. That hook is the integration seam and it is already built.

The adaptation tab is effectively a lightweight re-implementation of CLIMADA's CostBenefit engine: measures declare mechanism modifiers (damage multiplier, freeboard, surge depth reduction, reopen-time multiplier, heat-loss multiplier), modifiers compose without double counting, benefit is averted AAL annuitised at a discount rate, and a CLIMADA-style waterfall decomposes future risk into today + growth + climate change - measures. The uncertainty panel is a screening take on unsequa (one-at-a-time sweeps combined by root sum square), and the backtest tab mirrors CLIMADA's impact-function calibration loop against observed losses.

### 1.1 Issues found during review (fix these regardless of Petals)

**Finding 1 — the shipped hazard grid is present-day only.** hazard_grid.csv contains 14,955 rows and every one of them is `scenario=present`. The RCP fetches in refresh_hazard.py either failed silently (the try/except in `main()` logs a warning and continues) or the run predates them. Consequence: when this grid is loaded, every future scenario in the app silently reads present-day CLIMADA wind (via the provider's fallback), so the Scenarios tab shows no climate signal from the authoritative source. The log output of the last run should be checked; most likely the RCP dataset property combination (`nb_synth_tracks` presence, `ref_year` string) needs the same candidate-fallback treatment the present-day path already has.

**Finding 2 — scenario key mismatch between backend and frontend.** The backend writes `rcp45_2050`, `rcp85_2050`, `rcp85_2080`. The frontend's scenario keys are `present` and `{ssp126|ssp245|ssp585}_{2030|2050|2080}`, and `makeGridProvider` matches keys verbatim with a fallback to `present`. Even if Finding 1 were fixed, every RCP-tagged row would be unreachable and the app would again silently serve present-day hazard for all future horizons. A translation layer is required in exactly one place. The natural mapping, consistent with IPCC practice: rcp26 → ssp126, rcp45 → ssp245, rcp85 → ssp585, and Data API `ref_year` 2040 → app horizon 2050, 2060 → (interpolation anchor), 2080 → 2080. The cleanest fix is to have the backend write frontend-native scenario keys, so the CSV contract stays "whatever the app's dropdown says." The 2030 horizon has no Data API counterpart; either interpolate between present and 2040 in the backend, or let the app fall back to present for 2030 and label it as such.

**Finding 3 — no `hazard` column emitted.** The frontend defaults missing `hazard` to `tc`, so this is benign today, but the moment a second peril ships the backend must tag every row. Add it now so the contract is stable.

**Finding 4 — the frequency integration and the surge proxy embed assumptions Petals will replace.** The interim coastal-flood proxy derives surge from the present-day wind v100 and open-coast distance, which the app itself flags as understating sheltered below-sea-level basins (New Orleans). This is precisely the gap TCSurgeBathtub with a real DEM closes.

None of these are criticisms of the design; the fallback behaviour is graceful by construction. But Findings 1 and 2 together mean the current deployment is showing less CLIMADA signal than everyone likely believes, and they should be fixed in Phase 0 before any new layers land.

---

## 2. CLIMADA Core vs CLIMADA Petals: what each actually provides

CLIMADA Core (climada_python) is the risk engine: the Hazard, Exposures, ImpactFuncSet, Impact, Measure/MeasureSet, CostBenefit, unsequa (uncertainty and sensitivity via SALib), impact-function calibration, and Forecast classes, plus the Data API client. TropCyclone wind and LitPop exposures ship in Core as reference implementations. The Data API serves precomputed global hazard at roughly 4 km for tropical cyclone, river flood, agro drought, and European winter storm, plus LitPop exposures.

CLIMADA Petals (climada_petals) is the hazard and application generator that builds on Core and is not standalone. Most active development happens there. The modules relevant to this portfolio, in order of fit:

**TCSurgeBathtub** (`climada_petals.hazard.tc_surge_bathtub`). Converts a TropCyclone wind hazard into surge depth in metres using a linear wind-surge relationship fitted to SLOSH points (roughly 6 ft at 60 mph to 18 ft at 140 mph), subtracts land elevation from a user-supplied DEM raster, and applies inland decay (default 0.2 m per km, from Pielke and Pielke 1997) plus an `add_sea_level_rise` offset in metres. Input is the exact TropCyclone objects refresh_hazard.py already downloads; output is a Hazard with the same event set and centroids, intensity in metres of water. This is the single highest-leverage petal: it turns the pipeline you already run into a physically grounded coastal-flood layer whose units (depth in m) match what the app's `floodMdd` stage-damage curve already consumes, and whose event frequencies are inherited from the wind set so the same `local_exceedance_intensity` call produces the RP grid. Requires one dataset acquisition: SRTM15+ V2 (free global 15 arcsec bathymetry/topography GeoTIFF) or, better for populated coasts, CoastalDEM from Climate Central (on request; corrects SRTM's systematic overestimate of coastal elevation).

**TCSurgeGeoClaw**. A physical shallow-water surge model. Far more accurate for individual bays and harbours, and far heavier (per-event numerical simulation, compiled Fortran dependency). Not recommended for the portfolio screening tier; note it as the escalation path if a specific high-value site needs engineering-grade surge.

**RiverFlood** (`climada_petals.hazard.river_flood`) and the Data API `river_flood` datasets. Two routes to the same peril. Route A, the light one: the Data API already serves country-level river flood hazard (flood depth, 150 arcsec, derived from ISIMIP/CaMa-Flood) for historical and RCP2.6/6.0/8.5, retrievable with the identical `client.get_hazard("river_flood", properties=...)` pattern refresh_hazard.py uses for TC. Route B, the heavy one: build hazard directly from ISIMIP2b NetCDF (flddph/fldfrc) with the Petals RiverFlood class, which unlocks the FLOPROS flood-protection-standard layers (no protection vs 100-year vs merged FLOPROS database) and GHM/GCM ensemble control. Recommendation: Route A first (one code path change, immediate rflood layer), Route B later if protection standards matter for specific sites, which they will for New Orleans-type geographies. There is also `rf_glofas` (river flood from GloFAS discharge reanalysis/forecast), which is the most actively documented Petals flood module and doubles as an operational-forecast source.

**TCRain**. TC rainfall fields from the same track sets (R-CLIPER and TCR models). Pluvial flooding from cyclone rainfall is a genuine loss driver for resorts (Harvey-type events) that neither the wind nor the surge layer captures. Medium priority; the app would need a fourth damage peril or fold it into riverine flood.

**Wildfire**. FIRMS satellite-detection-based probabilistic wildfire. Relevant only if the portfolio grows into California/Mediterranean exposure; the current site list (Palm Springs aside) is not wildfire-led. Park for portfolio expansion.

**Landslide, LowFlow (water scarcity), RelativeCropyield**. Not portfolio-relevant. Skip.

**Hazard Emulator**. Statistical subsampling of large simulated event databases calibrated to climate indices (GMT time series), enabling arbitrary-year and arbitrary-warming-level hazard. This is the machinery to synthesise the app's 2030 horizon and to move from RCP-at-fixed-years to warming-level scenarios later. Advanced; Phase 5+.

**TCForecast and the Warn module**. ECMWF ensemble TC track forecasts converted to probabilistic wind footprints, and a warning-generation engine. This is a different product surface: a live "storm approaching the portfolio" operational view rather than annual screening. Flag as an attractive Phase 6 layer because the frontend's map and site model are already the right chassis for it.

**Engine petals: SupplyChain and CAT bonds.** SupplyChain propagates direct damage through multi-regional input-output tables to indirect economic impact; conceptually adjacent to the app's BI layer but modelled at national-sector granularity, poor fit for resort BI. The CAT bond module prices catastrophe bonds off CLIMADA loss exceedance curves; directly adjacent to the app's insurance-layering tab (attach/exhaust/load), and the natural upgrade if risk transfer analysis needs to move from indicative to priced.

**Exposure petals: OpenStreetMap (osm-flex) and BlackMarble.** OSM extraction can pull actual building footprints and infrastructure at each resort, upgrading exposure from a single point per site to a footprint. Useful for the surge layer where 200 m of position matters. LitPop (in Core) is not needed since real asset values exist.

**Core capabilities the plan will lean on beyond hazard**: `Impact` with full event sets for exact portfolio EP curves (fixing the app's documented "sum of per-site RP losses is an upper bound" caveat), `CostBenefit` for adaptation appraisal against the browser implementation, `unsequa` for real Monte Carlo uncertainty to validate the RSS screening bands, and the calibration module to fit the wind vulnerability curve to the observed-loss backtest data.

---

## 3. Gap analysis: current peril models vs Petals replacements

**TC wind.** Already CLIMADA-fed. Gaps are operational: present-only grid, scenario key mismatch, and `nb_synth_tracks="10"` which under-resolves the 250 and 500 year tail. Fix keys, add all three RCPs at 2040/2060/2080, and move to 50 synthetic tracks for the quarterly authoritative run (10 stays fine for dev runs).

**Coastal flood.** Interim proxy scales surge off wind v100 and open-coast distance with a fixed shape function and additive SLR. Known failure modes acknowledged in the app: sheltered basins, levee-protected below-sea-level land, harbour amplification. TCSurgeBathtub replaces the depth field with DEM-grounded, event-consistent surge; SLR enters through `add_sea_level_rise` per scenario using the same SLR table the app already carries (0.11 to 0.84 m). Residual limitations to document honestly: bathtub models have no hydrodynamics (no wave setup, no levee logic), and SRTM-family DEMs overstate elevation in vegetated/built coasts (hence CoastalDEM). Levees still need the app's existing `defended` freeboard attribute; that division of labour (Petals gives water level, the app's vulnerability attributes give protection) is clean and should be kept.

**Riverine flood.** Interim proxy is continentality-shaped and admits it. Data API river_flood gives modelled flood depth at 150 arcsec with real RCP scenarios. One modelling note: ISIMIP river flood events are annual-maximum fields, and the frequency integration to RP depths goes through the same `local_exceedance_intensity` call, so the backend code change is nearly copy-paste from the TC path. The FLOPROS protection question (does the model already net out levees?) must be answered per dataset and stated in the app's Method tab, because the app's freeboard/defended logic must not double-count protection the hazard layer already includes.

**Heat.** Neither Core nor Petals ships a canonical heat hazard, and the Data API has none, so heat cannot be "switched to Petals" the way the floods can. The right move is to make heat data-driven rather than latitude-driven using Core's generic `Hazard.from_xarray_raster` over ERA5 (present) and CMIP6/NEX-GDDP (scenarios): compute days-over-32C and days-over-35C per cell per scenario offline and ship them in the grid file as a `heat` hazard with indicator columns. The frontend's `heatIndicators` becomes a grid lookup with the current formula as fallback, exactly the supersession pattern the other perils use. This keeps the heat-revenue-at-risk financial logic untouched.

**TC rain / pluvial.** Currently absent. TCRain plus a shallow ponding assumption could feed a fifth column, but recommend deferring until the three replacements above are validated, since it adds a new peril to the UI rather than upgrading an existing one.

---

## 4. Integration architecture

### 4.1 Keep the contract, extend the schema

The grid CSV stays the sole backend-to-frontend interface for hazard. Extended contract (the frontend already parses all of it):

```
lat, lon, scenario, hazard, v10, v25, v50, v100, v250, v500
```

with `hazard` in {tc, cflood, rflood, heat} and `scenario` in the frontend's native key set (`present`, `ssp126_2050`, ...). Units by hazard: tc in m/s, cflood and rflood in metres of depth, heat rows carrying indicator values (see 4.3). One file, all perils, all scenarios; the app routes rows by hazard and supersedes per peril, so partial files (say tc+cflood only) degrade gracefully to interim for the rest — behaviour that already exists.

Add a small sidecar `hazard_grid_meta.json` written by the backend (run date, CLIMADA/Petals versions, dataset properties actually matched per hazard/scenario, DEM source, track count, row counts per scenario) and teach the app's provenance badge and Method tab to display it. This is cheap and is what turns "a CSV appeared" into disclosure-grade provenance.

### 4.2 Backend refactor shape

refresh_hazard.py grows from one fetch-and-grid function into a small pipeline of per-peril producers sharing the thinning and writing stages:

```
producers:
  tc_wind(country, scenario)      -> Hazard (Data API, as today, 50 tracks)
  tc_surge(tc_wind_hazard, DEM, slr(scenario)) -> Hazard (Petals TCSurgeBathtub)
  river_flood(country, scenario)  -> Hazard (Data API river_flood)
  heat(bbox, scenario)            -> indicator grid (ERA5/CMIP6 via xarray)
shared:
  local_rp_intensity(haz, RPS)    -> unchanged
  thin_to_grid(...)               -> unchanged, plus hazard tag
  scenario key translation        -> rcp*/ref_year -> ssp*_year
  writer                          -> CSV + meta JSON
```

Crucial efficiency detail: tc_surge consumes the TropCyclone object tc_wind already downloaded per country/scenario, so the surge layer adds DEM sampling and arithmetic but zero additional API downloads. Cache the downloaded hazards (the API client already caches to ~/climada/data) and the DEM once.

Environment: one mamba env, `climada=6.*` plus `climada_petals=6.*` from conda-forge (Core and Petals must share a MAJOR version; Petals' minor may lead Core's — Petals releases between Core releases and declares an open floor on Core, e.g. Petals 6.2.0 requires `climada>=6.1` and there is no Core 6.2.0, so `6.*`/`6.*` correctly resolves Core 6.1.0 + Petals 6.2.0). The corporate-TLS workaround from diagnose_network.py applies unchanged; the only new network dependency is the one-time SRTM15+/CoastalDEM download and, for heat, CDS/ESGF access, both of which can be done off-network and copied in if needed.

### 4.3 Heat row encoding

Two clean options. Option A (minimal frontend change): reuse the v-columns as indicator slots for `hazard=heat` rows, e.g. v10=daysOver32, v25=daysOver35, v50=cdd, others zero, and have `heatIndicators` check `gridByHazard.heat` first. Option B (cleaner long-term): a second small CSV `heat_grid.csv` with explicit columns (lat, lon, scenario, days32, days35, cdd) and a dedicated loader. Recommend Option A for Phase 4 to avoid a second file drop in the UX, documented plainly in the Method tab, with Option B as the eventual tidy-up if more chronic indicators (humidity, water stress) accumulate.

### 4.4 The deeper cut: a per-site results pack (Phase 5)

Everything above keeps impact in the browser, which is correct for interactivity. But three things the browser cannot do well are exactly Core's strengths: an event-consistent portfolio EP curve (the app currently sums per-site RP losses and honestly labels it an upper bound; Core's `Impact` over the actual event set with the real site exposures gives the true joint curve, replacing the ad hoc correlation blend in `finPortfolio`), a reference CostBenefit run for the adaptation measures (validating the browser's annuity math against the canonical implementation), and real unsequa Monte Carlo bands (validating the RSS screening bands).

Deliver these as a second optional artifact, `results_pack.json`, produced by a new script (refresh_impacts.py) that reads the site CSV, builds a point Exposures GeoDataFrame, applies the same Emanuel/JRC-style impact functions, runs Impact per peril per scenario over the full event sets, and emits per-site EAD, the portfolio EP curve at the six RPs, CostBenefit per measure, and unsequa quantiles. The frontend gains one more drop zone; when a results pack is loaded, the EP curve, VaR, and uncertainty panels display the authoritative figures alongside (not instead of) the live interactive model, badge-labelled. This preserves the app's instant interactivity while giving disclosure numbers a fully CLIMADA-native provenance chain. It also removes the last "screening, not disclosure" caveats in the footer for the perils covered.

---

## 5. Phased delivery plan

**Phase 0 — repair and harden the existing wind pipeline (small, do first).**
Fix the RCP fetch fallbacks so future scenarios actually land (extend the candidate-property pattern to the RCP branch; log matched properties into the meta JSON). Translate scenario keys to frontend-native ssp keys in the writer. Emit the `hazard` column (constant `tc`). Bump to 50 synthetic tracks for the scheduled run. Verify in-app that switching pathways now moves the wind numbers. Acceptance test: grid rows exist for every frontend scenario key except the 2030s (or including them via interpolation), and the app's Scenarios tab shows monotone wind EAD growth along SSP5-8.5.

**Phase 1 — coastal flood via TCSurgeBathtub (the flagship Petals integration).**
Acquire SRTM15+ V2 (request CoastalDEM in parallel; swap in when granted). For each country/scenario, run `TCSurgeBathtub.from_tc_winds(tc_haz, topo_path, add_sea_level_rise=SLR[scenario])`, compute RP depths with the shared exceedance call, thin, tag `hazard=cflood`. Frontend needs no code change: the existing `gridByHazard.cflood` supersession takes over, `floodMdd` with the coastal freeboard applies as-is, and the `defended` attribute continues to represent site protection. Validation: compare grid v100 depths at Galveston, New Orleans, Daytona, Rio Mar against NOAA SLOSH MOMs and FEMA coastal BFEs; confirm the New Orleans understatement the app documents is materially improved; confirm sites far from the coast get zeros (the bathtub inland decay handles this). Update the Method tab copy and the known-limits note (bathtub caveats replace the proximity-proxy caveats).

**Phase 2 — riverine flood via the Data API river_flood datasets.**
Add a `river_flood` producer mirroring the TC fetch (same client, `data_type="river_flood"`, scenario mapping rcp26/60/85 with rcp60 mapped to ssp245 as the nearest middle pathway, documented). Determine and record the protection assumption of the served dataset; if it is FLOPROS-protected, disable the app's freeboard double-count for rflood by noting it in Method and, if needed, zeroing the default riverine freeboard when a grid is live (one-line conditional). Tag `hazard=rflood`. Validation: San Antonio and Orlando sites should show plausible non-zero riverine depth at long RPs; coastal-only sites should not inherit riverine risk from proximity artifacts.

**Phase 3 — heat indicators from reanalysis and CMIP6.**
Offline notebook-grade script: ERA5 daily tmax 1991-2020 climatology for the present grid; NEX-GDDP-CMIP6 (or CMIP6 via ESGF) ensemble-median tmax for ssp126/245/585 at 2050/2080; compute days>32C, days>35C, CDD per 0.25 degree cell; write as `hazard=heat` rows per Option A. Frontend change is confined to `heatIndicators` (grid-first lookup, formula fallback) and Method copy. Validation: Palm Springs and San Antonio should overtake the coastal-latitude sites in days>35C, correcting the documented arid-inland understatement.

**Phase 4 — provenance and trust surface.**
Ship the meta JSON, render it in the Method tab and the hazard badge tooltip (versions, datasets, DEM, run date, per-peril coverage). Add a per-peril "authoritative since <date>" line. This phase is small but it is what lets the footer's disclosure caveats be narrowed peril by peril.

**Phase 5 — results pack (event-true portfolio curves, CostBenefit, unsequa).**
As specified in 4.4. This is the largest lift (a second backend script and a new frontend loader/panel) and the largest credibility gain: exact joint EP curve replacing the correlation blend, canonical measure appraisal, Monte Carlo bands. Also wire the calibration loop: feed the backtest observed-loss CSV into Core's impact-function calibration to fit v_half regionally, and surface the fitted curve as an optional vulnerability setting in the app.

**Phase 6 — optional expansions, in rough priority order.**
TCRain as a pluvial layer or riverine supplement. TCForecast + Warn as a live storm-watch mode over the same map and site model. CAT bond pricing behind the insurance-layering tab. OSM footprints for the highest-value coastal sites to refine surge exposure. Wildfire when the portfolio's western/Mediterranean footprint justifies it. Hazard Emulator for warming-level scenarios and true 2030 horizons.

---

## 6. Effort, runtime, and operational notes

Phase 0 is a day of work including verification. Phase 1 is the key new engineering: roughly two to four days including DEM acquisition, plus validation time; runtime cost is modest since surge reuses downloaded wind (expect the quarterly job to grow from minutes to low tens of minutes at 50 tracks across three countries and four scenario keys, dominated by wind-field downloads already incurred). Phase 2 is one to two days (a second fetch path plus the protection-standard investigation). Phase 3 is two to five days depending on CMIP6 data-access friction (CDS API registration, volume of daily tmax; consider precomputed indicator products such as NEX-GDDP-CMIP6 derived indices to shortcut). Phase 5 is one to two weeks including validation against the browser model.

File size stays comfortable: four hazards times ~13 scenario keys times ~15k cells is on the order of half a million rows, ~30-40 MB CSV; if drag-and-drop starts to feel heavy, gzip the file and add a two-line pako inflate in the loader, or split per peril (the loader can accept sequential drops by merging into gridByHazard rather than resetting it — a small, worthwhile frontend tweak in Phase 1).

Version-churn risk: the Data API property vocabulary has changed across releases (the codebase already carries scars and the candidate-fallback pattern to handle it). Keep that pattern for every new data_type, pin climada and climada_petals versions in the env spec, record matched properties in the meta JSON, and keep list_tc_datasets.py generalised into list_datasets.py taking a data_type argument as the standing discovery tool.

Licensing: CLIMADA and Petals are GPLv3. The current usage (running them as external tools that emit data files consumed by an unrelated app) creates no copyleft obligation on the HTML app. That boundary is worth keeping deliberate: keep CLIMADA code server-side in the pipeline scripts, keep the app consuming data.

Honesty of the model chain, restated for the Method tab after full integration: hazard becomes CLIMADA/Petals-authoritative per peril; vulnerability remains published-curve based (Emanuel wind, JRC-style stage-damage) until Phase 5 calibration; exposure remains user-supplied point values until OSM footprints; the bathtub surge has no waves or levee hydraulics; ISIMIP river flood is a ~5 km model, not a FEMA study; heat indicators are ensemble medians. Every one of those statements is defensible in a TCFD/ISSB appendix, which is the standard the app's disclosure ambition sets.

---

## 7. Summary of recommendations

Fix the two silent scenario failures first (Phase 0); they are the cheapest credibility repair available. Then integrate TCSurgeBathtub as the first Petals layer, because it reuses the exact hazard objects already downloaded, replaces the weakest interim proxy, outputs in the units the frontend already consumes, and requires zero frontend code. Follow with Data API river flood and reanalysis-driven heat, at which point all four perils are data-authoritative and the interim model becomes a pure offline fallback. Land the provenance sidecar alongside. Then, and only then, invest in the results pack to make the portfolio EP curve, adaptation appraisal, and uncertainty bands CLIMADA-native, closing the last gap between "screening" and "disclosure." The existing grid-supersession architecture means every phase ships independently and degrades gracefully, which is the property that made the current system good and should be the property that survives the integration.
