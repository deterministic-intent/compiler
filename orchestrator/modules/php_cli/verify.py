#!/usr/bin/env python3
"""Verify php_cli: php -l dist/main.php"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("PROJECT_ROOT", ".")).resolve()
DIST = ROOT / "dist"

ENV = {**os.environ, "LC_ALL": "C", "LANG": "C"}


def main() -> int:
    main_php = DIST / "main.php"
    if not main_php.exists():
        print("error: dist/main.php not found", file=sys.stderr)
        return 1
    return subprocess.run(
        ["php", "-l", str(main_php)],
        env=ENV,
        cwd=str(ROOT),
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
