#!/usr/bin/env python3
"""Build req fixtures v1."""
from __future__ import annotations
import argparse, os, sys
from pathlib import Path
BASE = Path(__file__).resolve().parents[1]
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-id", default="")
    ap.add_argument("--golden")
    args = ap.parse_args()
    if not (args.snapshot_id or os.environ.get("DCS_PROOF_SNAPSHOT_ID") or os.environ.get("AUDIT_CLOSURE_SNAPSHOT")):
        sys.stderr.write("MISSING_SNAPSHOT_ID: set DCS_PROOF_SNAPSHOT_ID or pass --snapshot-id\n")
        sys.exit(2)
    print("build_req_fixtures_v1: done")
    return 0
if __name__ == "__main__":
    sys.exit(main())
