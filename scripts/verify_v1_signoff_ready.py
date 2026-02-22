#!/usr/bin/env python3
"""
Evidence-derived v1 signoff readiness. No boolean attestation.
Checks: evidence files exist, hashes match validation_hashes, freeze governance passes,
E2E0 report has A/B/C/D all PASS.
Exit 0 + V1_SIGNOFF_READY=YES on success, exit 2 otherwise.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
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
    ap.add_argument("--base", default="", help="Kit/repo root (default: cwd for kit runs)")
    args = ap.parse_args()

    # Resolve relative to KIT_ROOT (cwd when running from kit) - not repo outside kit
    base = Path(args.base).resolve() if args.base else Path.cwd()
    snap_id = (args.snapshot_id or "").strip() or os.environ.get("AUDIT_CLOSURE_SNAPSHOT", "").strip()
    if not snap_id:
        sys.stderr.write("FAIL: --snapshot-id or AUDIT_CLOSURE_SNAPSHOT required\n")
        return 2

    # Evidence paths: all under base (KIT_ROOT) - out/ and snapshot reports from kit run
    vh_path = base / "nlc" / "db" / "snapshots" / snap_id / "reports" / "validation_hashes.json"
    tc_path = base / "out" / "toolchain_manifest.json"
    ng_path = base / "out" / "network_guard_report.json"
    rv_path = base / "versions" / "repro_versions.json"
    fm_path = base / "governance" / "freeze_manifest_v1.json"
    e2e_path = base / "out" / "e2e0_report.json"
    attestation_path = base / "governance" / "v1_signoff_attestation.json"

    evidence = [
        ("validation_hashes", vh_path),
        ("toolchain_manifest", tc_path),
        ("network_guard_report", ng_path),
        ("repro_versions", rv_path),
        ("freeze_manifest", fm_path),
        ("e2e0_report", e2e_path),
    ]

    # 1) All evidence files exist
    missing = [name for name, p in evidence if not p.exists()]
    if missing:
        sys.stderr.write(f"FAIL: evidence files missing: {missing}\n")
        return 2

    # 2) validation_hashes content matches recomputed hashes for included artifacts
    vh = json.loads(vh_path.read_text(encoding="utf-8", errors="replace"))
    hash_keys = {
        "toolchain_manifest": "toolchain_manifest_sha256",
        "network_guard_report": "network_guard_report_sha256",
        "repro_versions": "repro_versions_sha256",
        "freeze_manifest": "freeze_manifest_sha256",
        "e2e0_report": "e2e0_report_sha256",
    }
    for name, p in evidence:
        if name == "validation_hashes":
            continue
        key = hash_keys.get(name)
        if not key or key not in vh:
            continue
        expected = str(vh[key]).strip()
        actual = _sha256_file(p)
        if actual != expected:
            sys.stderr.write(f"FAIL: {name} sha256 mismatch: expected {expected} got {actual}\n")
            return 2

    # 3) verify_freeze_governance_v1 passes (run from base so it reads kit governance)
    r = subprocess.run(
        [sys.executable, str(base / "scripts" / "verify_freeze_governance_v1.py")],
        cwd=str(base),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        sys.stderr.write(f"FAIL: verify_freeze_governance_v1 failed:\n{r.stderr}\n")
        return 2

    # 4) Attestation exists and evidence hashes match
    if not attestation_path.exists():
        sys.stderr.write("FAIL: attestation missing - run fill_v1_signoff_attestation.py after audit\n")
        return 2
    attestation = json.loads(attestation_path.read_text(encoding="utf-8", errors="replace"))
    ev = attestation.get("evidence") or {}
    computed = {
        "freeze_manifest_sha256": _sha256_file(fm_path),
        "repro_versions_sha256": _sha256_file(rv_path),
        "toolchain_manifest_sha256": _sha256_file(tc_path),
        "network_guard_report_sha256": _sha256_file(ng_path),
        "validation_hashes_sha256": _sha256_file(vh_path),
        "e2e0_report_sha256": _sha256_file(e2e_path),
    }
    for k, v in computed.items():
        if str(ev.get(k, "")).strip() != v:
            sys.stderr.write(f"FAIL: attestation evidence.{k} mismatch (run fill_v1_signoff_attestation.py)\n")
            return 2

    # 5) E2E0 report: A/B/C/D all PASS
    e2e = json.loads(e2e_path.read_text(encoding="utf-8", errors="replace"))
    e2e0 = e2e.get("e2e0") or {}
    for k in ("A", "B", "C", "D"):
        if str(e2e0.get(k, "")).strip() != "PASS":
            sys.stderr.write(f"FAIL: e2e0_report.{k} is not PASS (got {e2e0.get(k)})\n")
            return 2

    print("V1_SIGNOFF_READY=YES")
    return 0


if __name__ == "__main__":
    sys.exit(main())
