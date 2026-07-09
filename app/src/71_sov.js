/* ============================================================
   SOV importer (overhaul Task 8)
   The broker's Statement of Values is the on-file source of record for
   campus codes, TIV, BI & EE declared values, tenure, occupancy, and
   per-site premium: exactly the fields that move the TCOR confidence
   bar from estimate toward complete. This module ingests the SOV
   workbook's CSV export under header aliases (broker column names
   drift, like the loss run's), matches rows to the loaded portfolio
   (site_id first, exact normalized name second, containment third:
   the loss-run matcher's discipline), and applies the SOV's facts,
   SUPERSEDING hand-keyed values for the schema-v3 TCOR fields the SOV
   carries: the SOV is the fact on file. Vulnerability profile fields
   (construction, year built) are filled only where ABSENT: an
   operator-verified profile is never overwritten by a broker schedule.
   Every applied field is recorded on the site (sov_fields) so the
   provenance vocabulary can read "sov"; unmatched rows are reported
   WITH their TIV so no exposure silently vanishes. With no portfolio
   loaded, an SOV that carries coordinates BOOTSTRAPS the portfolio.
   ============================================================ */
let sovLog=null;   // session import report: {name,loaded,matched,unmatched,...}

const SOV_ALIASES={
  site_id:["site id","location id","loc id","location number","location no","loc #","location #","site #","site no","bldg id","location code"],
  name:["location name","property name","site name","insured location","location description","property","location"],
  named_insured:["named insured","insured","insured name","entity"],
  campus_code:["campus code","campus id","campus #","campus no"],
  campus_name:["campus name","campus"],
  owned_or_leased:["owned/leased","owned or leased","tenure","ownership","own/lease","owned leased"],
  latitude:["latitude","lat"],
  longitude:["longitude","lon","lng","long"],
  tiv:["total insured value","tiv","total tiv","total values","total value","total insured values"],
  building:["building value","building","real property","building limit","building values"],
  contents:["contents","contents value","personal property","bpp","content value"],
  bi_ee:["bi/ee","bi & ee","bi and ee","bi ee","business interruption","business income","bi value","time element","bi/ee value","bi & ee value"],
  premium:["annual premium","premium","allocated premium","premium allocation","total premium","property premium"],
  occupancy:["occupancy","occupancy type","use","property type","occupancy description"],
  year_built:["year built","yr built","year of construction","construction year"],
  construction:["construction","construction type","construction class","iso construction"]
};
function sovHeaderMap(head){
  const m={};
  for(const key in SOV_ALIASES){
    for(const alias of SOV_ALIASES[key]){
      const i=head.indexOf(alias);
      if(i>=0){m[key]=alias;break;}
    }
  }
  return m;
}
/* does a parsed CSV header look like an SOV rather than CLAM's own site
   schema or a hazard grid? CLAM's schema (asset_value_usd) always wins. */
function sovLooksLike(head){
  if(head.indexOf("asset_value_usd")>=0)return false;
  if(["lat","lon","scenario"].every(k=>head.indexOf(k)>=0))return false;  // hazard grid
  const has=k=>SOV_ALIASES[k].some(a=>head.indexOf(a)>=0);
  const n=["tiv","building","campus_code","campus_name","named_insured","premium","bi_ee","owned_or_leased"]
    .filter(has).length;
  return has("tiv")||n>=2;
}
/* SOV construction strings -> the app's three vulnerability classes.
   Only used to FILL an absent profile field, never to overwrite one. */
function sovConstructionClass(v){
  const c=String(v==null?"":v).toLowerCase();
  if(!c.trim())return null;
  if(/fire\s*resist|reinforced|concrete|steel|superior|modified\s*fr/.test(c))return "engineered";
  if(/masonry|joisted|jm\b|cb\b|block|brick|non.?combustible/.test(c))return "masonry";
  if(/frame|wood|timber/.test(c))return "frame";
  return null;
}
function sovMoney(v){
  if(v==null)return null;
  const n=parseFloat(String(v).replace(/[$,()\s]/g,m=>m==="("?"-":""));
  return isFinite(n)&&n>=0?n:null;
}
/* row -> site: site_id against site_id or name, exact normalized name,
   then containment either way (lossrunNorm's normalization) */
