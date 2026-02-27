#!/usr/bin/env python3
"""Build mongodb_pack artifact: cp schema.json to dist"""
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
    schema = ROOT / "schema.json"
    if not schema.exists():
        schema = ROOT / "src" / "schema.json"
    shutil.copy2(schema, DIST / "schema.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
