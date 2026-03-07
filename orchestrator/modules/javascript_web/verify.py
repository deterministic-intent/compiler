#!/usr/bin/env python3
"""Verify javascript_web: test -f dist/*.js"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
DIST = ROOT / "dist"

ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}


def main() -> int:
    js_files = list(DIST.glob("*.js"))
    if not js_files:
        print("error: no .js in dist", file=sys.stderr)
        return 1
    for p in js_files:
        r = subprocess.run(["test", "-f", str(p)], env=ENV, cwd=str(ROOT))
        if r.returncode != 0:
            return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
