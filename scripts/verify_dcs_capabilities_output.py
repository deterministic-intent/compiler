#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def _fail(msg: str) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(1)


def _dcs_cmd() -> list[str]:
    cmd = shutil.which("dcs")
    if cmd:
        return [cmd]
    return [sys.executable, "-m", "dcs_cli.main"]


def main() -> int:
    snapshot_id = (os.environ.get("DCS_PROOF_SNAPSHOT_ID") or os.environ.get("AUDIT_CLOSURE_SNAPSHOT") or os.environ.get("NLC_DB_SNAPSHOT_ID") or "").strip()
    if not snapshot_id:
        _fail("MISSING_SNAPSHOT_ID: set DCS_PROOF_SNAPSHOT_ID or NLC_DB_SNAPSHOT_ID")
    caps_path = BASE / "nlc" / "db" / "snapshots" / snapshot_id / "capabilities.json"
    intents_path = BASE / "nlc" / "db" / "snapshots" / snapshot_id / "manifest" / "intents.json"
    mined_path = BASE / "nlc" / "db" / "snapshots" / snapshot_id / "manifest" / "intents_mined.json"
    caps = json.loads(caps_path.read_text(encoding="utf-8", errors="replace"))
    intents_obj = json.loads(intents_path.read_text(encoding="utf-8", errors="replace"))
    intents_map = {i["intent_id"]: i.get("name", i["intent_id"]) for i in intents_obj.get("intents", []) if isinstance(i, dict) and i.get("intent_id")}
    if mined_path.exists():
        mined_obj = json.loads(mined_path.read_text(encoding="utf-8", errors="replace"))
        mined = mined_obj.get("intents", []) if isinstance(mined_obj, dict) else []
        for it in mined:
            if isinstance(it, dict) and it.get("intent_id"):
                intents_map.setdefault(it["intent_id"], it.get("name", it["intent_id"]))
    languages = caps.get("languages", [])
    reachable_intents = caps.get("reachable_intents_from_text", [])
    truth_backed = caps.get("truth_backed_artifact_classes", [])
    lines = []
    lines.append("DCS CAPABILITIES")
    lines.append(f"snapshot_id: {snapshot_id}")
    lines.append(f"languages: {', '.join(languages)}")
    lines.append("reachable_intents:")
    for iid in reachable_intents:
        name = intents_map.get(iid, iid)
        lines.append(f"- {iid}: {name}")
    lines.append(f"truth_backed_artifact_classes: {', '.join(truth_backed)}")
    lines.append("run: dcs")
    expected = "\n".join(lines) + "\n"
    env = os.environ.copy()
    env["NLC_DB_SNAPSHOT_ID"] = SNAPSHOT
    p = subprocess.run(_dcs_cmd() + ["capabilities"], capture_output=True, text=True, env=env)
    if p.returncode != 0:
        _fail("FAIL dcs_capabilities: command failed")
    if p.stdout != expected:
        _fail("FAIL dcs_capabilities: output mismatch")
    print("PASS dcs_capabilities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

