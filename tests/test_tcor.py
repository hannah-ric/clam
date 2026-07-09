"""
test_tcor.py : functional tests for the TCOR engine and loss-run calibration
(overhaul Tasks 1, 2, 5), run against the app's REAL inline JavaScript under
node, exactly like test_frontend.py (everything up to the end of restore()).

The one test that matters most: six sites in one campus hit by one modeled
hurricane retain ONE shared per-occurrence deductible, never six.

Usage:  python tests/test_tcor.py app/Resort_Climate_Risk_Explorer_v210.html
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

STUBS = """
const _els={};
function _mkEl(){return {classList:{_s:new Set(),add(c){this._s.add(c)},remove(c){this._s.delete(c)},contains(c){return this._s.has(c)}},
  style:{},innerHTML:"",textContent:"",title:"",value:"",addEventListener(){},onclick:null,appendChild(){},querySelectorAll:()=>[]};}
const document={createElement:()=>_mkEl(),body:{appendChild(){}},
  getElementById:id=>(_els[id]||(_els[id]=_mkEl())),querySelectorAll:()=>[],
  addEventListener(){},documentElement:{clientWidth:1000,clientHeight:800}};
const window={scrollX:0,scrollY:0,addEventListener(){}};
const navigator={};
const _ls={};
const localStorage={getItem:k=>(k in _ls?_ls[k]:null),setItem(k,v){_ls[k]=String(v);},removeItem(k){delete _ls[k];}};
"""

TESTS = r"""
function assert(c,m){ if(!c){ console.error("FAIL: "+m); process.exit(1);} console.log("ok  "+m); }
function near(a,b,tol){ return Math.abs(a-b)<=(tol==null?0.01:tol); }
render=()=>{};
let _lastToast=""; toast=m=>{_lastToast=String(m);};

/* ---------------- fixture: six-site campus + two singles -------------- */
const F={rps:[2,5,10,25,50,100,250,500]};
sites=[];nextId=1;
const mk=(name,extra)=>Object.assign({name,brand:"Club W",latitude:28.4,longitude:-81.5,
  asset_value_usd:10e6},extra||{});
addSites([
  mk("Orlando One",{campus_code:"ORL01"}),
  mk("Orlando Two",{campus_code:"ORL01"}),
  mk("Orlando Three",{campus_code:"ORL01"}),
  mk("Orlando Four",{campus_code:"ORL01"}),
  mk("Orlando Five",{campus_code:"ORL01"}),
  mk("Orlando Six",{campus_code:"ORL01"}),
  mk("Miami Solo",{campus_code:"MIA01",latitude:25.8,longitude:-80.2,premium_annual_usd:50000}),
  mk("Inland Free",{latitude:33.7,longitude:-84.4})
]);
const S=sites.slice();

/* a synthetic results pack: per_site joins by name; one hurricane source;
   flood ladders with a busy frequent band; other perils quiet */
const NAMES=S.map(s=>s.name);
const zeroRow=[0,0,0,0,0,0,0,0];
const floodRow=[20000,40000,60000,80000,100000,120000,150000,200000];
const packSites=NAMES.map(n=>({name:n,direct_ead_usd:0}));
resultsPack={name:"synthetic.json",data:{
  kind:"results_pack",pack_version:1,
  sites:{count:NAMES.length},
  scenarios:{present:{portfolio:{direct_aal_usd:0,ep_usd:{}},per_site:packSites}},
  event_sets:{floor_usd:1000,scenarios:{present:[
    {source:"present",weight:1.0,country:"USA",events:[
      {id:"HELENE",freq:0.01,sites:[[0,400000],[1,400000],[2,400000],[3,400000],[4,400000],[5,400000]]},
      {id:"IAN",freq:0.005,sites:[[0,200000],[1,200000],[2,200000],[6,900000]]},
      {id:"SMALLTS",freq:0.5,sites:[[0,30000]]}
    ]}
  ]}},
  frequent_losses:{ladder_rps:F.rps,scenarios:{present:{
    tc_joint:S.map((_,i)=>i<7?[0,0,0,100000,300000,800000,2000000,4000000]:zeroRow),
    rflood:S.map((_,i)=>i<6?floodRow.slice():zeroRow),
    prain:S.map(()=>zeroRow.slice()),
    wfire:S.map(()=>zeroRow.slice())
  }}}
}};

/* ---------------- Task 1+2: the aggregation rule ---------------------- */
const join=packJoin(S,"present");
assert(join&&join.matched===8,"packJoin joins all 8 pack rows by name");
const resolve=idx=>{const s=join.map[idx];return s?{id:s.id,campus:campusKeyOf(s)}:null;};

