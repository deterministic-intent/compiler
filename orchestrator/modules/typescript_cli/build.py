#!/usr/bin/env python3
"""Build typescript_cli artifact: npm ci --offline, npx tsc, output dist/main.js"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
DIST = ROOT / "dist"

ENV = {
    **os.environ,
    "SOURCE_DATE_EPOCH": "1700000000",
    "TZ": "UTC",
    "LC_ALL": "C",
    "LANG": "C",
}


def main() -> int:
    r = subprocess.run(["npm", "ci", "--offline"], env=ENV, cwd=str(ROOT))
    if r.returncode != 0:
        return r.returncode
    r = subprocess.run(["npx", "tsc"], env=ENV, cwd=str(ROOT))
    if r.returncode != 0:
        return r.returncode
    # tsc typically outputs to dist/ per tsconfig; ensure dist/main.js exists
    # If tsconfig outDir is different, we may need to copy
    DIST.mkdir(parents=True, exist_ok=True)
    for base in [ROOT / "dist", ROOT]:
        main_js = base / "main.js"
        if main_js.exists():
            if base != DIST:
                shutil.copy2(main_js, DIST / "main.js")
            return 0
    # Check common tsc output locations
    for p in (ROOT / "dist").rglob("main.js"):
        shutil.copy2(p, DIST / "main.js")
        return 0
    print("error: main.js not found after tsc", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
