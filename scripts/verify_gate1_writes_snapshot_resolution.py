#!/usr/bin/env python3
"""
Gate1 contract: snapshot_resolution.json required when gate1 completes.
Verifies that a request that passed gate1 has snapshot_resolution.json.
"""
import argparse
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
REQUESTS_ROOT = BASE / "state" / "requests"


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify gate1 writes snapshot_resolution.json")
    ap.add_argument("--request-id", required=True, help="Request ID (e.g. E2E0-B-AUDIT)")
    args = ap.parse_args()

    req_dir = REQUESTS_ROOT / args.request_id
    if not req_dir.exists() or not req_dir.is_dir():
        print(f"ERROR: request dir not found: {req_dir}", file=sys.stderr)
        return 2

    sr = req_dir / "snapshot_resolution.json"
    if not sr.exists() or not sr.is_file():
        print(f"FAIL: snapshot_resolution.json missing in {req_dir}", file=sys.stderr)
        return 1
    if sr.stat().st_size == 0:
        print(f"FAIL: snapshot_resolution.json is empty in {req_dir}", file=sys.stderr)
        return 1

    print("✓ Gate1 contract: snapshot_resolution.json present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