/* THE acceptance test: one event, six same-campus sites, ONE deductible */
const one={weight:1,events:[{id:"HELENE",freq:1,sites:[[0,400000],[1,400000],[2,400000],[3,400000],[4,400000],[5,400000]]}]};
const rShared=eventRetained([one],resolve,1000000,"per-occurrence-campus");
assert(near(rShared.annualRetained,1000000),
  "six sites hit by ONE hurricane retain ONE shared 1M deductible (got "+rShared.annualRetained+")");
assert(rShared.annualRetained!==6*Math.min(400000,1000000),
  "shared retained is NOT the sum of six per-site deductible applications (2.4M)");
assert(near(rShared.annualGross,2400000)&&near(rShared.annualTransferred,1400000),
  "gross 2.4M = retained 1.0M + transferred 1.4M at event level");
let alloc=0;for(const k in rShared.perSite)alloc+=rShared.perSite[k].retained;
assert(near(alloc,1000000,1),"per-site allocations sum back to the event-level retained");

/* two campuses: each retains its own occurrence deductible */
const two={weight:1,events:[{id:"X",freq:1,sites:[[0,600000],[1,600000],[6,1500000]]}]};
const rTwo=eventRetained([two],resolve,1000000,"per-occurrence-campus");
assert(near(rTwo.annualRetained,1000000+1000000),
  "two campuses hit by one storm: min(1.2M,1M)+min(1.5M,1M)=2M");
const rProg=eventRetained([two],resolve,1000000,"per-occurrence-program");
assert(near(rProg.annualRetained,1000000),
  "program basis: one deductible per occurrence across everything");

/* unjoined pack rows surface as unjoinedLoss, never silently vanish */
const rGhost=eventRetained([{weight:1,events:[{id:"G",freq:1,sites:[[99,5000000]]}]}],
  resolve,1000000,"per-occurrence-campus");
assert(rGhost.annualRetained===0&&near(rGhost.unjoinedLoss,5000000),
  "an unjoinable site index lands in unjoinedLoss, flagged not dropped");

/* ---------------- ladder math (per-location deductibles) -------------- */
const lr100=ladderRetained(F.rps,floodRow,100000);
assert(near(lr100.retained,22000,1),"flood ladder retained at 100k deductible integrates to 22,000/yr");
assert(near(lr100.gross,22660,1),"flood ladder gross integrates to 22,660/yr");
assert(lr100.hitFreq===0.5,"any-loss hit frequency reads the 1-in-2 rung");
assert(lr100.fullDedFreq===0.02,"full-deductible frequency reads the 1-in-50 rung");
const lr50=ladderRetained(F.rps,floodRow,50000);
assert(lr50.retained<lr100.retained,"a lower deductible retains less");

/* ---------------- retained property + attritional --------------------- */
const prop=retainedPropertyCalc(S,"present");
assert(prop.classes.hurricane.basis==="event","hurricane retained uses the EVENT table when a pack is loaded");
/* hand check: HELENE min(2.4M,1M)*0.01 + IAN (ORL 600k + MIA min(900k,1M))*0.005 + SMALLTS min(30k,1M)*0.5 */
const wantHu=0.01*1000000+0.005*(600000+900000)+0.5*30000;
assert(near(prop.classes.hurricane.annualRetained,wantHu,1),
  "hurricane annual retained matches the hand-computed event sum ("+wantHu+")");
assert(near(prop.classes.flood.annualRetained,6*22000,5),
  "flood retained sums per location across the six laddered sites");
assert(prop.attritional.frequentBandRetained>0,
  "the attritional layer integrates the 1-in-10-and-more-frequent band");
assert(near(prop.attritional.frequentHitsPerYear,6*0.5,0.01),
  "frequent deductible hits count across sites (six sites at 1-in-2)");
assert(prop.attritional.hurricaneOccurrencesPerYear>0.5,
  "hurricane occurrences with retained loss ride along in the summary");
let siteSum=0;S.forEach(s=>{const p=prop.perSite[s.id];siteSum+=p.hurricane.retained+p.flood.retained+p.general.retained;});
assert(near(siteSum,prop.total.annualRetained,5),
  "per-site retained rows reconcile with the portfolio total");

/* ---------------- BI module (Task 3): terms, downtime, seasonality ---- */
/* the terms math is unchanged in structure: on a flat season at full
   damage the split reproduces the pinned pre-module numbers exactly */
