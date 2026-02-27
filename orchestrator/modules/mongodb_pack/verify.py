#!/usr/bin/env python3
"""Verify mongodb_pack: test -f dist/schema.json"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
DIST = ROOT / "dist"

ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}


def main() -> int:
    schema = DIST / "schema.json"
    if not schema.exists():
        print("error: dist/schema.json not found", file=sys.stderr)
        return 1
    return subprocess.run(
        ["test", "-f", str(schema)],
        env=ENV,
        cwd=str(ROOT),
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
