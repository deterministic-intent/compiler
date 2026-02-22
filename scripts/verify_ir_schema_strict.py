#!/usr/bin/env python3
"""Verify payload.json (IR) against ir_v1 schema. Hard fail on invalid."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request-dir", default="")
    ap.add_argument("--v1-only", action="store_true")
    args, _ = ap.parse_known_args()

    from verifier.schema_validate import validate_ir, SchemaValidationError

    req_root = Path(args.request_dir).resolve() if args.request_dir else (BASE / "state" / "requests")
    if not req_root.exists():
        sys.stderr.write(f"FAIL: request dir not found: {req_root}\n")
        return 1

    errors: list[str] = []
    for rd in sorted(req_root.iterdir()):
        if not rd.is_dir():
            continue
        payload_path = rd / "payload.json"
        if not payload_path.exists():
            continue
        try:
            obj = json.loads(payload_path.read_text(encoding="utf-8", errors="replace"))
            validate_ir(obj)
        except SchemaValidationError as e:
            errors.append(f"{rd.name}: {e}")
        except Exception as e:
            errors.append(f"{rd.name}: {e}")

    if errors:
        for e in errors:
            sys.stderr.write(f"IR_SCHEMA_INVALID: {e}\n")
        return 1
    print("verify_ir_schema_strict: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
