/* ============================================================
   TCOR engine (overhaul Tasks 1 + 2)
   Total Cost of Risk is the tool's output; physical damage is an input.
   TCOR per site per year = retained property loss + retained business
   interruption + allocated premium + annualized risk-control spend +
   allocated program admin. Indirect costs (guest rebooking, reputation)
   ride along as a FLAGGED estimate and are never added to the total.

   THE AGGREGATION RULE (the single most important correctness rule):
   - hurricane (joint wind+surge events) carries ONE per-occurrence
     deductible shared across the sites the event touched (the Campus
     grouping): retained loss is computed at the EVENT level from the
     results pack's per-event table and then summed across events. It is
     NEVER the sum of per-site hurricane deductibles.
   - flood and general property carry per-location deductibles: retained
     loss integrates each site's own loss ladder and sums per site.
   Portfolio TCOR is therefore event-level for correlated perils and
   site-level for the rest - not a column total.

   Everything here READS hazard/event outputs (results pack event_sets and
   frequent_losses, or the app's interim curves as a LABELED fallback);
   nothing here re-derives or alters the hazard science. Every estimate
   carries a basis label; a TCOR built on fallbacks says so.
   ============================================================ */

/* Program parameters. Deductibles are confidential and change at renewal,
   so they are PARAMETERS with documented defaults, never hardcoded facts.
   basis: "per-occurrence-campus" shares one hurricane deductible across a
   campus's sites per event (the SOV's Campus Code is the sharing unit);
   "per-occurrence-program" shares one across the whole portfolio per
   event; "per-location" applies per site per event. */
let tcorProgram={
  deductibles:{
    hurricane:{amountUsd:1000000,basis:"per-occurrence-campus"},
    flood:{amountUsd:100000,basis:"per-location"},
    general:{amountUsd:50000,basis:"per-location"}
  },
  /* peril -> deductible class; surge rides with wind under the hurricane
     occurrence by default (named-storm basis); reclassify at renewal if
     the program treats surge as flood */
  perilClass:{tc:"hurricane",cflood:"hurricane",rflood:"flood",prain:"flood",wfire:"general"},
  aggregateCapUsd:null,          // optional annual aggregate retention cap
  bi:{waitingDays:3,limitUsd:null,indemnityDays:365,provenance:"default"},
  premium:{programAnnualUsd:null,loadFactor:null},
  adminAnnualUsd:0,              // program/broker admin, allocated by TIV
  mitigationAnnualUsd:0,         // portfolio risk-control spend, by TIV
  indirect:{rebookShare:0.15},   // flagged-estimate factor on gross BI
  simYears:1000,simSeed:20260709 // seeded year simulation (cap + bad year)
};
const TCOR_CLASSES=["hurricane","flood","general"];
function perilClassOf(hz){ return tcorProgram.perilClass[hz]||"general"; }

/* Campus grouping: the hurricane-deductible-sharing unit. Comes from the
   SOV (campus_code / campus_name, schema v3); absent that, each site is
   its own unit, which is FLAGGED because it removes sharing and thereby
   overstates retained hurricane loss. */
function campusKeyOf(s){
  const c=String(s&&(s.campus_code!=null?s.campus_code:(s.campus_name!=null?s.campus_name:""))).trim();
  return c?("campus:"+c.toLowerCase()):("site:"+(s?s.id:"?"));
}
function campusDataShare(arr){
  if(!arr||!arr.length)return 0;
  return arr.filter(s=>String(s.campus_code!=null?s.campus_code:(s.campus_name!=null?s.campus_name:"")).trim()).length/arr.length;
}

/* Join the results pack's per_site order to the app's site list, by
   site_id first and name second. Unjoined pack rows are counted, never
   silently dropped: their losses surface as unjoinedLoss. */
function packJoin(sitesArr,sc){
  const pk=resultsPack&&resultsPack.data;
  if(!pk||!pk.scenarios||!pk.scenarios[sc])return null;
  const ps=pk.scenarios[sc].per_site||[];
  const bySid={},byName={};
  sitesArr.forEach(s=>{
    const sid=String(s.site_id==null?"":s.site_id).trim().toLowerCase();
    if(sid&&!bySid[sid])bySid[sid]=s;
    const nm=String(s.name==null?"":s.name).trim().toLowerCase();
    if(nm&&!byName[nm])byName[nm]=s;
  });
  const map=ps.map(x=>{
    const sid=String(x.site_id==null?"":x.site_id).trim().toLowerCase();
    if(sid&&bySid[sid])return bySid[sid];
    return byName[String(x.name==null?"":x.name).trim().toLowerCase()]||null;
  });
  const idxOf={};map.forEach((s,i)=>{if(s&&idxOf[s.id]==null)idxOf[s.id]=i;});
  return {map,idxOf,matched:map.filter(Boolean).length,total:ps.length};
}

