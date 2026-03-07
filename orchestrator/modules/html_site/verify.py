#!/usr/bin/env python3
"""Verify html_site: test -f dist/index.html"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
DIST = ROOT / "dist"

ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}


def main() -> int:
    index = DIST / "index.html"
    if not index.exists():
        print("error: dist/index.html not found", file=sys.stderr)
        return 1
    return subprocess.run(
        ["test", "-f", str(index)],
        env=ENV,
        cwd=str(ROOT),
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
