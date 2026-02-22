#!/usr/bin/env python3
"""Verify REQ.json against req_v1 schema. Hard fail on invalid."""
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

    from verifier.schema_validate import validate_req, SchemaValidationError

    req_root = Path(args.request_dir).resolve() if args.request_dir else (BASE / "suites" / "v1" / "req_cases")
    if not req_root.exists():
        # No req cases dir yet (e.g. before build_req_fixtures) - pass
        print("verify_req_schema_strict: PASS (no request dir)")
        return 0

    errors: list[str] = []
    for item in sorted(req_root.iterdir()):
        if item.is_dir():
            req_path = item / "REQ.json"
            if req_path.exists():
                try:
                    obj = json.loads(req_path.read_text(encoding="utf-8", errors="replace"))
                    validate_req(obj)
                except SchemaValidationError as e:
                    errors.append(f"{item.name}: {e}")
                except Exception as e:
                    errors.append(f"{item.name}: {e}")

    if errors:
        for e in errors:
            sys.stderr.write(f"REQ_SCHEMA_INVALID: {e}\n")
        return 1
    print("verify_req_schema_strict: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