/* ------------------------------------------------------------
   Event-level retained engine (pure): the aggregation rule itself.
   parts: [{weight, events:[{id,freq,sites:[[idx,lossUsd],...]}]}] - the
   pack's event_sets shape (sources are alternative catalogs blended by
   weight; countries' parts simply add because their sites are disjoint).
   resolve(idx) -> {id:appSiteId, campus:key} or null when unjoined.
   Per event: site losses group by campus; each campus retains
   min(campus loss, deductible) ONCE; the retained amount allocates back
   to sites pro-rata to their loss so per-site rows still sum to the
   event-level truth. "per-occurrence-program" groups everything.
   ------------------------------------------------------------ */
function eventRetained(parts,resolve,dedUsd,basis){
  let annualGross=0,annualRetained=0,occFreq=0,hitFreq=0,fullDedFreq=0,unjoinedLoss=0;
  const perSite={};
  (parts||[]).forEach(part=>{
    const w=+part.weight||0;
    (part.events||[]).forEach(e=>{
      const f=+e.freq||0;if(f<=0)return;
      const groups={};let total=0;
      (e.sites||[]).forEach(pair=>{
        const r=resolve(pair[0]),loss=+pair[1]||0;
        if(!r){unjoinedLoss+=w*f*loss;return;}
        const g=basis==="per-occurrence-program"?"~program":r.campus;
        (groups[g]||(groups[g]=[])).push([r.id,loss]);total+=loss;
      });
      if(!(total>0))return;
      let evRetained=0;
      for(const g in groups){
        const gl=groups[g].reduce((a,x)=>a+x[1],0);
        const gr=Math.min(gl,dedUsd);
        evRetained+=gr;
        if(gl>=dedUsd)fullDedFreq+=w*f;
        groups[g].forEach(x=>{
          const ps=perSite[x[0]]||(perSite[x[0]]={gross:0,retained:0});
          ps.gross+=w*f*x[1];
          ps.retained+=w*f*gr*(gl?x[1]/gl:0);
        });
      }
      annualGross+=w*f*total;
      annualRetained+=w*f*evRetained;
      occFreq+=w*f;
      if(evRetained>0)hitFreq+=w*f;
    });
  });
  return {annualGross,annualRetained,annualTransferred:annualGross-annualRetained,
          occFreq,hitFreq,fullDedFreq,perSite,unjoinedLoss};
}

/* ------------------------------------------------------------
   Ladder math (pure). A ladder is a site's own loss at each return
   period, LADDER-convention: rps ascending (2..500), losses non-
   decreasing with rarity. The integral is the same trapezoid over
   exceedance frequency that siteEad and layerStatsCalc use, plus the
   flat tail beyond the largest RP (the pack's recorded convention);
   events more frequent than the first rung are below the ladder's
   resolution and enter as zero (conservative-low, documented).
   ------------------------------------------------------------ */
function ladderIntegral(rps,losses,tr,fMin){
  tr=tr||(L=>L);fMin=fMin||0;
  const pts=rps.map((rp,i)=>({f:1/rp,L:tr(Math.max(+losses[i]||0,0))}))
    .filter(p=>p.f>=fMin).sort((a,b)=>b.f-a.f);
  if(!pts.length)return 0;
  let s=0;
  for(let i=0;i<pts.length-1;i++)s+=0.5*(pts[i].L+pts[i+1].L)*(pts[i].f-pts[i+1].f);
  if(fMin<=1/rps[rps.length-1])s+=pts[pts.length-1].L*pts[pts.length-1].f;
  return s;
}
/* the largest annual exceedance frequency at which the ladder loss
   reaches thr (step convention, matching the ladder's own basis) */
function ladderFreqAt(rps,losses,thr){
  for(let i=0;i<rps.length;i++)if((+losses[i]||0)>=thr)return 1/rps[i];
  return 0;
}
function ladderRetained(rps,losses,dedUsd){
  return {gross:ladderIntegral(rps,losses),
          retained:ladderIntegral(rps,losses,L=>Math.min(L,dedUsd)),
          hitFreq:ladderFreqAt(rps,losses,1),
          fullDedFreq:ladderFreqAt(rps,losses,dedUsd)};
}

/* ------------------------------------------------------------
   Site loss ladders: pack first (authoritative event outputs down to
   1-in-2), else the app's interim curves extended below 1-in-10 in loss
   space with exactly subTenPts' log-linear rule (LABELED interim).
   "tc_joint" is the same-catalog wind+surge sum, the hurricane
   occurrence basis.
   ------------------------------------------------------------ */
