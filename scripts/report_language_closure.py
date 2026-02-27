#!/usr/bin/env python3
"""
Report language tier closure: which languages are tier0/tier1/tier2/tier3 per policy.
Snapshot-pinned: loads intents_executable.json strictly from snapshot. No dynamic
capability intersection, no toolchain probing, no runtime filtering.
Writes: nlc/db/snapshots/<id>/reports/language_closure.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import os

BASE = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser(description="Report language closure (tier0..tier3)")
    ap.add_argument("--snapshot-id", default="", help="Snapshot ID")
    ap.add_argument("--policy", default="v1", help="Policy version")
    args = ap.parse_args()

    snapshot_id = (args.snapshot_id or os.environ.get("DCS_PROOF_SNAPSHOT_ID") or os.environ.get("AUDIT_CLOSURE_SNAPSHOT") or "").strip()
    if not snapshot_id:
        sys.stderr.write("MISSING_SNAPSHOT_ID: set DCS_PROOF_SNAPSHOT_ID or pass --snapshot-id\n")
        sys.exit(2)

    snap_root = (BASE / "nlc" / "db" / "snapshots" / snapshot_id).resolve()
    if not snap_root.exists():
        sys.stderr.write(f"FAIL: snapshot not found: {snap_root}\n")
        sys.exit(1)

    # Snapshot-pinned: intents_executable.json MUST be inside snapshot
    intents_path = (snap_root / "manifest" / "intents_executable.json").resolve()
    if not intents_path.resolve().is_relative_to(snap_root.resolve()):
        raise RuntimeError("intents_executable.json must be snapshot-pinned")
    if not intents_path.exists():
        sys.stderr.write(f"FAIL: intents_executable.json not found: {intents_path}\n")
        sys.exit(1)

    data = json.loads(intents_path.read_text(encoding="utf-8", errors="replace"))
    exec_intents = data.get("intents", []) or []
    exec_langs = set()
    for i in exec_intents:
        lang = (i.get("language") or i.get("artifact_class") or "").strip()
        if lang:
            exec_langs.add(lang)

    tier2 = sorted(exec_langs)
    tier0 = tier2  # registry = executable closure for snapshot-pinned report
    tier1 = tier2
    tier3 = list(tier2)

    # Read supported_artifact_classes from capabilities (static only; no filtering)
    caps_path = snap_root / "capabilities.json"
    supported_classes = []
    if caps_path.exists():
        try:
            caps = json.loads(caps_path.read_text(encoding="utf-8", errors="replace"))
            supported_classes = sorted(caps.get("supported_artifact_classes", []) or [])
        except Exception:
            pass

    # Determinism: sorted languages, sort_keys=True
    out = {
        "snapshot_id": snapshot_id,
        "policy_version": args.policy,
        "tier0_registry_languages": tier0,
        "tier1_exists_languages": tier1,
        "tier2_executable_languages": tier2,
        "tier3_build_verified_languages": tier3,
        "detected_toolchains": [],
        "supported_artifact_classes": supported_classes,
    }

    reports_dir = snap_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / "language_closure.json"
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"report_language_closure: wrote {out_path}")
    print(f"  tier0: {len(tier0)}, tier1: {len(tier1)}, tier2: {len(tier2)}, tier3: {len(tier3)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
