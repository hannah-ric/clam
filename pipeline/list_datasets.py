"""
list_datasets.py
================

Generalisation of list_tc_datasets.py: prints every dataset the CLIMADA Data
API has for a given data_type and country, with the property tags that
distinguish them. Use it whenever a fetch in refresh_hazard.py reports
"no single match": the output shows exactly how the release you are talking
to tags its datasets, and the candidate list in fetch_wind can be adjusted in
one edit.

Usage (env active, cert exports set if on the corporate network):

    python list_datasets.py tropical_cyclone USA
    python list_datasets.py tropical_cyclone PRI
    python list_datasets.py river_flood USA        # Phase 2 discovery

Then paste the output back.
"""

from __future__ import annotations

import sys

from climada.util.api_client import Client

INTERESTING = ["climate_scenario", "event_type", "ref_year", "nb_synth_tracks",
               "model_name", "gcm", "res_arcsec", "spatial_coverage"]


def props_of(d):
    p = getattr(d, "properties", {})
    if isinstance(p, dict):
        return p
    try:   # some releases expose a list of objects with .name/.value
        return {x.name: x.value for x in p}
    except Exception:
        return {}


def main(data_type: str, iso3: str) -> int:
    c = Client()
    ds = c.list_dataset_infos(data_type, properties={"country_iso3alpha": iso3})
    if not ds:
        # some data types are tagged by country_name only, or are global
        ds = c.list_dataset_infos(data_type)
        print(f"(no country_iso3alpha match for {iso3}; listing ALL "
              f"{data_type} datasets instead)")
    print(f"{len(ds)} dataset(s) for data_type={data_type}, country={iso3}\n")
    for d in ds:
        p = props_of(d)
        tags = "  ".join(f"{k}={p[k]}" for k in INTERESTING if k in p)
        extra = "  ".join(f"{k}={v}" for k, v in p.items()
                          if k not in INTERESTING and not k.startswith("country"))
        print(f"- {getattr(d, 'name', '?')}  (v{getattr(d, 'version', '?')})")
        print(f"    {tags}")
        if extra:
            print(f"    {extra}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python list_datasets.py <data_type> <ISO3>\n"
              "e.g.:  python list_datasets.py tropical_cyclone USA")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