function sovSiteMatch(rowSiteId,rowName,sitesArr){
  const sid=String(rowSiteId==null?"":rowSiteId).trim().toLowerCase();
  if(sid){
    for(const s of sitesArr){
      if(String(s.site_id==null?"":s.site_id).trim().toLowerCase()===sid)return s;
    }
  }
  const cn=lossrunNorm(rowName);if(!cn)return null;
  for(const s of sitesArr)if(lossrunNorm(s.name)===cn)return s;
  for(const s of sitesArr){
    const sn=lossrunNorm(s.name);
    if(sn&&(cn.indexOf(sn)>=0||sn.indexOf(cn)>=0))return s;
  }
  return null;
}
/* one SOV row -> the field set to apply. supersede: schema-v3 TCOR facts
   + TIV; fill-if-absent: vulnerability profile fields. */
function sovRowFields(row,cols){
  const out={supersede:{},fill:{},flags:[]};
  const get=k=>cols[k]!=null?row.get(cols[k]):undefined;
  const cc=String(get("campus_code")||"").trim();if(cc)out.supersede.campus_code=cc.slice(0,40);
  const cn=String(get("campus_name")||"").trim();if(cn)out.supersede.campus_name=cn.slice(0,120);
  const ni=String(get("named_insured")||"").trim();if(ni)out.supersede.named_insured=ni.slice(0,80);
  const ol=String(get("owned_or_leased")||"").trim().toLowerCase();
  if(/^own/.test(ol))out.supersede.owned_or_leased="owned";
  else if(/^leas|^rent/.test(ol))out.supersede.owned_or_leased="leased";
  const be=sovMoney(get("bi_ee"));if(be!=null)out.supersede.bi_ee_usd=be;
  const pa=sovMoney(get("premium"));if(pa!=null)out.supersede.premium_annual_usd=pa;
  let tiv=sovMoney(get("tiv"));
  if(tiv==null){
    const b=sovMoney(get("building")),c2=sovMoney(get("contents"));
    if(b!=null){tiv=b+(c2||0);out.flags.push("TIV derived as building + contents");}
  }
  if(tiv!=null&&tiv>0)out.supersede.asset_value_usd=tiv;
  const sid=String(get("site_id")||"").trim();if(sid)out.fill.site_id=sid.slice(0,80);
  const occ=String(get("occupancy")||"").toLowerCase();
  if(/timeshare|vacation\s*ownership|fractional|interval/.test(occ)){
    out.fill.timeshare_share=1;
    out.flags.push("occupancy reads timeshare: continuing-revenue share defaulted for the BI module (edit per site if mixed)");
  }
  const cs=sovConstructionClass(get("construction"));if(cs)out.fill.construction=cs;
  const yb=toNum(get("year_built"));if(isFinite(yb)&&yb>1800&&yb<2100)out.fill.year_built=Math.round(yb);
  return out;
}
function loadSovCsv(text,name){
  const {head,out}=parseCsv(text);
  const cols=sovHeaderMap(head);
  if(cols.tiv==null&&cols.building==null&&cols.campus_code==null&&cols.bi_ee==null&&cols.premium==null){
    toast("That CSV does not look like an SOV (need TIV / campus / BI & EE / premium columns).");return;
  }
  if(cols.name==null&&cols.site_id==null){
    toast("SOV needs a location name or site/location id column to match against the portfolio.");return;
  }
  const rows=[];
  out.forEach(row=>{
    const nm=String(cols.name!=null?row.get(cols.name)||"":"").trim();
    const sid=String(cols.site_id!=null?row.get(cols.site_id)||"":"").trim();
    if(!nm&&!sid)return;
    rows.push({row,nm,sid});
  });
  if(!rows.length){toast("No usable SOV rows found.");return;}

  /* bootstrap: no portfolio loaded and the SOV carries coordinates */
  if(!sites.length){
    if(cols.latitude==null||cols.longitude==null){
      toast("No portfolio is loaded and this SOV has no coordinates: load the portfolio CSV first, then drop the SOV to enrich it.");return;
    }
    const recs=[];let skipped=0;
    rows.forEach(x=>{
      const lat=toNum(x.row.get(cols.latitude)),lon=toNum(x.row.get(cols.longitude));
      const f=sovRowFields(x.row,cols);
      const val=f.supersede.asset_value_usd;
      if(!isFinite(lat)||!isFinite(lon)||lat<-90||lat>90||lon<-180||lon>180||!(val>0)){skipped++;return;}
      const rec=Object.assign({name:(x.nm||x.sid).slice(0,120),latitude:lat,longitude:lon},
        f.supersede,f.fill);
      rec.sov_fields=Object.keys(f.supersede).concat(Object.keys(f.fill));
      recs.push(rec);
    });
    if(!recs.length){toast("No SOV rows carried valid coordinates and TIV; nothing loaded.");return;}
    sites=[];nextId=1;selectedId=null;clearHazCache();ui.portfolioSource="sov";
    addSites(recs);
    sovLog={name:name||"sov.csv",loaded:new Date().toISOString().slice(0,16).replace("T"," "),
      mode:"bootstrap",matched:recs.length,unmatched:[],skipped,
      fieldsApplied:recs.reduce((a,r)=>a+r.sov_fields.length,0)};
    if(typeof cmdInvalidate==="function")cmdInvalidate();
    toast("Portfolio bootstrapped from the SOV: "+recs.length+" site"+(recs.length>1?"s":"")
      +(skipped?", "+skipped+" row(s) skipped (missing coordinates or TIV)":""));
    return;
  }

  /* enrich: match each SOV row to a site and apply its facts */
  let matched=0,fieldsApplied=0;const unmatched=[];const flags={};
  const touched={};
  rows.forEach(x=>{
    const s=sovSiteMatch(x.sid,x.nm,sites);
    const f=sovRowFields(x.row,cols);
    if(!s){
      unmatched.push({name:x.nm||x.sid,tiv:f.supersede.asset_value_usd||0});
      return;
    }
    matched++;
    const applied=[];
    for(const k in f.supersede){ s[k]=f.supersede[k]; applied.push(k); }
    for(const k in f.fill){ if(s[k]==null||s[k]===""){ s[k]=f.fill[k]; applied.push(k); } }
    f.flags.forEach(fl=>{flags[fl]=(flags[fl]||0)+1;});
    if(applied.length){
      const prev=Array.isArray(s.sov_fields)?s.sov_fields:[];
      s.sov_fields=prev.concat(applied.filter(k=>prev.indexOf(k)<0));
      fieldsApplied+=applied.length;
      touched[s.id]=true;
    }
  });
  const unTiv=unmatched.reduce((a,u)=>a+(u.tiv||0),0);
  sovLog={name:name||"sov.csv",loaded:new Date().toISOString().slice(0,16).replace("T"," "),
    mode:"enrich",matched,unmatched,unmatchedTiv:unTiv,fieldsApplied,
    flags:Object.keys(flags).map(k=>k+(flags[k]>1?" ("+flags[k]+" rows)":""))};
  clearHazCache();
  if(typeof cmdInvalidate==="function")cmdInvalidate();
  persist();render();
  toast("SOV applied: "+matched+" of "+rows.length+" rows matched, "+fieldsApplied+" fields set"
    +(unmatched.length?"; "+unmatched.length+" unmatched row(s) carrying "+fmt$(unTiv)+" TIV (see Method & data)":""));
}
/* the portfolio drop zone accepts either CLAM's site schema or an SOV:
   sniff the header and route. Wired in place of the bare loadSiteCsv. */
function routeSiteCsv(text,name){
  const first=(String(text||"").replace(/^\uFEFF/,"").split(/\r?\n/,1)[0]||"").toLowerCase();
  const head=splitCsvLine(first).map(h=>h.trim());
  if(sovLooksLike(head))loadSovCsv(text,name);
  else loadSiteCsv(text);
}