const TCOR_LADDER_RPS=[2,5,10,25,50,100,250,500];
function interimLossLadder(s,hz,sc){
  const r=hzSite(s,hz,sc);const by={};
  ((r&&r.curve)||[]).forEach(c=>{by[c.rp]=Math.max(c.loss||0,0);});
  const l10=by[10]||0,l25=by[25]||0;
  const b=Math.max((l25-l10)/(Math.log(25)-Math.log(10)),0);
  const sub=rp=>Math.max(l10-b*(Math.log(10)-Math.log(rp)),0);
  return {rps:TCOR_LADDER_RPS,
          losses:[sub(2),sub(5)].concat(RPS.map(rp=>by[rp]||0)),
          basis:"interim"};
}
function siteLadderFor(s,hz,sc,join){
  const pk=resultsPack&&resultsPack.data;
  const fl=pk&&pk.frequent_losses;
  if(fl&&fl.scenarios&&fl.scenarios[sc]&&fl.scenarios[sc][hz]
     &&join&&join.idxOf[s.id]!=null){
    const row=fl.scenarios[sc][hz][join.idxOf[s.id]];
    if(row&&row.length===(fl.ladder_rps||[]).length)
      return {rps:fl.ladder_rps.slice(),losses:row.slice(),basis:"pack"};
  }
  if(hz==="tc_joint"){
    const a=interimLossLadder(s,"tc",sc),c=interimLossLadder(s,"cflood",sc);
    return {rps:a.rps,losses:a.losses.map((x,i)=>x+(c.losses[i]||0)),
            basis:"interim"};   // comonotonic wind+surge add, labeled
  }
  return interimLossLadder(s,hz,sc);
}

/* degraded hurricane path when no event table is loaded: within a campus,
   nearby sites share storms, so campus loss at each frequency is the
   comonotonic sum of member ladders and ONE deductible applies to it.
   A LABELED approximation of the event math, never presented as it. */
function campusLadderRetained(sitesArr,sc,join,dedUsd,basis){
  const groups={};
  sitesArr.forEach(s=>{
    const g=basis==="per-occurrence-program"?"~program":campusKeyOf(s);
    (groups[g]||(groups[g]=[])).push(s);
  });
  let annualGross=0,annualRetained=0,hitFreq=0,fullDedFreq=0;
  const perSite={};
  for(const g in groups){
    const lads=groups[g].map(s=>({s,lad:siteLadderFor(s,"tc_joint",sc,join)}));
    const rps=lads[0].lad.rps;
    const campusLoss=rps.map((_,i)=>lads.reduce((a,x)=>a+(+x.lad.losses[i]||0),0));
    const r=ladderRetained(rps,campusLoss,dedUsd);
    annualGross+=r.gross;annualRetained+=r.retained;
    hitFreq+=r.hitFreq;fullDedFreq+=r.fullDedFreq;
    const tot=lads.reduce((a,x)=>a+ladderIntegral(x.lad.rps,x.lad.losses),0);
    lads.forEach(x=>{
      const gi=ladderIntegral(x.lad.rps,x.lad.losses);
      perSite[x.s.id]={gross:gi,retained:tot?r.retained*gi/tot:0};
    });
  }
  return {annualGross,annualRetained,annualTransferred:annualGross-annualRetained,
          hitFreq,fullDedFreq,perSite,unjoinedLoss:0};
}

/* ------------------------------------------------------------
   Retained property (Task 2): event-level for hurricane, per-location
   ladders for flood and general, plus the explicit attritional layer.
   ------------------------------------------------------------ */
