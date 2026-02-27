#!/usr/bin/env python3
"""Create 6 NEG Golden Suite dirs."""
import json
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SUITE = BASE / "suites" / "golden" / "v1" / "requests"
ORCH = BASE / "orchestrator" / "orchestrator.py"
SNAP = "20260215T120000Z"


def gate0(neg_id: str, obj: str, env_add: dict) -> None:
    env = {**os.environ, **env_add}
    rd = BASE / "state" / "requests" / neg_id
    if rd.exists():
        import shutil
        shutil.rmtree(rd)
    r = subprocess.run(
        [sys.executable, str(ORCH), "gate0_init", neg_id, json.dumps(obj), "[]", "[]", "[]"],
        cwd=str(BASE), env=env, capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        sys.exit(1)


def copy_to_suite(neg_id: str) -> None:
    rd = BASE / "state" / "requests" / neg_id
    dest = SUITE / neg_id
    dest.mkdir(parents=True, exist_ok=True)
    for f in ("REQUEST.md", "payload.json", "gate0.status", "gate0.result.json"):
        if (rd / f).exists():
            (dest / f).write_bytes((rd / f).read_bytes())


def main():
    SUITE.mkdir(parents=True, exist_ok=True)

    # 1. NEG_MISSING_SNAPSHOT_ID
    gate0("NEG_MISSING_SNAPSHOT_ID", "Request without snapshot.", {"NLC_DB_SNAPSHOT_ID": "", "NLC_SNAPSHOT_ID": "", "NLC_KB_SNAPSHOT_ID": ""})
    copy_to_suite("NEG_MISSING_SNAPSHOT_ID")

    # 2. NEG_UNDECLARED_ARTIFACT_CLASS
    obj = "Request with undeclared lang_project.\n\n```json\n{\"artifact_class\": \"lang_project\"}\n```"
    gate0("NEG_UNDECLARED_ARTIFACT_CLASS", obj, {"NLC_DB_SNAPSHOT_ID": SNAP, "NLC_SNAPSHOT_ID": SNAP, "NLC_KB_SNAPSHOT_ID": SNAP})
    copy_to_suite("NEG_UNDECLARED_ARTIFACT_CLASS")

    # 3. NEG_SNAPSHOT_AUTHORITY_MISSING
    gate0("NEG_SNAPSHOT_AUTHORITY_MISSING", "Request with bogus snapshot.", {"NLC_DB_SNAPSHOT_ID": "BOGUS_SNAPSHOT_ID", "NLC_SNAPSHOT_ID": "BOGUS_SNAPSHOT_ID", "NLC_KB_SNAPSHOT_ID": "BOGUS_SNAPSHOT_ID"})
    copy_to_suite("NEG_SNAPSHOT_AUTHORITY_MISSING")

    # 4. NEG_BLOCKED_INVALID_ADAPTER
    obj = "Request with invalid adapter.\n\n```json\n{\"artifact_class\": \"nonexistent\", \"module_refs\": [\"fake/module.json\"]}\n```"
    gate0("NEG_BLOCKED_INVALID_ADAPTER", obj, {"NLC_DB_SNAPSHOT_ID": SNAP, "NLC_SNAPSHOT_ID": SNAP, "NLC_KB_SNAPSHOT_ID": SNAP})
    copy_to_suite("NEG_BLOCKED_INVALID_ADAPTER")

    # 5. NEG_ENV_OVERRIDE_FORBIDDEN
    (SUITE / "NEG_ENV_OVERRIDE_FORBIDDEN").mkdir(parents=True, exist_ok=True)
    (SUITE / "NEG_ENV_OVERRIDE_FORBIDDEN" / "expected_failure_id").write_text("ENV_OVERRIDE_FORBIDDEN_IN_V1\n")

    # 6. NEG_CONTRACT_OUTPUT_MISSING
    (SUITE / "NEG_CONTRACT_OUTPUT_MISSING").mkdir(parents=True, exist_ok=True)
    (SUITE / "NEG_CONTRACT_OUTPUT_MISSING" / "expected_failure_id").write_text("CONTRACT_OUTPUT_MISSING\n")

    print("create_neg_dirs: 6 NEG dirs created")


if __name__ == "__main__":
    main()
