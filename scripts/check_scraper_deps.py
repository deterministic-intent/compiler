#!/usr/bin/env python3
"""
Step 19: dependency detection for scraper stack (no installs, only detection).

Behavior:
- Tries importing: sqlalchemy, httpx, bs4
- On missing, prints exactly one line:
    SCRAPER_DEPS_MISSING: <missing...>
  (only list what's missing)
- Exit 1 if any missing, else exit 0.
"""

from __future__ import annotations

import sys


def _can_import(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def main() -> int:
    missing: list[str] = []
    for mod in ("sqlalchemy", "httpx", "bs4"):
        if not _can_import(mod):
            missing.append(mod)
    if missing:
        # Exactly one line.
        sys.stdout.write("SCRAPER_DEPS_MISSING: " + " ".join(missing) + "\n")
        sys.stdout.flush()
        return 1
    # Exactly one line.
    sys.stdout.write("SCRAPER_DEPS_OK\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


