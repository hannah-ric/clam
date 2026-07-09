/* ============================================================
   TCOR-aware adaptation payoff engine (v3 overhaul).
   A measure's annual payoff is NOT one number: part of it the owner
   keeps with certainty (reduced retained losses: below-deductible
   damage, waiting-period and over-limit BI, uninsured heat cost), and
   part of it only becomes cash if the insurer reprices at renewal
   (reduced TRANSFERRED expected loss, priced at the program load and
   haircut by a credit-realization factor, because market recognition
   of mitigation is bounded and discretionary). This engine computes
   both halves per (site, measure) through the SAME ladder-and-terms
   math the TCOR engine stands on, and reports the benefit-cost ratio
   twice: certain-only, and with the negotiated premium credit. The
   two are never blended silently.

   Accounting discipline (NIST SP 1197's rule: count premium savings
   OR avoided payouts, never both): certain savings are reductions in
   the owner's own retained losses; the negotiated half prices ONLY
   the transferred slice. No dollar appears on both sides.

   READ-ONLY over the hazard, adaptation, TCOR, and premium engines:
   the measure's per-return-period effect comes from adaptedFinSite's
   own curves, the retained/transferred split from the TCOR ladders
   and deductibles (campus-shared for hurricane), the load from the
   premium module (market-implied when premiums are on file).
   ============================================================ */

function payoffCreditRealization(){
  const v=tcorProgram.premium.creditRealization;
  return (v!=null&&isFinite(+v))?Math.min(Math.max(+v,0),1):PREMIUM_CREDIT_REALIZATION;
}

/* per-return-period loss-reduction factors a measure causes, per peril,
   read off the adaptation engine's own curves (base vs modified) */
function payoffFactors(s,sc,mods){
  const base=adaptedFinSite(s,sc,{}),mod=adaptedFinSite(s,sc,mods);
  const fac={};
  ["tc","cflood","rflood","prain"].forEach(hz=>{
    const o={};
    RPS.forEach((rp,i)=>{
      const b=base.curves[hz][i]?base.curves[hz][i].loss:0;
      o[rp]=b>0?(mod.curves[hz][i]?mod.curves[hz][i].loss:0)/b:1;
    });
    fac[hz]=o;
  });
  /* tc_joint (the hurricane occurrence basis): loss-weighted blend of
     the wind and surge factors at each return period */
  const oj={};
  RPS.forEach((rp,i)=>{
    const bw=base.curves.tc[i]?base.curves.tc[i].loss:0;
    const bc=base.curves.cflood[i]?base.curves.cflood[i].loss:0;
    const mw=mod.curves.tc[i]?mod.curves.tc[i].loss:0;
    const mc=mod.curves.cflood[i]?mod.curves.cflood[i].loss:0;
    oj[rp]=(bw+bc)>0?(mw+mc)/(bw+bc):1;
  });
  fac.tc_joint=oj;
  fac.wfire=base.curves.wfireFrac>0?mod.curves.wfireFrac/base.curves.wfireFrac:1;
  return {base,mod,fac};
}
/* scale a TCOR ladder rung by rung; the sub-1-in-10 rungs (2, 5) ride
   the 1-in-10 factor (they are extrapolated from it in the first place) */
function payoffScaleLadder(lad,facByRp){
  return {rps:lad.rps.slice(),basis:lad.basis,
    losses:lad.losses.map((L,i)=>{
      const rp=lad.rps[i];
      const k=facByRp[rp]!=null?facByRp[rp]:facByRp[10];
      return (+L||0)*(k==null?1:k);
    })};
}

/* hurricane: the campus (or program) shares ONE occurrence deductible,
   so a single site's hardening changes the CAMPUS retained ladder;
   both sides are computed on the shared ladder, never per site alone */
