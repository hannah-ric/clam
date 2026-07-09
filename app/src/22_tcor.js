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
  /* creditRealization: fraction of the technical premium saving assumed
     negotiable at renewal (null = the registry default); range 0..1 */
  premium:{programAnnualUsd:null,loadFactor:null,creditRealization:null},
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

   Task 3 extension: every drawn occurrence also draws an ARRIVAL MONTH
   from its peril's climatology and retains that occurrence's BI through
   the full seasonal terms chain (waiting per event, indemnity, limit),
   so the bad year is the joint property + BI year, not property with
   BI riding at expected level. The aggregate cap stays a property-
   program cap: it never truncates BI.
   ------------------------------------------------------------ */
/* cumulative month tables for the simulation's arrival-month draws */
function biCumOf(timing){
  const c=[];let a=0;
  for(let m=0;m<12;m++){a+=timing[m];c.push(a);}
  c[11]=1;return c;
}
function biDrawMonth(cum,rnd){
  const u=rnd();
  for(let m=0;m<12;m++)if(u<=cum[m])return m;
  return 11;
}
/* the 12 monthly retained-BI values for one event loss at one site,
   precomputed once so the year loop is a table lookup */
function biMonthlyRetained(lossUsd,terms,econ){
  const out=new Array(12);
  for(let m=0;m<12;m++)out[m]=biEventSplit(lossUsd,terms,econ,m).retained;
  return out;
}
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
  const econOf={},termsOf={};
  sitesArr.forEach(s=>{econOf[s.id]=biEconOf(s);termsOf[s.id]=biTermsOf(s);});
  const tcCum=biCumOf(BI_TC_MONTH_W),flatCum=biCumOf(BI_TIMING_FLAT);
  /* pre-resolve hurricane events to campus groups, grouped by country:
     each country's catalog is independent (its sites are disjoint), so
     every simulated year draws ONE alternative source per country by
     weight and then Poisson-draws that source's events. Each event also
     carries its per-site monthly retained-BI table (Task 3). */
  let huCountries=null;
  if(evScen&&join&&join.matched>0){
    const byCountry={};
    evScen.forEach(part=>{
      const key=part.country||"?";
      (byCountry[key]||(byCountry[key]=[])).push({weight:+part.weight||0,
        events:(part.events||[]).map(e=>{
          const groups={};const biRows=[];
          (e.sites||[]).forEach(pair=>{
            const s=join.map[pair[0]];if(!s)return;
            const g=ded.hurricane.basis==="per-occurrence-program"?"~program":campusKeyOf(s);
            const loss=+pair[1]||0;
            groups[g]=(groups[g]||0)+loss;
            if(loss>0)biRows.push(biMonthlyRetained(loss,termsOf[s.id],econOf[s.id]));
          });
          return {freq:+e.freq||0,groups,biRows};
        }).filter(e=>e.freq>0)});
    });
    huCountries=Object.keys(byCountry).map(k=>byCountry[k]);
  }
  /* per-location bands carry their own monthly retained BI and the
     arrival-month table of their peril, so one draw drives both sides */
  const siteBands=[];
  sitesArr.forEach(s=>{
    ["flood","general"].forEach(cls=>{
      TCOR_CLASS_PERILS[cls].forEach(hz=>{
        const lad=siteLadderFor(s,hz,sc,join);
        const cum=(BI_PERIL_TIMING[hz]||BI_TIMING_FLAT)===BI_TC_MONTH_W?tcCum:flatCum;
        ladderBands(lad.rps,lad.losses).forEach(b=>
          siteBands.push({rate:b.rate,loss:b.loss,ded:ded[cls].amountUsd,
            biMonthly:biMonthlyRetained(b.loss,termsOf[s.id],econOf[s.id]),cum}));
      });
    });
  });
  /* degraded hurricane in the simulation: campus-comonotonic bands for
     property; per-site tc_joint bands for BI (labeled approximation:
     without an event table the two sides draw independently) */
  let huBands=null,huBiBands=null;
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
    huBiBands=[];
    sitesArr.forEach(s=>{
      const lad=siteLadderFor(s,"tc_joint",sc,join);
      ladderBands(lad.rps,lad.losses).forEach(b=>
        huBiBands.push({rate:b.rate,
          biMonthly:biMonthlyRetained(b.loss,termsOf[s.id],econOf[s.id])}));
    });
  }
  const totals=new Array(years),hits=new Array(years),biTotals=new Array(years);
  for(let y=0;y<years;y++){
    let ret=0,nHits=0,biRet=0;
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
            /* one arrival month per occurrence drives every hit site's BI */
            const m=biDrawMonth(tcCum,rnd);
            for(const row of e.biRows)biRet+=row[m];
          }
        });
      });
    }else{
      huBands.forEach(b=>{
        const n=b.rate<0.05?(rnd()<b.rate?1:0):poissonDraw(b.rate,rnd);
        for(let k=0;k<n;k++){ret+=Math.min(b.loss,b.ded);nHits++;}
      });
      huBiBands.forEach(b=>{
        const n=b.rate<0.05?(rnd()<b.rate?1:0):poissonDraw(b.rate,rnd);
        for(let k=0;k<n;k++)biRet+=b.biMonthly[biDrawMonth(tcCum,rnd)];
      });
    }
    siteBands.forEach(b=>{
      const n=b.rate<0.05?(rnd()<b.rate?1:0):poissonDraw(b.rate,rnd);
      for(let k=0;k<n;k++){
        ret+=Math.min(b.loss,b.ded);nHits++;
        biRet+=b.biMonthly[biDrawMonth(b.cum,rnd)];
      }
    });
    totals[y]=cap!=null?Math.min(ret,cap):ret;
    hits[y]=nHits;
    biTotals[y]=biRet;
  }
  const qOf=arr=>{
    const sorted=arr.slice().sort((a,b)=>a-b);
    const q=p=>sorted[Math.min(sorted.length-1,Math.floor(p*sorted.length))];
    return {mean:arr.reduce((a,x)=>a+x,0)/arr.length,
            median:q(0.5),p90:q(0.9),p99:q(0.99)};
  };
  const prop=qOf(totals),bi=qOf(biTotals);
  const combined=qOf(totals.map((x,i)=>x+biTotals[i]));
  return {years,seed,capUsd:cap,
    mean:prop.mean,median:prop.median,p90:prop.p90,p99:prop.p99,
    bi,combined,
    meanHits:hits.reduce((a,x)=>a+x,0)/years,
    basis:(huCountries?"event table":"ladder bands (labeled approximation)")
      +(cap!=null?", annual aggregate cap applied per simulated year (property program only)":"")
      +"; BI retained per occurrence with a seasonal arrival-month draw (Task 3)"};
}

