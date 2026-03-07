#!/usr/bin/env python3
"""Build php_cli artifact: cp src/main.php dist/main.php"""
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
    shutil.copy2(SRC / "main.php", DIST / "main.php")
    return 0


if __name__ == "__main__":
    sys.exit(main())
