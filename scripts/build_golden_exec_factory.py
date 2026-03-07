#!/usr/bin/env python3
"""Build golden exec factory."""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
BASE = Path(__file__).resolve().parents[1]
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-id", default="")
    args = ap.parse_args()
    if not (args.snapshot_id or os.environ.get("DCS_PROOF_SNAPSHOT_ID") or os.environ.get("AUDIT_CLOSURE_SNAPSHOT")):
        sys.stderr.write("MISSING_SNAPSHOT_ID: set DCS_PROOF_SNAPSHOT_ID or pass --snapshot-id\n")
        sys.exit(2)
    out = BASE / "scripts" / "e2e" / "fixtures" / "golden_exec_factory.v1.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        out.write_text(json.dumps({"languages": [], "cases": []}) + "\n")
    print("build_golden_exec_factory: done")
    return 0
if __name__ == "__main__":
    sys.exit(main())
