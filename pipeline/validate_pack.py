"""
validate_pack.py
================

The acceptance gate for results_pack.json, the same role validate_grid.py
plays for the hazard grid: run it after every refresh_impacts.py run, BEFORE
giving the pack to the app or a report. Exit 0 = clean or warnings only;
1 = hard failure, do not ship.

Usage:
    python validate_pack.py results_pack.json [results_pack_meta.json]

Checks, in order:
  A. shape: pack_version 1, kind "results_pack", required sections present
  B. scenario coverage: every app scenario key present (missing keys warn;
     a present-only pack hard-fails, the v1 grid failure mode all over again)
  C. exceedance curves: losses non-decreasing with return period, all
     values finite and non-negative
  D. internal consistency: portfolio direct AAL within tolerance of the
     per-site EAD sum; by-peril AALs within tolerance of the acute total
  E. climate signal: portfolio AAL should not fall from present to
     ssp585_2080 (warn, as in the grid validator)
  F. adaptation: averted AAL non-negative, costs positive, BCR consistent
     with benefit/cost within tolerance
  G. uncertainty: p5 <= p50 <= p95 and the central estimate inside the band
     (warn if outside: a small MC sample can do that legitimately)
  H. provenance cross-check (when the meta sidecar is passed): the meta's
     layer list agrees with the pack's scenarios
"""

from __future__ import annotations

import json
import sys

APP_KEYS = ["present"] + [f"{p}_{h}" for h in (2030, 2050, 2080)
                          for p in ("ssp126", "ssp245", "ssp585")]
RPS = [10, 25, 50, 100, 250, 500]
TOL = 0.015                     # 1.5% relative tolerance on reconciliations


def fail(msg):
    print(f"FAIL  {msg}")
    return True


def warn(msg):
    print(f"WARN  {msg}")


def ok(msg):
    print(f"ok    {msg}")


def rel_close(a, b, tol=TOL):
    return abs(a - b) <= tol * max(abs(a), abs(b), 1.0)


