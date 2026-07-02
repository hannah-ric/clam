"""
check_climada.py
================

Run this ONCE before refresh_hazard.py. It is a 60-second pre-flight that:
  1. confirms you are in the right environment and CLIMADA imports,
  2. proves the CLIMADA data API connection with one small, fast download,
  3. prints the exact property values your data release offers, so we can
     confirm the present-day tag refresh_hazard.py uses.

In VS Code: open the terminal, make sure the prompt shows (climada_env),
then run:  python check_climada.py

If step 2 prints OK, you are clear to run refresh_hazard.py.
If anything errors, copy the whole output back and it can be fixed in one edit.
"""

import sys


def main():
    print("=" * 60)
    print("STEP 1  environment")
    print("  python :", sys.executable)          # should live under climada_env
    try:
        import climada  # noqa: F401
    except Exception as exc:
        print("  FAILED to import climada:", exc)
        print("  Fix: make sure the prompt shows (climada_env) and rerun.")
        return 1
    try:
        from importlib.metadata import version
        print("  climada:", version("climada"))
    except Exception:
        print("  climada: imported OK (version metadata unavailable)")

    from climada.util.api_client import Client
    client = Client()

    print("=" * 60)
    print("STEP 2  data API connection (small test download: Puerto Rico)")
    try:
        haz = client.get_hazard(
            "tropical_cyclone",
            properties={
                "country_iso3alpha": "PRI",
                "climate_scenario": "rcp45",
                "ref_year": "2040",
                "nb_synth_tracks": "10",
            },
        )
        print("  OK  intensity matrix:", haz.intensity.shape,
              "(events x centroids)")
    except Exception as exc:
        print("  FAILED:", exc)
        print("  If this is an SSL or proxy error, it is your corporate network.")
        print("  Copy this output back for the exact .condarc fix.")
        return 1

    print("=" * 60)
    print("STEP 3  what your release calls each scenario (for Puerto Rico)")
    try:
        ds = client.list_dataset_infos(data_type="tropical_cyclone")
        vals = client.get_property_values(
            ds, known_property_values={"country_iso3alpha": "PRI"}
        )
        for key in ("climate_scenario", "ref_year", "event_type", "nb_synth_tracks"):
            if key in vals:
                print(f"  {key:16}: {sorted(map(str, vals[key]))}")
        print()
        print("  ACTION: send the 'climate_scenario' and 'event_type' lines back")
        print("  so the present-day setting can be confirmed. The script's")
        print("  fallback already tries the common tags, so it will likely just work.")
    except Exception as exc:
        print("  Discovery step failed (not fatal):", exc)

    print("=" * 60)
    print("All good. Next:  python refresh_hazard.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
