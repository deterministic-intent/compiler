#!/usr/bin/env python3
"""Verify typescript_cli: test -f dist/main.js"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
DIST = ROOT / "dist"

ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}


def main() -> int:
    main_js = DIST / "main.js"
    if not main_js.exists():
        print("error: dist/main.js not found", file=sys.stderr)
        return 1
    return subprocess.run(
        ["test", "-f", str(main_js)],
        env=ENV,
        cwd=str(ROOT),
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
