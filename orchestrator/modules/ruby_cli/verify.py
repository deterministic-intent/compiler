#!/usr/bin/env python3
"""Verify ruby_cli: ruby -c dist/main.rb"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
DIST = ROOT / "dist"

ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}


def main() -> int:
    main_rb = DIST / "main.rb"
    if not main_rb.exists():
        print("error: dist/main.rb not found", file=sys.stderr)
        return 1
    return subprocess.run(
        ["ruby", "-c", str(main_rb)],
        env=ENV,
        cwd=str(ROOT),
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
