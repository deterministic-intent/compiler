#!/usr/bin/env python3
"""
Fill v1_signoff_attestation.json with hash commitments from produced artifacts.
Run after audit and validation_hashes update. Hard fail if any evidence missing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-id", default="", help="Snapshot ID (default: AUDIT_CLOSURE_SNAPSHOT env)")
    ap.add_argument("--base", default="", help="Kit root (default: cwd)")
    args = ap.parse_args()

    base = Path(args.base).resolve() if args.base else Path.cwd()
    snap_id = (args.snapshot_id or "").strip() or os.environ.get("AUDIT_CLOSURE_SNAPSHOT", "").strip()
    if not snap_id:
        sys.stderr.write("FAIL: --snapshot-id or AUDIT_CLOSURE_SNAPSHOT required\n")
        return 1

    vh_path = base / "nlc" / "db" / "snapshots" / snap_id / "reports" / "validation_hashes.json"
    tc_path = base / "out" / "toolchain_manifest.json"
    ng_path = base / "out" / "network_guard_report.json"
    rv_path = base / "versions" / "repro_versions.json"
    fm_path = base / "governance" / "freeze_manifest_v1.json"
    e2e_path = base / "out" / "e2e0_report.json"

    for name, p in [("validation_hashes", vh_path), ("toolchain_manifest", tc_path),
                    ("network_guard_report", ng_path), ("repro_versions", rv_path),
                    ("freeze_manifest", fm_path), ("e2e0_report", e2e_path)]:
        if not p.exists():
            sys.stderr.write(f"FAIL: evidence file missing: {p}\n")
            return 1

    evidence = {
        "freeze_manifest_sha256": _sha256_file(fm_path),
        "repro_versions_sha256": _sha256_file(rv_path),
        "toolchain_manifest_sha256": _sha256_file(tc_path),
        "network_guard_report_sha256": _sha256_file(ng_path),
        "validation_hashes_sha256": _sha256_file(vh_path),
        "e2e0_report_sha256": _sha256_file(e2e_path),
    }

    attestation_path = base / "governance" / "v1_signoff_attestation.json"
    existing = {}
    if attestation_path.exists():
        try:
            existing = json.loads(attestation_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass

    out = {
        **existing,
        "attestation_version": "v1",
        "target_tag": "nlc-v1.0.0",
        "source_tag": "nlc-v1.0.0-rc2",
        "rc_commit": existing.get("rc_commit", "10ac61e"),
        "evidence": evidence,
    }
    attestation_path.parent.mkdir(parents=True, exist_ok=True)
    attestation_path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
