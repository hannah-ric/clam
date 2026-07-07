const SAMPLE=[
  ["Club Wyndham Ocean Walk","Club Wyndham",29.2247,-81.0068,58000000,{construction:"masonry",year_built:2002}],
  ["Club Wyndham Sea Gardens","Club Wyndham",26.2731,-80.0906,42000000,{construction:"masonry",year_built:1988}],
  ["Margaritaville Rio Mar","Margaritaville",18.3797,-65.8083,51000000,{construction:"engineered",year_built:1996,defended:true}],
  ["Club Wyndham Bonnet Creek","Club Wyndham",28.3402,-81.5460,73000000,{construction:"engineered",year_built:2011}],
  ["WorldMark New Orleans","WorldMark",29.9536,-90.0653,31000000,{construction:"masonry",year_built:1970,defended:true}],
  ["Club Wyndham Kona Hawaiian","Club Wyndham",19.6406,-155.9967,39000000,{construction:"frame",year_built:1992}],
  ["Shell Vacations Kauai Coast","Shell Vacations Club",22.0731,-159.3200,28000000,{construction:"frame",year_built:1987}],
  ["Club Wyndham Galveston","Club Wyndham",29.2810,-94.7940,34000000,{construction:"masonry",year_built:1999,defended:true}],
  ["WorldMark San Antonio","WorldMark",29.4241,-98.4936,22000000,{construction:"frame",year_built:2005}],
  ["Club Wyndham Myrtle Beach","Club Wyndham",33.6891,-78.8867,45000000,{construction:"masonry",year_built:2006}],
  ["Margaritaville St Thomas","Margaritaville",18.3358,-64.8963,47000000,{construction:"masonry",year_built:1989}],
  /* wui_class makes the sample demonstrate the wildfire peril out of the box:
     Palm Springs sits against the San Jacinto wildland edge (illustrative) */
  ["WorldMark Palm Springs","WorldMark",33.8303,-116.5453,17000000,{construction:"frame",year_built:1999,wui_class:"interface",defensible_space_m:20}],
];
let sites=[];
let hazardGrid=null;       // {rows, meta}: the loaded grid and its summary
let hazardMeta=null;       // provenance sidecar (hazard_grid_meta.json), optional
let resultsPack=null;      // CLIMADA results pack (results_pack.json), optional
let backtest=null;         // {rows:[{name,observed}],loaded} observed-loss history for calibration
let gridByHazard={};       // hazardKey -> grid provider fn, when a grid is loaded
let scenario="present";
let activeHazard="tc";     // peril driving the map, overview, and detail
let selectedId=null;
let _scorecardId=null;     // the site whose scorecard is open (for the Edit button)
let sortKey="ead", sortDir=-1;
let nextId=1;
let brandFilter="";        // map-only brand filter (session, not persisted)
let _lastBrandKey="";      // rebuilt brand options only when the brand set changes
let scenHook=null;         // wire() installs the topbar-select sync for the scrubber
let scrubTimer=null;       // scenario scrubber playback
/* View/UI preferences (persisted, defensively merged like finAssume). Holds the
   chosen visualization lenses (ui.views: how a chart is grouped or measured) and,
   later, first-run and simple-view flags. Never affects a computed number: these
   keys only change how existing figures are shown. */
let ui={views:{matrixGroup:"site",matrixMetric:"pct",mapColor:"peril"},onboarded:false,simpleView:false,
  /* v2.3.0 executive home: the full-bleed map with floating priority panels
     is the default landing view; Analyst restores the classic tab workspace.
     A pure display flag: it changes no computed figure. */
  execMode:true};

/* hazard provider is built once (not per call) and cached per site+scenario,
   so the many scoring passes in one render do not repeat spatial lookups. */