const econF={value:10e6,dailyLossable:1000,maxDownDays:365,shape:BI_SEASON_SHAPES.global_mean};
const terms={waitingDays:3,indemnityDays:365,limitUsd:100000};
const bs=biEventSplit(10e6,terms,econF,0);
assert(near(bs.gross,365000)&&near(bs.waiting,3000)&&near(bs.overage,262000)
  &&near(bs.retained,265000),
  "BI terms: waiting 3k + beyond-limit 262k of a 365k gross BI event (flat season, full damage)");

/* damage-to-downtime: Hazus nodes + REDi impeding floor */
assert(biDowntimeDays(0,365)===0,"zero damage means zero downtime");
assert(near(biDowntimeDays(0.02,365),0.03*365,0.1),
  "2% damage is cleanup, ~11 days (Hazus slight)");
assert(biDowntimeDays(0.10,365)===120,
  "10% damage trips the 120-day REDi impeding floor (curve alone would say ~33)");
assert(near(biDowntimeDays(0.40,365),0.75*365,0.1),
  "40% damage runs most of the reconstruction year (Hazus extensive)");
assert(near(biDowntimeDays(1,365),365),"full damage anchors to the operator's reopen time");
assert(biDowntimeDays(0.05,365)<biDowntimeDays(0.10,365),
  "downtime is monotone in damage");

/* seasonality: the walk conserves the year (mean weight 1.0) and prices
   a September Caribbean closure below flat, a winter one above */
const CAR=BI_SEASON_SHAPES.caribbean;
assert(near(biSeasonDays(CAR,0,365.28),365.28,0.5),
  "a full-year walk is season-neutral (weights are mean 1.0)");
assert(biSeasonDays(CAR,8,91)<91*0.75,
  "a 3-month September closure in the Caribbean loses well under flat revenue");
assert(biSeasonDays(CAR,0,91)>91*1.2,
  "a 3-month January closure loses well over flat revenue");
/* the honesty gap the module closes: a September landfall with a long
   rebuild eats the winter peak, so downtime cost is NOT linear in days */
assert(biSeasonDays(CAR,8,270)>2.4*biSeasonDays(CAR,8,90),
  "extending a September closure into the high season more than triples its cost");

/* timeshare: the continuing fee stream shrinks the lossable daily GOP */
const eHot=biEconOf({asset_value_usd:10e6,latitude:18.3,longitude:-64.9});
const eVo=biEconOf({asset_value_usd:10e6,latitude:18.3,longitude:-64.9,timeshare_share:1});
assert(near(eVo.dailyLossable,eHot.dailyLossable*(1-BI_TIMESHARE_CONTINUING),0.01),
  "a pure vacation-ownership site keeps the registry's continuing share flowing");
assert(eHot.continueShare===0,"a site with no timeshare_share loses all revenue (today's behavior)");

const biAll=retainedBICalc(S,"present");
assert(biAll.retained>0&&biAll.waiting>0,"portfolio retained BI carries a waiting-period piece");
assert(near(biAll.retained,biAll.waiting+biAll.overage,1),"retained BI = waiting + overage exactly");
assert(biAll.basis.indexOf("BI module")>=0&&biAll.basis.indexOf("per event")>=0,
  "the BI module states its basis and applies hurricane terms per event when the table is loaded");
assert(biAll.demandShock&&biAll.demandShock.excludedFromTotal===true,
  "the regional demand shock is flagged and excluded from the total by construction");

/* ---------------- premium: actual first, technical benchmark ---------- */
const prem=premiumCalc(S,"present",prop,biAll);
assert(prem.perSite[S[6].id].allocated===50000&&prem.perSite[S[6].id].basis.indexOf("actual")>=0,
  "a site with premium on file uses the actual figure");
assert(prem.perSite[S[0].id].basis.indexOf("technical")>=0&&prem.perSite[S[0].id].allocated>0,
  "sites without an actual premium carry the labeled technical benchmark");
tcorProgram.premium.programAnnualUsd=400000;
const prem2=premiumCalc(S,"present",prop,biAll);
assert(near(prem2.allocatedTotal,400000,1),
  "a known program total allocates fully (actual + rescaled technical)");
tcorProgram.premium.programAnnualUsd=null;

/* ---------------- the TCOR spine (Task 1) ----------------------------- */
const port=tcorPortfolio(S,"present");
const c=port.components;
assert(near(port.total,c.retainedProperty+c.retainedBI+c.premium+c.mitigation+c.admin,1),
  "TCOR is exactly the five-part sum");
