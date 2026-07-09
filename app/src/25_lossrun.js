/* ============================================================
   Loss-run calibration (overhaul Task 5)
   The portfolio owner's actual claims history is the anchor that grounds the modeled
   TCOR. This module ingests the loss run (claims report), maps claimants
   to sites and Coverage Major to CLAM's peril/coverage classes, groups
   claims into events (so a storm that hit six sites is ONE occurrence,
   which also validates the shared-deductible logic), aggregates actual
   retained loss by site / peril / year / event, and compares the model's
   frequent layers against it.

   Credibility limits, enforced in code: a few years of claims can
   calibrate the BODY of the distribution (attritional hits, BI) but
   NEVER the rare-cat tail. Named-catastrophe claims are split out and
   reported, the tail stays modeled and labeled, and open claims are
   flagged as developing (Net Incurred carries reserves that can move).
   Where model and actuals disagree materially, the disagreement is the
   headline, not a footnote.
   ============================================================ */
let lossRun=null;    // {claims, name, loaded, years, flags} or null

/* header aliases: the report arrives from a TPA with names that drift */
const LOSSRUN_ALIASES={
  claim_no:["claim number","claim no","claim #","claim","claimnumber"],
  date_of_loss:["date of loss","loss date","dol","date"],
  claimant:["claimant name","claimant","insured location","location name","site"],
  coverage:["coverage major","coverage","coverage line","line","peril"],
  status:["status","claim status"],
  carrier:["tpa/carrier","carrier","tpa"],
  net_paid:["net paid","paid","net paid amount"],
  net_outstanding:["net outstanding","outstanding","reserves","net outstanding amount"],
  recovery:["recovery received","recovery","recoveries"],
  net_incurred:["net incurred","incurred","net incurred amount","total incurred"],
  area:["area of impact","area","impact area"],
  description:["event description","description","loss description","cause"]
};
function lossrunHeaderMap(head){
  const m={};
  for(const key in LOSSRUN_ALIASES){
    for(const alias of LOSSRUN_ALIASES[key]){
      const i=head.indexOf(alias);
      if(i>=0){m[key]=alias;break;}
    }
  }
  return m;
}
function lossrunMoney(v){
  if(v==null)return null;
  const n=parseFloat(String(v).replace(/[$,()\s]/g,m=>m==="("?"-":""));
  return isFinite(n)?n:null;
}
function lossrunDate(v){
  const s=String(v==null?"":v).trim();if(!s)return null;
  let m=s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
  if(m)return {y:+m[1],mo:+m[2],d:+m[3]};
  m=s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})/);
  if(m){const y=+m[3]<100?2000+ +m[3]:+m[3];return {y,mo:+m[1],d:+m[2]};}
  return null;
}
function lossrunDayNum(dt){ return dt?Math.floor(Date.UTC(dt.y,dt.mo-1,dt.d)/86400000):null; }

/* Coverage Major -> CLAM peril/coverage class. Keyword rules, editable;
   anything unmatched is FLAGGED unmapped, never silently bucketed. */
function coverageClassOf(coverage){
  const c=String(coverage==null?"":coverage).toLowerCase();
  if(!c.trim())return null;
  if(/named\s*storm|hurricane|wind|tropical|cyclone|hail/.test(c))return {cls:"hurricane",kind:"property"};
  if(/business\s*int|time\s*element|\bbi\b|extra\s*expense|rental\s*income|loss\s*of\s*income/.test(c))return {cls:"bi",kind:"bi"};
  if(/flood|surge|water\s*damage|storm\s*water/.test(c))return {cls:"flood",kind:"property"};
  if(/fire|wildfire|smoke/.test(c))return {cls:"general",kind:"property"};
  if(/property|all\s*risk|apd|building|equipment\s*breakdown/.test(c))return {cls:"general",kind:"property"};
  return null;
}

/* claimant -> site: site_id, exact name, then containment either way on
   normalized names. Unmatched claimants are flagged with their dollars. */
