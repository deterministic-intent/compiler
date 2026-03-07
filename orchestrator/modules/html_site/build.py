#!/usr/bin/env python3
"""Build html_site artifact: cp index.html to dist"""
import os
import shutil
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
    DIST.mkdir(parents=True, exist_ok=True)
    index = ROOT / "src" / "index.html"
    if not index.exists():
        print("error: src/index.html not found", file=sys.stderr)
        return 1
    shutil.copy2(index, DIST / "index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