/* ------------------------------------------------------------
   Retained business interruption: the BI module (overhaul Task 3).
   The interim linear transform is retired. Chain per event:
   damage ratio -> downtime days (the Hazus RES4 piecewise nodes on
   the operator's reopen anchor, with the REDi impeding-factor floor
   once damage is structural) -> a seasonal calendar walk over the
   downtime window (regional monthly revenue weights, the event's
   arrival month drawn from the peril's climatology: hurricanes land
   in the September trough but long downtime eats the winter peak) ->
   gross BI on the LOSSABLE share of daily GOP (the vacation-ownership
   fee stream keeps flowing through a closure) -> the unchanged policy
   terms split: waiting period retained on every event, downtime
   beyond the indemnity period, insurable BI beyond the limit. All
   constants live in the sourced assumptions registry.
   The regional demand shock (undamaged sites in a hit region lose
   transient demand; NO physical-damage trigger, so standard BI never
   pays it) is computed on the event table and rides as a FLAGGED
   indirect line, never inside retained BI or the TCOR total.
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
const BI_MONTH_DAYS=30.44;
const BI_TIMING_FLAT=[1/12,1/12,1/12,1/12,1/12,1/12,1/12,1/12,1/12,1/12,1/12,1/12];
/* event-arrival climatology per peril: TC-driven perils land on the
   hurricane calendar; the rest carry no asserted timing */
const BI_PERIL_TIMING={tc_joint:BI_TC_MONTH_W,prain:BI_TC_MONTH_W,
                       rflood:BI_TIMING_FLAT,wfire:BI_TIMING_FLAT};
function biSeasonShapeOf(s){
  return BI_SEASON_SHAPES[slrRegionOf(+s.latitude,+s.longitude)]||BI_SEASON_SHAPES.global_mean;
}
/* revenue-weighted equivalent days of a downtime window starting at the
   beginning of month m0 (0-11): the seasonal calendar walk */
