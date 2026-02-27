#!/usr/bin/env python3
"""Verify kotlin_cli: test -f dist/MainKt.class or Main.class"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
DIST = ROOT / "dist"

ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}


def main() -> int:
    for name in ("MainKt.class", "Main.class"):
        p = DIST / name
        if p.exists():
            return subprocess.run(
                ["test", "-f", str(p)],
                env=ENV,
                cwd=str(ROOT),
            ).returncode
    print("error: no MainKt.class or Main.class in dist", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
