#!/usr/bin/env python3
"""
Milestone 3.1: Deterministic debug report UX proof.

Proof:
- Deterministic debug output for:
  - a verifier FAIL (M30-BAD from milestone 3.0 proof)
  - a repair rejection (M21-REJECT from milestone 2.1 proof)
- Byte-identical output across two runs for each.
- Output sourced only from existing artifacts (dcs debug is read-only).

Locked failure tokens (exact):
  FAIL m31:missing_fixture_requests
  FAIL m31:debug_not_deterministic
  FAIL m31:debug_missing_expected_content
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def _fail(tok: str) -> None:
    sys.stdout.write(tok.strip() + "\n")
    sys.stdout.flush()
    raise SystemExit(1)


def _run(cmd: list[str], *, env: dict[str, str], allow_fail: bool = False) -> subprocess.CompletedProcess:
    p = subprocess.run(
        cmd,
        cwd=str(BASE),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=False,
        timeout=240,
    )
    if p.returncode != 0 and not allow_fail:
        sys.stdout.write(((p.stdout or b"") + (p.stderr or b"")).decode("utf-8", errors="replace"))
        sys.stdout.flush()
        raise SystemExit(p.returncode or 2)
    return p


def _rd(rid: str) -> Path:
    return BASE / "state" / "requests" / rid


def _debug(rid: str, env: dict[str, str]) -> bytes:
    cmd = [str(BASE / "scripts" / "bin" / "dcs"), "--no-banner", "--no-color", "debug", "--request-id", rid]
    p = _run(cmd, env=env)
    return (p.stdout or b"") + (p.stderr or b"")


def main() -> int:
    env = os.environ.copy()
    env["NLC_POLICY_VERSION"] = "v1"
    env["NLC_DB_SNAPSHOT_ID"] = "20260103T060637Z"
    env["NLC_SNAPSHOT_ID"] = "20260103T060637Z"
    env["NLC_KB_SNAPSHOT_ID"] = "20260103T060637Z"

    # Ensure fixture requests exist by running the milestone proofs (they are deterministic and pinned).
    _run([sys.executable, "scripts/verify_milestone_3_0.py"], env=env)
    _run([sys.executable, "scripts/verify_milestone_2_1.py"], env=env)

    rid_fail = "M30-BAD"
    rid_reject = "M21-REJECT"
    if not (_rd(rid_fail).exists() and _rd(rid_reject).exists()):
        _fail("FAIL m31:missing_fixture_requests")

    # Verifier FAIL debug: deterministic + contains compile_error evidence
    out1 = _debug(rid_fail, env)
    out2 = _debug(rid_fail, env)
    if out1 != out2:
        _fail("FAIL m31:debug_not_deterministic")
    t = out1.decode("utf-8", errors="replace")
    if "DCS DEBUG REPORT" not in t or "verifier_failure_kinds" not in t or "compile_error" not in t:
        _fail("FAIL m31:debug_missing_expected_content")

    # Repair reject debug: deterministic + contains FAIL_PATCH_REJECTED and stop reason
    out1 = _debug(rid_reject, env)
    out2 = _debug(rid_reject, env)
    if out1 != out2:
        _fail("FAIL m31:debug_not_deterministic")
    t = out1.decode("utf-8", errors="replace")
    if "repair_final_status:" not in t or "FAIL_PATCH_REJECTED" not in t or "repair_stop_reason_short:" not in t:
        _fail("FAIL m31:debug_missing_expected_content")

    sys.stdout.write("✓ Milestone 3.1 debug UX proof: PASS\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


