const UNC_FACTORS=[
  {key:"haz",label:"Hazard intensity \u00b18%",lo:{hazMult:0.92},hi:{hazMult:1.08}},
  {key:"dmg",label:"Damage-curve steepness \u221230/+40%",lo:{dmgScale:0.70},hi:{dmgScale:1.40}},
  {key:"exp",label:"Asset values \u00b115%",lo:{expMult:0.85},hi:{expMult:1.15}},
  {key:"rev",label:"Revenue basis \u00b120%",lo:{revMult:0.80},hi:{revMult:1.20}},
  {key:"reopen",label:"Reopen time \u221225/+50%",lo:{reopenMult:0.75},hi:{reopenMult:1.50}},
];
function uncRange(sitesArr,sc){
  const c=adaptedTotal(sitesArr,sc,{});
  const central=c.totalAal, acuteC=c.directEad+c.biEad;
  let dn2=0,up2=0,adn2=0,aup2=0;
  const factors=UNC_FACTORS.map(f=>{
    const lo=adaptedTotal(sitesArr,sc,f.lo), hi=adaptedTotal(sitesArr,sc,f.hi);
    const lt=Math.min(lo.totalAal,hi.totalAal), ht=Math.max(lo.totalAal,hi.totalAal);
    dn2+=Math.pow(Math.max(central-lt,0),2); up2+=Math.pow(Math.max(ht-central,0),2);
    const la=Math.min(lo.directEad+lo.biEad,hi.directEad+hi.biEad), ha=Math.max(lo.directEad+lo.biEad,hi.directEad+hi.biEad);
    adn2+=Math.pow(Math.max(acuteC-la,0),2); aup2+=Math.pow(Math.max(ha-acuteC,0),2);
    return {label:f.label,lo:lt,hi:ht,swing:ht-lt};
  }).sort((a,b)=>b.swing-a.swing);
  const low=Math.max(central-Math.sqrt(dn2),0), high=central+Math.sqrt(up2);
  // acute-based ratios approximate the band on tail VaR (VaR is acute-only)
  const varLoMult=acuteC?Math.max(acuteC-Math.sqrt(adn2),0)/acuteC:1;
  const varHiMult=acuteC?(acuteC+Math.sqrt(aup2))/acuteC:1;
  return {central,low,high,factors,varLoMult,varHiMult};
}
/* sensitivity tornado: per-factor low/high totals around the central AAL */
function tornadoSvg(u){
  const rows=u.factors;
  const W=460,rowH=34,H=rows.length*rowH+40,padL=170,padR=14;
  const xmin=Math.min(u.low,Math.min.apply(null,rows.map(r=>r.lo)))*0.98;
  const xmax=Math.max(u.high,Math.max.apply(null,rows.map(r=>r.hi)))*1.02;
  const X=v=>padL+(v-xmin)/(xmax-xmin||1)*(W-padL-padR);
  let s=svgEl(W,H);
  rows.forEach((r,i)=>{
    const y=i*rowH+14;
    s+='<text x="0" y="'+(y+12)+'" font-size="10.5" style="fill:var(--chart-ink2)">'+esc(r.label)+'</text>';
    s+='<rect x="'+X(r.lo)+'" y="'+y+'" width="'+Math.max(X(r.hi)-X(r.lo),1.5)+'" height="16" rx="3" style="fill:var(--chart-brand2)" opacity="0.85"><title>'+esc(r.label)+': '+fmt$(r.lo)+' to '+fmt$(r.hi)+'</title></rect>';
    s+='<text x="'+(X(r.hi)+5)+'" y="'+(y+12)+'" font-size="9.5" class="mono" style="fill:var(--chart-ink)">'+fmt$(r.swing)+'</text>';
  });
  const xc=X(u.central);
  s+='<line x1="'+xc+'" y1="8" x2="'+xc+'" y2="'+(H-26)+'" style="stroke:var(--chart-bad)" stroke-width="1.5" stroke-dasharray="4 4"/>';
  s+='<text x="'+xc+'" y="'+(H-14)+'" text-anchor="middle" font-size="10" style="fill:var(--chart-bad)">central '+fmt$(u.central)+'</text>';
  s+='<text x="'+((padL+W-padR)/2)+'" y="'+(H-2)+'" text-anchor="middle" font-size="10" style="fill:var(--chart-muted)">Expected annual cost when each input moves across its plausible range</text>';
  s+="</svg>";return s;
}

/* ============================================================
   App state
   ============================================================ */