def main(path: str, meta_path: str | None = None) -> int:
    hard = False
    try:
        with open(path) as f:
            pack = json.loads(f.read())
    except Exception as exc:
        print(f"FAIL  could not read {path}: {exc}")
        return 1

    # A. shape -----------------------------------------------------------------
    if pack.get("kind") != "results_pack" or pack.get("pack_version") != 1:
        return int(fail("not a results_pack v1 (kind/pack_version mismatch)"))
    for sect in ("scenarios", "adaptation", "uncertainty", "sites"):
        if sect not in pack:
            hard |= fail(f"missing section '{sect}'")
    if hard:
        return 1
    ok("pack shape (kind, version, sections)")

    scen = pack["scenarios"]
    print(f"\nScenarios in pack: {len(scen)}; sites: {pack['sites'].get('count')}")

    # B. scenario coverage --------------------------------------------------------
    if not scen:
        return int(fail("pack contains no scenarios at all: nothing to ship"))
    bad = sorted(set(scen) - set(APP_KEYS))
    if bad:
        hard |= fail(f"scenario keys the app cannot select: {bad}")
    missing = [k for k in APP_KEYS if k not in scen]
    if set(scen) == {"present"}:
        hard |= fail("pack contains ONLY the present scenario (the v1 grid "
                     "failure mode): future horizons would show no signal")
    elif missing:
        warn(f"missing scenarios {missing}: the app shows these as not covered")
    else:
        ok(f"all {len(APP_KEYS)} app scenarios covered")

    # C. exceedance curves ---------------------------------------------------------
    ep_bad = 0
    for k, s in scen.items():
        ep = s["portfolio"]["ep_usd"]
        absent = [rp for rp in RPS if str(rp) not in ep]
        if absent:
            hard |= fail(f"{k}: exceedance curve missing return periods "
                         f"{absent} (a truncated curve must not pass as flat)")
            continue
        vals = [float(ep[str(rp)]) for rp in RPS]
        if any(v < 0 or v != v for v in vals):
            hard |= fail(f"{k}: negative or non-finite exceedance loss")
        if any(vals[i] > vals[i + 1] + 0.01 for i in range(len(vals) - 1)):
            ep_bad += 1
    if ep_bad:
        hard |= fail(f"{ep_bad} scenario(s) have exceedance losses that "
                     f"DECREASE with return period")
    else:
        ok("exceedance losses non-decreasing with return period")

    # D. internal consistency ---------------------------------------------------------
    recon_bad = 0
    for k, s in scen.items():
        p = s["portfolio"]
        site_sum = sum(x["direct_ead_usd"] for x in s["per_site"])
        if not rel_close(p["direct_aal_usd"], site_sum):
            recon_bad += 1
        peril_sum = sum(p["by_peril_aal_usd"].values())
        if not rel_close(p["direct_aal_usd"], peril_sum):
            recon_bad += 1
    if recon_bad:
        hard |= fail(f"{recon_bad} reconciliation(s) failed: portfolio AAL vs "
                     f"per-site sum or by-peril sum (beyond {TOL:.1%})")
    else:
        ok("portfolio AAL reconciles with per-site and by-peril sums")

    # D1b. per-site return-period losses (Task 5): when present, they must be
    # finite, non-negative, and non-decreasing with rarity
    rp_bad = 0
    for k, s in scen.items():
        for x in s["per_site"]:
            if "loss_rp100_usd" not in x:
                continue
            a, b = float(x["loss_rp100_usd"]), float(x["loss_rp250_usd"])
            if a < 0 or b < 0 or a != a or b != b or b < a - 0.01:
                rp_bad += 1
    if rp_bad:
        hard |= fail(f"{rp_bad} per-site return-period record(s) negative, "
                     f"non-finite, or decreasing with rarity")
    elif any("loss_rp100_usd" in x for s in scen.values()
             for x in s["per_site"]):
        ok("per-site 1-in-100 / 1-in-250 losses present and monotone")

    # D2. wildfire share sanity: this portfolio is not wildfire-led (coastal
    # SE US / Gulf / Caribbean / Hawaii), so a large wildfire share of the
    # acute AAL is the signature of the retired cell-occupancy inflation
    if "present" in scen:
        bp = scen["present"]["portfolio"].get("by_peril_aal_usd", {})
        acute = sum(bp.values()) or 1.0
        wf_share = bp.get("wfire", 0.0) / acute * 100
        if wf_share > 25:
            warn(f"wildfire is {wf_share:.0f}% of present-day acute AAL: "
                 f"this portfolio is not wildfire-led; inspect the burn-"
                 f"probability source before shipping")
        else:
            ok(f"wildfire share of acute AAL is {wf_share:.1f}% "
               f"(not wildfire-led, as designed)")

    # E. climate signal ------------------------------------------------------------------
    if "present" in scen and "ssp585_2080" in scen:
        now = scen["present"]["portfolio"]["direct_aal_usd"]
        fut = scen["ssp585_2080"]["portfolio"]["direct_aal_usd"]
        if fut < now * 0.98:
            warn(f"portfolio AAL falls from present ({now:,.0f}) to "
                 f"ssp585_2080 ({fut:,.0f}); plausible regionally but verify")
        else:
            ok("climate signal present -> ssp585_2080 is non-negative")

    # F. adaptation --------------------------------------------------------------------
    f_bad = False
    for mk, m in pack["adaptation"].items():
        for sk, r in m.get("per_scenario", {}).items():
            if r["averted_direct_aal_usd"] < 0:
                f_bad |= fail(f"adaptation {mk}/{sk}: negative averted AAL")
            if r["cost_usd"] <= 0:
                warn(f"adaptation {mk}/{sk}: non-positive cost")
            elif r["bcr"] is not None and not rel_close(
                    r["bcr"], r["npv_benefit_usd"] / r["cost_usd"], 0.02):
                f_bad |= fail(f"adaptation {mk}/{sk}: BCR inconsistent with "
                              f"benefit/cost")
    hard |= f_bad
    if not f_bad:
        ok("adaptation: averted AAL, costs, and BCR internally consistent")

    # G. uncertainty --------------------------------------------------------------------
    g_bad = False
    for sk, u in pack["uncertainty"].items():
        for metric in ("acute_aal_usd", "loss_1in100_usd"):
            b = u[metric]
            if not (b["p5"] <= b["p50"] <= b["p95"]):
                g_bad |= fail(f"uncertainty {sk}/{metric}: quantiles out of order")
            if not (b["p5"] * 0.99 <= b["central"] <= b["p95"] * 1.01):
                warn(f"uncertainty {sk}/{metric}: central estimate outside "
                     f"the p5..p95 band (small MC samples can do this)")
    hard |= g_bad
    if not g_bad:
        ok("uncertainty: quantile ordering sane")

    # G2. calibration (optional section) ---------------------------------------------------
    cal = pack.get("calibration")
    if cal:
        c_bad = False
        if not (40.0 <= cal.get("fitted_v_half", 0) <= 150.0):
            c_bad |= fail("calibration: fitted v_half outside its search bounds")
        if cal.get("applied") is not False:
            warn("calibration: 'applied' is not false; pack figures should "
                 "use the published curve until adoption is deliberate")
        if cal.get("clipped_at_bound"):
            warn("calibration: fit clipped at a bound; observed losses are "
                 "outside what the wind curve can reproduce, review inputs")
        if cal.get("flag"):
            warn(f"calibration: {cal['flag']}")
        hard |= c_bad
        if not c_bad:
            ok(f"calibration recorded (fitted v_half "
               f"{cal.get('fitted_v_half')}, not applied)")

    # G3. capital plan (optional section) --------------------------------------------------
    plan = pack.get("capital_plan")
    if plan:
        p_bad = False
        prj = plan.get("projects", [])
        funded = [p for p in prj if p.get("year") is not None or "year" not in p]
        deferred = [p for p in prj if "year" in p and p.get("year") is None]
        bcrs = [p["bcr"] for p in prj]
        if any(b is None or b < 0 for b in bcrs):
            p_bad |= fail("capital plan: missing or negative BCR")
        fb = [p["bcr"] for p in funded]
        if any(fb[i] < fb[i + 1] for i in range(len(fb) - 1)):
            p_bad |= fail("capital plan: funded projects not sorted by BCR "
                          "descending")
        if deferred and prj[-len(deferred):] != deferred:
            p_bad |= fail("capital plan: deferred projects must trail the plan")
        r, h_yr = plan.get("discount_rate"), plan.get("horizon_years")
        if r and h_yr:
            def an_of(p):
                yrs = int(p.get("annuity_years") or h_yr)
                return sum(1.0 / (1.0 + r) ** t for t in range(1, yrs + 1))
            # renovation synergy discounts the cost AFTER the BCR ranking was
            # computed on the undiscounted cost, so reconcile those loosely
            bad_bcr = sum(
                1 for p in prj if p["cost_usd"] > 0 and not rel_close(
                    p["bcr"],
                    p["averted_direct_aal_usd"] * an_of(p) / p["cost_usd"],
                    0.25 if p.get("renovation_synergy") else 0.02))
            if bad_bcr:
                p_bad |= fail(f"capital plan: {bad_bcr} project BCR(s) do not "
                              f"reconcile with averted x annuity / cost")
        budget = plan.get("budget_annual_usd")
        if budget:
            spent = {}
            for p in prj:
                y = p.get("year")
                if y is not None:
                    spent[y] = spent.get(y, 0.0) + p["cost_usd"]
            over = {y: s for y, s in spent.items() if s > budget * 1.001}
            if over:
                p_bad |= fail(f"capital plan: year(s) {sorted(over)} exceed "
                              f"the annual budget")
        if plan.get("scenario") not in APP_KEYS:
            p_bad |= fail("capital plan: appraisal scenario is not an app key")
        hard |= p_bad
        if not p_bad:
            ok(f"capital plan: {len(prj)} project(s) "
               f"({len(deferred)} deferred), ordering and BCRs reconcile "
               f"({plan.get('scenario')})")

    # I. event sets (TCOR Task A, optional section) -----------------------------------------
    # The per-event joint wind+surge table is the shared hurricane
    # deductible's hard dependency: if it is present it must be internally
    # sound (ids unique per source, frequencies positive, site indices in
    # range, per-country weights normalized) and must RECONCILE with the
    # scenario's tc + cflood AAL, with the floor-dropped remainder bounded.
    ev = pack.get("event_sets")
    if ev:
        i_bad = False
        n_sites = int(pack["sites"].get("count") or 0)
        floor = float(ev.get("floor_usd") or 0.0)
        for k, parts in (ev.get("scenarios") or {}).items():
            if k not in scen:
                i_bad |= fail(f"event_sets: scenario {k} absent from pack")
                continue
            by_country = {}
            kept_total = 0.0
            aal_total = 0.0
            for p in parts:
                by_country.setdefault(p.get("country", "?"), 0.0)
                by_country[p.get("country", "?")] += float(p["weight"])
                kept_total += p["weight"] * float(p.get("kept_aal_usd", 0.0))
                aal_total += p["weight"] * float(p.get("aal_usd", 0.0))
                ids = [e["id"] for e in p["events"]]
                if len(ids) != len(set(ids)):
                    i_bad |= fail(f"event_sets {k}/{p.get('source')}: "
                                  f"duplicate event ids within one source")
                for e in p["events"]:
                    if not (float(e["freq"]) > 0):
                        i_bad |= fail(f"event_sets {k}/{p.get('source')}: "
                                      f"event {e['id']} has non-positive "
                                      f"frequency")
                        break
                    if any(j < 0 or j >= n_sites or l < floor - 0.01
                           or l != l for j, l in e["sites"]):
                        i_bad |= fail(f"event_sets {k}/{p.get('source')}: "
                                      f"event {e['id']} carries a site index "
                                      f"out of range or a loss below the "
                                      f"floor")
                        break
            for iso3, wsum in by_country.items():
                if abs(wsum - 1.0) > 0.01:
                    i_bad |= fail(f"event_sets {k}: source weights for "
                                  f"{iso3} sum to {wsum:.3f}, not 1")
            bp = scen[k]["portfolio"].get("by_peril_aal_usd", {})
            joint = float(bp.get("tc", 0.0)) + float(bp.get("cflood", 0.0))
            if aal_total > 0 and not rel_close(aal_total, joint, 0.02):
                i_bad |= fail(f"event_sets {k}: weighted event AAL "
                              f"({aal_total:,.0f}) does not reconcile with "
                              f"tc + cflood AAL ({joint:,.0f})")
            if aal_total > 0:
                dropped = (aal_total - kept_total) / aal_total
                if dropped > 0.10:
                    i_bad |= fail(f"event_sets {k}: the floor dropped "
                                  f"{dropped:.1%} of the joint AAL; the "
                                  f"attritional layer would be understated "
                                  f"(lower --event-floor)")
                elif dropped > 0.02:
                    warn(f"event_sets {k}: floor dropped {dropped:.1%} of "
                         f"joint AAL; acceptable but review --event-floor")
        hard |= i_bad
        if not i_bad:
            n_ev = sum(len(p["events"])
                       for parts in (ev.get("scenarios") or {}).values()
                       for p in parts)
            ok(f"event sets: ids, weights, indices, and AAL reconciliation "
               f"sound ({n_ev} events across "
               f"{len(ev.get('scenarios') or {})} scenario(s))")
    else:
        warn("no event_sets section: the shared per-occurrence hurricane "
             "deductible cannot be computed at event level from this pack; "
             "TCOR consumers fall back to labeled approximations")

    # I2. frequent-loss ladders (optional section) -------------------------------------------
    lad = pack.get("frequent_losses")
    if lad:
        l_bad = False
        rps_l = lad.get("ladder_rps") or []
        n_sites = int(pack["sites"].get("count") or 0)
        if sorted(rps_l) != rps_l or not rps_l or rps_l[0] >= 10:
            l_bad |= fail("frequent_losses: ladder_rps must ascend and reach "
                          "into the sub-1-in-10 attritional band")
        for k, by_peril in (lad.get("scenarios") or {}).items():
            for p, rows in by_peril.items():
                if len(rows) != n_sites:
                    l_bad |= fail(f"frequent_losses {k}/{p}: {len(rows)} "
                                  f"rows for {n_sites} sites")
                    continue
                for r in rows:
                    if len(r) != len(rps_l) or any(
                            x < 0 or x != x for x in r) or any(
                            r[i] > r[i + 1] + 0.01
                            for i in range(len(r) - 1)):
                        l_bad |= fail(f"frequent_losses {k}/{p}: a site row "
                                      f"is malformed, negative, or decreases "
                                      f"with rarity")
                        break
        hard |= l_bad
        if not l_bad:
            ok(f"frequent-loss ladders: shape and monotonicity sound "
               f"(rps {rps_l})")
    else:
        warn("no frequent_losses section: per-location deductible math and "
             "the attritional layer fall back to the app's interim curves")

    # H. provenance cross-check ------------------------------------------------------------
    if meta_path:
        print(f"\nProvenance cross-check against {meta_path}:")
        try:
            with open(meta_path) as f:
                meta = json.loads(f.read())
        except Exception as exc:
            hard |= fail(f"could not read meta JSON: {exc}")
            meta = None
        if meta is not None:
            claimed = {l.get("scenario") for l in meta.get("layers", [])}
            actual = set(scen)
            ghost = sorted(claimed - actual)
            silent = sorted(actual - claimed)
            if ghost:
                hard |= fail(f"meta claims scenarios absent from the pack: "
                             f"{ghost[:6]}")
            if silent:
                warn(f"pack carries scenarios the meta does not record: "
                     f"{silent[:6]}")
            if not ghost and not silent:
                ok(f"meta layers and pack scenarios agree ({len(actual)})")
            n_skip = len(meta.get("skipped", []))
            if n_skip:
                warn(f"meta records {n_skip} skipped item(s); confirm expected")

    print("\n" + ("RESULT: HARD FAILURE - do not ship this pack." if hard
                  else "RESULT: pack is shippable (review warnings above)."))
    return 1 if hard else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python validate_pack.py results_pack.json "
              "[results_pack_meta.json]")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
