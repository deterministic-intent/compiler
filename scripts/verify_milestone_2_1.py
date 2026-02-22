#!/usr/bin/env python3
"""
Milestone 2.1: Deterministic repair loop proof on real verifier FAILs.

Proof targets:
- Repair triggers only when verifier status == FAIL
- iter_0 always exists when repair runs
- Accept path: FAIL -> PASS_AFTER_REPAIR
- Reject path: FAIL -> FAIL_PATCH_REJECTED with rollback proof (hashes restored)
- No repair on PASS or CLARIFY

Locked failure tokens (exact):
  FAIL m21:trigger_incorrect
  FAIL m21:accept_missing_artifacts
  FAIL m21:accept_not_pass_after_repair
  FAIL m21:reject_not_patch_rejected
  FAIL m21:rollback_not_verified
  FAIL m21:unexpected_repair
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def _fail(token: str) -> None:
    sys.stdout.write(token.strip() + "\n")
    sys.stdout.flush()
    raise SystemExit(1)


def _run(cmd: List[str], *, env: Dict[str, str], allow_fail: bool = False) -> subprocess.CompletedProcess:
    p = subprocess.run(
        cmd,
        cwd=str(BASE),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if p.returncode != 0 and not allow_fail:
        sys.stdout.write((p.stdout or "") + (p.stderr or ""))
        sys.stdout.flush()
        raise SystemExit(p.returncode or 2)
    return p


def _rd(request_id: str) -> Path:
    return BASE / "state" / "requests" / request_id


def _cleanup(request_id: str) -> None:
    rd = _rd(request_id)
    if rd.exists():
        shutil.rmtree(rd, ignore_errors=True)


def _write_text(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")


def _load_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8", errors="replace"))


def _stage_proposal(request_id: str, diff_text: str) -> Path:
    # Repair runner reads state/requests/<id>/repair/iter_1/proposal.diff in stub mode.
    p = _rd(request_id) / "repair" / "iter_1" / "proposal.diff"
    _write_text(p, diff_text)
    return p


def _patch_payload_add_deliverable(request_id: str, relpath: str) -> None:
    payload_path = _rd(request_id) / "payload.json"
    payload = _load_json(payload_path)
    if not isinstance(payload, dict):
        _fail("FAIL m21:accept_missing_artifacts")
    dels = payload.get("deliverables", [])
    if not isinstance(dels, list):
        dels = []
    if not any(isinstance(d, dict) and d.get("path") == relpath for d in dels):
        dels.append({"path": relpath, "format": "markdown"})
    payload["deliverables"] = dels
    payload_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_gate_chain(request_id: str, env: Dict[str, str], *, through_gate: int) -> None:
    orch = str(BASE / "orchestrator" / "orchestrator.py")
    # gate0
    _run(
        [
            sys.executable,
            orch,
            "gate0_init",
            request_id,
            json.dumps("Make a CLI that counts from 1 to 3 by 1"),
            json.dumps([]),
            json.dumps([]),
            json.dumps([]),
        ],
        env=env,
    )
    for gate_cmd, gate_n in (
        ("gate1_planning", 1),
        ("gate2_delegation", 2),
        ("gate3_execution", 3),
        ("gate4_review", 4),
        ("gate5_finalize", 5),
        ("gate6_complete", 6),
    ):
        if gate_n > through_gate:
            break
        _run([sys.executable, orch, gate_cmd, request_id], env=env, allow_fail=True)


def _assert_no_repair(request_id: str) -> None:
    if (_rd(request_id) / "repair").exists():
        _fail("FAIL m21:unexpected_repair")


def _assert_repair_iter0_exists(request_id: str) -> Path:
    p = _rd(request_id) / "repair" / "iter_0"
    if not p.exists():
        _fail("FAIL m21:trigger_incorrect")
    return p


def _read_repair_status(request_id: str) -> Dict[str, Any]:
    p = _rd(request_id) / "repair" / "status.json"
    if not p.exists():
        _fail("FAIL m21:trigger_incorrect")
    obj = _load_json(p)
    if not isinstance(obj, dict):
        _fail("FAIL m21:trigger_incorrect")
    return obj


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-id", default="20260103T060637Z")
    ap.add_argument("--policy", default="v1")
    args = ap.parse_args()

    snapshot_id = str(args.snapshot_id).strip()
    policy = str(args.policy).strip() or "v1"

    env = os.environ.copy()
    env["NLC_POLICY_VERSION"] = policy
    env["NLC_DB_SNAPSHOT_ID"] = snapshot_id
    env["NLC_SNAPSHOT_ID"] = snapshot_id
    env["NLC_KB_SNAPSHOT_ID"] = snapshot_id

    # 1) Trigger correctness: PASS case must not run repair.
    rid_pass = "M21-PASS"
    _cleanup(rid_pass)
    _run_gate_chain(rid_pass, env, through_gate=3)
    st3 = (_rd(rid_pass) / "gate3.status").read_text(encoding="utf-8", errors="replace").strip()
    if st3 != "PASS":
        _fail("FAIL m21:trigger_incorrect")
    _assert_no_repair(rid_pass)

    # 1b) CLARIFY case must not run repair.
    rid_clar = "M21-CLARIFY"
    _cleanup(rid_clar)
    orch = str(BASE / "orchestrator" / "orchestrator.py")
    _run(
        [
            sys.executable,
            orch,
            "gate0_init",
            rid_clar,
            json.dumps("Make a CLI that does something"),
            json.dumps([]),
            json.dumps([]),
            json.dumps([]),
        ],
        env=env,
    )
    _run([sys.executable, orch, "gate1_planning", rid_clar], env=env, allow_fail=True)
    st1 = (_rd(rid_clar) / "gate1.status").read_text(encoding="utf-8", errors="replace").strip()
    if st1 != "CLARIFY":
        _fail("FAIL m21:trigger_incorrect")
    _assert_no_repair(rid_clar)

    # 2) Accept path: create a real verifier FAIL (missing deliverable), then repair adds it -> PASS_AFTER_REPAIR.
    rid_accept = "M21-ACCEPT"
    _cleanup(rid_accept)
    # Stage a patch that adds RUNBOOK.md (allowed top-level file by contract).
    accept_diff = (
        "--- /dev/null\n"
        "+++ b/RUNBOOK.md\n"
        "@@ -0,0 +1,5 @@\n"
        "+# Runbook\n"
        "+\n"
        "+This runbook is created by deterministic repair to satisfy a required deliverable.\n"
        "+\n"
        "+OK.\n"
    )
    # gate0 first so request dir exists for staging.
    _run(
        [
            sys.executable,
            orch,
            "gate0_init",
            rid_accept,
            json.dumps("Make a CLI that counts from 1 to 3 by 1"),
            json.dumps([]),
            json.dumps([]),
            json.dumps([]),
        ],
        env=env,
    )
    _patch_payload_add_deliverable(rid_accept, "RUNBOOK.md")
    _stage_proposal(rid_accept, accept_diff)
    # Now run gates 1..3; gate3 should FAIL then repair -> PASS
    _run([sys.executable, orch, "gate1_planning", rid_accept], env=env)
    _run([sys.executable, orch, "gate2_delegation", rid_accept], env=env)
    _run([sys.executable, orch, "gate3_execution", rid_accept], env=env, allow_fail=True)

    # Repair must have run; iter_0 must exist.
    _assert_repair_iter0_exists(rid_accept)
    st = _read_repair_status(rid_accept)
    if st.get("final_status") != "PASS_AFTER_REPAIR":
        _fail("FAIL m21:accept_not_pass_after_repair")
    if st.get("stop_reason") != "PASS":
        _fail("FAIL m21:accept_not_pass_after_repair")

    # 3) Reject + rollback path: same real FAIL (missing deliverable), patch applies but doesn't improve => rejected, rollback verified.
    rid_reject = "M21-REJECT"
    _cleanup(rid_reject)
    _run(
        [
            sys.executable,
            orch,
            "gate0_init",
            rid_reject,
            json.dumps("Make a CLI that counts from 1 to 3 by 1"),
            json.dumps([]),
            json.dumps([]),
            json.dumps([]),
        ],
        env=env,
    )
    _patch_payload_add_deliverable(rid_reject, "RUNBOOK.md")
    # Patch applies cleanly but does not add RUNBOOK.md => no improvement => rollback.
    reject_diff = (
        "--- /dev/null\n"
        "+++ b/workspace/project/NOTE.txt\n"
        "@@ -0,0 +1,2 @@\n"
        "+note: this change does not fix the failing deliverable requirement\n"
        "+\n"
    )
    _stage_proposal(rid_reject, reject_diff)
    _run([sys.executable, orch, "gate1_planning", rid_reject], env=env)
    _run([sys.executable, orch, "gate2_delegation", rid_reject], env=env)
    _run([sys.executable, orch, "gate3_execution", rid_reject], env=env, allow_fail=True)

    _assert_repair_iter0_exists(rid_reject)
    st = _read_repair_status(rid_reject)
    if st.get("final_status") != "FAIL_PATCH_REJECTED":
        _fail("FAIL m21:reject_not_patch_rejected")
    if st.get("stop_reason_short") != "no_improve":
        _fail("FAIL m21:reject_not_patch_rejected")

    # Rollback proof: decision.json must have rollback_verified true and hashes must match.
    iter1 = _rd(rid_reject) / "repair" / "iter_1"
    dec = _load_json(iter1 / "decision.json")
    if not (isinstance(dec, dict) and dec.get("rollback_verified") is True):
        _fail("FAIL m21:rollback_not_verified")

    # Rollback proof: compare hashes recorded immediately before apply vs hashes recorded immediately after rollback.
    before = _load_json(iter1 / "workspace_hashes.before.json")
    after_rb_path = iter1 / "workspace_hashes.after_rollback.json"
    if not after_rb_path.exists():
        _fail("FAIL m21:rollback_not_verified")
    after_rb = _load_json(after_rb_path)
    if before != after_rb:
        _fail("FAIL m21:rollback_not_verified")

    sys.stdout.write("✓ Milestone 2.1 repair loop proof: PASS\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