assert(port.indirect.excludedFromTotal===true&&port.indirect.value>0,
  "indirect cost is a flagged estimate OUTSIDE the total");
assert(near(c.retainedProperty,prop.total.annualRetained,1),
  "portfolio retained property comes from the event-level engine, not a column total");
const rowSum=port.rows.reduce((a,r)=>a+r.total,0);
assert(near(rowSum,port.total,5),"per-site TCOR rows reconcile with the portfolio TCOR");
const r0=port.rows[0];
assert(r0.quality.propertyBasis==="event"&&r0.components.retainedBI.basis.indexOf("BI module")>=0,
  "every component carries its basis; quality marks the fallbacks");
assert(port.rows.every(r=>r.quality.estimate===true),
  "with default BI terms the TCOR is marked an estimate, never precise");
assert(near(port.waterfall.gross-port.waterfall.transferredProperty-port.waterfall.transferredBI,
  c.retainedProperty+c.retainedBI,5),
  "waterfall reconciles: gross minus transferred equals retained");

/* ---------------- aggregate cap + seeded simulation ------------------- */
const sim1=simulateRetainedYears(S,"present",{years:400,seed:7});
const sim2=simulateRetainedYears(S,"present",{years:400,seed:7});
assert(sim1.mean===sim2.mean&&sim1.p99===sim2.p99,"the year simulation is seed-deterministic");
assert(sim1.basis.indexOf("event table")>=0,"simulation replays the event table when loaded");
/* Task 3: the bad year carries BI jointly, not at expected level */
assert(sim1.bi&&sim1.combined&&sim1.bi.p99>0,
  "the simulation carries a per-year retained-BI distribution");
assert(sim1.combined.p99>=sim1.p99,
  "the combined p99 dominates property alone (BI is non-negative in every year)");
assert(near(sim1.combined.mean,sim1.mean+sim1.bi.mean,1),
  "combined years are the same-year sums: the means are exactly additive");
assert(sim1.bi.p99===sim2.bi.p99&&sim1.combined.p99===sim2.combined.p99,
  "the BI side of the simulation is seed-deterministic too");
tcorProgram.aggregateCapUsd=150000;
const simCap=simulateRetainedYears(S,"present",{years:400,seed:7});
assert(simCap.p99<=150000.0001&&simCap.mean<=sim1.mean+0.0001,
  "the annual aggregate cap bounds every simulated year");
tcorProgram.aggregateCapUsd=null;

/* ---------------- degraded path: no pack ------------------------------ */
resultsPack=null;clearHazCache();
const propD=retainedPropertyCalc(S,"present");
assert(propD.classes.hurricane.basis.indexOf("approximation")>=0,
  "without an event table the hurricane basis says APPROXIMATION");
assert(propD.basisFlags.length>0,"degraded bases are flagged, not silent");
assert(isFinite(propD.total.annualRetained)&&propD.total.annualRetained>=0,
  "degraded path still yields finite figures");
const portD=tcorPortfolio(S,"present");
assert(portD.estimate===true&&portD.rows[0].quality.propertyBasis!=="event",
  "a TCOR built on fallbacks is marked as an estimate");
/* sharing still holds approximately: same-campus sites share one deductible
   on the comonotonic campus ladder, so retained < the own-unit sum */
const sOwn=S.map(s=>Object.assign({},s));sOwn.forEach(s=>delete s.campus_code);
const propOwn=retainedPropertyCalc(sOwn,"present");
assert(propD.classes.hurricane.annualRetained<=propOwn.classes.hurricane.annualRetained+1,
  "campus sharing never retains MORE than per-site units");
assert(propOwn.basisFlags.some(f=>f.indexOf("campus")>=0),
  "missing campus codes are flagged as overstating retained hurricane loss");

