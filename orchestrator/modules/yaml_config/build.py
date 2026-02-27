#!/usr/bin/env python3
"""Build yaml_config artifact: cp yaml to dist"""
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
    DIST.mkdir(parents=True, exist_ok=True)
    # Copy all .yaml/.yml files from src or root
    for base in [SRC, ROOT]:
        if base.exists():
            for p in base.glob("*.yaml"):
                shutil.copy2(p, DIST / p.name)
            for p in base.glob("*.yml"):
                shutil.copy2(p, DIST / p.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