function biSeasonDays(shape,m0,days){
  let left=days,m=m0,acc=0;
  while(left>0){
    const take=Math.min(left,BI_MONTH_DAYS);
    acc+=shape[m%12]*take;left-=take;
    if(++m-m0>600)break;
  }
  return acc;
}
/* damage ratio -> downtime days: piecewise Hazus RES4 nodes as fractions
   of the operator's reopen anchor, then the REDi impeding floor once
   damage is structural (external processes the operator cannot
   compress: inspection, financing, contractor mobilization, permits) */
function biDowntimeDays(dmg,maxDownDays){
  if(!(dmg>0)||!(maxDownDays>0))return 0;
  const N=BI_DOWNTIME_NODES;
  let f=1;
  if(dmg<1){
    for(let i=1;i<N.length;i++){
      if(dmg<=N[i][0]){
        f=N[i-1][1]+(N[i][1]-N[i-1][1])*(dmg-N[i-1][0])/(N[i][0]-N[i-1][0]);
        break;
      }
    }
  }
  let d=f*maxDownDays;
  if(dmg>=BI_IMPEDING_THRESH)d=Math.max(d,BI_IMPEDING_DAYS);
  return d;
}
/* per-site BI economics: seasonal shape, the lossable share of daily
   GOP after the vacation-ownership continuing stream, the reopen anchor */
function biEconOf(s){
  const a=assumeFor(s);
  const gop=siteRevenue(s)*a.gopMargin;
  const tshare=Math.min(Math.max(+s.timeshare_share||0,0),1);
  const continueShare=tshare*BI_TIMESHARE_CONTINUING;
  return {value:+s.asset_value_usd||0,gop,daily:gop/365,
    dailyLossable:(gop/365)*(1-continueShare),
    continueShare,tshare,
    maxDownDays:a.reopenMonths/12*365,
    shape:biSeasonShapeOf(s)};
}
/* the terms split for ONE event loss arriving at month m0. The waiting
   period is the window's first days, the indemnity period its first
   terms.indemnityDays: both priced at the season they actually fall in. */
