#!/usr/bin/env python3
"""Verify rust_cli: test -x dist/main"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
DIST = ROOT / "dist"

ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}


def main() -> int:
    main_exe = DIST / "main"
    if not main_exe.exists():
        print("error: dist/main not found", file=sys.stderr)
        return 1
    return subprocess.run(
        ["test", "-x", str(main_exe)],
        env=ENV,
        cwd=str(ROOT),
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