const TCOR_CLASS_PERILS={flood:["rflood","prain"],general:["wfire"]};
function retainedPropertyCalc(sitesArr,sc){
  const ded=tcorProgram.deductibles;
  const join=packJoin(sitesArr,sc);
  const pk=resultsPack&&resultsPack.data;
  const evScen=pk&&pk.event_sets&&pk.event_sets.scenarios&&pk.event_sets.scenarios[sc];
  const out={classes:{},perSite:{},attritional:null,basisFlags:[]};
  sitesArr.forEach(s=>{out.perSite[s.id]={};TCOR_CLASSES.forEach(c=>out.perSite[s.id][c]={gross:0,retained:0});});

  let hu,huBasis;
  if(evScen&&join&&join.matched>0){
    const resolve=idx=>{const s=join.map[idx];return s?{id:s.id,campus:campusKeyOf(s)}:null;};
    hu=eventRetained(evScen,resolve,ded.hurricane.amountUsd,ded.hurricane.basis);
    huBasis="event";
    if(hu.unjoinedLoss>0)out.basisFlags.push("hurricane: "+(join.total-join.matched)+" pack site(s) did not join the portfolio; their event losses are excluded and flagged");
  }else{
    hu=campusLadderRetained(sitesArr,sc,join,ded.hurricane.amountUsd,ded.hurricane.basis);
    huBasis="campus-comonotonic approximation (no per-event table loaded)";
    out.basisFlags.push("hurricane retained is a labeled approximation until a results pack with event_sets is loaded");
  }
  if(ded.hurricane.basis==="per-occurrence-campus"&&campusDataShare(sitesArr)<1)
    out.basisFlags.push("campus grouping incomplete: sites without campus_code are their own sharing unit, which overstates retained hurricane loss");
  out.classes.hurricane={annualGross:hu.annualGross,annualRetained:hu.annualRetained,
    annualTransferred:hu.annualTransferred,hitFreq:hu.hitFreq,
    fullDedFreq:hu.fullDedFreq||0,basis:huBasis,unjoinedLoss:hu.unjoinedLoss||0,
    dedUsd:ded.hurricane.amountUsd,dedBasis:ded.hurricane.basis};
  sitesArr.forEach(s=>{
    const ps=hu.perSite[s.id];
    if(ps){out.perSite[s.id].hurricane={gross:ps.gross,retained:ps.retained};}
  });

  /* per-location classes: each site's own ladder, one deductible per
     occurrence per location, summed across sites (the rule for
     uncorrelated perils) */
  const ladBases={};
  ["flood","general"].forEach(cls=>{
    const d=ded[cls];
    let gross=0,retained=0,hitFreq=0,fullDedFreq=0;
    sitesArr.forEach(s=>{
      TCOR_CLASS_PERILS[cls].forEach(hz=>{
        const lad=siteLadderFor(s,hz,sc,join);
        ladBases[lad.basis]=true;
        const r=ladderRetained(lad.rps,lad.losses,d.amountUsd);
        gross+=r.gross;retained+=r.retained;
        hitFreq+=r.hitFreq;fullDedFreq+=r.fullDedFreq;
        out.perSite[s.id][cls].gross+=r.gross;
        out.perSite[s.id][cls].retained+=r.retained;
      });
    });
    out.classes[cls]={annualGross:gross,annualRetained:retained,
      annualTransferred:gross-retained,hitFreq,fullDedFreq,
      basis:ladBases.pack?(ladBases.interim?"pack+interim ladders":"pack ladders"):"interim ladders",
      dedUsd:d.amountUsd,dedBasis:d.basis};
  });
  if(ladBases.interim)out.basisFlags.push("some per-location ladders come from the interim model (no pack frequent_losses row for that site/peril): labeled estimate");

  /* the attritional frequency layer (Task 2): across the portfolio, small
     events trip the per-location deductibles often; the frequent band
     (1-in-10 and more frequent) is a real annual cost no single-site or
     tail view shows. Hurricane occurrence hits ride along as a count. */
  const F_ATTR=0.1;
  let attrRetained=0,attrHits=0;
  sitesArr.forEach(s=>{
    ["flood","general"].forEach(cls=>{
      TCOR_CLASS_PERILS[cls].forEach(hz=>{
        const lad=siteLadderFor(s,hz,sc,join);
        attrRetained+=ladderIntegral(lad.rps,lad.losses,
          L=>Math.min(L,ded[cls].amountUsd),F_ATTR);
        const hf=ladderFreqAt(lad.rps,lad.losses,1);
        if(hf>=F_ATTR)attrHits+=hf;
      });
    });
  });
  out.attritional={frequentBandRetained:attrRetained,
    frequentHitsPerYear:attrHits,
    hurricaneOccurrencesPerYear:out.classes.hurricane.hitFreq,
    fMin:F_ATTR,
    note:"expected annual retained loss and deductible hits from events at 1-in-10 frequency or more, summed across all sites"};

  out.total={
    annualGross:TCOR_CLASSES.reduce((a,c)=>a+out.classes[c].annualGross,0),
    annualRetained:TCOR_CLASSES.reduce((a,c)=>a+out.classes[c].annualRetained,0)
  };
  out.total.annualTransferred=out.total.annualGross-out.total.annualRetained;
  out.join=join?{matched:join.matched,total:join.total}:null;
  return out;
}

/* ------------------------------------------------------------
   Seeded year simulation: the exact treatment of the optional annual
   aggregate retention cap, and the source of bad-year figures and the
   attritional-year distribution. Hurricane years replay the pack's event
   table (one alternative catalog drawn per year by weight, then a
   Poisson draw per event); per-location perils decompose each site
   ladder into frequency bands with midpoint losses. Deterministic seed.
   ------------------------------------------------------------ */
