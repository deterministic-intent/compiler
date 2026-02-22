#!/usr/bin/env python3
"""
Step 11: Build request-local deterministic index DB from snapshots only.

Usage:
  python3 scripts/build_index_db.py <request_id>
"""

import argparse
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("request_id")
    args = ap.parse_args()

    request_dir = BASE / "state" / "requests" / args.request_id
    if not request_dir.exists():
        print(f"ERROR: request dir not found: {request_dir}", file=sys.stderr)
        return 2

    from nlc.index.index_builder import build_index

    build_index(request_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


