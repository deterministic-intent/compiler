#!/usr/bin/env python3
"""Verify python_cli: python -m py_compile dist/*.py"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
DIST = ROOT / "dist"

ENV = {**os.environ, "LC_ALL": "C", "LANG": "C", "PYTHONHASHSEED": "0"}


def main() -> int:
    py_files = list(DIST.glob("*.py"))
    if not py_files:
        print("error: no .py in dist", file=sys.stderr)
        return 1
    for p in py_files:
        r = subprocess.run(
            [sys.executable, "-m", "py_compile", str(p)],
            env=ENV,
            cwd=str(ROOT),
        )
        if r.returncode != 0:
            return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
