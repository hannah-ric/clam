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

/* ---------------- BI terms: waiting vs overage ------------------------ */
const econ={value:10e6,daily:1000,maxDownDays:365};
const terms={waitingDays:3,indemnityDays:365,limitUsd:100000};
const bs=biSplitForLoss(10e6,S[0],terms,econ);
assert(near(bs.gross,365000)&&near(bs.waiting,3000)&&near(bs.overage,262000)
  &&near(bs.retained,265000),
  "BI terms: waiting 3k + beyond-limit 262k of a 365k gross BI event");
const biAll=retainedBICalc(S,"present");
assert(biAll.retained>0&&biAll.waiting>0,"portfolio retained BI carries a waiting-period piece");
assert(near(biAll.retained,biAll.waiting+biAll.overage,1),"retained BI = waiting + overage exactly");
assert(biAll.basis.indexOf("interim")>=0,"the interim BI chain says it is interim");

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
assert(r0.quality.propertyBasis==="event"&&r0.components.retainedBI.basis.indexOf("interim")>=0,
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

console.log("\nALL TCOR + LOSS-RUN TESTS PASSED");
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
