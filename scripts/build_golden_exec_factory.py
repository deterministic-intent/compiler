#!/usr/bin/env python3
"""Build golden exec factory."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
BASE = Path(__file__).resolve().parents[1]
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-id", default="20260208T190113Z")
    args = ap.parse_args()
    out = BASE / "scripts" / "e2e" / "fixtures" / "golden_exec_factory.v1.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        out.write_text(json.dumps({"languages": [], "cases": []}) + "\n")
    print("build_golden_exec_factory: done")
    return 0
if __name__ == "__main__":
    sys.exit(main())