function biEventSplit(lossUsd,terms,econ,m0){
  const dmg=econ.value>0?Math.min(Math.max(lossUsd,0)/econ.value,1):0;
  const down=biDowntimeDays(dmg,econ.maxDownDays);
  if(!(down>0))return {gross:0,waiting:0,overage:0,retained:0,downDays:0};
  const k=econ.dailyLossable;
  const segAll=biSeasonDays(econ.shape,m0,down);
  const segWait=biSeasonDays(econ.shape,m0,Math.min(down,terms.waitingDays));
  const segIndem=biSeasonDays(econ.shape,m0,Math.min(down,terms.indemnityDays));
  const gross=k*segAll,waiting=k*segWait,beyondIndem=k*(segAll-segIndem);
  const insurable=Math.max(gross-waiting-beyondIndem,0);
  const overLimit=terms.limitUsd!=null?Math.max(insurable-terms.limitUsd,0):0;
  return {gross,waiting,overage:beyondIndem+overLimit,
          retained:waiting+beyondIndem+overLimit,downDays:down};
}
/* expectation over the peril's event-arrival climatology */
function biEventSplitTimed(lossUsd,terms,econ,timing){
  const out={gross:0,waiting:0,overage:0,retained:0,downDays:0};
  for(let m=0;m<12;m++){
    const w=timing[m];if(!(w>0))continue;
    const b=biEventSplit(lossUsd,terms,econ,m);
    out.gross+=w*b.gross;out.waiting+=w*b.waiting;
    out.overage+=w*b.overage;out.retained+=w*b.retained;
    out.downDays+=w*b.downDays;
  }
  return out;
}
function retainedBICalc(sitesArr,sc){
  const join=packJoin(sitesArr,sc);
  const pk=resultsPack&&resultsPack.data;
  const evScen=pk&&pk.event_sets&&pk.event_sets.scenarios&&pk.event_sets.scenarios[sc];
  const perSite={};let waiting=0,overage=0,gross=0;
  const econOf={},termsOf={};
  sitesArr.forEach(s=>{
    econOf[s.id]=biEconOf(s);termsOf[s.id]=biTermsOf(s);
    perSite[s.id]={gross:0,waiting:0,overage:0,retained:0,
      basis:"BI module: Hazus/REDi downtime, seasonal calendar walk"
        +(econOf[s.id].tshare>0?", vacation-ownership continuing share "
          +Math.round(econOf[s.id].continueShare*100)+"%":"")};
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
          const b=biEventSplitTimed(+pair[1]||0,termsOf[s.id],econOf[s.id],BI_TC_MONTH_W);
          const ps=perSite[s.id];
          ps.gross+=w*f*b.gross;ps.waiting+=w*f*b.waiting;
          ps.overage+=w*f*b.overage;ps.retained+=w*f*b.retained;
        });
      });
    });
  }
  sitesArr.forEach(s=>{
    const terms=termsOf[s.id],econ=econOf[s.id];
    const perils=huEventBased?["rflood","prain","wfire"]
                             :["tc_joint","rflood","prain","wfire"];
    perils.forEach(hz=>{
      const lad=siteLadderFor(s,hz,sc,join);
      const timing=BI_PERIL_TIMING[hz]||BI_TIMING_FLAT;
      /* the per-rung terms split once, then the same trapezoid integral
         per field (every field is non-decreasing in the rung loss) */
      const F={gross:[],waiting:[],overage:[],retained:[]};
      lad.losses.forEach(L=>{
        const b=biEventSplitTimed(Math.max(+L||0,0),terms,econ,timing);
        F.gross.push(b.gross);F.waiting.push(b.waiting);
        F.overage.push(b.overage);F.retained.push(b.retained);
      });
      const ps=perSite[s.id];
      ps.gross+=ladderIntegral(lad.rps,F.gross);
      ps.waiting+=ladderIntegral(lad.rps,F.waiting);
      ps.overage+=ladderIntegral(lad.rps,F.overage);
      ps.retained+=ladderIntegral(lad.rps,F.retained);
    });
    gross+=perSite[s.id].gross;waiting+=perSite[s.id].waiting;
    overage+=perSite[s.id].overage;
  });
  /* regional demand shock: event table only (it needs event structure to
     hang on), portfolio TIV as the destination proxy, flagged always */
  const demandPerSite={};sitesArr.forEach(s=>demandPerSite[s.id]=0);
  let demandTotal=0;
  if(huEventBased){
    const regionOf={},regTiv={};
    sitesArr.forEach(s=>{
      const r=slrRegionOf(+s.latitude,+s.longitude);
      regionOf[s.id]=r;regTiv[r]=(regTiv[r]||0)+(+s.asset_value_usd||0);
    });
    const W=BI_DEMAND_SHOCK.months*BI_MONTH_DAYS;
    evScen.forEach(part=>{
      const w=+part.weight||0;
      (part.events||[]).forEach(e=>{
        const f=+e.freq||0;if(f<=0)return;
        const dmgTiv={},downOf={};
        (e.sites||[]).forEach(pair=>{
          const s=join.map[pair[0]];if(!s)return;
          const econ=econOf[s.id];
          const dmg=econ.value>0?Math.min((+pair[1]||0)/econ.value,1):0;
          downOf[s.id]=biDowntimeDays(dmg,econ.maxDownDays);
          if(dmg>=BI_IMPEDING_THRESH){
            const r=regionOf[s.id];
            dmgTiv[r]=(dmgTiv[r]||0)+econ.value;
          }
        });
        for(const reg in dmgTiv){
          const R=regTiv[reg]>0?dmgTiv[reg]/regTiv[reg]:0;
          if(R<BI_DEMAND_SHOCK.min_severity)continue;
          const shock0=Math.min(BI_DEMAND_SHOCK.cap,BI_DEMAND_SHOCK.gain*R);
          sitesArr.forEach(s=>{
            if(regionOf[s.id]!==reg)return;
            const econ=econOf[s.id];
            /* the shock decays linearly over the window and bites only
               while the site is OPEN: closed forward-looking exposure
               integrates to shock0 x (W - ownDown)^2 / 2W */
            const open=Math.max(W-(downOf[s.id]||0),0);
            const g=econ.dailyLossable*shock0*open*open/(2*W);
            demandPerSite[s.id]+=w*f*g;demandTotal+=w*f*g;
          });
        }
      });
    });
  }
  return {perSite,gross,waiting,overage,retained:waiting+overage,
    transferred:gross-waiting-overage,
    demandShock:{total:demandTotal,perSite:demandPerSite,flagged:true,
      excludedFromTotal:true,
      basis:huEventBased
        ?"regional demand shock on the event table: sites in a hit region lose transient demand while open (no physical-damage trigger, so standard BI never pays it); severity-banded to the 2017-2019 record, flagged, never in the TCOR total"
        :"not computed: the demand shock needs the results pack's event table"},
    basis:"BI module (Task 3): Hazus RES4 damage-to-downtime with the REDi "
      +BI_IMPEDING_DAYS+"-day impeding floor, regional seasonality x hurricane "
      +"landfall climatology, vacation-ownership continuing share; "
      +(huEventBased?"hurricane terms applied per event":"no event table: hurricane terms applied on ladders (labeled)"),
    termsProvenance:tcorProgram.bi.provenance};
}

