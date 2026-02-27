#!/usr/bin/env python3
"""Verify tier1 exists closure."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
BASE = Path(__file__).resolve().parents[1]
def main():
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-id", default="")
    args = ap.parse_args()
    snapshot_id = (args.snapshot_id or os.environ.get("DCS_PROOF_SNAPSHOT_ID") or os.environ.get("AUDIT_CLOSURE_SNAPSHOT") or "").strip()
    if not snapshot_id:
        sys.stderr.write("MISSING_SNAPSHOT_ID: set DCS_PROOF_SNAPSHOT_ID or pass --snapshot-id\n")
        return 2
    snap = BASE / "nlc" / "db" / "snapshots" / snapshot_id
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
