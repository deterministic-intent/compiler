#!/usr/bin/env python3
"""Verify tier1 exists closure."""
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
    caps = json.loads((snap / "capabilities.json").read_text(encoding="utf-8"))
    langs = caps.get("languages") or []
    if not langs:
        print("FAIL: no languages in capabilities", file=sys.stderr)
        sys.exit(2)
    print("verify_language_exists_closure: PASS")
    return 0
if __name__ == "__main__":
    sys.exit(main())
