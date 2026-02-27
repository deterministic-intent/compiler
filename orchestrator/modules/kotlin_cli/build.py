#!/usr/bin/env python3
"""Build kotlin_cli artifact: kotlinc src/Main.kt -d dist"""
import os
import subprocess
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
    return subprocess.run(
        ["kotlinc", str(SRC / "Main.kt"), "-d", str(DIST)],
        env=ENV,
        cwd=str(ROOT),
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
