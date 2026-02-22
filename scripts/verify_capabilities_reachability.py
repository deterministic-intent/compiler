#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = "20260103T060637Z"


def _fail() -> None:
    print("FAIL capabilities:reachability_mismatch", file=sys.stderr)
    raise SystemExit(1)


def _read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8", errors="replace"))


def main() -> int:
    snapshot_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SNAPSHOT
    caps_path = BASE / "nlc" / "db" / "snapshots" / snapshot_id / "capabilities.json"
    if not caps_path.exists():
        _fail()
    caps = _read_json(caps_path)
    supported = caps.get("supported_artifact_classes", [])
    reachable = caps.get("reachable_artifact_classes_from_text", [])
    reachable_intents = caps.get("reachable_intents_from_text", [])
    if not isinstance(supported, list) or not isinstance(reachable, list) or not isinstance(reachable_intents, list):
        _fail()
    if any(r not in supported for r in reachable):
        _fail()

    intents_path = BASE / "nlc" / "db" / "snapshots" / snapshot_id / "manifest" / "intents.json"
    if not intents_path.exists():
        _fail()
    intents = _read_json(intents_path).get("intents", [])
    manifest_ids = [i.get("intent_id") for i in intents if isinstance(i, dict) and i.get("intent_id")]

    mined_path = BASE / "nlc" / "db" / "snapshots" / snapshot_id / "manifest" / "intents_mined.json"
    mined_ids = []
    if mined_path.exists():
        mined_obj = _read_json(mined_path)
        mined_intents = mined_obj.get("intents", []) if isinstance(mined_obj, dict) else []
        for it in mined_intents:
            if isinstance(it, dict) and it.get("intent_id") and it.get("status") == "ACTIVE":
                mined_ids.append(it.get("intent_id"))

    expected_reachable = sorted(set(manifest_ids + mined_ids))
    if sorted(reachable_intents) != expected_reachable:
        _fail()

    print("PASS capabilities_reachability")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

