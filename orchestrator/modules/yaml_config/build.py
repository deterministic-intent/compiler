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
    if not SRC.exists():
        print("error: src/ not found", file=sys.stderr)
        return 1
    copied = 0
    for p in SRC.glob("*.yaml"):
        shutil.copy2(p, DIST / p.name)
        copied += 1
    for p in SRC.glob("*.yml"):
        shutil.copy2(p, DIST / p.name)
        copied += 1
    if copied == 0:
        print("error: no .yaml/.yml in src/", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
