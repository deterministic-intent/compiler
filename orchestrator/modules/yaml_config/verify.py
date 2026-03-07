#!/usr/bin/env python3
"""Verify yaml_config: test -f dist/*.yaml or dist/*.yml"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
DIST = ROOT / "dist"

ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}


def main() -> int:
    yaml_files = list(DIST.glob("*.yaml")) + list(DIST.glob("*.yml"))
    if not yaml_files:
        print("error: no .yaml/.yml in dist", file=sys.stderr)
        return 1
    for p in yaml_files:
        r = subprocess.run(["test", "-f", str(p)], env=ENV, cwd=str(ROOT))
        if r.returncode != 0:
            return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
