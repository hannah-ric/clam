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
        pack = json.loads(open(path).read())
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
        if not (40.0 <= cal.get("fitted_v_half", 0) <= 150.0):
            hard |= fail("calibration: fitted v_half outside its search bounds")
        if cal.get("applied") is not False:
            warn("calibration: 'applied' is not false; pack figures should "
                 "use the published curve until adoption is deliberate")
        if cal.get("clipped_at_bound"):
            warn("calibration: fit clipped at a bound; observed losses are "
                 "outside what the wind curve can reproduce, review inputs")
        if cal.get("flag"):
            warn(f"calibration: {cal['flag']}")
        if not hard:
            ok(f"calibration recorded (fitted v_half "
               f"{cal.get('fitted_v_half')}, not applied)")

    # H. provenance cross-check ------------------------------------------------------------
    if meta_path:
        print(f"\nProvenance cross-check against {meta_path}:")
        try:
            meta = json.loads(open(meta_path).read())
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