function lossrunNorm(x){
  return String(x==null?"":x).toLowerCase()
    .replace(/\b(resort|club|villas?|inn|hotel|the|at|by|llc|inc|assn|association|hoa)\b/g," ")
    .replace(/[^a-z0-9]+/g," ").trim();
}
function lossrunSiteMatch(claimant,sitesArr){
  const cn=lossrunNorm(claimant);if(!cn)return null;
  for(const s of sitesArr){
    const sid=String(s.site_id==null?"":s.site_id).trim().toLowerCase();
    if(sid&&sid===String(claimant).trim().toLowerCase())return s;
  }
  for(const s of sitesArr)if(lossrunNorm(s.name)===cn)return s;
  for(const s of sitesArr){
    const sn=lossrunNorm(s.name);
    if(sn&&(cn.indexOf(sn)>=0||sn.indexOf(cn)>=0))return s;
  }
  return null;
}

function loadLossRun(text,name){
  const {head,out}=parseCsv(text);
  const cols=lossrunHeaderMap(head);
  const need=["date_of_loss","claimant","coverage","net_incurred"];
  const missing=need.filter(k=>!cols[k]&&!(k==="net_incurred"&&cols.net_paid));
  if(missing.length){
    toast("Loss run is missing required column(s): "+missing.join(", ")+".");
    return;
  }
  const claims=[];let skipped=0,basisMismatch=0,basisChecked=0;
  out.forEach(row=>{
    const dt=lossrunDate(row.get(cols.date_of_loss));
    if(!dt){skipped++;return;}
    const paid=lossrunMoney(cols.net_paid?row.get(cols.net_paid):null);
    const outst=lossrunMoney(cols.net_outstanding?row.get(cols.net_outstanding):null);
    const rec=lossrunMoney(cols.recovery?row.get(cols.recovery):null);
    let inc=lossrunMoney(cols.net_incurred?row.get(cols.net_incurred):null);
    let incBasis="reported";
    if(inc==null){
      if(paid==null){skipped++;return;}
      inc=(paid||0)+(outst||0)-(rec||0);incBasis="derived (paid + outstanding - recovery)";
    }else if(paid!=null&&outst!=null){
      basisChecked++;
      if(Math.abs(inc-((paid||0)+(outst||0)-(rec||0)))>Math.max(1,Math.abs(inc)*0.02))basisMismatch++;
    }
    const status=String(cols.status?row.get(cols.status)||"":"").trim().toLowerCase();
    claims.push({
      claimNo:String(cols.claim_no?row.get(cols.claim_no)||"":"").trim(),
      date:dt,day:lossrunDayNum(dt),year:dt.y,
      claimant:String(row.get(cols.claimant)||"").trim(),
      coverage:String(row.get(cols.coverage)||"").trim(),
      open:/open|pend/.test(status),
      carrier:String(cols.carrier?row.get(cols.carrier)||"":"").trim(),
      netPaid:paid,netOutstanding:outst,recovery:rec,
      netIncurred:inc,incBasis,
      area:String(cols.area?row.get(cols.area)||"":"").trim(),
      desc:String(cols.description?row.get(cols.description)||"":"").trim()
    });
  });
  if(!claims.length){toast("No usable claims found in that file.");return;}
  const years=claims.map(c=>c.year);
  const flags=[];
  if(skipped)flags.push(skipped+" row(s) skipped (no parseable date or amount)");
  if(basisMismatch)flags.push(basisMismatch+" of "+basisChecked+" claims where Net Incurred does not equal paid + outstanding - recovery: CONFIRM the report's Net Incurred basis (assumed net of recovery)");
  const openN=claims.filter(c=>c.open).length;
  if(openN)flags.push(openN+" open claim(s): Net Incurred includes reserves that may still move (development risk)");
  lossRun={claims,name:name||"loss_run.csv",loaded:new Date().toISOString(),
    years:{min:Math.min.apply(null,years),max:Math.max.apply(null,years),
           n:Math.max(Math.max.apply(null,years)-Math.min.apply(null,years)+1,1)},
    flags};
  if(typeof persistLossRun==="function")persistLossRun();
  toast("Loss run loaded: "+claims.length+" claims, "+lossRun.years.min+"-"+lossRun.years.max);
  render();
}

/* group claims into events: named catastrophes by storm name, else
   same-class claims within a 3-day window. Multi-site events are the
   ground truth the shared-deductible logic is validated against. */
