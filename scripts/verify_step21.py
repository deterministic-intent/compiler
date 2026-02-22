#!/usr/bin/env python3
"""
Step 21: Capability catalog (snapshot-derived) + determinism proof.

Acceptance:
  python3 scripts/verify_step21.py; echo STEP21_EXIT=$?

Locked failure tokens:
  FAIL step21:missing_snapshot
  FAIL step21:index_missing
  FAIL step21:non_deterministic_output
  FAIL step21:capability_claim_without_evidence
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


BASE = Path(__file__).resolve().parents[1]
SNAP_ROOT = BASE / "nlc" / "db" / "snapshots"


def _fail(token: str) -> None:
    sys.stdout.write(f"FAIL {token}\n")
    sys.stdout.flush()
    raise SystemExit(1)


def _sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()


def _read_bytes(p: Path) -> bytes:
    return p.read_bytes()


def _read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8", errors="replace"))


def _run_build(snapshot_id: str, policy: str) -> Path:
    p = subprocess.run(
        [sys.executable, str(BASE / "scripts" / "build_capabilities.py"), "--snapshot-id", snapshot_id, "--policy", policy],
        cwd=str(BASE),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=180,
    )
    out = (p.stdout or "").strip().splitlines()
    if p.returncode != 0 or not out:
        # build_capabilities emits locked FAIL tokens; surface them.
        sys.stdout.write((p.stdout or "") + (p.stderr or ""))
        sys.stdout.flush()
        raise SystemExit(p.returncode or 1)
    return Path(out[-1]).resolve()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-id", default="20260103T060637Z")
    ap.add_argument("--policy", default="v1")
    args = ap.parse_args()

    snapshot_id = str(args.snapshot_id).strip()
    policy = str(args.policy).strip() or "v1"

    snap_dir = SNAP_ROOT / snapshot_id
    if not snap_dir.exists():
        _fail("step21:missing_snapshot")

    # Build twice and ensure byte-identical output.
    p1 = _run_build(snapshot_id, policy)
    b1 = _read_bytes(p1)
    h1 = _sha256_bytes(b1)

    p2 = _run_build(snapshot_id, policy)
    b2 = _read_bytes(p2)
    h2 = _sha256_bytes(b2)
    if b1 != b2 or h1 != h2:
        _fail("step21:non_deterministic_output")

    obj = _read_json(p1)
    if not isinstance(obj, dict):
        _fail("step21:capability_claim_without_evidence")

    # Required fields
    langs = obj.get("languages", [])
    tools = obj.get("tools", [])
    arts = obj.get("supported_artifact_classes", [])
    evidence = obj.get("evidence", {})
    if not (isinstance(langs, list) and langs):
        _fail("step21:capability_claim_without_evidence")
    if not (isinstance(tools, list) and tools):
        _fail("step21:capability_claim_without_evidence")
    if not (isinstance(arts, list) and arts):
        _fail("step21:capability_claim_without_evidence")
    if not (isinstance(evidence, dict) and str(evidence.get("index_sha256", "")).strip()):
        _fail("step21:index_missing")

    # Evidence must align with snapshot manifests (no claim without evidence).
    modules_path = snap_dir / "manifest" / "modules.json"
    intents_path = snap_dir / "manifest" / "intents.json"
    if not modules_path.exists() or not intents_path.exists():
        _fail("step21:missing_snapshot")

    mods = _read_json(modules_path)
    ints = _read_json(intents_path)
    if not isinstance(mods, dict) or not isinstance(ints, dict):
        _fail("step21:missing_snapshot")

    mod_acs = set()
    for m in (mods.get("modules", []) if isinstance(mods.get("modules", []), list) else []):
        if isinstance(m, dict) and isinstance(m.get("artifact_class"), str) and m.get("artifact_class").strip():
            mod_acs.add(m.get("artifact_class").strip())
    intent_ids = set()
    for it in (ints.get("intents", []) if isinstance(ints.get("intents", []), list) else []):
        if isinstance(it, dict) and isinstance(it.get("intent_id"), str) and it.get("intent_id").strip():
            intent_ids.add(it.get("intent_id").strip())

    for ac in arts:
        if ac not in mod_acs:
            _fail("step21:capability_claim_without_evidence")
    for t in tools:
        if t not in intent_ids:
            _fail("step21:capability_claim_without_evidence")

    sys.stdout.write("✓ Step 21 capabilities.json is deterministic and snapshot-pinned\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