function payoffHurricane(s,sitesArr,sc,join,facJoint){
  const ded=tcorProgram.deductibles.hurricane;
  const members=(ded.basis==="per-occurrence-program")?sitesArr
    :sitesArr.filter(x=>campusKeyOf(x)===campusKeyOf(s));
  const lads=members.map(x=>({x,lad:siteLadderFor(x,"tc_joint",sc,join)}));
  const myBase=(lads.find(z=>z.x.id===s.id)||{lad:siteLadderFor(s,"tc_joint",sc,join)}).lad;
  const rps=myBase.rps;
  const baseLosses=rps.map((_,i)=>lads.reduce((a,z)=>a+(+z.lad.losses[i]||0),0));
  const myMod=payoffScaleLadder(myBase,facJoint);
  const modLosses=rps.map((_,i)=>baseLosses[i]-(+myBase.losses[i]||0)+(+myMod.losses[i]||0));
  const rb=ladderRetained(rps,baseLosses,ded.amountUsd);
  const rm=ladderRetained(rps,modLosses,ded.amountUsd);
  return {dGross:Math.max(ladderIntegral(rps,myBase.losses)-ladderIntegral(rps,myMod.losses),0),
          dRetained:Math.max(rb.retained-rm.retained,0),
          modLadder:myMod};
}
/* flood and general: per-location ladders, one deductible per site */
function payoffPerLocation(s,sc,join,fac){
  const out={dGross:0,dRetained:0,mod:{}};
  ["flood","general"].forEach(cls=>{
    const dd=tcorProgram.deductibles[cls].amountUsd;
    TCOR_CLASS_PERILS[cls].forEach(hz=>{
      const lad=siteLadderFor(s,hz,sc,join);
      const mlad=hz==="wfire"
        ?{rps:lad.rps.slice(),basis:lad.basis,
          losses:lad.losses.map(L=>(+L||0)*fac.wfire)}
        :payoffScaleLadder(lad,fac[hz]);
      const rb=ladderRetained(lad.rps,lad.losses,dd);
      const rm=ladderRetained(mlad.rps,mlad.losses,dd);
      out.dGross+=Math.max(rb.gross-rm.gross,0);
      out.dRetained+=Math.max(rb.retained-rm.retained,0);
      out.mod[hz]=mlad;
    });
  });
  return out;
}
/* BI delta through the Task 3 chain on base vs modified ladders; a
   reopen-time measure additionally shortens the downtime anchor */
function payoffBI(s,sc,join,modLads,reopenMult){
  const terms=biTermsOf(s);
  const econB=biEconOf(s);
  const econM=(reopenMult==null||reopenMult===1)?econB
    :Object.assign({},econB,{maxDownDays:econB.maxDownDays*reopenMult});
  const perils=["tc_joint","rflood","prain","wfire"];
  let bGross=0,bRet=0,mGross=0,mRet=0;
  perils.forEach(hz=>{
    const timing=BI_PERIL_TIMING[hz]||BI_TIMING_FLAT;
    const ladB=siteLadderFor(s,hz,sc,join);
    const ladM=modLads[hz]||ladB;
    const FB={gross:[],retained:[]},FM={gross:[],retained:[]};
    ladB.losses.forEach(L=>{
      const b=biEventSplitTimed(Math.max(+L||0,0),terms,econB,timing);
      FB.gross.push(b.gross);FB.retained.push(b.retained);
    });
    ladM.losses.forEach(L=>{
      const b=biEventSplitTimed(Math.max(+L||0,0),terms,econM,timing);
      FM.gross.push(b.gross);FM.retained.push(b.retained);
    });
    bGross+=ladderIntegral(ladB.rps,FB.gross);bRet+=ladderIntegral(ladB.rps,FB.retained);
    mGross+=ladderIntegral(ladM.rps,FM.gross);mRet+=ladderIntegral(ladM.rps,FM.retained);
  });
  return {dGross:Math.max(bGross-mGross,0),dRetained:Math.max(bRet-mRet,0)};
}