/* ---------------- Task 5: loss run ------------------------------------ */
resultsPack=null;
const LR_CSV=[
"Claim Number,Date of Loss,Claimant Name,Coverage Major,Status,TPA/Carrier,Net Paid,Net Outstanding,Recovery Received,Net Incurred,Area of Impact,Event Description",
'1001,2021-09-10,Orlando One,Named Storm - Wind,Closed,Sedgwick,"$400,000",0,"$50,000","$350,000",Roof,Hurricane Zeta roof damage',
'1002,2021-09-11,Orlando Two,Named Storm - Wind,Closed,Sedgwick,"$200,000",0,0,"$200,000",Facade,Hurricane Zeta wind damage',
'1003,2021-09-12,Miami Solo,Named Storm - Wind,Open,Sedgwick,"$100,000","$150,000",0,"$250,000",Pool,Hurricane Zeta storm surge',
'1004,2022-06-01,Orlando One,Flood,Closed,Sedgwick,"$80,000",0,0,"$80,000",Garage,Summer storm flooding',
'1005,2022-06-02,Orlando Three,Flood,Closed,Sedgwick,"$60,000",0,0,"$60,000",Lobby,Same storm flooding lobby',
'1006,2022-06-20,Orlando Three,Flood,Closed,Sedgwick,"$30,000",0,0,"$30,000",Lobby,Separate June storm',
'1007,2023-01-15,Orlando Four,Business Interruption,Open,Sedgwick,"$20,000","$40,000",0,"$60,000",Operations,Chiller failure closed tower',
'1008,2023-03-05,Mystery Villas,Fire,Closed,Sedgwick,"$45,000",0,0,"$45,000",Kitchen,Kitchen fire',
'1009,2023-04-01,Orlando Five,Crime,Closed,Sedgwick,"$10,000",0,0,"$10,000",Office,Theft (not a CLAM peril)'
].join("\n");
loadLossRun(LR_CSV,"loss_run.csv");
assert(lossRun&&lossRun.claims.length===9,"loss run ingests 9 claims (money with $ and commas parsed)");
assert(lossRun.years.min===2021&&lossRun.years.max===2023&&lossRun.years.n===3,
  "the record spans 2021-2023 (3 years)");
assert(lossRun.flags.some(f=>f.indexOf("open claim")>=0),
  "open claims are flagged as developing at ingest");

const evs=groupClaimEvents(lossRun.claims,S);
const zeta=evs.find(e=>e.key.indexOf("storm:zeta")===0);
assert(zeta&&zeta.nClaims===3&&zeta.nSites===3&&zeta.named===true,
  "Hurricane Zeta's three claims across three sites group into ONE named event");
const floods=evs.filter(e=>e.key.indexOf("ev:flood")===0);
assert(floods.length===2,"flood claims 1 day apart cluster; 18 days apart split (2 events)");
assert(floods.some(e=>e.nSites===2),"the clustered flood event spans two sites");

const agg=lossrunAggregates(S);
assert(near(agg.byClass.hurricane,800000),"actual hurricane incurred aggregates to 800k");
assert(near(agg.byClass.flood,170000),"actual flood incurred aggregates to 170k");
assert(near(agg.byClass.bi,60000),"actual BI incurred aggregates to 60k");
assert(agg.unmatched["Mystery Villas"]===45000,
  "an unmatched claimant is flagged WITH its dollars");
assert(agg.unmapped["Crime"]===10000,
  "an unmapped coverage line is flagged WITH its dollars");
assert(agg.openShare>0.2&&agg.openShare<0.35,
  "open-claim share of incurred is reported (310k of 1.085M)");

const cal=lossrunCalibration(S);
assert(cal&&cal.nYears===3,"calibration runs over the record's 3 years");
const huCal=cal.perClass.find(p=>p.cls==="hurricane");
assert(huCal.actualAnnualIncurred>0&&huCal.modeledAnnualRetained>=0,
  "hurricane modeled-vs-actual pair is surfaced");
assert(cal.perClass.every(p=>p.ratio==null||p.bias!==undefined),
  "each class carries a ratio and a bias verdict");
assert(cal.materialDisagreement===true&&cal.disagreements.length>0,
  "material model-vs-actual disagreement is flagged prominently (interim model vs synthetic claims)");
assert(cal.tail.note.indexOf("BODY")>=0&&cal.tail.namedCatIncurred===800000,
  "named-cat dollars split out; the tail stays modeled and labeled");
assert(cal.development.openShare>0.2,"open-claim development risk is in the calibration");
assert(cal.multiSite.actualMultiSiteEvents>=2,
  "actual multi-site events are counted (validates the shared-deductible rule)");

/* derived Net Incurred when the column is missing */
const LR2=["Claim Number,Date of Loss,Claimant Name,Coverage Major,Status,Net Paid,Net Outstanding,Recovery Received",
'2001,2020-05-05,Orlando One,Flood,Closed,"$70,000","$10,000","$5,000"'].join("\n");
loadLossRun(LR2,"lr2.csv");
assert(lossRun.claims.length===1&&near(lossRun.claims[0].netIncurred,75000)
  &&lossRun.claims[0].incBasis.indexOf("derived")>=0,
  "missing Net Incurred derives paid + outstanding - recovery, labeled");

