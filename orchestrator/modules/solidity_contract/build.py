#!/usr/bin/env python3
"""Build solidity_contract artifact: solc --metadata-hash none --bin src/main.sol -o dist"""
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
        [
            "solc",
            "--metadata-hash",
            "none",
            "--bin",
            str(SRC / "main.sol"),
            "-o",
            str(DIST),
        ],
        env=ENV,
        cwd=str(ROOT),
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
