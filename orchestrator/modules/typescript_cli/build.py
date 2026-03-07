#!/usr/bin/env python3
"""Build typescript_cli artifact: tsc --pretty false --project tsconfig.json (no npm, zero deps)"""
import os
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
    tsconfig = ROOT / "tsconfig.json"
    if not tsconfig.exists():
        print("error: tsconfig.json not found", file=sys.stderr)
        return 1
    r = subprocess.run(
        ["tsc", "--pretty", "false", "--project", str(tsconfig)],
        env=ENV,
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        return r.returncode
    # tsc outputs to dist/ per tsconfig outDir; verify main.js
    main_js = DIST / "main.js"
    if not main_js.exists():
        main_js = ROOT / "dist" / "main.js"
    if not main_js.exists():
        print("error: main.js not found after tsc", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
