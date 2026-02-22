#!/usr/bin/env python3
"""
Enforce formal freeze governance. Cryptographic + semantic.
- freeze_manifest hashes.* must match recomputed file hashes (FREEZE_HASH_MISMATCH)
- IR/REQ schema versions must match freeze manifest (FREEZE_VERSION_MISMATCH)
- All required files must exist (FREEZE_FILE_MISSING)
No fallback. No best-effort.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
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
    if not FREEZE_PATH.exists():
        sys.stderr.write(f"FAIL: FREEZE_FILE_MISSING: freeze manifest not found: {FREEZE_PATH}\n")
        return 1

    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8", errors="replace"))
    expect_ir = str(freeze.get("ir_schema_version", "")).strip()
    expect_req = str(freeze.get("req_schema_version", "")).strip()
    expect_contract = str(freeze.get("artifact_contract_version", "")).strip()
    hashes_block = freeze.get("hashes")

    errors: list[str] = []

    # Hard fail if hashes block missing (do not build it - run build_freeze_hashes_v1.py first)
    if not hashes_block or not isinstance(hashes_block, dict):
        errors.append("FREEZE_HASH_MISMATCH: hashes block missing in freeze manifest - run build_freeze_hashes_v1.py first")

    # FREEZE_FILE_MISSING: all hashed files must exist
    for key, p in FILES.items():
        if not p.exists():
            errors.append(f"FREEZE_FILE_MISSING: {key} source not found: {p}")

    # FREEZE_HASH_MISMATCH: recompute and compare
    if hashes_block:
        for key, p in sorted(FILES.items()):
            if not p.exists():
                continue
            expected = str(hashes_block.get(key, "")).strip()
            if not expected:
                errors.append(f"FREEZE_HASH_MISMATCH: freeze manifest missing hash for {key}")
                continue
            actual = _sha256_file(p)
            if actual != expected:
                errors.append(f"FREEZE_HASH_MISMATCH: {key} expected {expected} got {actual}")

    # FREEZE_VERSION_MISMATCH: schema/contract versions
    try:
        from verifier.schema_validate import IR_SCHEMA_VERSION, REQ_SCHEMA_VERSION
        if IR_SCHEMA_VERSION != expect_ir:
            errors.append(f"FREEZE_VERSION_MISMATCH: IR schema expected {expect_ir} got {IR_SCHEMA_VERSION}")
        if REQ_SCHEMA_VERSION != expect_req:
            errors.append(f"FREEZE_VERSION_MISMATCH: REQ schema expected {expect_req} got {REQ_SCHEMA_VERSION}")
    except Exception as e:
        errors.append(f"FREEZE_VERSION_MISMATCH: could not load schema versions: {e}")

    contract_path = BASE / "contracts" / "contract_rules.json"
    if contract_path.exists():
        try:
            cr = json.loads(contract_path.read_text(encoding="utf-8", errors="replace"))
            got = str(cr.get("version", "")).strip()
            if got != expect_contract:
                errors.append(f"FREEZE_VERSION_MISMATCH: artifact contract expected {expect_contract} got {got}")
        except Exception as e:
            errors.append(f"FREEZE_VERSION_MISMATCH: could not read contract: {e}")
    elif not errors:  # only if we didn't already fail on FILE_MISSING
        errors.append("FREEZE_FILE_MISSING: contracts/contract_rules.json not found")

    if errors:
        for e in errors:
            sys.stderr.write(f"FAIL: {e}\n")
        return 1

    print("verify_freeze_governance_v1: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