/* ------------------------------------------------------------
   Premium module (Task 4): allocation + the technical-vs-actual gap
   surface. Actual per-site premium wins when the profile carries it
   (SOV columns via schema v3 / the Task 8 importer); else the
   technical benchmark: transferred expected loss (property + insurable
   BI) times the program loading factor. A known program total rescales
   the technical allocation, labeled.

   The gap surface (additive; nothing above changes): per-site rate per
   $100 TIV on both bases, the signed actual-vs-technical gap, and the
   portfolio position: the IMPLIED market load (actual premium over
   modeled transferred expected loss, computed only on the sites whose
   premium is on file) beside the assumed load, plus the over/under
   split. The implied load is the renewal conversation's anchor: it is
   what the market is actually charging per dollar of modeled transfer,
   so a repriced technical benchmark and the payoff engine's negotiated
   savings can stand on the market's own number instead of an
   assumption whenever the SOV carries premiums.
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
    const transferredEl=transProp+transBi;
    const technical=transferredEl*load;
    technicalTotal+=technical;
    const actual=+s.premium_annual_usd>0?+s.premium_annual_usd:null;
    if(actual!=null){actualTotal+=actual;nActual++;}
    perSite[s.id]={technical,actual,transferredEl,
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
  /* the gap surface: rates, signed gaps, implied market load */
  let tiv=0,tivActual=0,actTransEl=0,overTech=0,underTech=0;
  sitesArr.forEach(s=>{
    const v=+s.asset_value_usd||0;tiv+=v;
    const ps=perSite[s.id];
    ps.ratePer100=v>0?ps.allocated/v*100:null;
    ps.technicalRatePer100=v>0?ps.technical/v*100:null;
    if(ps.actual!=null){
      tivActual+=v;actTransEl+=ps.transferredEl;
      ps.gapUsd=ps.actual-ps.technical;
      ps.gapPct=ps.technical>0?(ps.actual/ps.technical-1)*100:null;
      if(ps.gapUsd>0)overTech+=ps.gapUsd;else underTech-=ps.gapUsd;
    }else{ps.gapUsd=null;ps.gapPct=null;}
  });
  const impliedLoad=(nActual>0&&actTransEl>0)?actualTotal/actTransEl:null;
  return {perSite,technicalTotal,actualTotal,nActual,load,
    allocatedTotal:sitesArr.reduce((a,s)=>a+perSite[s.id].allocated,0),
    allocBasis,
    position:{impliedLoad,assumedLoad:load,
      loadBasis:impliedLoad!=null
        ?"implied by the "+nActual+" premium"+(nActual>1?"s":"")+" on file (actual premium / modeled transferred expected loss)"
        :"assumed (no per-site premiums on file)",
      tivShareWithActual:tiv>0?tivActual/tiv:0,
      overTechnicalUsd:overTech,underTechnicalUsd:underTech,
      gapTotalUsd:overTech-underTech,
      note:"gaps read on sites with an actual premium only; a positive gap "
        +"means paying above the modeled technical benchmark"}};
}
/* the loading factor negotiated savings should stand on: the market's own
   implied load when premiums are on file, else the assumed program load */
function premiumLoadEff(prem){
  return (prem&&prem.position&&prem.position.impliedLoad!=null)
    ?prem.position.impliedLoad:(prem?prem.load:1.5);
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
    indirect:{value:b.gross*tcorProgram.indirect.rebookShare
        +((ctx.bi.demandShock&&ctx.bi.demandShock.perSite[s.id])||0),
      rebooking:b.gross*tcorProgram.indirect.rebookShare,
      demandShock:(ctx.bi.demandShock&&ctx.bi.demandShock.perSite[s.id])||0,
      flagged:true,excludedFromTotal:true,
      basis:"flagged estimate: guest rebooking ("+Math.round(tcorProgram.indirect.rebookShare*100)
        +"% of gross BI) plus the regional demand shock at open sites; never added to the TCOR total"},
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
