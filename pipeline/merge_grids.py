"""
merge_grids.py  (v2 : Phase 4 aware)
====================================

Merge two or more hazard-grid CSVs (same schema) into the single file the app
consumes, because the app's loader replaces ALL grids on each drop: one file,
one drop. Later inputs win on (lat, lon, scenario, hazard) collisions, so run
it as   python merge_grids.py hazard_grid.csv heat_grid.csv -o hazard_grid.csv
to refresh the heat layer without touching the CLIMADA layers, or in the
other order to do the reverse.

Phase 4: provenance follows the data. For each input CSV, the sibling
provenance sidecar (<stem>_meta.json, the convention both refresh scripts
write) is picked up automatically when present, and a COMBINED sidecar is
written next to the output as <out-stem>_meta.json:

    { "combined": true, "generated_utc": ...,
      "sources": [ <each producer's full meta> ],
      "layers":  [ union, deduped by (hazard, scenario, country), later wins ],
      "skipped": [ concatenated ] }

The app's Phase 4 renderer accepts both a single-producer meta and this
combined shape, so drop the combined JSON together with the merged CSV.
Re-running the merge is safe: an input that already carries a combined meta
contributes its sources, not a nested combined blob.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

COLS = ["lat", "lon", "scenario", "hazard", "v10", "v25", "v50", "v100", "v250", "v500"]


def sidecar_of(csv_path: str) -> Path:
    p = Path(csv_path)
    return p.with_name(p.stem + "_meta.json")


def combine_metas(metas: list) -> dict:
    """Pure and unit-tested. Flattens already-combined inputs, dedupes layers
    by (hazard, scenario, country) with later inputs winning, concatenates
    skipped records."""
    sources, layers, skipped = [], {}, []
    for m in metas:
        for s in (m.get("sources") or [m]):
            sources.append(s)
        for lay in m.get("layers", []):
            key = (lay.get("hazard"), lay.get("scenario"), lay.get("country", ""))
            layers[key] = lay
        skipped.extend(m.get("skipped", []))
    return {
        "combined": True,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": sources,
        "layers": list(layers.values()),
        "skipped": skipped,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", help="grid CSVs, later files win on collisions")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--no-meta", action="store_true",
                    help="skip sidecar meta merging")
    args = ap.parse_args()

    frames, metas = [], []
    for path in args.inputs:
        df = pd.read_csv(path)
        if "hazard" not in df.columns:
            df["hazard"] = "tc"
        missing = [c for c in COLS if c not in df.columns]
        if missing:
            raise SystemExit(f"{path}: missing columns {missing}")
        frames.append(df[COLS])
        print(f"read {len(df):>8,} rows  {path}")
        if not args.no_meta:
            sc = sidecar_of(path)
            if sc.exists():
                try:
                    metas.append(json.loads(sc.read_text()))
                    print(f"     + provenance  {sc}")
                except Exception as exc:
                    print(f"     ! could not read {sc}: {exc}")

    out = pd.concat(frames, ignore_index=True)
    before = len(out)
    out = out.drop_duplicates(subset=["lat", "lon", "scenario", "hazard"], keep="last")
    out.to_csv(args.out, index=False)
    print(f"wrote {len(out):>7,} rows  {args.out}  "
          f"({before - len(out):,} collisions resolved, later file wins)")

    if metas and not args.no_meta:
        combined = combine_metas(metas)
        out_meta = sidecar_of(args.out)
        out_meta.write_text(json.dumps(combined, indent=2))
        print(f"wrote combined provenance ({len(combined['sources'])} source(s), "
              f"{len(combined['layers'])} layers)  {out_meta}")
        print("Drop the CSV and this JSON on the app's hazard zone together.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