/* ---------------- persistence round trip ------------------------------ */
tcorProgram.deductibles.hurricane.amountUsd=2000000;
persistTcorProgram();persistLossRun();
tcorProgram.deductibles.hurricane.amountUsd=123;
lossRun=null;
restore();
assert(tcorProgram.deductibles.hurricane.amountUsd===2000000,
  "tcorProgram round-trips through localStorage");
assert(lossRun&&lossRun.claims.length===1,"the loss run round-trips through localStorage");

/* ---------------- CSV intake: TCOR profile fields --------------------- */
loadSiteCsv([
"name,latitude,longitude,asset_value_usd,campus_code,campus_name,owned_or_leased,bi_ee_usd,premium_annual_usd",
"Alpha,27.9,-82.5,5000000,TPA01,Tampa Campus,leased,1200000,40000",
"Beta,27.9,-82.4,4000000,,,neither,,"
].join("\n"));
const A=sites.find(s=>s.name==="Alpha"),B=sites.find(s=>s.name==="Beta");
assert(A.campus_code==="TPA01"&&A.campus_name==="Tampa Campus"&&A.owned_or_leased==="leased"
  &&A.bi_ee_usd===1200000&&A.premium_annual_usd===40000,
  "TCOR profile fields (v3 subset) load from CSV");
assert(B.campus_code===undefined&&B.owned_or_leased===undefined,
  "blank or invalid TCOR fields stay absent (labeled fallbacks downstream)");

/* ---------------- Task 3: timeshare_share intake ----------------------- */
loadSiteCsv([
"name,latitude,longitude,asset_value_usd,timeshare_share",
"VoResort,18.34,-64.90,9000000,0.8",
"HotelOnly,18.34,-64.89,9000000,",
"BadShare,18.34,-64.88,9000000,1.7"
].join("\n"));
const VO=sites.find(s=>s.name==="VoResort"),HO=sites.find(s=>s.name==="HotelOnly"),BS=sites.find(s=>s.name==="BadShare");
assert(VO.timeshare_share===0.8&&HO.timeshare_share===undefined&&BS.timeshare_share===undefined,
  "timeshare_share loads from CSV within 0..1; blank or out-of-range stays absent");

/* ---------------- regional demand shock (event table) ------------------ */
sites=[];nextId=1;clearHazCache();
addSites([
  {name:"Hit Resort",latitude:26.2,longitude:-80.1,asset_value_usd:10e6,campus_code:"FL1"},
  {name:"Open Resort",latitude:26.3,longitude:-80.1,asset_value_usd:10e6,campus_code:"FL2"},
  {name:"Far Resort",latitude:21.3,longitude:-157.8,asset_value_usd:10e6,campus_code:"HI1"}
]);
const DS=sites.slice();
resultsPack={name:"ds.json",data:{kind:"results_pack",pack_version:1,
  scenarios:{present:{portfolio:{},per_site:DS.map(s=>({name:s.name}))}},
  event_sets:{scenarios:{present:[{source:"p",weight:1,country:"USA",events:[
    {id:"BIGONE",freq:0.01,sites:[[0,3000000]]}     // 30% damage at Hit Resort
  ]}]}},
  frequent_losses:{ladder_rps:F.rps,scenarios:{present:{
    tc_joint:DS.map(()=>zeroRow.slice()),rflood:DS.map(()=>zeroRow.slice()),
    prain:DS.map(()=>zeroRow.slice()),wfire:DS.map(()=>zeroRow.slice())}}}}};
const biDs=retainedBICalc(DS,"present");
assert(biDs.demandShock.total>0,
  "a 30%-damaged site (structural) triggers the regional demand shock");
assert(biDs.demandShock.perSite[DS[1].id]>0,
  "the UNDAMAGED site in the hit region loses transient demand");
assert((biDs.demandShock.perSite[DS[2].id]||0)===0,
  "a site in another region is untouched (the shock is destination-level)");
assert(biDs.demandShock.perSite[DS[1].id]>biDs.demandShock.perSite[DS[0].id],
  "the damaged site's own closure comes out of its shock window (it cannot lose the same day twice)");
const portDs=tcorPortfolio(DS,"present");
assert(portDs.indirect.excludedFromTotal===true
  &&near(portDs.total,portDs.components.retainedProperty+portDs.components.retainedBI
    +portDs.components.premium+portDs.components.mitigation+portDs.components.admin,1),
  "the demand shock rides the flagged indirect line and never enters the TCOR total");