function tcorRng(seed){let a=seed>>>0;return function(){
  a|=0;a=(a+0x6D2B79F5)|0;let t=Math.imul(a^(a>>>15),1|a);
  t=(t+Math.imul(t^(t>>>7),61|t))^t;return((t^(t>>>14))>>>0)/4294967296;};}
function poissonDraw(lambda,rnd){
  if(lambda<=0)return 0;
  const L=Math.exp(-lambda);let k=0,p=1;
  do{k++;p*=rnd();}while(p>L&&k<50);
  return k-1;
}
function ladderBands(rps,losses){
  /* consecutive rungs become arrival bands: rate = f_k - f_{k+1} at the
     midpoint loss; the rarest rung keeps its own rate at its own loss */
  const pts=rps.map((rp,i)=>({f:1/rp,L:Math.max(+losses[i]||0,0)})).sort((a,b)=>b.f-a.f);
  const bands=[];
  for(let i=0;i<pts.length-1;i++){
    const rate=pts[i].f-pts[i+1].f,L=0.5*(pts[i].L+pts[i+1].L);
    if(rate>0&&L>0)bands.push({rate,loss:L});
  }
  const last=pts[pts.length-1];
  if(last.f>0&&last.L>0)bands.push({rate:last.f,loss:last.L});
  return bands;
}
function simulateRetainedYears(sitesArr,sc,opts){
  opts=opts||{};
  const years=opts.years||tcorProgram.simYears,seed=opts.seed||tcorProgram.simSeed;
  const ded=tcorProgram.deductibles,cap=tcorProgram.aggregateCapUsd;
  const join=packJoin(sitesArr,sc);
  const pk=resultsPack&&resultsPack.data;
  const evScen=pk&&pk.event_sets&&pk.event_sets.scenarios&&pk.event_sets.scenarios[sc];
  const rnd=tcorRng(seed);
  /* pre-resolve hurricane events to campus groups, grouped by country:
     each country's catalog is independent (its sites are disjoint), so
     every simulated year draws ONE alternative source per country by
     weight and then Poisson-draws that source's events */
  let huCountries=null;
  if(evScen&&join&&join.matched>0){
    const byCountry={};
    evScen.forEach(part=>{
      const key=part.country||"?";
      (byCountry[key]||(byCountry[key]=[])).push({weight:+part.weight||0,
        events:(part.events||[]).map(e=>{
          const groups={};
          (e.sites||[]).forEach(pair=>{
            const s=join.map[pair[0]];if(!s)return;
            const g=ded.hurricane.basis==="per-occurrence-program"?"~program":campusKeyOf(s);
            groups[g]=(groups[g]||0)+(+pair[1]||0);
          });
          return {freq:+e.freq||0,groups};
        }).filter(e=>e.freq>0)});
    });
    huCountries=Object.keys(byCountry).map(k=>byCountry[k]);
  }
  const siteBands=[];
  sitesArr.forEach(s=>{
    ["flood","general"].forEach(cls=>{
      TCOR_CLASS_PERILS[cls].forEach(hz=>{
        const lad=siteLadderFor(s,hz,sc,join);
        ladderBands(lad.rps,lad.losses).forEach(b=>
          siteBands.push({rate:b.rate,loss:b.loss,ded:ded[cls].amountUsd}));
      });
    });
  });
  /* degraded hurricane in the simulation: campus-comonotonic bands */
  let huBands=null;
  if(!huCountries){
    const groups={};
    sitesArr.forEach(s=>{
      const g=ded.hurricane.basis==="per-occurrence-program"?"~program":campusKeyOf(s);
      (groups[g]||(groups[g]=[])).push(s);
    });
    huBands=[];
    for(const g in groups){
      const lads=groups[g].map(s=>siteLadderFor(s,"tc_joint",sc,join));
      const rps=lads[0].rps;
      const campusLoss=rps.map((_,i)=>lads.reduce((a,l)=>a+(+l.losses[i]||0),0));
      ladderBands(rps,campusLoss).forEach(b=>
        huBands.push({rate:b.rate,loss:b.loss,ded:ded.hurricane.amountUsd}));
    }
  }
  const totals=new Array(years),hits=new Array(years);
  for(let y=0;y<years;y++){
    let ret=0,nHits=0;
    if(huCountries){
      huCountries.forEach(srcs=>{
        /* draw one alternative catalog by weight, then its events */
        let u=rnd(),src=srcs[srcs.length-1];
        for(const p of srcs){if(u<p.weight){src=p;break;}u-=p.weight;}
        src.events.forEach(e=>{
          const n=e.freq<0.05?(rnd()<e.freq?1:0):poissonDraw(e.freq,rnd);
          for(let k=0;k<n;k++){
            for(const g in e.groups){
              ret+=Math.min(e.groups[g],ded.hurricane.amountUsd);nHits++;
            }
          }
        });
      });
    }else{
      huBands.forEach(b=>{
        const n=b.rate<0.05?(rnd()<b.rate?1:0):poissonDraw(b.rate,rnd);
        for(let k=0;k<n;k++){ret+=Math.min(b.loss,b.ded);nHits++;}
      });
    }
    siteBands.forEach(b=>{
      const n=b.rate<0.05?(rnd()<b.rate?1:0):poissonDraw(b.rate,rnd);
      for(let k=0;k<n;k++){ret+=Math.min(b.loss,b.ded);nHits++;}
    });
    totals[y]=cap!=null?Math.min(ret,cap):ret;
    hits[y]=nHits;
  }
  const sorted=totals.slice().sort((a,b)=>a-b);
  const q=p=>sorted[Math.min(sorted.length-1,Math.floor(p*sorted.length))];
  return {years,seed,capUsd:cap,
    mean:totals.reduce((a,x)=>a+x,0)/years,
    median:q(0.5),p90:q(0.9),p99:q(0.99),
    meanHits:hits.reduce((a,x)=>a+x,0)/years,
    basis:(huCountries?"event table":"ladder bands (labeled approximation)")
      +(cap!=null?", annual aggregate cap applied per simulated year":"")};
}

