"""
validate_grid.py
================

Run this on hazard_grid.csv after every refresh_hazard.py run, BEFORE dropping
the file into the browser app. It is the acceptance test for Phases 0 and 1:
it would have caught both silent failures found in the v1 deployment (a grid
containing only the present-day scenario, and scenario keys the app cannot
match), and it sanity-checks the new surge layer.

Usage:
    python validate_grid.py hazard_grid.csv [hazard_grid_meta.json]

Exit code 0 = clean or warnings only; 1 = hard failure (do not ship the file).

Checks, in order (v2: heat- and rflood-aware):
  A. schema: required columns, parseable numerics, lat/lon in range, no NaN
  B. coverage: every app scenario key present for every hazard in the file
     (a missing scenario means the app silently serves present-day there)
  C. keys: every scenario value is one the app's dropdown can select
  D. monotonicity: v10 <= v25 <= ... <= v500 per row (small violations can
     arise from tail extrapolation; they are counted and warned, not failed)
  E. climate signal: portfolio-mean v100 should not DECREASE from present to
     ssp585_2080 for tc (warn: this is the symptom of the v1 key bug)
  F. water-layer sanity (cflood AND rflood): depths in metres (warn above
     15/20 m), some wet cells, inland/dry zeros preserved (coverage tracks tc
     coverage per scenario, so nearest-cell snapping cannot leak water depth)
  G. heat sanity: hazard=heat rows use the indicator encoding v10=days>32C,
     v25=days>35C, v50=CDD, v100..v500=0; they are EXCLUDED from monotonicity
     and v100 signal checks, and validated on their own terms instead
  H. provenance cross-check (only when the meta JSON is passed): every layer
     the sidecar claims exists in the CSV and vice versa, so what the app's
     Phase 4 trust surface DISPLAYS can never drift from what it COMPUTES
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

RPS = [10, 25, 50, 100, 250, 500]
VCOLS = [f"v{rp}" for rp in RPS]
APP_KEYS = ["present"] + [f"{p}_{h}" for h in (2030, 2050, 2080)
                          for p in ("ssp126", "ssp245", "ssp585")]


def fail(msg):
    print(f"FAIL  {msg}")
    return True


def warn(msg):
    print(f"WARN  {msg}")


def ok(msg):
    print(f"ok    {msg}")


def main(path: str, meta_path: str | None = None) -> int:
    hard = False
    df = pd.read_csv(path)
    print(f"Loaded {len(df):,} rows from {path}\n")
    if not len(df):
        return int(fail("grid contains no rows at all: nothing to ship"))

    # A. schema ---------------------------------------------------------------
    need = ["lat", "lon", "scenario"] + VCOLS
    missing = [c for c in need if c not in df.columns]
    if missing:
        return int(fail(f"missing required columns: {missing}"))
    if "hazard" not in df.columns:
        warn("no 'hazard' column: the app will treat every row as tc wind")
        df["hazard"] = "tc"
    if df[["lat", "lon"] + VCOLS].isna().any().any():
        hard |= fail("NaN values present in coordinates or intensities")
    if not df["lat"].between(-90, 90).all() or not df["lon"].between(-180, 180).all():
        hard |= fail("coordinates out of range")
    if (df[VCOLS] < 0).any().any():
        hard |= fail("negative intensities present")
    if not hard:
        ok("schema, ranges, and NaN checks")

    # B + C. coverage and key validity ---------------------------------------
    print("\nCoverage (rows per hazard x scenario):")
    pivot = df.pivot_table(index="scenario", columns="hazard",
                           values="lat", aggfunc="count").fillna(0).astype(int)
    print(pivot.to_string())
    bad_keys = sorted(set(df["scenario"]) - set(APP_KEYS))
    if bad_keys:
        hard |= fail(f"scenario keys the app cannot select (it will silently fall "
                     f"back to present for them): {bad_keys}")
    for hz in sorted(df["hazard"].unique()):
        have = set(df.loc[df["hazard"] == hz, "scenario"])
        miss = [k for k in APP_KEYS if k not in have]
        if miss:
            warn(f"hazard '{hz}' missing scenarios {miss}: the app falls back to "
                 f"this hazard's PRESENT grid there")
        else:
            ok(f"hazard '{hz}' covers all {len(APP_KEYS)} app scenarios")
    if set(df["scenario"]) == {"present"}:
        hard |= fail("grid contains ONLY the present scenario: this is the v1 "
                     "failure mode; future horizons would show no climate signal")

    # D. monotonicity (water/wind layers only: heat and wfire use indicator
    #    encodings) ---------------------------------------------------------
    dnh = df[~df["hazard"].isin(["heat", "wfire"])]
    v = dnh[VCOLS].to_numpy()
    viol = (np.diff(v, axis=1) < -0.011).any(axis=1)   # > 1 cm/0.01 m/s tolerance
    if len(v) and viol.any():
        share = viol.mean() * 100
        (warn if share < 1 else fail)(
            f"{viol.sum():,} rows ({share:.2f}%) have return-period intensities "
            f"that DECREASE with rarity: inspect tail extrapolation")
        hard |= share >= 1
    else:
        ok("intensities non-decreasing across return periods")

    # E. climate signal (signal column: v100, except heat which carries its
    #    money-driving indicator, days over 35C, in v25) ------------------------
    print("\nClimate signal by scenario:")
    for hz in sorted(df["hazard"].unique()):
        col = {"heat": "v25", "wfire": "v10"}.get(hz, "v100")
        sub = df[df["hazard"] == hz]
        means = sub.groupby("scenario")[col].mean()
        line = "  ".join(f"{k}={means[k]:.2f}" for k in APP_KEYS if k in means)
        print(f"  {hz} ({col}): {line}")
        if "present" in means and "ssp585_2080" in means:
            if means["ssp585_2080"] < means["present"] * 0.98:
                warn(f"hazard '{hz}': mean {col} falls from present to ssp585_2080 "
                     f"({means['present']:.2f} -> {means['ssp585_2080']:.2f}); "
                     f"plausible regionally but verify the scenario mapping")
            else:
                ok(f"hazard '{hz}': signal present -> ssp585_2080 is non-negative")

    # F. water-layer sanity (cflood and rflood) ------------------------------------
    for hz, cap, what in (("cflood", 15, "surge"), ("rflood", 20, "river flood")):
        w = df[df["hazard"] == hz]
        if not len(w):
            warn(f"no {hz} rows: {what} layer absent this run (app uses its "
                 f"interim model for this peril)")
            continue
        print(f"\n{hz} layer:")
        mx = w[VCOLS].to_numpy().max()
        wet = (w["v100"] > 0).mean() * 100
        print(f"  max depth {mx:.2f} m, {wet:.1f}% of cells wet at 1-in-100")
        if mx > cap:
            warn(f"max {what} depth above {cap} m is implausible; inspect the "
                 f"source data before shipping")
        if wet == 0:
            hard |= fail(f"{hz} layer has no wet cells at all: the {what} "
                         f"computation is wrong")
        if wet > 60:
            warn(f"more than 60% of {hz} cells wet at 1-in-100: coverage may be "
                 f"wet-cells-only (dry zeros missing), which makes the app snap "
                 f"dry sites to wet cells. Check align_to_cells ran.")
        for sc in sorted(w["scenario"].unique()):
            n_w = len(w[w["scenario"] == sc])
            n_tc = len(df[(df["hazard"] == "tc") & (df["scenario"] == sc)])
            if n_tc and n_w < 0.9 * n_tc:
                warn(f"{hz}/{sc} has {n_w} cells vs tc's {n_tc}: dry zeros may "
                     f"be missing (nearest-cell snapping risk)")

    # G. heat sanity ------------------------------------------------------------------
    ht = df[df["hazard"] == "heat"]
    if len(ht):
        print("\nheat layer (v10=days>32C, v25=days>35C, v50=CDD):")
        d32, d35, cdd = ht["v10"], ht["v25"], ht["v50"]
        print(f"  days>32C mean {d32.mean():.0f} max {d32.max():.0f}; "
              f"days>35C mean {d35.mean():.0f} max {d35.max():.0f}; "
              f"CDD mean {cdd.mean():.0f} max {cdd.max():.0f}")
        if (d32 > 366).any() or (d35 > 366).any():
            hard |= fail("heat day counts exceed 366: encoding or units error")
        if (d35 > d32 + 0.11).any():
            hard |= fail("days>35C exceeds days>32C somewhere: thresholds swapped?")
        if (ht[["v100", "v250", "v500"]].to_numpy() != 0).any():
            warn("heat rows carry nonzero v100/v250/v500: the app ignores them "
                 "but the Option A encoding says they should be 0")
        if cdd.max() > 6500:
            warn("CDD above 6500 looks high even for the hottest US sites; "
                 "check the tmean units")
    else:
        warn("no heat rows: heat layer absent (app uses its latitude formula)")

    # G2. wildfire sanity (v10 = annual burn probability, percent) ---------------
    wf = df[df["hazard"] == "wfire"]
    if len(wf):
        print("\nwfire layer (v10 = annual burn probability, percent):")
        print(f"  mean {wf['v10'].mean():.2f}%  max {wf['v10'].max():.2f}%")
        if (wf["v10"] < 0).any() or (wf["v10"] > 100).any():
            hard |= fail("wfire burn probability outside 0..100 percent")
        if (wf[["v25", "v50", "v100", "v250", "v500"]].to_numpy() != 0).any():
            warn("wfire rows carry nonzero v25..v500: the encoding says 0")
        if wf["v10"].max() > 5:
            warn("burn probability above 5%/yr somewhere: plausible only in "
                 "extreme WUI; inspect before shipping")

    # G3. rainfall sanity (mm at return periods) ----------------------------------
    pr = df[df["hazard"] == "prain"]
    if len(pr):
        mx = pr[VCOLS].to_numpy().max()
        print(f"\nprain layer: max {mx:.0f} mm at any return period")
        if mx > 2500:
            warn("rainfall above 2500 mm/event is implausible; check units")
        if mx <= 0:
            hard |= fail("prain layer has no rainfall anywhere: computation "
                         "is wrong")

    # H. provenance cross-check --------------------------------------------------
    if meta_path:
        import json
        print("\nProvenance cross-check against", meta_path, ":")
        try:
            with open(meta_path) as f:
                meta = json.loads(f.read())
        except Exception as exc:
            hard |= fail(f"could not read meta JSON: {exc}")
            meta = None
        if meta is not None:
            claimed = {(l.get("hazard"), l.get("scenario"))
                       for l in meta.get("layers", [])}
            actual = set(map(tuple, df[["hazard", "scenario"]]
                             .drop_duplicates().to_numpy().tolist()))
            ghost = sorted(claimed - actual)
            silent = sorted(actual - claimed)
            if ghost:
                hard |= fail(f"meta claims layers absent from the CSV (the trust "
                             f"surface would overstate coverage): {ghost[:6]}"
                             + (" ..." if len(ghost) > 6 else ""))
            if silent:
                warn(f"CSV carries layers the meta does not record (regenerate or "
                     f"re-merge the sidecar): {silent[:6]}"
                     + (" ..." if len(silent) > 6 else ""))
            if not ghost and not silent:
                ok(f"meta layers and CSV layers agree "
                   f"({len(claimed)} hazard x scenario combinations)")
            srcs = meta.get("sources") or [meta]
            if "cflood" in set(df["hazard"]) and not any(
                    (s.get("surge") or {}).get("dem_path") for s in srcs):
                warn("cflood rows present but no source records a DEM path")
            if "heat" in set(df["hazard"]) and not any(s.get("method") for s in srcs):
                warn("heat rows present but no source records a method")
            n_skip = len(meta.get("skipped", []))
            if n_skip:
                warn(f"meta records {n_skip} skipped layer(s) from the last run: "
                     f"the app shows this on the Method tab; confirm it is expected")

    print("\n" + ("RESULT: HARD FAILURE - do not ship this grid." if hard
                  else "RESULT: grid is shippable (review warnings above)."))
    return 1 if hard else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python validate_grid.py hazard_grid.csv [hazard_grid_meta.json]")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
