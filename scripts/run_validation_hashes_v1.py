#!/usr/bin/env python3
"""
Build validation_hashes.json for snapshot. Includes language_closure.json
in the hash bundle for determinism. Languages are sorted before writing.
Paths are normalized for deterministic hashing (no /tmp/stab_run*, etc.).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from dcs_core.path_normalize import normalize_proof_obj


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-id", required=True)
    ap.add_argument("--out", required=True, help="Output path for validation_hashes.json")
    ap.add_argument("--network-guard-report", default="", help="Path to network_guard_report.json to include")
    ap.add_argument("--toolchain-manifest", default="", help="Path to toolchain_manifest.json to include")
    ap.add_argument("--repro-versions", default="", help="Path to repro_versions.json to include")
    ap.add_argument("--freeze-manifest", default="", help="Path to freeze_manifest_v1.json to include")
    ap.add_argument("--e2e0-report", default="", help="Path to e2e0_report.json to include")
    args = ap.parse_args()

    snap_root = BASE / "nlc" / "db" / "snapshots" / args.snapshot_id
    if not snap_root.exists():
        sys.stderr.write(f"FAIL: snapshot not found: {snap_root}\n")
        return 1

    closure_path = snap_root / "reports" / "language_closure.json"
    if not closure_path.exists():
        sys.stderr.write(f"FAIL: language_closure.json not found. Run report_language_closure first.\n")
        return 1

    language_closure_sha256 = _sha256_file(closure_path)
    clo = json.loads(closure_path.read_text(encoding="utf-8", errors="replace"))
    languages = sorted(clo.get("tier2_executable_languages", []) or [])

    out_path = Path(args.out)
    existing = {}
    if out_path.exists():
        try:
            existing = normalize_proof_obj(json.loads(out_path.read_text(encoding="utf-8", errors="replace")))
        except Exception:
            pass

    out = {
        **existing,
        "snapshot_id": args.snapshot_id,
        "language_closure_sha256": language_closure_sha256,
        "languages": languages,
    }

    ng_path = Path(args.network_guard_report).resolve() if args.network_guard_report else None
    if ng_path and ng_path.exists():
        out["network_guard_report_sha256"] = _sha256_file(ng_path)

    tc_path = Path(args.toolchain_manifest).resolve() if args.toolchain_manifest else None
    if tc_path and tc_path.exists():
        out["toolchain_manifest_sha256"] = _sha256_file(tc_path)

    rv_path = Path(args.repro_versions).resolve() if args.repro_versions else None
    if rv_path and rv_path.exists():
        out["repro_versions_sha256"] = _sha256_file(rv_path)

    fm_path = Path(args.freeze_manifest).resolve() if args.freeze_manifest else None
    if fm_path and fm_path.exists():
        out["freeze_manifest_sha256"] = _sha256_file(fm_path)

    e2e_path = Path(args.e2e0_report).resolve() if args.e2e0_report else None
    if e2e_path and e2e_path.exists():
        out["e2e0_report_sha256"] = _sha256_file(e2e_path)

    # Normalize paths for deterministic VALIDATION_HASHES_SHA256
    out = normalize_proof_obj(out)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(out, sort_keys=True)
    print(f"VH_OUT_PATH={out_path}")
    print(f"VH_PREWRITE_TMP_COUNT={blob.count('/tmp/stab_run')}")
    if "/tmp/stab_run" in blob:
        raise SystemExit("VALIDATION_HASH_PATH_NOT_NORMALIZED")
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written = out_path.read_text(encoding="utf-8", errors="replace")
    print(f"VH_POSTWRITE_TMP_COUNT={written.count('/tmp/stab_run')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