function lossrunEventKey(c){
  const m=(c.desc||"").match(/\b(?:hurricane|tropical\s+storm|ts\.?|typhoon)\s+([a-z]+)/i);
  if(m)return {key:"storm:"+m[1].toLowerCase()+":"+c.year,named:true};
  return null;
}
function groupClaimEvents(claims,sitesArr){
  const withMap=claims.map(c=>{
    const cov=coverageClassOf(c.coverage);
    return {c,cov,site:lossrunSiteMatch(c.claimant,sitesArr||[]),
            namedEv:lossrunEventKey(c)};
  });
  const events={};
  const clustered=[];
  withMap.forEach(x=>{
    if(x.namedEv){(events[x.namedEv.key]||(events[x.namedEv.key]={key:x.namedEv.key,named:true,claims:[]})).claims.push(x);}
    else clustered.push(x);
  });
  clustered.sort((a,b)=>(a.c.day||0)-(b.c.day||0));
  let cur=null,seq=0;
  clustered.forEach(x=>{
    const cls=x.cov?x.cov.cls:"unmapped";
    if(cur&&cls===cur.cls&&x.c.day!=null&&cur.lastDay!=null&&x.c.day-cur.lastDay<=3){
      cur.claims.push(x);cur.lastDay=x.c.day;
    }else{
      const key="ev:"+cls+":"+(x.c.day!=null?x.c.day:"n"+(seq++));
      cur={key,named:false,cls,lastDay:x.c.day,claims:[x]};
      events[key]=cur;
    }
  });
  return Object.keys(events).map(k=>{
    const e=events[k];
    const siteIds={};e.claims.forEach(x=>{if(x.site)siteIds[x.site.id]=true;});
    return {key:e.key,named:!!e.named,
      nClaims:e.claims.length,
      nSites:Object.keys(siteIds).length,
      totalIncurred:e.claims.reduce((a,x)=>a+(x.c.netIncurred||0),0),
      year:e.claims[0].c.year,
      claims:e.claims};
  }).sort((a,b)=>b.totalIncurred-a.totalIncurred);
}

/* actual retained loss aggregated by site, peril class, year, and event,
   with unmatched claimants and unmapped coverages flagged (with dollars,
   so nobody can ignore them) */
function lossrunAggregates(sitesArr){
  if(!lossRun)return null;
  const evs=groupClaimEvents(lossRun.claims,sitesArr);
  const bySite={},byClass={},byYear={},unmatched={},unmapped={};
  let matchedIncurred=0,totalIncurred=0,openIncurred=0;
  evs.forEach(ev=>ev.claims.forEach(x=>{
    const inc=x.c.netIncurred||0;totalIncurred+=inc;
    if(x.c.open)openIncurred+=inc;
    if(!x.site){unmatched[x.c.claimant]=(unmatched[x.c.claimant]||0)+inc;}
    if(!x.cov){unmapped[x.c.coverage||"(blank)"]=(unmapped[x.c.coverage||"(blank)"]||0)+inc;}
    if(x.site&&x.cov){
      matchedIncurred+=inc;
      const sid=x.site.id;
      (bySite[sid]||(bySite[sid]={site:x.site.name,total:0,byClass:{}}));
      bySite[sid].total+=inc;
      bySite[sid].byClass[x.cov.cls]=(bySite[sid].byClass[x.cov.cls]||0)+inc;
      byClass[x.cov.cls]=(byClass[x.cov.cls]||0)+inc;
      byYear[x.c.year]=(byYear[x.c.year]||0)+inc;
    }
  }));
  return {events:evs,bySite,byClass,byYear,
    unmatched,unmapped,
    matchedIncurred,totalIncurred,openIncurred,
    openShare:totalIncurred?openIncurred/totalIncurred:0,
    years:lossRun.years,flags:lossRun.flags.slice()};
}

/* ------------------------------------------------------------
   The calibration itself: modeled frequent layers vs actual claims.
   Present-day scenario only (claims are history, not a pathway).
   ------------------------------------------------------------ */
