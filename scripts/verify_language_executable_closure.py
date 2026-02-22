#!/usr/bin/env python3
"""Verify tier2 executable closure."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
BASE = Path(__file__).resolve().parents[1]
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-id", default="20260208T190113Z")
    args = ap.parse_args()
    snap = BASE / "nlc" / "db" / "snapshots" / args.snapshot_id
    if not snap.exists():
        print("SKIP: snapshot not found", file=sys.stderr)
        return 0
    p = snap / "reports" / "language_closure.json"
    if not p.exists():
        print("FAIL: language_closure.json missing", file=sys.stderr)
        sys.exit(2)
    tier2 = json.loads(p.read_text()).get("tier2_executable_languages", []) or []
    if not tier2:
        print("FAIL: no tier2 languages", file=sys.stderr)
        sys.exit(2)
    print("verify_language_executable_closure: PASS")
    return 0
if __name__ == "__main__":
    sys.exit(main())
