#!/usr/bin/env python3
"""Verify solidity_contract: test -f dist/*.bin"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
DIST = ROOT / "dist"

ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}


def main() -> int:
    bin_files = list(DIST.glob("*.bin"))
    if not bin_files:
        print("error: no .bin in dist", file=sys.stderr)
        return 1
    for p in bin_files:
        r = subprocess.run(["test", "-f", str(p)], env=ENV, cwd=str(ROOT))
        if r.returncode != 0:
            return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
