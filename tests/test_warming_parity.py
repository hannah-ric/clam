"""Cross-file contract: the WARMING table is mirrored in FOUR places (the
app, refresh_heat.py, refresh_wildfire.py, refresh_prain.py). One drifted
value silently desynchronizes grid scaling from app scaling, so this gate
extracts the app's table from the DEPLOYABLE HTML (highest version in app/)
and asserts exact equality with all three producer dicts, plus the SLR table
against refresh_hazard.py.

The same guard covers the vulnerability and damage constants the results
pack shares with the app (refresh_impacts.py): a one-sided edit to any of
them would silently diverge pack figures from the live model.

    python3 test_warming_parity.py
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import refresh_hazard as rh
import refresh_heat as hh
import refresh_impacts as ri
import refresh_prain as rp
import refresh_wildfire as rw


def deployable():
    """Highest-versioned app file: the one users open."""
    def ver(p):
        m = re.search(r"_v(\d+)\.html$", p.name)
        return int(m.group(1)) if m else -1
    apps = sorted(ROOT.glob("app/TNL_Resort_Climate_Risk_Explorer*.html"),
                  key=ver)
    return apps[-1]


def extract_js_table(html, name):
    """Parse a `const NAME={...};` block of scalar entries into a dict."""
    m = re.search(name + r"\s*=\s*\{(.*?)\};", html, re.S)
    assert m, f"{name} table not found in the app"
    body = "{" + m.group(1).replace("\n", " ") + "}"
    body = re.sub(r"(\w+):", r'"\1":', body)          # quote the JS keys
    return {k: float(v) for k, v in json.loads(body).items()}


def extract_js_scalar(html, name):
    """Parse the first `NAME=<number>` assignment into a float."""
    m = re.search(r"\b" + re.escape(name) + r"\s*=\s*([0-9]+(?:\.[0-9]+)?)", html)
    assert m, f"{name} scalar not found in the app"
    return float(m.group(1))


def main():
    app = deployable()
    html = app.read_text()
    print(f"deployable: {app.name}")

    app_warming = extract_js_table(html, "const WARMING")
    for label, table in (("refresh_heat", hh.WARMING),
                         ("refresh_wildfire", rw.WARMING),
                         ("refresh_prain", rp.WARMING)):
        assert app_warming == {k: float(v) for k, v in table.items()}, \
            f"WARMING drifted between the app and {label}"
        print(f"ok  WARMING identical: app == {label}")

    app_slr = extract_js_table(html, "const SLR")
    assert app_slr == {k: float(v) for k, v in rh.SLR_M.items()}, \
        "SLR drifted between the app and refresh_hazard"
    print("ok  SLR identical: app == refresh_hazard")

    # vulnerability / damage constants shared with the results pack
    for name, val in (("V_THRESH", ri.V_THRESH), ("V_HALF", ri.V_HALF),
                      ("FB_COAST", ri.FB_COAST), ("FB_RIVER", ri.FB_RIVER),
                      ("FIRE_MDD", ri.FIRE_MDD),
                      ("PRAIN_DRAIN_MM", ri.PRAIN_DRAIN_MM),
                      ("PRAIN_POND_COEFF", ri.PRAIN_POND_COEFF),
                      ("PRAIN_FB", ri.PRAIN_FB)):
        assert extract_js_scalar(html, name) == float(val), \
            f"{name} drifted between the app and refresh_impacts"
        print(f"ok  {name} identical: app == refresh_impacts")

    app_cf = extract_js_table(html, "const CONSTR_FACTOR")
    assert app_cf == {k: float(v) for k, v in ri.CONSTR_FACTOR.items()}, \
        "CONSTR_FACTOR drifted between the app and refresh_impacts"
    print("ok  CONSTR_FACTOR identical: app == refresh_impacts")

    print("\nALL WARMING/SLR/VULNERABILITY PARITY CHECKS PASSED")


if __name__ == "__main__":
    main()