function lossrunCalibration(sitesArr){
  const agg=lossrunAggregates(sitesArr);
  if(!agg)return null;
  const nYears=agg.years.n;
  const sc="present";
  const prop=retainedPropertyCalc(sitesArr,sc);
  const bi=retainedBICalc(sitesArr,sc);
  /* split actuals: named-cat events belong to the tail conversation; the
     body (everything else) is what a short record can actually calibrate */
  let namedIncurred=0,bodyIncurred=0;
  const bodyByClass={},bodyClaimYears={};
  agg.events.forEach(ev=>{
    if(ev.named){namedIncurred+=ev.totalIncurred;return;}
    bodyIncurred+=ev.totalIncurred;
    ev.claims.forEach(x=>{
      if(x.cov&&x.site){
        bodyByClass[x.cov.cls]=(bodyByClass[x.cov.cls]||0)+(x.c.netIncurred||0);
        if(x.cov.kind==="property")bodyClaimYears[x.c.year]=(bodyClaimYears[x.c.year]||0)+1;
      }
    });
  });
  const perClass=[];
  ["hurricane","flood","general"].forEach(cls=>{
    const modeled=prop.classes[cls]?prop.classes[cls].annualRetained:0;
    const actual=(cls==="hurricane"
      ?((agg.byClass.hurricane||0))            // named + body wind claims
      :(bodyByClass[cls]||0))/nYears;
    const ratio=actual>0?modeled/actual:null;
    perClass.push({cls,modeledAnnualRetained:modeled,actualAnnualIncurred:actual,
      ratio,
      bias:ratio!=null&&(ratio>2||ratio<0.5)
        ?(ratio>2?"model HIGH vs actuals":"model LOW vs actuals"):null,
      note:cls==="hurricane"
        ?"actuals include named storms; a short record understates the modeled tail by construction, so this ratio reads on the deductible-frequency body only"
        :"body claims only (named catastrophes excluded)"});
  });
  const modeledBI=bi.retained;
  const actualBI=(agg.byClass.bi||0)/nYears;
  const biRatio=actualBI>0?modeledBI/actualBI:null;
  /* attritional frequency: modeled deductible hits per year vs actual
     property claims per year in the body */
  const actualClaimsPerYear=Object.keys(bodyClaimYears).length
    ?Object.keys(bodyClaimYears).reduce((a,y)=>a+bodyClaimYears[y],0)/nYears:0;
  const modeledHits=prop.attritional.frequentHitsPerYear
    +prop.attritional.hurricaneOccurrencesPerYear;
  /* shared-deductible reality check: do multi-site actual events exist,
     and does the model produce multi-site occurrences too */
  const actualMulti=agg.events.filter(e=>e.nSites>1).length;
  const disagreements=[];
  perClass.forEach(p=>{if(p.bias)disagreements.push("retained "+p.cls+" is "
    +(p.ratio>1?p.ratio.toFixed(1)+"x actual":"1/"+(1/p.ratio).toFixed(1)+" of actual")
    +" over "+nYears+" year(s) of claims: "+p.bias);});
  if(biRatio!=null&&(biRatio>2||biRatio<0.5))
    disagreements.push("retained BI is "+(biRatio>1?biRatio.toFixed(1)+"x":"1/"+(1/biRatio).toFixed(1)+" of")
      +" actual BI claims: review the damage-to-downtime chain");
  if(actualClaimsPerYear>0&&(modeledHits>3*actualClaimsPerYear||modeledHits<actualClaimsPerYear/3))
    disagreements.push("modeled deductible hits ("+modeledHits.toFixed(1)
      +"/yr) vs actual property claims ("+actualClaimsPerYear.toFixed(1)
      +"/yr) differ beyond 3x: the attritional layer needs review");
  return {years:agg.years,nYears,
    perClass,
    bi:{modeledAnnualRetained:modeledBI,actualAnnualIncurred:actualBI,ratio:biRatio},
    attritional:{modeledHitsPerYear:modeledHits,actualClaimsPerYear},
    multiSite:{actualMultiSiteEvents:actualMulti,
      modeledBasis:prop.classes.hurricane.basis,
      note:actualMulti>0
        ?"the loss run confirms multi-site occurrences: the shared per-occurrence deductible is the correct aggregation"
        :"no multi-site event in the record yet; the shared-deductible rule still applies by policy terms"},
    tail:{namedCatIncurred:namedIncurred,
      note:"the record ("+nYears+" year(s)) calibrates the BODY (attritional + BI) only; the rare-cat tail stays MODELED and labeled - do not scale it to a short record"},
    development:{openShare:agg.openShare,
      flagged:agg.openShare>0.1,
      note:agg.openShare>0?"open claims are "+(agg.openShare*100).toFixed(0)+"% of incurred: figures will develop":"all claims closed"},
    unmatched:agg.unmatched,unmapped:agg.unmapped,
    disagreements,
    materialDisagreement:disagreements.length>0,
    flags:agg.flags};
}