let _baseProvider=(la,lo,sc)=>interimVector(la,lo,sc);
let _hazCache=new Map();
function clearHazCache(){ _hazCache=new Map(); }
function provider(){
  return function(la,lo,sc){
    const k=la.toFixed(5)+","+lo.toFixed(5)+","+sc;
    let hit=_hazCache.get(k);
    if(hit===undefined){ hit=_baseProvider(la,lo,sc); _hazCache.set(k,hit); }
    return hit;
  };
}
function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function toNum(v){ if(v==null)return NaN; const s=String(v).replace(/[$,%\s]/g,""); return s===""?NaN:parseFloat(s); }
function csvCell(s){ s=String(s==null?"":s); return /[",\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s; }
function fmt$(x){ if(!isFinite(x))x=0; if(Math.abs(x)>=1e6)return "$"+(x/1e6).toFixed(2)+"M"; if(Math.abs(x)>=1e3)return "$"+(x/1e3).toFixed(0)+"k"; return "$"+Math.round(x); }
function fmtFull(x){ return "$"+Math.round(x).toLocaleString(); }
function toast(m){const t=document.getElementById("toast");t.textContent=m;t.classList.add("show");setTimeout(()=>t.classList.remove("show"),2200);}

/* ============================================================
   Explain-it info layer
   Plain-language explanations of every headline number and the
   assumptions behind it, surfaced as accessible popovers. Any element
   with data-info="<key>" becomes a trigger. Content is trusted static
   markup authored below.
   ============================================================ */
const INFO={
  controls:{t:"Peril, pathway and horizon",b:
    "<p><b>Peril</b> picks which climate hazard drives the map colour and the site detail: tropical-cyclone wind, coastal flood, riverine flood, extreme heat, wildfire, or TC rainfall. The Overview risk-driver panel always shows all perils together.</p>"+
    "<p><b>Pathway</b> is an emissions future from the IPCC: <b>SSP1-2.6</b> is rapid decarbonisation, <b>SSP2-4.5</b> a middle road, <b>SSP5-8.5</b> high emissions.</p>"+
    "<p><b>Horizon</b> is the future decade (2030, 2050, 2080). Warming and sea-level rise grow with both the pathway and the horizon.</p>"+
    "<p><b>Brand</b> filters which sites appear on the map. <b>Map colour</b> is a display lens: colour the markers by the selected peril's band, by combined all-peril risk, or by each site's dominant peril. It changes the map only, never a figure.</p>",
    s:"Framework: IPCC AR6 SSP-RCP scenarios."},
  scrub:{t:"The scenario timeline",b:
    "<p>The timeline steps the whole app through <b>Present, 2030, 2050, and 2080</b> under the pathway selected in the top bar (SSP2-4.5 if the top bar is on Present day). Every figure on every tab recomputes at each step: it is the same model, walked through time.</p>"+
    "<p><b>Play</b> animates the walk so you can watch where cost concentrates and how fast it grows. Clicking a step pins the app to that future; the top-bar controls stay in sync.</p>",
    s:"Same scenario engine as the Pathway and Horizon controls; nothing extra is modeled."},
  trace:{t:"Tracing a number to its source",b:
    "<p>Each row walks one peril's figure back to where it came from: the <b>data source</b> (a loaded CLIMADA grid with the distance to the nearest cell, a named interim screening model, or an honest zero when neither exists), the <b>intensities</b> at each return period, the <b>named factors</b> this building's profile applies, and the resulting expected annual damage.</p>"+
    "<p>If a number surprises you, the trace shows which ingredient drove it. A grid supersedes the interim model per peril; a zero always says why it is zero.</p>",
    s:"The trace reads the same functions that computed the score; it cannot diverge from them."},
  execHome:{t:"The executive view",b:
    "<p>Everything on this panel is the same model the analyst workspace runs, read at the scenario on the timeline below: the <b>headline</b> is the portfolio's expected annual climate cost (damage, business interruption, and heat together), the tiles carry the <b>1-in-100 year</b>, the <b>tolerance position</b>, and the <b>largest driver</b>, and the ranked plan lists the sites where the money concentrates: each with <b>what to do, the dollars (cost, averted loss, payback), and the act-by deadline</b>. Its own i button explains each basis.</p>"+
    "<p>Click a priority to open the site's full scorecard, with the why-these-numbers trace. The <b>Analyst</b> switch in the top bar opens every specialist surface (perils, adaptation, insurance, uncertainty, method); <b>Export &amp; brief</b> carries the same figures out as a board one-pager or CSV artifacts.</p>",
    s:"A display lens over the shared engine: it computes nothing new and changes no figure."},
  execPlan:{t:"Top risks and the plan: how to read it",b:
    "<p><b>Which sites:</b> ranked by all-in expected annual cost (physical damage, business interruption, and heat together), so the biggest climate risk sits at the top regardless of which peril drives it.</p>"+
    "<p><b>What to do and the dollars:</b> each site shows its best value measure with the model's own figures: the one-time capital cost, the annual loss it averts, the share of that site's risk it removes, and the simple payback (cost divided by averted annual loss). Costs are planning-grade defaults from published mitigation studies scaled to the site's value and profile: firm enough to rank and budget, but replace them with engineering estimates before committing capital. Where no measure clears breakeven, the honest answer is shown instead: transfer the risk (insure) or accept it.</p>"+
    "<p><b>By when:</b> the deadline is not a new model. It is the first horizon (Present, 2030, 2050, 2080, under the selected outlook) at which the site's annual cost crosses <b>your own risk tolerance</b>, set on the analyst Summary tab. Over it today reads act now, and each year of delay forfeits the measure's averted loss; never over it by 2080 reads monitor. When a CLIMADA results pack is loaded, its capital plan's phase (Y1, Y2, deferred) is shown beside the urgency as the canonical schedule.</p>",
    s:"Same engine as the adaptation tab's action queue; the roll-up line never double-counts overlapping measures."},
  brief:{t:"The board brief",b:
    "<p>Builds a print-ready one-pager of the portfolio at the current scenario: headline figures, cost by peril, the most exposed sites, the trajectory to 2080, and the data provenance line, then opens your browser's print dialog. Choose <b>Save as PDF</b> to get the file.</p>"+
    "<p>The brief states its data basis (CLIMADA grid or interim screening) and carries the same disclosure caveats as the app; nothing is computed specially for it.</p>",
    s:"Zero-install by design: the PDF comes from the browser, no service involved."},
  interim:{t:"Where the hazard comes from",b:
    "<p>With no data loaded, the app uses a built-in <b>interim model</b>: transparent regional proxies for each peril. It is good for exploration, not for disclosure.</p>"+
    "<p>Drop a <b>CLIMADA hazard grid</b> on the Method tab to replace any peril with authoritative values. Perils not in the grid stay on the interim model. The badge in the top bar shows which source is live, per peril.</p>"+
    "<p>The pipeline also writes <code>hazard_grid_meta.json</code>. Drop it on the same zone to attach the run record (date, CLIMADA and Petals versions, datasets matched, DEM, anything skipped) to the badge and the Method tab.</p>"},
  tiv:{t:"Total insured value",b:
    "<p>The combined value of every site in the portfolio. All dollar losses are measured against it.</p>"+
    "<p>Sample values are illustrative and are not actual Travel + Leisure Co. figures.</p>"},
  ead:{t:"Expected annual damage (EAD)",b:
    "<p>The <b>average</b> loss per year from this peril, blending frequent-small and rare-large events into one number.</p>"+
    "<p>We compute the damage at the six tabulated return periods (1-in-10 up to 1-in-500) and take the area under the loss-versus-frequency curve, <b>extended below 1-in-10</b>: the intensity curve is extrapolated to 1-in-5 and 1-in-2 and run through the same damage curve, so frequent events count instead of being silently floored at zero. Calm sites are unchanged (the damage threshold or freeboard zeroes the extension); chronically-exposed ones stop hiding their frequent losses. The results pack's event math never had the floor.</p>",
    s:"Vulnerability: Emanuel (2011) for wind; stage-damage curve for flood."},
  eadPct:{t:"EAD as a share of value",b:
    "<p>Expected annual damage divided by the site's insured value. A site at <code>0.50%</code> loses, on average, half a percent of its value to this peril each year.</p>"+
    "<p>It puts sites of very different sizes on the same footing.</p>"},
  rp100:{t:"1-in-100 loss",b:
    "<p>Per site, this is that site's own loss at the 1-in-100-year intensity, straight from its damage curve: a physical-units figure to read beside the expected annual damage.</p>"+
    "<p>At portfolio level we add each site's 1-in-100 loss, which assumes the peril strikes every site at once. Real events rarely hit the whole portfolio together, so the portfolio figure is an <b>upper bound, never the joint tail</b>: the results pack's per-event math carries the canonical joint curve, and every surface states which one it shows.</p>"},
  bands:{t:"Risk bands",b:
    "<p>Five plain-language bands from the annual loss ratio, so you can sort and communicate without reading every number:</p>"+
    "<p><b>Minimal</b> &middot; <b>Low</b> to 0.25% &middot; <b>Moderate</b> to 0.75% &middot; <b>High</b> to 1.5% &middot; <b>Severe</b> above 1.5%.</p>"},
  ratings:{t:"Per-peril ratings",b:
    "<p>One letter per peril: <b>W</b> wind, <b>F</b> coastal flood, <b>R</b> riverine flood, <b>H</b> heat, <b>B</b> wildfire, <b>P</b> TC rainfall.</p>"+
    "<p>Each shows the site's risk band for that peril at the selected scenario, so you see the whole risk profile at a glance. Colours follow the same band scale.</p>"},
  drivers:{t:"Risk drivers",b:
    "<p>Portfolio expected annual damage split by peril, so you can see what actually drives the loss rather than assuming it is wind.</p>"+
    "<p>Heat is tracked as indicators, not damage dollars, so it sits outside this split; its cost appears as heat revenue at risk on the Financial impact tab.</p>"},
  epcurve:{t:"Loss exceedance curve",b:
    "<p>Each point is the portfolio loss at a return period. The curve rising to the right means rarer events cause larger losses.</p>"+
    "<p>Expected annual damage is the area under this curve.</p>"},
  brand:{t:"Expected annual damage by brand",b:
    "<p>Where expected loss concentrates by brand, so you can see which banner carries the exposure.</p>"},
  namedInsured:{t:"Named insured aggregation",b:
    "<p>A single physical <b>site</b> (a resort campus) can carry several <b>named insured</b> parties: an owners' association (HOA) and the operating company (TNL), for example, each insuring different buildings on the same land.</p>"+
    "<p>The map shows <b>one marker per physical site</b>, so the portfolio reads as sites rather than duplicate pins stacked at the same coordinates. Everywhere the split matters, a <b>breakout</b> reports each named insured's value, expected annual damage, and share of the site total, so you can see <b>who is impacted and to what degree</b>.</p>"+
    "<p>Records are grouped by <code>site_id</code> when present, otherwise by exact coordinates. A portfolio with neither draws one marker per record, exactly as before.</p>",
    s:"A display and rollup lens: it groups the same per-record figures, changing none of them."},
  wfire:{t:"Wildfire",b:
    "<p>Wildfire uses the <b>annual probability fire reaches the site point</b> (USFS Wildfire Risk to Communities burn probability, point-sampled by the pipeline at 30 m; never fire-anywhere-in-a-cell, never buffered): expected damage = value x point burn probability x a <b>conditional damage ratio given fire</b>, cut by a Class A roof (x0.6) and defensible space of 30 m or more (x0.7).</p>"+
    "<p>The conditional ratio comes from the modeled <b>flame length</b> at the site (the grid's v25) where the WRC CFL layer was supplied; otherwise an <b>interim flat ratio ("+(FIRE_COND_INTERIM*100)+"%, capped)</b> applies and is labeled interim on the trust surface and the score trace.</p>"+
    "<p>Without a wfire grid, the site's <code>wui_class</code> gives an interim point probability (interface "+FIRE_WUI_PBURN.interface+"%/yr, intermix "+FIRE_WUI_PBURN.intermix+"%/yr), scaled with warming. Without either, wildfire is zero by design.</p>"+
    "<p><b>Honest limit:</b> at realistic point probabilities (roughly 0 to 2%/yr even in high-risk WUI) wildfire contributes to expected annual damage but not to the 1-in-100 tail figures in this app. The results pack carries the fire tail as a per-site occurrence exceedance.</p>"},
  prain:{t:"TC rainfall",b:
    "<p>Event rainfall (mm at each return period, from a prain grid) becomes ponding depth through documented drainage constants: depth = max(0, rain - "+PRAIN_DRAIN_MM+" mm) x "+PRAIN_POND_COEFF+", then the flood damage curve with a "+PRAIN_FB+" m freeboard.</p>"+
    "<p>There is deliberately <b>no interim model</b>: rainfall cannot be proxied honestly from regional anchors, so this peril stays zero until a grid is loaded and the trust chip says so.</p>"},
  tc:{t:"Tropical-cyclone wind",b:
    "<p>Wind speeds by return period feed the <b>Emanuel (2011)</b> damage curve, the same one CLIMADA uses (<code>emanuel_usa</code>).</p>"+
    "<p>Damage begins around <code>25.7 m/s</code> and rises steeply toward <code>74.7 m/s</code>.</p>"},
  cflood:{t:"Coastal flood and surge",b:
    "<p>Flood depth by return period is driven by how close the site is to the coast and its surge exposure, then raised by <b>sea-level rise</b> under each scenario. Depth feeds a stage-damage curve.</p>"+
    "<p>Interim proxy until a CLIMADA coastal-flood grid is loaded.</p>"},
  rflood:{t:"Riverine flood",b:
    "<p>A deliberately coarse screening proxy that rises with distance inland and with warming.</p>"+
    "<p>It is among the least precise perils here and improves the most when a CLIMADA river-flood grid is loaded.</p>"},
  heat:{t:"Extreme heat",b:
    "<p>Reported as <b>indicators</b>, not a dollar loss: days per year over 32&deg;C and 35&deg;C, and cooling degree-days.</p>"+
    "<p>Two lenses on the same days. <b>Dry-bulb</b> temperature is the structural and financial view (equipment ratings, the heat revenue-at-risk math). The <b>feels-like heat index</b> is the guest-comfort, cooling-load, and outdoor-labor view: 33&deg;C at 75% coastal humidity is dangerous where 33&deg;C of dry desert air is not, and a beach portfolio lives on the humid side. Humid-heat days (feels-like over 35&deg;C) are counted with a documented screening humidity: warm-season RH decays from 80% at the coast toward 45% inland, then the NOAA heat-index regression. They are never fewer than the dry-bulb count.</p>"+
    "<p>Heat's cost to a resort is mostly lost business and energy; the Financial impact tab prices it as heat revenue at risk on dangerous-heat days (dry-bulb, so the money is unchanged by the comfort lens).</p>",
    s:"Heat index: NOAA/NWS Rothfusz regression; humidity is a coastal-proximity screening proxy, labeled as such."},
  scenShift:{t:"Present to 2080 shift",b:
    "<p>How this site's risk moves from present day to a high-emissions late-century world (SSP5-8.5, 2080), holding its location and value fixed.</p>"},
  value:{t:"Asset value",b:
    "<p>The site's insured or replacement value. Every dollar loss scales with it.</p>"+
    "<p>Use <b>Edit site</b> (on the site detail or its scorecard) to change the value, the revenue, the construction, and the other building facts, and everything recomputes.</p>"},
  scenarios:{t:"Combined physical risk by pathway",b:
    "<p>All acute perils summed into one physical expected-annual-damage figure, compared across emissions pathways at the horizon selected in the top bar.</p>"+
    "<p><b>Band migration</b> shows how many sites move into higher bands as the climate warms.</p>"},
  bcr:{t:"Benefit-cost ratio",b:
    "<p>Benefit is the <b>averted</b> expected annual climate cost (direct damage plus business interruption plus heat), capitalised over the appraisal horizon at the discount rate. Cost is the up-front spend.</p>"+
    "<p>Above <code>1.0</code> the measure returns more than it costs. Published mitigation studies typically find 2 to 6x for wind and flood retrofits in high-hazard zones.</p>"},
  levers:{t:"Appraisal settings",b:
    "<p><b>Horizon</b> is how many years of averted loss you count. The <b>discount rate</b> converts future averted losses to today's dollars. <b>Exposure growth</b> scales asset values and revenue into the future for the waterfall.</p>"+
    "<p>Together they set how much a measure's benefits are worth now, and how large future risk grows.</p>"},
  growth:{t:"Exposure growth",b:
    "<p>Annual growth in asset values and revenue, from refurbishment, densification, and inflation. Because expected loss scales with what is exposed, growth alone raises future risk even with no climate change.</p>"+
    "<p>The waterfall separates this growth increment from the climate increment, so each driver is visible on its own.</p>"},
  measLib:{t:"Measure library",b:
    "<p>Each measure works through one mechanism in the risk chain: reducing damage, reducing depth, shortening downtime, or cutting heat losses. Checked measures form the adaptation portfolio.</p>"+
    "<p>The portfolio's combined benefit is computed jointly on the modified risk chain, so overlapping measures are never double-counted.</p>"},
  mWind:{t:"Wind hardening",b:
    "<p>Roof tie-downs, impact-rated openings, and secondary water barriers. Modeled as a multiplier on wind damage: residual damage 65% means one third of wind loss is averted, and the business interruption that damage would have caused falls with it.</p>"},
  mFlood:{t:"Dry floodproofing & utility elevation",b:
    "<p>Sealing lower levels, flood barriers, and lifting electrical, mechanical, and IT plant above flood level. Modeled as added freeboard: the water must rise further before damage begins, for both coastal and riverine flooding.</p>"},
  mBuffer:{t:"Coastal buffer",b:
    "<p>Dune restoration and mangrove or reef planting in front of coastal sites. Modeled as a reduction in storm-surge depth reaching the building. Nature-based coastal measures report benefit-cost ratios above 3.5 in Gulf Coast studies.</p>"},
  mOps:{t:"Resilient operations",b:
    "<p>Backup power, pre-negotiated restoration contracts, and rapid-reopen playbooks. These do not reduce damage; they shorten the closed period, so the measure acts only on business interruption.</p>"+
    "<p>On a pure profit basis this often lands below 1.0x. It still carries option value (guest safety, brand protection) the ratio does not capture.</p>"},
  mCool:{t:"Cooling & shading retrofit",b:
    "<p>High-efficiency HVAC, shaded outdoor areas, and misting or pool capacity. Modeled as a percentage cut in the profit lost on dangerous-heat days. Its ratio improves under warmer scenarios as heat costs grow.</p>"},
  costCurve:{t:"Adaptation cost curve",b:
    "<p>The classic economics-of-climate-adaptation chart. Measures are sorted by benefit-cost ratio; each bar's width is the annual cost it averts, its height the ratio. Fund from the left until bars drop below the 1.0 breakeven line.</p>"+
    "<p>Dimmed bars are measures not currently in the portfolio. Together the bars show how much of total risk can be bought down cost-effectively.</p>"},
  waterfall:{t:"Total climate risk waterfall",b:
    "<p>CLIMADA's signature decomposition. Start from today's expected annual cost, add the increment from exposure growth, add the increment from climate change, and you have future risk. Subtract what the selected measures avert and the remainder is <b>residual risk</b>: what you retain, insure, or accept.</p>"+
    "<p>The bars reconcile exactly: today + growth + climate = future, and future - adaptation = residual.</p>"},
  mFire:{t:"Wildfire hardening",b:
    "<p>Defensible space and a Class A roof assembly cut the share of value lost when fire reaches the site. The slider is the burn-loss reduction; the measure applies only where the site has wildfire exposure (a wfire grid or a wui_class profile field).</p>"+
    "<p>Wildfire uses the annual probability fire reaches the site point, not a return-period depth: expected damage = value x point burn probability x the conditional damage ratio given fire (flame-length-conditioned, or the "+(FIRE_COND_INTERIM*100)+"% interim cap), modified by roof_class_a and defensible_space_m.</p>"},
  layering:{t:"Risk layering & insurance",b:
    "<p>Standard catastrophe practice splits the loss curve into layers: <b>retain</b> frequent small losses, <b>transfer</b> the middle to insurance between an attachment and an exhaustion point, and hold the extreme tail beyond the limit.</p>"+
    "<p>Transferred expected loss is the slice of the diversified loss curve inside the layer, applied to acute expected loss so retained plus transferred always reconcile. Chronic heat cost is operational, not insurable here.</p>"},
  loading:{t:"Premium loading factor",b:
    "<p>Insurers charge more than the expected loss they take on; the loading covers capital, expenses, and profit. A loading of 1.5x means the premium is one and a half times the transferred expected annual loss.</p>"+
    "<p>The difference between premium and transferred loss is the annual cost of certainty: what you pay to cap volatility.</p>"},
  recommend:{t:"Where to act first",b:
    "<p>For each site, every in-scope measure is appraised individually and the best benefit-cost ratio wins. Sites are ranked by that ratio, so the cheapest risk reduction in the portfolio rises to the top.</p>"+
    "<p>Site-level cost uses the same rates as the portfolio appraisal, so the two views stay consistent. Click a row to open the site's full scorecard.</p>"},
  unc:{t:"Uncertainty & sensitivity",b:
    "<p>A screening version of CLIMADA's unsequa analysis. Each input is swept across a plausible range while the others hold; the per-input swings form the tornado and are combined by root-sum-square (assuming independence) into the low-to-high band.</p>"+
    "<p>The band is asymmetric upward because damage curves are convex: the same hazard uncertainty costs more on the upside. The tallest bar is where better data most improves the estimate.</p>"},
  backtest:{t:"Backtest against observed losses",b:
    "<p>CLIMADA pairs modeled impacts with observed disaster data for calibration; this does the same with your loss history. Modeled present-day direct-damage AAL is compared to average observed annual losses per site.</p>"+
    "<p>Read the portfolio-level bias, not single-site scatter: catastrophe losses are so volatile that even a decade of clean records is a small sample. Bias outside roughly 0.5 to 2x is a signal to revisit hazard intensity, damage steepness, or the vulnerability attributes.</p>"},
  prio:{t:"Harden these first",b:
    "<p>Sites ranked by averted expected annual damage per dollar of hardening spend, so the cheapest risk reduction rises to the top.</p>"},
  exportInfo:{t:"Export schema",b:
    "<p>Writes one row per site with per-peril EAD and rating, combined physical EAD and %, heat indicators, and combined return-period losses.</p>"+
    "<p>The column layout matches the Power BI model, so it drops straight into the RtV pipeline.</p>"},
  totalAal:{t:"Expected annual cost (AAL)",b:
    "<p>The average total climate cost per year: direct asset damage plus business interruption plus heat-driven revenue at risk, summed across all perils.</p>"+
    "<p>Insurers call this the annual average loss (AAL). Shown as dollars per year and as a share of both asset value and annual revenue.</p>"},
  indirect:{t:"Indirect share",b:
    "<p>The part of the annual cost that is not physical damage: business interruption while a site is closed, plus heat's drag on revenue.</p>"+
    "<p>Indirect losses are often overlooked and can rival the damage bill for a hospitality portfolio.</p>"},
  var100:{t:"1-in-100 Value at Risk",b:
    "<p>The tail-risk yardstick: what a 1-in-100-year year would cost the portfolio.</p>"+
    "<p><b>Which curve you are seeing is stated on every surface.</b> When a results pack is loaded, the CANONICAL figure is its <b>joint event tail</b>: per-event losses summed across sites first (wind and surge share events), direct damage only. Without a pack, the app shows its live construction: per-site return-period losses blended through a correlation assumption (direct + business interruption) - a co-occurrence <b>approximation, never presented as the joint tail</b>.</p>"},
  var250:{t:"1-in-250 Value at Risk",b:
    "<p>The same tail measure at a rarer 1-in-250-year severity, a common capital and stress-test threshold.</p>"+
    "<p>Diversified across sites; treat as a screening estimate until a CLIMADA event set is loaded.</p>"},
  costsplit:{t:"Where the cost comes from",b:
    "<p><b>Direct damage</b> is repair and replacement of the building. <b>Business interruption</b> is lost operating profit while the site is closed. <b>Heat revenue at risk</b> is the profit shed on extreme-heat days.</p>"+
    "<p>All three are expected annual figures and add up to the total cost above.</p>"},
  acuteChronic:{t:"Acute vs chronic",b:
    "<p><b>Acute</b> risk is event-driven: wind, coastal flood, riverine flood, TC rainfall, wildfire, and the business interruption they cause. <b>Chronic</b> risk is gradual: heat's steady drag on operations.</p>"+
    "<p>TCFD and ISSB ask for physical risk reported in exactly this split.</p>"},
  assumptions:{t:"Assumptions",b:
    "<p>These five levers turn hazard into money. They are deliberately visible and adjustable so the logic is auditable and you can fit them to your own portfolio.</p>"+
    "<p>A per-site <code>annual_revenue_usd</code> column in the upload overrides the revenue lever for that site.</p>"},
  brandAssume:{t:"Per-brand overrides",b:
    "<p>The three revenue-and-operations assumptions above are portfolio-wide defaults. A resort brand often runs a different economic model, so you can override the revenue ratio, the operating margin, or the reopening time for any brand, and only that brand's sites recompute.</p>"+
    "<p>Blank means "+"\"use the portfolio default,\" so an untouched table reproduces the global numbers exactly. Reset clears a brand back to the defaults. A per-site <code>annual_revenue_usd</code> value still wins over both, for that one site.</p>",
    s:"A per-brand input to the same model; it changes which assumption a site uses, not the math."},
  revRatio:{t:"Revenue as % of asset value",b:
    "<p>Sets each site's annual revenue as a share of its value, used for business interruption and heat costs when no per-site revenue is supplied.</p>"+
    "<p>Hospitality real estate commonly runs 25 to 45%.</p>"},
  gop:{t:"Gross operating margin",b:
    "<p>The share of revenue that is operating profit. Business interruption and heat losses are measured on this profit, not on gross revenue, matching how business-interruption insurance is written.</p>"},
  reopen:{t:"Months to reopen at total loss",b:
    "<p>How long a totally destroyed site takes to rebuild and reopen. Downtime for a given event scales with its damage, so this sets the ceiling on business-interruption loss.</p>"},
  heatDrop:{t:"Profit lost per extreme-heat day",b:
    "<p>The share of a day's operating profit lost on each day above 35&deg;C beyond a 15-day comfort baseline: softer demand, cancellations, and higher cooling load.</p>"+
    "<p>Days over 35&deg;C (dangerous heat) are the driver because they are where guest comfort and outdoor operations genuinely degrade.</p>"},
  corr:{t:"Hazard correlation across sites",b:
    "<p>How much perils strike sites together. At <code>1.0</code> the portfolio tail is a full sum (every site hit at once); at <code>0</code> sites are independent and the tail is far smaller.</p>"+
    "<p>A spread portfolio sits in between. This is a screening stand-in for the spatial correlation a CLIMADA event set captures exactly.</p>"},
  disclosure:{t:"Climate-related financial disclosure",b:
    "<p>A TCFD and ISSB (IFRS S2) physical-risk summary: expected annual loss split into acute and chronic, plus a 1-in-100 tail, as a share of value, across time horizons.</p>"+
    "<p>This is the shape of table those frameworks ask for. Load a CLIMADA grid before using it for filing.</p>"},
  finsites:{t:"Most exposed sites",b:
    "<p>Sites ranked by total expected annual climate cost (direct plus business interruption plus heat) at the selected scenario, so capital and adaptation attention goes where the money is.</p>"},
  premium:{t:"Climate premium",b:
    "<p>The increase in expected annual cost from today to the selected future, the part of the bill that warming adds on top of present-day risk.</p>"+
    "<p>If the scenario selector is on present day, this compares against the mid-century pathway.</p>"},
  aggPeril:{t:"Cost by peril",b:
    "<p>The total expected annual cost split across all six perils. Each acute peril carries its own direct damage plus the business interruption it causes; heat carries its revenue-at-risk.</p>"+
    "<p>The shares add up to the same total as the cost-by-type view.</p>"},
  aggType:{t:"Cost by type",b:
    "<p>The same total split a second way: physical damage to buildings, business interruption while sites are closed, and heat's drag on operating profit.</p>"+
    "<p>Two lenses on one number, so you can see both what is at risk and why.</p>"},
  aggTraj:{t:"Trajectory",b:
    "<p>Expected annual cost today and under the selected pathway at 2050 and 2080. The rise is the climate signal, independent of any single year's weather.</p>"},
  aggBands:{t:"Portfolio risk mix",b:
    "<p>How many sites fall into each combined physical-risk band (all acute perils) at the selected scenario. A quick read on how concentrated the exposure is.</p>"},
  aggSites:{t:"Most exposed sites",b:
    "<p>The handful of sites carrying the most expected annual climate cost. Addressing the top of this list moves the portfolio number most.</p>"},
  aggBrand:{t:"By brand",b:
    "<p>Expected annual climate cost rolled up to each brand, so exposure can be owned and managed at the brand level.</p>"},
  riskMatrix:{t:"Portfolio risk matrix",b:
    "<p>One grid for the whole portfolio: each <b>row</b> is a site (or a brand), each <b>column</b> is a peril, and the last column is the combined physical risk. Every cell is coloured by its risk band, from Minimal to Severe, so hot spots jump out without reading a single number.</p>"+
    "<p>Read <b>across a row</b> for one site's full risk profile, or <b>down a column</b> to see which sites drive the portfolio's exposure to a single peril. Rows are ordered by combined expected annual cost, so the most exposed sit at the top.</p>"+
    "<p>The <b>View</b> control regroups the rows by site or by brand; the <b>Show</b> control switches each cell between percent of value, dollars per year, and the band name. Heat is a chronic indicator, so its cell is coloured but carries no dollar figure (its cost is on the Financial impact tab). Click any site row to open its scorecard.</p>",
    s:"A display lens only: the matrix reads the same per-site figures as every other tab and changes none of them."},
  riskValue:{t:"Risk vs value",b:
    "<p>The classic capital-allocation picture. Each bubble is a site, placed by its <b>asset value</b> (left to right) and its <b>expected annual cost as a share of that value</b> (bottom to top), and sized by the <b>dollars at risk each year</b>. Colour is the site's combined risk band.</p>"+
    "<p>The dashed lines split the portfolio into four quadrants: the vertical at the portfolio's median value, the horizontal at this app's Moderate-to-High band boundary. <b>Top right</b> is high value meeting high risk, where hardening usually pays back first; <b>top left</b> is smaller but exposed, often a transfer-or-harden call; <b>bottom right</b> is valuable but calmer, worth monitoring; <b>bottom left</b> is low on both, usually accepted.</p>"+
    "<p>Click any bubble to open that site's scorecard.</p>",
    s:"A display lens only: bubbles plot the same per-site figures shown elsewhere and change none of them."},
  tolerance:{t:"Risk tolerance",b:
    "<p>A risk tolerance is the line between <b>monitor</b> and <b>act</b>: how much expected loss the business is willing to carry before something has to change. The app never sets it for you. These three thresholds are yours to edit, and whatever you set becomes the documented basis for every breach flag in the app.</p>"+
    "<p>The defaults, and why: a site flags at <b>75 bps</b> (0.75% of its value in expected annual cost, this app's own boundary between the Moderate and High bands); the portfolio flags at <b>1.0%</b> of insured value (the middle of the published screening range this model is calibrated against); the tail flags when a 1-in-100 year would cost more than <b>10%</b> of portfolio value, a common capital stress screen.</p>"+
    "<p>Each breach is routed to a lane: <b>capex</b> when a measure at that site clears breakeven, <b>risk transfer or acceptance</b> when none does. Disclosure standards (IFRS S2) expect the entity to set and document its own materiality threshold; editing these numbers is exactly that act.</p>",
    s:"A policy layer only: thresholds flag numbers, they never change them."},
  quote:{t:"Broker quote vs technical premium",b:
    "<p>The <b>technical premium</b> is the transferred expected loss times the loading you set: the model's benchmark for what the configured layer is worth. Enter your broker's quoted annual premium and the app states the gap.</p>"+
    "<p>Read the gap as grounds for a conversation, not a verdict. A technical premium is a negotiation benchmark, not a market price: capacity cycles, terms, deductible structure, and the insurer's own model all move real quotes. When a results pack is loaded, the event-set benchmark is the stronger anchor because its loss curve is joint across sites rather than an approximation.</p>"+
    "<p>What moves quotes most is submission data quality: documented roof age, opening protection, and floor elevation routinely swing modeled pricing by double-digit percentages. That is what the broker evidence pack is for.</p>"},
  retention:{t:"Retention: which attachment to buy",b:
    "<p>Each row prices the same insurance structure at a different attachment point. Raising the attachment keeps more of the frequent losses in-house (the <b>retained below</b> column grows) and cuts the premium; the <b>cost of certainty</b> column is what you pay the insurer above the expected loss they take on.</p>"+
    "<p>There is no single right answer to optimize toward: with any loading above 1.0, insuring less always looks cheaper on average, because that is what loading means. What the table answers is what each step of volatility protection costs, so the attachment can be matched to how much loss the business can absorb in a bad year.</p>"+
    "<p>The retained-below figure is also the <b>working layer</b>: the expected annual loss a higher retention or a captive would need to fund.</p>"},
  queue:{t:"Action queue and funding cutline",b:
    "<p>Every site-and-measure pair the model finds in scope, ranked by benefit-cost ratio. With a program budget set, funding fills from the top: nothing below breakeven is funded, and what does not fit is kept on the list as unfunded rather than dropped, the same defer-not-delete discipline the pipeline's capital plan uses.</p>"+
    "<p>Rows are appraised one measure at a time. The program roll-up recomputes the funded set jointly per site, so overlapping measures are never double-counted; the joint figure is the one to quote.</p>"+
    "<p>When a CLIMADA results pack is loaded, its capital plan is the canonical appraisal (full event sets, refurbishment-window phasing) and is shown beside this interactive queue and included in the export. Measure costs here are planning-grade defaults until replaced with engineering estimates; the export carries the assumptions so every number can be traced.</p>"},
  decision:{t:"The decision view",b:
    "<p>One row per site, ranked: the landing artifact. Read a row left to right and you have the decision: <b>what drives the site</b> (its dominant peril by expected annual cost, business interruption and heat included), what a <b>1-in-100 year does to it in physical units</b> (dollars of damage, metres of flood depth at the structure, days of downtime), what it costs <b>every year</b> (EAD), the <b>best in-scope measure</b> with its benefit-cost ratio, and how much of the model is real data (<b>n of 6 perils modeled</b>).</p>"+
    "<p>Physical units lead; the qualitative bands stay on the ratings surfaces as the secondary read. Click any column header to re-rank, click a row to open the site's scorecard, where the <b>why-these-numbers trace</b> takes every figure back to its data source, one interaction away.</p>"+
    "<p>Per-site 1-in-100 figures assume that site's own 1-in-100 intensity; they are not addable into a portfolio tail (the results pack's joint event curve is the canonical tail).</p>",
    s:"A display ranking over the same pinned math as every other tab; it computes nothing new."},
  brokerPack:{t:"Broker evidence pack",b:
    "<p>A CSV built for the renewal submission: per site, the verified construction and protection attributes underwriters call secondary modifiers (roof type and year, opening protection, first-floor elevation, elevated equipment, defenses, wildfire attributes), plus this model's present-day damage view, so your broker can put a documented alternative view beside the insurer's model.</p>"+
    "<p>Documented attributes are the highest-return lever in renewal pricing: they change the insurer's modeled loss, not just the negotiation. Blank cells are honest blanks; fill them from surveys rather than guesses.</p>"+
    "<p>The modeled columns state their source (CLIMADA grid or interim screening model). Interim figures are for exploration; load a grid before putting these numbers in front of an underwriter.</p>"},
};
let _infoPop=null,_infoBtn=null;
function ensureInfoPop(){
  if(_infoPop)return _infoPop;
  _infoPop=document.createElement("div");
  _infoPop.className="infopop";_infoPop.setAttribute("role","dialog");_infoPop.setAttribute("aria-label","Explanation");
  document.body.appendChild(_infoPop);
  return _infoPop;
}
function showInfo(btn){
  const c=INFO[btn.dataset.info];if(!c)return;
  const pop=ensureInfoPop();
  pop.innerHTML='<button class="close" aria-label="Close explanation">&times;</button><h4>'+esc(c.t)+'</h4>'+c.b+(c.s?'<div class="src">'+c.s+'</div>':"");
  pop.classList.add("open");
  const r=btn.getBoundingClientRect();
  const pw=pop.offsetWidth,ph=pop.offsetHeight,vw=document.documentElement.clientWidth,vh=document.documentElement.clientHeight;
  let left=r.left+window.scrollX;
  left=Math.min(left,window.scrollX+vw-pw-10);left=Math.max(left,window.scrollX+8);
  let top=r.bottom+window.scrollY+6;
  if(r.bottom+ph+10>vh){ top=r.top+window.scrollY-ph-6; }        // flip above if no room below
  if(top<window.scrollY+6)top=window.scrollY+6;
  pop.style.left=left+"px";pop.style.top=top+"px";
  btn.setAttribute("aria-expanded","true");_infoBtn=btn;
  pop.querySelector(".close").onclick=()=>{hideInfo();btn.focus();};
}
function hideInfo(){ if(_infoPop)_infoPop.classList.remove("open"); if(_infoBtn){_infoBtn.setAttribute("aria-expanded","false");_infoBtn=null;} }
function infoBtn(key,dark){ return '<button type="button" class="info'+(dark?" on-dark":"")+'" data-info="'+key+'" aria-label="How this is calculated" aria-expanded="false">i</button>'; }
function wireInfo(){
  document.addEventListener("click",e=>{
    const b=e.target.closest(".info");
    if(b){ e.preventDefault();e.stopPropagation(); if(_infoBtn===b){hideInfo();} else {hideInfo();showInfo(b);} return; }
    if(_infoPop&&!e.target.closest(".infopop"))hideInfo();
  });
  document.addEventListener("keydown",e=>{ if(e.key==="Escape"&&_infoBtn){const b=_infoBtn;hideInfo();b.focus();} });
  window.addEventListener("scroll",()=>{ if(_infoBtn)hideInfo(); },true);
  window.addEventListener("resize",()=>{ if(_infoBtn)hideInfo(); });
}

/* ---- map (degrades gracefully if Leaflet CDN or tiles are blocked) ---- */
let map, markers=[], mapOk=false, _lastFitKey="";
function showMapUnavailable(){
  const el=document.getElementById("map");
  el.style.height="auto";el.style.minHeight="0";el.style.padding="16px 18px";
  el.style.display="flex";el.style.alignItems="center";el.style.justifyContent="center";
  el.style.background="#eef2f1";el.style.borderBottom="1px solid var(--line)";
  el.innerHTML='<div style="color:#43535F;font-size:13px;text-align:center">Map is unavailable on this network. Every analysis below is fully functional without it.</div>';
}
function initMap(){
  if(typeof L==="undefined"){ showMapUnavailable(); return; }
  try{
    /* Voyager basemap (roads, water, terrain tinting) reads like a consumer
       map product; zoom sits bottom-right so the executive panel never
       covers it. Falls back exactly as before when tiles are unreachable. */
    map=L.map("map",{scrollWheelZoom:true,zoomControl:false}).setView([27,-84],4);
    L.control.zoom({position:"bottomright"}).addTo(map);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
      {attribution:"&copy; OpenStreetMap &copy; CARTO",subdomains:"abcd",maxZoom:19}).addTo(map);
    map.on("click",e=>{ openAdd(e.latlng.lat,e.latlng.lng); });
    mapOk=true;
  }catch(err){ showMapUnavailable(); }
}
/* Band fills darkened in step with the --r-* CSS variables so white text on
   any band clears 3:1; the band NAME always rides beside the colour. */
const BAND_COLOR={Minimal:"#6E8494",Low:"#2E8B6F",Moderate:"#B07B10",High:"#C05F17",Severe:"#B23A32"};
/* SVP review: what a map marker is coloured by (the map's "change views" lens).
   Pure, so the node tests can pin the two new modes. "peril" keeps the legacy
   behaviour (the selected peril's band); "combined" uses the all-perils band;
   "dominant" uses the leading peril's own colour. */
function markerFill(r,mode,sc,perilBand){
  if(mode==="combined")return BAND_COLOR[scorePhysTotal([r],sc).rows[0].band];
  if(mode==="dominant"){let best=null,bv=-1;for(const hz of ACUTE){const e=hzSite(r,hz,sc).ead;if(e>bv){bv=e;best=hz;}}return (bv>0&&best)?HAZARD_BY[best].color:BAND_COLOR.Minimal;}
  return BAND_COLOR[perilBand!=null?perilBand:hzSite(r,activeHazard,sc).band];
}
let legendCtl=null;
function updateLegend(){
  if(!mapOk)return;
  if(legendCtl){try{map.removeControl(legendCtl);}catch(e){}}
  legendCtl=L.control({position:"bottomright"});
  legendCtl.onAdd=function(){
    const d=L.DomUtil.create("div","maplegend");
    const mode=ui.views.mapColor;
    if(mode==="dominant"){
      d.innerHTML='<div class="lh">Dominant peril</div>'+
        ACUTE.map(hz=>'<span class="li"><i style="background:'+HAZARD_BY[hz].color+'"></i>'+HAZARD_LABEL[hz]+'</span>').join("");
    }else{
      const title=(mode==="combined")?"Combined risk":(HAZARD_LABEL[activeHazard]+" rating");
      const bands=["Minimal","Low","Moderate","High","Severe"];
      d.innerHTML='<div class="lh">'+title+'</div>'+
        bands.map(b=>'<span class="li"><i style="background:'+BAND_COLOR[b]+'"></i>'+b+'</span>').join("");
    }
    /* Task 6: the confidence key, in every colour mode */
    d.innerHTML+='<div class="lh" style="margin-top:6px">Model basis</div>'+
      '<span class="li"><span class="mono" style="font-weight:600">n/6</span>&nbsp;perils modeled at the site</span>'+
      '<span class="li"><i style="background:#fff;border:2px dashed #43535F"></i>any peril degraded</span>';
    return d;
  };
  legendCtl.addTo(map);
}
function syncBrandFilter(rows){
  const sel=document.getElementById("brandSel"); if(!sel)return;
  const brands=[];rows.forEach(r=>{const b=r.brand||"Unbranded";if(brands.indexOf(b)<0)brands.push(b);});
  brands.sort();
  const key=brands.join("|");
  if(key!==_lastBrandKey){
    _lastBrandKey=key;
    if(brandFilter&&brands.indexOf(brandFilter)<0)brandFilter="";
    sel.innerHTML='<option value="">All brands</option>'+brands.map(b=>'<option value="'+esc(b)+'">'+esc(b)+'</option>').join("");
    sel.value=brandFilter;
  }
}
function drawMarkers(scored){
  syncBrandFilter(scored.rows);
  if(!mapOk)return;
  markers.forEach(m=>map.removeLayer(m));markers=[];
  // one marker per PHYSICAL site: records sharing a site_id (or, absent that,
  // exact coordinates) are aggregated, so an HOA record and a TNL record at the
  // same campus draw a single marker sized by the site's total value, with a
  // named-insured breakout in the popup. A portfolio with no site_id and
  // distinct coordinates draws one marker per record, exactly as before.
  const recs=brandFilter?sites.filter(r=>(r.brand||"Unbranded")===brandFilter):sites;
  const groups=siteGroups(recs).map(g=>scoreGroup(g,scenario));
  if(!groups.length){_lastFitKey="";updateLegend();return;}
  const heat=activeHazard==="heat";
  const maxV=Math.max.apply(null,groups.map(g=>g.value))||1;
  const colorMode=ui.views.mapColor;
  groups.forEach(g=>{
    const rad=7+16*Math.sqrt(Math.max(g.value,0)/maxV);
    const activeEad=g.perHaz[activeHazard]||0, activePct=g.value?activeEad/g.value*100:0;
    const activeBand=heat?heatBand(g.heatDays):bandOf(activePct);
    /* Task 6: confidence ON the marker, not only in chip colour. A fully
       modeled site keeps the solid white ring; any degraded peril switches
       the ring to dashed slate, and every marker carries a permanent n/6
       text badge, so the model basis reads at a glance (and survives
       greyscale printing and colour-blind palettes). */
    const tr=groupTrust(g,scenario);
    const full=tr.modeled===tr.total;
    const m=L.circleMarker([g.latitude,g.longitude],{
      radius:rad,color:full?"#fff":"#43535F",weight:full?1.5:2,dashArray:full?null:"3 3",
      fillColor:groupMarkerFill(g,colorMode,activeHazard),fillOpacity:.85
    }).addTo(map);
    m.bindTooltip(tr.modeled+"/"+tr.total,{permanent:true,direction:"right",
      offset:[rad-2,0],className:"trustbadge"+(full?"":" degraded")});
    const metric=heat ? g.heatDays+" days &gt;32&deg;C"
                      : fmt$(activeEad)+"/yr &middot; "+activePct.toFixed(2)+"%";
    const targetId=tr.target.id;
    const breakout=g.multi
      ? "<div style='margin-top:5px;border-top:1px solid #E3E8E5;padding-top:5px'><b>Named insured</b> ("+g.byInsured.length+")"+
        g.byInsured.map(r=>"<br>"+esc(r.insured)+": "+fmt$(r.value)+" val &middot; "+fmt$(r.ead)+"/yr ("+r.share.toFixed(0)+"%)").join("")+"</div>"
      : (insuredOf(g.members[0])!=="Unspecified"?"<br><span class='mono'>Named insured: "+esc(insuredOf(g.members[0]))+"</span>":"");
    m.bindPopup("<b>"+esc(g.name)+"</b>"+(g.multi?" <span class='mono'>("+g.members.length+" insured groups)</span>":"")+"<br>"+esc(g.brand||"")+
      "<br><span class='mono'>Site value "+fmt$(g.value)+"</span>"+
      "<br><span class='mono'>"+HAZARD_LABEL[activeHazard]+" &middot; "+metric+" &middot; "+activeBand+"</span>"+
      "<br><span class='mono'>Model basis: "+tr.modeled+" of "+tr.total+" perils modeled"+
        (tr.degraded.length?" &middot; degraded: "+esc(tr.degraded.join(", ")):"")+"</span>"+
      breakout+
      "<br><button class='lightbtn' style='margin-top:6px' onclick='openScorecard("+(+targetId)+")'>Open scorecard</button>");
    /* In the executive home the analyst tabs are hidden, so a marker click
       keeps you on the map (the popup's scorecard button is the drill-down);
       in the analyst workspace it jumps to the Sites tab as it always has. */
    m.on("click",()=>{ selectedId=targetId; if(!(ui&&ui.execMode)){ switchTab("sites"); renderSites(); } });
    markers.push(m);
  });
  updateLegend();
  // only re-frame the map when the set of physical sites changes, not on every recompute
  const key=groups.map(g=>g.key).sort().join(",");
  if(key!==_lastFitKey){ try{ map.fitBounds(L.featureGroup(markers).getBounds().pad(0.25)); }catch(e){} _lastFitKey=key; }
}

/* ---- SVG helpers ---- */
function svgEl(w,h){return '<svg viewBox="0 0 '+w+' '+h+'" width="100%" height="'+h+'" preserveAspectRatio="xMidYMid meet">';}
function epCurveSvg(rpLoss){
  const W=460,H=210,pad=44;
  const xs=RPS.map(rp=>Math.log(rp));
  const xmin=Math.min.apply(null,xs),xmax=Math.max.apply(null,xs);
  const vals=RPS.map(rp=>rpLoss[rp]);const ymax=Math.max(1,Math.max.apply(null,vals));
  const X=lx=>pad+(lx-xmin)/(xmax-xmin)*(W-pad-14);
  const Y=v=>H-30-(v/ymax)*(H-30-14);
  let s=svgEl(W,H);
  [0,.25,.5,.75,1].forEach(t=>{const y=Y(t*ymax);s+='<line x1="'+pad+'" y1="'+y+'" x2="'+(W-14)+'" y2="'+y+'" stroke="#EEF0EC"/>';
    s+='<text x="'+(pad-6)+'" y="'+(y+3)+'" text-anchor="end" font-size="10" fill="#7A8893">'+fmt$(t*ymax)+'</text>';});
  let path="";RPS.forEach((rp,i)=>{path+=(i?"L":"M")+X(Math.log(rp))+" "+Y(rpLoss[rp])+" ";});
  s+='<path d="'+path+'" fill="none" stroke="#0F3A4B" stroke-width="2.5"/>';
  RPS.forEach(rp=>{s+='<circle cx="'+X(Math.log(rp))+'" cy="'+Y(rpLoss[rp])+'" r="3.5" fill="#12586F"/>';
    s+='<text x="'+X(Math.log(rp))+'" y="'+(H-12)+'" text-anchor="middle" font-size="10" fill="#7A8893">'+rp+'</text>';});
  s+='<text x="'+(W/2)+'" y="'+(H-1)+'" text-anchor="middle" font-size="10" fill="#43535F">Return period (years)</text>';
  s+="</svg>";return s;
}
function barsSvg(items,valKey,labKey,color){
  const W=460,rowH=30,H=items.length*rowH+14;const max=Math.max(1,Math.max.apply(null,items.map(i=>i[valKey])));
  const lab=140;let s=svgEl(W,H);
  items.forEach((it,i)=>{const y=i*rowH+10;const w=(it[valKey]/max)*(W-lab-70);
    const full=String(it[labKey]);
    s+='<text x="0" y="'+(y+13)+'" font-size="11.5" fill="#43535F">'+esc(full.slice(0,24))+'<title>'+esc(full)+'</title></text>';
    s+='<rect x="'+lab+'" y="'+y+'" width="'+Math.max(w,1)+'" height="17" rx="3" fill="'+color+'"><title>'+esc(full)+': '+fmt$(it[valKey])+'</title></rect>';
    s+='<text x="'+(lab+w+6)+'" y="'+(y+13)+'" font-size="11" fill="#15202B" class="mono">'+fmt$(it[valKey])+'</text>';});
  s+="</svg>";return s;
}
function countBarsSvg(items,valKey,labKey,color,suffix){
  suffix=suffix||"";
  const W=460,rowH=26,H=items.length*rowH+14;const max=Math.max(1,Math.max.apply(null,items.map(i=>i[valKey])));
  const lab=150;let s=svgEl(W,H);
  items.forEach((it,i)=>{const y=i*rowH+8;const w=(it[valKey]/max)*(W-lab-56);
    const full=String(it[labKey]);
    s+='<text x="0" y="'+(y+13)+'" font-size="11" fill="#43535F">'+esc(full.slice(0,24))+'<title>'+esc(full)+'</title></text>';
    s+='<rect x="'+lab+'" y="'+y+'" width="'+Math.max(w,1)+'" height="15" rx="3" fill="'+color+'"><title>'+esc(full)+': '+Math.round(it[valKey])+suffix+'</title></rect>';
    s+='<text x="'+(lab+w+6)+'" y="'+(y+12)+'" font-size="11" fill="#15202B" class="mono">'+Math.round(it[valKey])+suffix+'</text>';});
  s+="</svg>";return s;
}
function median(a){ if(!a.length)return 0; const s=a.slice().sort((x,y)=>x-y),m=s.length>>1; return s.length%2?s[m]:(s[m-1]+s[m])/2; }
/* SVP review: risk-vs-value quadrant. X = asset value, Y = expected annual cost
   as a share of value, bubble area tracks EAD dollars, colour is the combined
   band. The dashed dividers (median value, and the Moderate/High band boundary)
   split the portfolio into the classic capital-allocation quadrants. A bubble
   click opens the site scorecard, the same as the map and the matrix. Pure over
   its inputs: it plots figures the engine already computed, changing none. */
function quadrantSvg(pts){
  const W=480,H=300,padL=54,padR=16,padT=20,padB=44;
  if(!pts.length)return svgEl(W,H)+"</svg>";
  const xmax=(Math.max.apply(null,pts.map(p=>p.value))*1.06)||1;
  const ymax=Math.max(0.6,Math.max.apply(null,pts.map(p=>p.eadPct))*1.12);
  const rmax=Math.max.apply(null,pts.map(p=>p.ead))||1;
  const xDiv=median(pts.map(p=>p.value)), yDiv=0.75;
  const X=v=>padL+(v/xmax)*(W-padL-padR);
  const Y=v=>H-padB-(v/ymax)*(H-padB-padT);
  const R=e=>5+15*Math.sqrt(Math.max(e,0)/rmax);
  let s=svgEl(W,H);
  [0,.25,.5,.75,1].forEach(t=>{const yv=t*ymax,y=Y(yv);
    s+='<line x1="'+padL+'" y1="'+y+'" x2="'+(W-padR)+'" y2="'+y+'" stroke="#EEF0EC"/>';
    s+='<text x="'+(padL-6)+'" y="'+(y+3)+'" text-anchor="end" font-size="9.5" fill="#7A8893">'+yv.toFixed(1)+'%</text>';});
  [0.5,1].forEach(t=>{const xv=t*xmax,x=X(xv);
    s+='<text x="'+x+'" y="'+(H-padB+14)+'" text-anchor="middle" font-size="9.5" fill="#7A8893">'+fmt$(xv)+'</text>';});
  s+='<line x1="'+X(xDiv)+'" y1="'+padT+'" x2="'+X(xDiv)+'" y2="'+(H-padB)+'" stroke="#CBD3CE" stroke-dasharray="4 3"/>';
  if(yDiv<ymax)s+='<line x1="'+padL+'" y1="'+Y(yDiv)+'" x2="'+(W-padR)+'" y2="'+Y(yDiv)+'" stroke="#CBD3CE" stroke-dasharray="4 3"/>';
  const tag=(x,y,anc,txt)=>'<text x="'+x+'" y="'+y+'" text-anchor="'+anc+'" font-size="9.5" fill="#9AA7A0" font-style="italic">'+txt+'</text>';
  s+=tag(W-padR-2,padT+11,"end","protect first")+tag(padL+2,padT+11,"start","harden / transfer")+
     tag(W-padR-2,H-padB-5,"end","monitor")+tag(padL+2,H-padB-5,"start","accept");
  pts.slice().sort((a,b)=>b.ead-a.ead).forEach(p=>{
    s+='<circle cx="'+X(p.value).toFixed(1)+'" cy="'+Y(Math.min(p.eadPct,ymax)).toFixed(1)+'" r="'+R(p.ead).toFixed(1)+'" fill="'+BAND_COLOR[p.band]+'" fill-opacity="0.72" stroke="#fff" stroke-width="1.2" style="cursor:pointer" onclick="openScorecard('+(+p.id)+')"><title>'+esc(p.name)+' · '+fmt$(p.value)+' value · '+p.eadPct.toFixed(2)+'% cost · '+fmt$(p.ead)+'/yr · '+p.band+'</title></circle>';});
  s+='<text x="'+((padL+W-padR)/2)+'" y="'+(H-4)+'" text-anchor="middle" font-size="10" fill="#43535F">Asset value</text>';
  const ymid=(padT+H-padB)/2;
  s+='<text x="14" y="'+ymid+'" text-anchor="middle" font-size="10" fill="#43535F" transform="rotate(-90 14 '+ymid+')">Annual cost, % of value</text>';
  s+="</svg>";return s;
}

/* ============================================================
   Rendering
   ============================================================ */