/* the payoff of one measure at one site, split and priced */
function tcorPayoffFor(s,m,st,sc,ctx){
  ctx=ctx||{};
  const sitesArr=ctx.sites||(typeof sites!=="undefined"?sites:[s]);
  const join=(ctx.join!==undefined)?ctx.join:packJoin(sitesArr,sc);
  const mods=m.mods(st);
  const pf=payoffFactors(s,sc,mods);
  const hu=payoffHurricane(s,sitesArr,sc,join,pf.fac.tc_joint);
  const pl=payoffPerLocation(s,sc,join,pf.fac);
  const modLads=Object.assign({tc_joint:hu.modLadder},pl.mod);
  const bi=payoffBI(s,sc,join,modLads,mods.reopenMult);
  const heat=Math.max(pf.base.heatCost-pf.mod.heatCost,0);
  const dRetainedProp=hu.dRetained+pl.dRetained;
  const dGrossProp=hu.dGross+pl.dGross;
  const certain=dRetainedProp+bi.dRetained+heat;
  const dTransferred=Math.max(dGrossProp-dRetainedProp,0)
    +Math.max(bi.dGross-bi.dRetained,0);
  const loadEff=ctx.prem?premiumLoadEff(ctx.prem)
    :(tcorProgram.premium.loadFactor!=null?tcorProgram.premium.loadFactor
      :(typeof adapt!=="undefined"&&adapt&&adapt.load?adapt.load:1.5));
  const cr=payoffCreditRealization();
  const premiumSaving=dTransferred*loadEff*cr;
  const cost=m.siteCost(s,st);
  const af=ctx.af!=null?ctx.af
    :annuity(APPRAISAL_DEFAULTS.horizonYears,APPRAISAL_DEFAULTS.discountPct/100);
  return {measure:m.name,key:m.key,target:m.target,cost,af,
    certain:{property:dRetainedProp,bi:bi.dRetained,heat,total:certain},
    negotiated:{transferredEl:dTransferred,loadEff,creditRealization:cr,premiumSaving},
    grossAverted:dGrossProp+bi.dGross+heat,
    bcrCertain:cost>0?certain*af/cost:0,
    bcrWithCredit:cost>0?(certain+premiumSaving)*af/cost:0,
    basis:"TCOR ladder basis"
      +(join?" (pack ladders where loaded)":" (interim ladders)")
      +": certain = retained property + retained BI + uninsured heat; "
      +"negotiated = transferred-loss reduction x "+loadEff.toFixed(2)
      +" load x "+Math.round(cr*100)+"% credit realization, cash only if the insurer reprices"};
}
/* every in-scope measure at one site, appraised and split */
function sitePayoffs(s,sc,ctx){
  return MEASURES.filter(m=>m.inScope(s,sc))
    .map(m=>tcorPayoffFor(s,m,adapt.m[m.key],sc,ctx))
    .sort((a,b)=>b.bcrCertain-a.bcrCertain);
}
/* the renewal ask: the funded action queue's negotiated premium savings,
   the number the broker submission carries into the renewal meeting */
function renewalAskFor(sitesArr,sc,af,budget,ctx){
  const q=actionQueue(sitesArr,sc,af,budget||0);
  let ask=0,certain=0,n=0;
  q.items.forEach(it=>{
    if(!it.funded)return;
    const s=sitesArr.find(x=>x.id===it.id);if(!s)return;
    const m=MEASURES.find(x=>x.key===it.key);if(!m)return;
    const p=tcorPayoffFor(s,m,adapt.m[m.key],sc,
      Object.assign({sites:sitesArr,af},ctx||{}));
    ask+=p.negotiated.premiumSaving;certain+=p.certain.total;n++;
  });
  return {n,premiumAskUsd:ask,certainUsd:certain,
    note:"summed per funded measure; overlapping measures at one site are "
      +"not jointly recomputed here, so read it as the upper end of the ask"};
}