/* ------------------------------------------------------------
   Retained business interruption, INTERIM chain (labeled; the full
   Task 3 module - archetype downtime, seasonality, timeshare revenue,
   regional demand shock - replaces the transform, not the terms math).
   Per event: damage ratio -> downtime days (the app's linear reopen
   model) -> gross BI -> retained = waiting period (always) + downtime
   beyond the indemnity period + insurable BI beyond the limit. The
   frequent small piece (waiting) and the rare large piece (overage) are
   kept separate; the BI & EE declared value caps insurable BI when no
   explicit limit is set.
   ------------------------------------------------------------ */
function biTermsOf(s){
  const t=tcorProgram.bi;
  const lim=(t.limitUsd!=null&&t.limitUsd>0)?t.limitUsd
    :((+s.bi_ee_usd>0)?+s.bi_ee_usd:null);
  return {waitingDays:t.waitingDays,indemnityDays:t.indemnityDays,
    limitUsd:lim,
    limitBasis:(t.limitUsd!=null&&t.limitUsd>0)?"program"
      :((+s.bi_ee_usd>0)?"BI & EE declared value":"none on file (overage reads zero, labeled)"),
    provenance:t.provenance};
}
function biSplitForLoss(lossUsd,s,terms,econ){
  const dmg=econ.value>0?Math.min(lossUsd/econ.value,1):0;
  const down=dmg*econ.maxDownDays;
  const gross=econ.daily*down;
  const waiting=econ.daily*Math.min(down,terms.waitingDays);
  const beyondIndem=econ.daily*Math.max(down-terms.indemnityDays,0);
  const insurable=Math.max(gross-waiting-beyondIndem,0);
  const overLimit=terms.limitUsd!=null?Math.max(insurable-terms.limitUsd,0):0;
  return {gross,waiting,overage:beyondIndem+overLimit,
          retained:waiting+beyondIndem+overLimit,downDays:down};
}
function retainedBICalc(sitesArr,sc){
  const join=packJoin(sitesArr,sc);
  const pk=resultsPack&&resultsPack.data;
  const evScen=pk&&pk.event_sets&&pk.event_sets.scenarios&&pk.event_sets.scenarios[sc];
  const perSite={};let waiting=0,overage=0,gross=0;
  const econOf={};
  sitesArr.forEach(s=>{
    const a=assumeFor(s);
    const gop=siteRevenue(s)*a.gopMargin;
    econOf[s.id]={value:+s.asset_value_usd||0,daily:gop/365,
                  maxDownDays:a.reopenMonths/12*365};
    perSite[s.id]={gross:0,waiting:0,overage:0,retained:0,basis:"interim BI chain (Task 3 pending)"};
  });
  /* hurricane: per event when the table is joined (the waiting period
     applies per occurrence, which per-year averages cannot represent) */
  let huEventBased=false;
  if(evScen&&join&&join.matched>0){
    huEventBased=true;
    evScen.forEach(part=>{
      const w=+part.weight||0;
      (part.events||[]).forEach(e=>{
        const f=+e.freq||0;if(f<=0)return;
        (e.sites||[]).forEach(pair=>{
          const s=join.map[pair[0]];if(!s)return;
          const b=biSplitForLoss(+pair[1]||0,s,biTermsOf(s),econOf[s.id]);
          const ps=perSite[s.id];
          ps.gross+=w*f*b.gross;ps.waiting+=w*f*b.waiting;
          ps.overage+=w*f*b.overage;ps.retained+=w*f*b.retained;
        });
      });
    });
  }
  sitesArr.forEach(s=>{
    const terms=biTermsOf(s),econ=econOf[s.id];
    const perils=huEventBased?["rflood","prain","wfire"]
                             :["tc_joint","rflood","prain","wfire"];
    perils.forEach(hz=>{
      const lad=siteLadderFor(s,hz,sc,join);
      const ps=perSite[s.id];
      ps.gross+=ladderIntegral(lad.rps,lad.losses,L=>biSplitForLoss(L,s,terms,econ).gross);
      ps.waiting+=ladderIntegral(lad.rps,lad.losses,L=>biSplitForLoss(L,s,terms,econ).waiting);
      ps.overage+=ladderIntegral(lad.rps,lad.losses,L=>biSplitForLoss(L,s,terms,econ).overage);
      ps.retained+=ladderIntegral(lad.rps,lad.losses,L=>biSplitForLoss(L,s,terms,econ).retained);
    });
    gross+=perSite[s.id].gross;waiting+=perSite[s.id].waiting;
    overage+=perSite[s.id].overage;
  });
  return {perSite,gross,waiting,overage,retained:waiting+overage,
    transferred:gross-waiting-overage,
    basis:"interim BI chain: linear damage-to-downtime, revenue-proxy GOP, "
      +(huEventBased?"hurricane terms applied per event":"no event table: hurricane terms applied on ladders")
      +"; seasonality, timeshare revenue split, and regional demand shock arrive with the BI module (Task 3)",
    termsProvenance:tcorProgram.bi.provenance};
}

