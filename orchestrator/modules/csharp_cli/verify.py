#!/usr/bin/env python3
"""Verify csharp_cli: test -f dist/*.dll"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
DIST = ROOT / "dist"

ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}


def main() -> int:
    dlls = list(DIST.glob("*.dll"))
    if not dlls:
        print("error: no .dll in dist", file=sys.stderr)
        return 1
    for dll in dlls:
        r = subprocess.run(["test", "-f", str(dll)], env=ENV, cwd=str(ROOT))
        if r.returncode != 0:
            return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
