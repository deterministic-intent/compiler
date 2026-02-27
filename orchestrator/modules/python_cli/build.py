#!/usr/bin/env python3
"""Build python_cli artifact: cp src to dist"""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
SRC = ROOT / "src"
DIST = ROOT / "dist"

ENV = {
    **os.environ,
    "SOURCE_DATE_EPOCH": "1700000000",
    "TZ": "UTC",
    "LC_ALL": "C",
    "LANG": "C",
}


def main() -> int:
    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(SRC, DIST)
    return 0


if __name__ == "__main__":
    sys.exit(main())