/* ------------------------------------------------------------
   Premium (interim allocation; the full Task 4 module adds the
   technical-vs-actual gap surface). Actual per-site premium wins when
   the profile carries it (SOV AIG columns via schema v3); else the
   technical benchmark: transferred expected loss (property + insurable
   BI) times the program loading factor. A known program total rescales
   the technical allocation, labeled.
   ------------------------------------------------------------ */
function premiumCalc(sitesArr,sc,prop,bi){
  const load=tcorProgram.premium.loadFactor!=null?tcorProgram.premium.loadFactor
    :(typeof adapt!=="undefined"&&adapt&&adapt.load?adapt.load:1.5);
  const perSite={};let technicalTotal=0,actualTotal=0,nActual=0;
  sitesArr.forEach(s=>{
    const p=prop.perSite[s.id];
    const transProp=TCOR_CLASSES.reduce((a,c)=>a+Math.max(p[c].gross-p[c].retained,0),0);
    const b=bi.perSite[s.id];
    const transBi=Math.max((b.gross||0)-(b.retained||0),0);
    const technical=(transProp+transBi)*load;
    technicalTotal+=technical;
    const actual=+s.premium_annual_usd>0?+s.premium_annual_usd:null;
    if(actual!=null){actualTotal+=actual;nActual++;}
    perSite[s.id]={technical,actual,
      allocated:actual!=null?actual:technical,
      basis:actual!=null?"actual (per-site premium on file)"
        :"technical benchmark (modeled transferred loss x "+load+" load)"};
  });
  let allocBasis="actual where on file, technical benchmark elsewhere";
  const progTot=tcorProgram.premium.programAnnualUsd;
  if(progTot>0&&technicalTotal>0){
    /* a known program total rescales the technical allocations so the
       sites without an actual premium share the real spend */
    const techOnly=sitesArr.filter(s=>perSite[s.id].actual==null);
    const techSum=techOnly.reduce((a,s)=>a+perSite[s.id].technical,0);
    const rest=Math.max(progTot-actualTotal,0);
    if(techSum>0)techOnly.forEach(s=>{
      perSite[s.id].allocated=rest*perSite[s.id].technical/techSum;
      perSite[s.id].basis="program total allocated by modeled transferred expected loss";
    });
    allocBasis="program annual premium allocated by modeled transferred expected loss";
  }
  return {perSite,technicalTotal,actualTotal,nActual,load,
    allocatedTotal:sitesArr.reduce((a,s)=>a+perSite[s.id].allocated,0),
    allocBasis};
}

