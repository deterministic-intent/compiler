#!/usr/bin/env python3
"""Backfill schema_version='ir_v1' into payload.json files lacking it. Run once before strict IR validation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request-dir", default="", help="Request root (default: state/requests)")
    args = ap.parse_args()
    req_root = Path(args.request_dir).resolve() if args.request_dir else (BASE / "state" / "requests")
    if not req_root.exists():
        return 0
    n = 0
    for rd in sorted(req_root.iterdir()):
        if not rd.is_dir():
            continue
        payload_path = rd / "payload.json"
        if not payload_path.exists():
            continue
        try:
            obj = json.loads(payload_path.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:
            sys.stderr.write(f"{rd.name}: skip (invalid JSON): {e}\n")
            continue
        if obj.get("schema_version") == "ir_v1":
            continue
        obj["schema_version"] = "ir_v1"
        payload_path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        n += 1
        print(f"backfill: {rd.name}")
    if n:
        print(f"backfill_ir_schema_version: updated {n} payload(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
