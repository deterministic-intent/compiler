#!/usr/bin/env python3
"""Verify java_cli: test -f dist/Main.class"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
DIST = ROOT / "dist"

ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}


def main() -> int:
    main_class = DIST / "Main.class"
    if not main_class.exists():
        print("error: dist/Main.class not found", file=sys.stderr)
        return 1
    return subprocess.run(
        ["test", "-f", str(main_class)],
        env=ENV,
        cwd=str(ROOT),
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
