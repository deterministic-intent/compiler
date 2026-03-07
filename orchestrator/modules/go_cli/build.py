#!/usr/bin/env python3
"""Build go_cli artifact: go build -trimpath -buildvcs=false -ldflags="-buildid=" -o dist/main"""
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
    DIST.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [
            "go",
            "build",
            "-trimpath",
            "-buildvcs=false",
            '-ldflags=-buildid=',
            "-o",
            str(DIST / "main"),
            ".",
        ],
        env=ENV,
        cwd=str(ROOT),
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
