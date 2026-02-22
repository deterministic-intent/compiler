#!/usr/bin/env python3
"""
Build freeze manifest hash block. Single source of truth for governance.
Computes sha256 of authoritative schema/contract/taxonomy files and writes
the hashes block into governance/freeze_manifest_v1.json.
Hard fail if any file missing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
FREEZE_PATH = BASE / "governance" / "freeze_manifest_v1.json"

FILES = {
    "ir_schema_sha256": BASE / "schemas" / "ir_v1.schema.json",
    "req_schema_sha256": BASE / "schemas" / "req_v1.schema.json",
    "failure_taxonomy_sha256": BASE / "workers" / "failure_canonicalizer.py",
    "artifact_contract_sha256": BASE / "contracts" / "contract_rules.json",
}


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="", help="Override output path for freeze manifest")
    args = ap.parse_args()
    out_path = Path(args.out).resolve() if args.out else FREEZE_PATH

    for key, p in FILES.items():
        if not p.exists():
            sys.stderr.write(f"FAIL: FREEZE_FILE_MISSING: {key} source not found: {p}\n")
            return 1

    hashes = {k: _sha256_file(p) for k, p in sorted(FILES.items())}

    existing = {}
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass

    out = {**existing, "hashes": hashes}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
