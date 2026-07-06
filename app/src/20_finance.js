const ACUTE=["tc","cflood","rflood","prain","wfire"];
const HEAT_COMFORT_DAYS=15;                 // days over 35C treated as baseline-normal
let finAssume={revRatio:0.35,gopMargin:0.30,reopenMonths:12,heatDrop:0.12,corr:0.30};
/* Risk tolerance (Wave 1 decision layer): the operator's documented
   materiality thresholds. A policy layer only: these values never change a
   computed figure, they only decide what counts as a breach. Defaults are
   anchored to stated practice (see the INFO entry) and are meant to be
   edited; edits persist and become the portfolio's documented tolerance. */
let tolerance={siteAalBps:75,portAalPct:1.0,varPctValue:10};
function siteRevenue(s){ return (s.annual_revenue_usd>0)?s.annual_revenue_usd:s.asset_value_usd*finAssume.revRatio; }
function finSite(s,sc){
  const value=s.asset_value_usd, revenue=siteRevenue(s), gop=revenue*finAssume.gopMargin;
  const maxDownDays=finAssume.reopenMonths/12*365, dailyGop=gop/365;
  const directByRp={},biByRp={}; RPS.forEach(rp=>{directByRp[rp]=0;biByRp[rp]=0;});
  let directEad=0,biEad=0;
  for(const hz of ACUTE){
    const r=hzSite(s,hz,sc);                              // direct damage for this peril
    directEad+=r.ead;
    biEad+=gop*(finAssume.reopenMonths/12)*(r.eadPct/100);// BI EAD = annual GOP x reopen-share x damage-EAD fraction
    r.curve.forEach(c=>{ directByRp[c.rp]+=c.loss; biByRp[c.rp]+=dailyGop*maxDownDays*(value?c.loss/value:0); });
  }
  // chronic heat: profit at risk from dangerous-heat days (over 35C) above a comfort baseline
  const ind=heatIndicators(s.latitude,s.longitude,sc);
  const excess=Math.max(0,ind.daysOver35-HEAT_COMFORT_DAYS);
  const heatCost=dailyGop*excess*finAssume.heatDrop;
  const totalAal=directEad+biEad+heatCost;
  return {value,revenue,gop,directEad,biEad,heatCost,totalAal,
    acuteAal:directEad+biEad,chronicAal:heatCost,directByRp,biByRp,heatDays:ind.daysOver32,excess};
}
function finPortfolio(sites,sc){
  const rows=sites.map(s=>Object.assign({name:s.name,brand:s.brand,id:s.id},finSite(s,sc)));
  const sum=k=>rows.reduce((a,r)=>a+r[k],0);
  const value=sum("value"),revenue=sum("revenue");
  // diversified tail: sites rarely share one event, so blend fully-correlated
  // (sum) and independent (root-sum-square) via the correlation assumption.
  const rho=finAssume.corr;
  const varByRp={};RPS.forEach(rp=>{
    let sv=0,sq=0;rows.forEach(r=>{const v=r.directByRp[rp]+r.biByRp[rp];sv+=v;sq+=v*v;});
    varByRp[rp]=Math.sqrt(Math.max(0,(1-rho)*sq+rho*sv*sv));
  });
  const directEad=sum("directEad"),biEad=sum("biEad"),heatCost=sum("heatCost"),totalAal=sum("totalAal");
  return {rows,value,revenue,directEad,biEad,heatCost,totalAal,
    acuteAal:directEad+biEad,chronicAal:heatCost,
    aalPctValue:value?totalAal/value*100:0,aalPctRev:revenue?totalAal/revenue*100:0,
    var100:varByRp[100],var250:varByRp[250],varByRp};
}
// TCFD/ISSB-style disclosure rows: present plus the selected pathway at 2050 and 2080
function finDisclosure(sites,pathway){
  const pw=(pathway&&pathway!=="present")?pathway:"ssp245";
  const scens=[["Present day","present"],[PATHWAY_LABEL[pw]+" \u00b7 2050",pw+"_2050"],[PATHWAY_LABEL[pw]+" \u00b7 2080",pw+"_2080"]];
  return scens.map(([label,sc])=>{const f=finPortfolio(sites,sc);
    return {label,acutePct:f.value?f.acuteAal/f.value*100:0,chronicPct:f.value?f.chronicAal/f.value*100:0,
      totalPct:f.aalPctValue,var100Pct:f.value?f.var100/f.value*100:0};});
}
/* Aggregate across every risk: one expected-annual-cost total, decomposed two
   consistent ways (by peril and by cost type), plus the portfolio band mix.
   This is the single all-risk picture the Summary tab is built on. */
function aggregatePortfolio(sites,sc){
  const f=finPortfolio(sites,sc);
  const gopShare=finAssume.reopenMonths/12;
  const byPeril={};ACUTE.forEach(hz=>byPeril[hz]=0);byPeril.heat=f.heatCost;
  sites.forEach(s=>{
    const gop=siteRevenue(s)*finAssume.gopMargin;
    ACUTE.forEach(hz=>{const r=hzSite(s,hz,sc);byPeril[hz]+=r.ead+gop*gopShare*(r.eadPct/100);});
  });
  const byType={direct:f.directEad,bi:f.biEad,heat:f.heatCost};
  const perSite=f.rows.map(r=>({name:r.name,brand:r.brand,total:r.totalAal,value:r.value,revenue:r.revenue}));
  const byBrand={};perSite.forEach(r=>{const b=r.brand||"Unbranded";byBrand[b]=(byBrand[b]||0)+r.total;});
  const bands={Minimal:0,Low:0,Moderate:0,High:0,Severe:0};
  scorePhysTotal(sites,sc).rows.forEach(r=>bands[r.band]=(bands[r.band]||0)+1);
  return {total:f.total||f.totalAal,f,byPeril,byType,perSite,byBrand,bands};
}

