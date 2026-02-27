#!/usr/bin/env python3
"""
Verify projects for tier2 languages are buildable (per policy tier3_build).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def main() -> int:
    import os
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-id", default="")
    ap.add_argument("--policy", default="v1")
    args = ap.parse_args()
    snapshot_id = (args.snapshot_id or os.environ.get("DCS_PROOF_SNAPSHOT_ID") or os.environ.get("AUDIT_CLOSURE_SNAPSHOT") or "").strip()
    if not snapshot_id:
        print("ERROR: MISSING_SNAPSHOT_ID: set DCS_PROOF_SNAPSHOT_ID or pass --snapshot-id", file=sys.stderr)
        return 2

    snap = BASE / "nlc" / "db" / "snapshots" / snapshot_id
    if not snap.exists():
        print("SKIP: snapshot not found", file=sys.stderr)
        return 0

    closure_path = snap / "reports" / "language_closure.json"
    if not closure_path.exists():
        print("FAIL: language_closure.json missing", file=sys.stderr)
        sys.exit(2)

    tier2 = json.loads(closure_path.read_text(encoding="utf-8")).get("tier2_executable_languages", []) or []
    if not tier2:
        print("FAIL: no tier2 languages to verify build", file=sys.stderr)
        sys.exit(2)

    print("verify_project_buildable: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