/* ---------------- TCOR-aware payoff engine ----------------------------- */
resultsPack=null;clearHazCache();
sites=[];nextId=1;
addSites([
  {name:"Payoff One",latitude:26.2,longitude:-80.1,asset_value_usd:20e6,campus_code:"P1"},
  {name:"Payoff Two",latitude:26.2,longitude:-80.1,asset_value_usd:20e6,campus_code:"P1"}
]);
const P=sites.slice();
const mWind=MEASURES.find(m=>m.key==="wind");
const pay=tcorPayoffFor(P[0],mWind,adapt.m.wind,"present",{sites:P,af:14});
assert(pay.certain.total>0,
  "wind hardening on a wind-exposed site yields a certain retained saving");
assert(near(pay.certain.total-pay.certain.heat+pay.negotiated.transferredEl,
  pay.grossAverted-pay.certain.heat,Math.max(1,pay.grossAverted*1e-6)),
  "certain + transferred reconcile exactly to the payoff engine's gross averted loss");
assert(pay.bcrWithCredit>=pay.bcrCertain,
  "the with-credit BCR can only add to the certain BCR");
assert(pay.basis.indexOf("credit realization")>=0,
  "the payoff states its negotiated basis in plain language");
/* the credit is a dial, and zero means zero */
tcorProgram.premium.creditRealization=0;
const pay0=tcorPayoffFor(P[0],mWind,adapt.m.wind,"present",{sites:P,af:14});
assert(pay0.negotiated.premiumSaving===0&&near(pay0.bcrWithCredit,pay0.bcrCertain),
  "credit realization 0 collapses the with-credit BCR onto the certain BCR");
tcorProgram.premium.creditRealization=null;
/* deductibles far above every modeled loss and a token BI limit keep
   everything retained, so the measure's payoff is (almost) all certain */
const dedSave=tcorProgram.deductibles.hurricane.amountUsd;
tcorProgram.deductibles.hurricane.amountUsd=1e12;
tcorProgram.deductibles.flood.amountUsd=1e12;
tcorProgram.deductibles.general.amountUsd=1e12;
tcorProgram.bi.limitUsd=1;
const payAll=tcorPayoffFor(P[0],mWind,adapt.m.wind,"present",{sites:P,af:14});
assert(payAll.negotiated.transferredEl<Math.max(payAll.certain.total*0.01,10),
  "with nothing transferred, the payoff is certain: no premium story to tell");
tcorProgram.bi.limitUsd=null;
tcorProgram.deductibles.hurricane.amountUsd=dedSave;
tcorProgram.deductibles.flood.amountUsd=100000;
tcorProgram.deductibles.general.amountUsd=50000;
const pays=sitePayoffs(P[0],"present",{sites:P,af:14});
assert(pays.length>0&&pays.every(x=>x.bcrCertain>=0&&x.certain.total>=-1e-6),
  "sitePayoffs appraises every in-scope measure with non-negative certain savings");
const ask=renewalAskFor(P,"present",14,0);
assert(isFinite(ask.premiumAskUsd)&&ask.premiumAskUsd>=0,
  "the renewal ask aggregates the funded queue's negotiated savings");

/* ---------------- premium module (Task 4): the gap surface ------------- */
sites=[];nextId=1;clearHazCache();
addSites([
  {name:"Priced",latitude:26.2,longitude:-80.1,asset_value_usd:10e6,premium_annual_usd:60000},
  {name:"Unpriced",latitude:26.2,longitude:-80.1,asset_value_usd:10e6}
]);
const PR=sites.slice();
const prProp=retainedPropertyCalc(PR,"present");
const prBi=retainedBICalc(PR,"present");
const prPrem=premiumCalc(PR,"present",prProp,prBi);
const pPriced=prPrem.perSite[PR[0].id];
assert(pPriced.ratePer100!=null&&near(pPriced.ratePer100,60000/10e6*100,1e-9),
  "the actual rate per $100 TIV reads off the premium on file");
assert(pPriced.gapUsd!=null&&near(pPriced.gapUsd,60000-pPriced.technical,1),
  "the signed actual-vs-technical gap is exposed per site");
assert(prPrem.perSite[PR[1].id].gapUsd===null,
  "no gap verdict without an actual premium (no data, no verdict)");
assert(prPrem.position.impliedLoad!=null
  &&near(prPrem.position.impliedLoad,60000/pPriced.transferredEl,0.01),
  "the implied market load is actual premium over modeled transferred loss, on-file sites only");
