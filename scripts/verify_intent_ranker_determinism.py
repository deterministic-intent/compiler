#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def _fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    snapshot_id = (os.environ.get("DCS_PROOF_SNAPSHOT_ID") or os.environ.get("AUDIT_CLOSURE_SNAPSHOT") or os.environ.get("NLC_DB_SNAPSHOT_ID") or "").strip()
    if not snapshot_id:
        _fail("MISSING_SNAPSHOT_ID: set DCS_PROOF_SNAPSHOT_ID or NLC_DB_SNAPSHOT_ID")
    intents_path = BASE / "nlc" / "db" / "snapshots" / snapshot_id / "manifest" / "intents.json"
    if not intents_path.exists():
        _fail("FAIL intent_ranker: intents manifest missing")
    obj = json.loads(intents_path.read_text(encoding="utf-8", errors="replace"))
    intents_manifest = {i["intent_id"]: i for i in obj.get("intents", []) if isinstance(i, dict) and i.get("intent_id")}
    if not intents_manifest:
        _fail("FAIL intent_ranker: intents manifest empty")
    from nlc.prompt_compiler import rank_intents
    prompt = "do something with numbers and csv"
    r1 = rank_intents(prompt, intents_manifest)
    r2 = rank_intents(prompt, intents_manifest)
    if json.dumps(r1, sort_keys=True) != json.dumps(r2, sort_keys=True):
        _fail("FAIL intent_ranker: nondeterministic ranking")
    print("PASS intent_ranker")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

