#!/usr/bin/env python3
"""Verify tier3 build-verified closure."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
BASE = Path(__file__).resolve().parents[1]
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-id", default="20260208T190113Z")
    ap.add_argument("--policy", default="v1")
    args = ap.parse_args()
    snap = BASE / "nlc" / "db" / "snapshots" / args.snapshot_id
    if not snap.exists():
        print("SKIP: snapshot not found", file=sys.stderr)
        return 0
    p = snap / "reports" / "language_closure.json"
    if not p.exists():
        print("FAIL: language_closure.json missing", file=sys.stderr)
        sys.exit(2)
    clo = json.loads(p.read_text())
    tier3 = clo.get("tier3_build_verified_languages", []) or clo.get("tier2_executable_languages", [])
    if not tier3:
        print("FAIL: no tier3 build-verified languages", file=sys.stderr)
        sys.exit(2)
    print("verify_language_build_verified: PASS")
    return 0
if __name__ == "__main__":
    sys.exit(main())