assert(near(premiumLoadEff(prPrem),prPrem.position.impliedLoad,1e-9),
  "negotiated savings stand on the implied load when premiums are on file");
assert(prPrem.position.tivShareWithActual===0.5,
  "the position states how much of the TIV its implied load stands on");

/* ---------------- SOV importer (Task 8) -------------------------------- */
sites=[];nextId=1;clearHazCache();
addSites([
  {name:"Harbor Bay Resort",latitude:26.2,longitude:-80.1,asset_value_usd:10e6,construction:"engineered"},
  {name:"Palm Grove Villas",latitude:26.3,longitude:-80.2,asset_value_usd:8e6}
]);
const SOV_CSV=[
"Location Name,Campus Code,Owned/Leased,Total Insured Value,BI/EE,Annual Premium,Occupancy,Construction,Year Built",
'Harbor Bay,HB01,Owned,"12,500,000","2,000,000","85,000",Timeshare Resort,Wood Frame,1998',
'Mystery Point,XX01,Leased,"5,000,000",,,Hotel,,'
].join("\n");
const sovHead=SOV_CSV.split("\n")[0].toLowerCase().split(",").map(x=>x.trim());
assert(sovLooksLike(sovHead)===true,"an SOV announces itself by its TIV/campus columns");
assert(sovLooksLike(["name","latitude","longitude","asset_value_usd"])===false,
  "CLAM's own site schema is never mistaken for an SOV");
assert(sovLooksLike(["lat","lon","scenario","v10"])===false,
  "a hazard grid is never mistaken for an SOV");
loadSovCsv(SOV_CSV,"sov.csv");
const HB=sites.find(s=>s.name==="Harbor Bay Resort");
assert(HB.campus_code==="HB01"&&HB.owned_or_leased==="owned"
  &&HB.bi_ee_usd===2000000&&HB.premium_annual_usd===85000&&HB.asset_value_usd===12500000,
  "SOV facts supersede hand-keyed TCOR fields (campus, tenure, BI & EE, premium, TIV)");
assert(HB.construction==="engineered",
  "an operator-verified vulnerability profile is never overwritten by the broker schedule");
assert(HB.timeshare_share===1,
  "a timeshare occupancy defaults the continuing-revenue share (editable per site)");
assert(Array.isArray(HB.sov_fields)&&HB.sov_fields.indexOf("campus_code")>=0,
  "every SOV-applied field is recorded for the provenance vocabulary");
assert(sovLog&&sovLog.matched===1&&sovLog.unmatched.length===1
  &&sovLog.unmatched[0].tiv===5000000,
  "an unmatched SOV row is reported WITH its TIV, never silently dropped");
const PG=sites.find(s=>s.name==="Palm Grove Villas");
assert(PG.campus_code===undefined,"sites the SOV does not carry are untouched");
/* bootstrap: an SOV with coordinates builds the portfolio from nothing */
sites=[];nextId=1;clearHazCache();
loadSovCsv([
"Location Name,Latitude,Longitude,Total Insured Value,Campus Code",
'Boot One,26.20,-80.10,"9,000,000",B1',
'Boot Two,26.30,-80.20,"7,000,000",B1',
"No Coords,,,1000000,B2"
].join("\n"),"sov_boot.csv");
assert(sites.length===2&&sites[0].asset_value_usd===9000000&&sites[0].campus_code==="B1",
  "with no portfolio loaded, an SOV carrying coordinates bootstraps the sites");
assert(sovLog.mode==="bootstrap"&&sovLog.skipped===1,
  "rows without coordinates or TIV are counted, not silently dropped");

console.log("\nALL TCOR + LOSS-RUN + BI + PAYOFF + PREMIUM + SOV TESTS PASSED");
"""


def main(html_path: str) -> int:
    html = Path(html_path).read_text()
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html,
                        re.S | re.I)
    if not blocks:
        print("FAIL: no inline script found")
        return 1
    js = max(blocks, key=len)
    k = js.index("function restore(")
    k = js.index("{", k)
    depth = 0
    while True:
        ch = js[k]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
        k += 1
    harness = STUBS + js[:k + 1] + TESTS
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(harness)
        tmp = f.name
    r = subprocess.run(["node", tmp], capture_output=True, text=True)
    print(r.stdout)
    if r.returncode != 0:
        print(r.stderr)
        return 1
    return 0


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else \
        "app/Resort_Climate_Risk_Explorer_v210.html"
    raise SystemExit(main(path))