/* ------------------------------------------------------------
   The TCOR spine (Task 1): five parts, plus the flagged indirect
   estimate that is NEVER in the total, plus a per-site quality mark
   that names every fallback the figure is standing on.
   ------------------------------------------------------------ */
function tcorContext(sitesArr,sc){
  const prop=retainedPropertyCalc(sitesArr,sc);
  const bi=retainedBICalc(sitesArr,sc);
  const prem=premiumCalc(sitesArr,sc,prop,bi);
  const tiv=sitesArr.reduce((a,s)=>a+(+s.asset_value_usd||0),0)||1;
  return {sc,prop,bi,prem,tiv};
}
function tcorSite(s,sc,ctx){
  ctx=ctx||tcorContext([s],sc);
  const p=ctx.prop.perSite[s.id];
  const retainedProperty=TCOR_CLASSES.reduce((a,c)=>a+p[c].retained,0);
  const b=ctx.bi.perSite[s.id];
  const share=(+s.asset_value_usd||0)/ctx.tiv;
  const mitigation=(+s.mitigation_annual_usd>0?+s.mitigation_annual_usd:0)
    +tcorProgram.mitigationAnnualUsd*share;
  const admin=tcorProgram.adminAnnualUsd*share;
  const premium=ctx.prem.perSite[s.id].allocated;
  const total=retainedProperty+b.retained+premium+mitigation+admin;
  const missing=[];
  if(!String(s.campus_code!=null?s.campus_code:"").trim())missing.push("campus grouping (SOV Campus Code)");
  if(!(+s.annual_revenue_usd>0))missing.push("site revenue (BI uses the value-ratio proxy)");
  if(!(+s.bi_ee_usd>0)&&tcorProgram.bi.limitUsd==null)missing.push("BI limit / BI & EE declared value");
  if(!(+s.premium_annual_usd>0))missing.push("actual per-site premium");
  if(tcorProgram.bi.provenance==="default")missing.push("BI policy terms (waiting period, indemnity) are defaults");
  return {id:s.id,name:s.name,total,
    components:{
      retainedProperty:{value:retainedProperty,byClass:{
        hurricane:p.hurricane.retained,flood:p.flood.retained,general:p.general.retained},
        basis:ctx.prop.classes.hurricane.basis},
      retainedBI:{value:b.retained,waiting:b.waiting,overage:b.overage,basis:b.basis},
      premium:{value:premium,basis:ctx.prem.perSite[s.id].basis},
      mitigation:{value:mitigation,basis:+s.mitigation_annual_usd>0?"site risk-control spend on file":"program allocation by TIV"},
      admin:{value:admin,basis:"program admin allocated by TIV"}
    },
    indirect:{value:b.gross*tcorProgram.indirect.rebookShare,flagged:true,
      excludedFromTotal:true,
      basis:"flagged estimate ("+Math.round(tcorProgram.indirect.rebookShare*100)
        +"% of gross BI): guest rebooking and reputation; never added to the TCOR total"},
    quality:{estimate:missing.length>0||ctx.prop.classes.hurricane.basis!=="event",
      missing,
      propertyBasis:ctx.prop.classes.hurricane.basis,
      note:"TCOR is an estimate; every fallback above widens it"}};
}
function tcorPortfolio(sitesArr,sc){
  const ctx=tcorContext(sitesArr,sc);
  const rows=sitesArr.map(s=>tcorSite(s,sc,ctx));
  /* the portfolio number is the event-level engine's own total for the
     correlated class plus per-location sums for the rest; the per-site
     rows were ALLOCATED from those same totals, so the sum reconciles by
     construction (asserted in tests), but the truth lives event-side */
  const retainedProperty=ctx.prop.total.annualRetained;
  const retainedBI=ctx.bi.retained;
  const premium=ctx.prem.allocatedTotal;
  const mitigation=rows.reduce((a,r)=>a+r.components.mitigation.value,0);
  const admin=tcorProgram.adminAnnualUsd;
  return {sc,rows,ctx,
    components:{retainedProperty,retainedBI,premium,mitigation,admin},
    total:retainedProperty+retainedBI+premium+mitigation+admin,
    indirect:{value:rows.reduce((a,r)=>a+r.indirect.value,0),flagged:true,excludedFromTotal:true},
    attritional:ctx.prop.attritional,
    waterfall:{gross:ctx.prop.total.annualGross+ctx.bi.gross,
      transferredProperty:ctx.prop.total.annualTransferred,
      retainedProperty,transferredBI:ctx.bi.transferred,retainedBI,
      premium,mitigation,admin},
    basisFlags:ctx.prop.basisFlags.slice(),
    estimate:rows.some(r=>r.quality.estimate)};
}
