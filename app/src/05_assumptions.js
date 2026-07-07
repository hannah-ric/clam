
/* ============================================================
   GENERATED FILE - DO NOT EDIT.
   Source: pipeline/assumptions.py (the single sourced scenario-
   assumptions registry: every value there carries units, baseline
   period, citation, and any explicit conservative delta vs the
   AR6 central estimate). Regenerate with:
       python pipeline/assumptions.py --write-app
   ============================================================ */
const ASSUMPTIONS_VERSION="1";
// degC above the 1995-2014 baseline; AR6 WG1 Table 4.1 central +
// explicit conservative delta (see the registry for per-entry detail)
const WARMING={"present":0.0,"ssp126_2030":0.6,"ssp245_2030":0.7,"ssp585_2030":0.8,"ssp126_2050":1.0,"ssp245_2050":1.4,"ssp585_2050":2.0,"ssp126_2080":1.3,"ssp245_2080":2.3,"ssp585_2080":3.6};
// m above the 1995-2014 baseline, REGIONAL: AR6 Table 9.9 GMSL
// central + explicit delta, x NOAA 2022 regional factor. First
// matching box wins; outside every box the global-mean table
// (identical to the legacy single table) applies.
const SLR_REGIONS={"gulf":{"present":0.0,"ssp126_2030":0.12,"ssp245_2030":0.14,"ssp585_2030":0.15,"ssp126_2050":0.26,"ssp245_2050":0.3,"ssp585_2050":0.36,"ssp126_2080":0.46,"ssp245_2080":0.59,"ssp585_2080":0.84},"florida_atlantic":{"present":0.0,"ssp126_2030":0.1,"ssp245_2030":0.11,"ssp585_2030":0.13,"ssp126_2050":0.22,"ssp245_2050":0.25,"ssp585_2050":0.31,"ssp126_2080":0.39,"ssp245_2080":0.51,"ssp585_2080":0.71},"caribbean":{"present":0.0,"ssp126_2030":0.09,"ssp245_2030":0.1,"ssp585_2030":0.12,"ssp126_2050":0.2,"ssp245_2050":0.23,"ssp585_2050":0.28,"ssp126_2080":0.36,"ssp245_2080":0.46,"ssp585_2080":0.65},"hawaii":{"present":0.0,"ssp126_2030":0.09,"ssp245_2030":0.1,"ssp585_2030":0.11,"ssp126_2050":0.19,"ssp245_2050":0.22,"ssp585_2050":0.27,"ssp126_2080":0.34,"ssp245_2080":0.44,"ssp585_2080":0.62},"global_mean":{"present":0.0,"ssp126_2030":0.09,"ssp245_2030":0.1,"ssp585_2030":0.11,"ssp126_2050":0.19,"ssp245_2050":0.22,"ssp585_2050":0.27,"ssp126_2080":0.34,"ssp245_2080":0.44,"ssp585_2080":0.62}};
const SLR=SLR_REGIONS.global_mean;
const SLR_REGION_BOXES=[["gulf",24.0,31.5,-100.5,-82.0],["florida_atlantic",24.0,37.5,-82.0,-74.0],["hawaii",18.0,23.0,-161.0,-154.0],["caribbean",17.0,19.5,-68.0,-64.0]];
// appraisal convention, unified with the results pack (3% real, 25y)
const APPRAISAL_DEFAULTS={"discountPct":3.0,"horizonYears":25};
// structural archetypes: curve-level vulnerability differentiation;
// the profile factor table stays the mapping layer on top. The
// default reproduces the published curve exactly.
const ARCHETYPES={"lowrise_timber":{"v_half_mult":1.0,"fb_add_m":0.0,"flood_cap":null,"label":"Low-rise timber frame"},"lowrise_masonry":{"v_half_mult":1.08,"fb_add_m":0.0,"flood_cap":null,"label":"Low-rise masonry"},"midrise_concrete":{"v_half_mult":1.18,"fb_add_m":0.0,"flood_cap":null,"label":"Mid-rise concrete frame (4-7 stories)"},"tower_concrete":{"v_half_mult":1.3,"fb_add_m":0.0,"flood_cap":0.5,"label":"High-rise concrete tower"},"beachfront_lowrise":{"v_half_mult":0.95,"fb_add_m":-0.3,"flood_cap":null,"label":"Beachfront low-rise"},"setback_elevated":{"v_half_mult":1.0,"fb_add_m":0.5,"flood_cap":null,"label":"Set-back / elevated siting"},"mep_basement":{"v_half_mult":1.0,"fb_add_m":-0.2,"flood_cap":0.9,"label":"Critical plant in basement"},"mep_elevated_plant":{"v_half_mult":1.0,"fb_add_m":0.0,"flood_cap":0.5,"label":"Critical plant elevated"}};
const DEFAULT_ARCHETYPE="lowrise_timber";
const FIRE_WARMING_UPLIFT=0.14;   // burn-probability uplift per deg C
const TC_UPLIFT_PER_C=0.02;     // interim TC field intensity uplift per deg C
// interim flat conditional damage ratio given fire reaches the
// site (capped; LABELED interim); a grid carrying flame-length-
// conditioned ratios in v25 supersedes it per site
const FIRE_COND_INTERIM=0.35;
