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
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("request_id")
    ap.add_argument("--requests-root", help="Requests dir (default: BASE/state/requests or NLC_REQUESTS_ROOT)")
    args = ap.parse_args()
    if args.requests_root:
        req_root = Path(args.requests_root).resolve()
    elif os.environ.get("NLC_REQUESTS_ROOT"):
        req_root = Path(os.environ["NLC_REQUESTS_ROOT"]).resolve()
    else:
        req_root = BASE / "state" / "requests"

    request_dir = req_root / args.request_id
    if not request_dir.exists():
        print(f"ERROR: request dir not found: {request_dir}", file=sys.stderr)
        return 2

    from nlc.index.index_builder import build_index

    build_index(request_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


