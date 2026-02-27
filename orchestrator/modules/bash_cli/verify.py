#!/usr/bin/env python3
"""Verify bash_cli: bash -n dist/main.sh"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
DIST = ROOT / "dist"

ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}


def main() -> int:
    main_sh = DIST / "main.sh"
    if not main_sh.exists():
        print("error: dist/main.sh not found", file=sys.stderr)
        return 1
    return subprocess.run(
        ["bash", "-n", str(main_sh)],
        env=ENV,
        cwd=str(ROOT),
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
