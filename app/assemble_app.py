"""
assemble_app.py : builds the deployable single-file app from app/src/.

Phase C retires the anchor-patch chain: the app's SOURCE OF TRUTH is now the
readable modules in app/src/ (shell head, eight JS domain modules, shell
tail, concatenated in MANIFEST order). This assembler joins them into the
same zero-install, single-file deliverable the system has always shipped:
opens from file://, no build toolchain, no module loading, nothing leaves
the machine.

The patchers (patch_frontend*.py) remain as verified historical lineage,
regenerating v1.6 through v1.13 from the v1.5 original; new work edits
app/src/ and reassembles.

Usage:
    python assemble_app.py            # writes the deployable
    python assemble_app.py --check    # byte-compare against the committed
                                      # deployable; exit 1 on drift (CI gate)
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
# v2.1.0: the wildfire structural fix (WRC point burn probability) changes a
# headline loss figure, so the deployable version steps; v200 stays committed
# as frozen lineage, exactly like v1.5 through v1.13 before it.
OUT = Path(__file__).resolve().parent / "TNL_Resort_Climate_Risk_Explorer_v210.html"


def assemble() -> str:
    order = (SRC / "MANIFEST").read_text().split()
    return "".join((SRC / name).read_text() for name in order)


def main() -> int:
    html = assemble()
    if "--check" in sys.argv:
        if not OUT.exists():
            print(f"MISSING: {OUT.name} is not committed")
            return 1
        if OUT.read_text() != html:
            print(f"DRIFT: {OUT.name} does not match app/src/. "
                  f"Run: python app/assemble_app.py")
            return 1
        print(f"ok  {OUT.name} matches app/src/ byte for byte")
        return 0
    OUT.write_text(html)
    print(f"wrote {OUT.name} ({len(html):,} chars) from {SRC}/MANIFEST")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
