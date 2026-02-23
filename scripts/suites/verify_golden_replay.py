#!/usr/bin/env python3
"""
Phase 2: Golden suite replay verifier.

Proves replay is byte-identical and deterministic by running run_replay.py for each
case that produced verifier outputs.

Locked failure tokens (exact):
  FAIL suite:replay_failed <case_id>
  FAIL suite:invalid_suite_format
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

BASE = Path(__file__).resolve().parents[2]


def _fail(line: str, code: int = 1) -> None:
    sys.stdout.write(line.rstrip("\n") + "\n")
    sys.stdout.flush()
    raise SystemExit(code)


def _load_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8", errors="replace"))


def _sanitize_request_id(suite_id: str, case_id: str) -> str:
    rid = f"SUITE-{suite_id}-{case_id}"
    rid = re.sub(r"[^A-Za-z0-9_.-]+", "_", rid)
    return rid[:120]


def _gate_for_request_dir(rd: Path) -> Optional[str]:
    """
    Determine the gate name to replay based on gate status files.
    We replay the last gate that actually ran verifier and wrote request_dir/verifier/*.
    """
    # If we got all the way to gate 6 PASS, replay gate6_complete.
    st6 = (rd / "gate6.status").read_text(encoding="utf-8", errors="replace").strip() if (rd / "gate6.status").exists() else ""
    if st6 == "PASS":
        return "gate6_complete"
    # Otherwise, replay the first failing gate among 1..6 (deterministic fail boundary).
    for n, name in (
        (5, "gate5_finalize"),
        (4, "gate4_review"),
        (3, "gate3_execution"),
        (2, "gate2_delegation"),
        (1, "gate1_planning"),
    ):
        p = rd / f"gate{n}.status"
        if not p.exists():
            continue
        st = p.read_text(encoding="utf-8", errors="replace").strip().upper()
        if st and st != "PASS" and st != "NOT_RUN" and st != "SKIPPED_CLARIFY":
            return name
        # Most FAIL cases will have gate3.status == FAIL; if it exists, prefer it.
        if n == 3 and st == "FAIL":
            return name
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default=str(BASE / "suites" / "v1" / "golden_pack.json"))
    ap.add_argument("--replay-id", default="golden")
    args = ap.parse_args()

    suite_path = Path(args.suite).resolve()
    if not suite_path.exists():
        _fail("FAIL suite:invalid_suite_format", 2)

    suite = _load_json(suite_path)
    if not isinstance(suite, dict):
        _fail("FAIL suite:invalid_suite_format", 2)
    suite_id = str(suite.get("suite_id", "")).strip()
    cases = suite.get("cases", [])
    if not suite_id or not isinstance(cases, list):
        _fail("FAIL suite:invalid_suite_format", 2)

    env = os.environ.copy()
    # Replay clamp: no network, no LLM. (Verifier has additional replay checks based on env.)
    env["DCS_REPRO"] = "1"

    for c in cases:
        if not isinstance(c, dict):
            _fail("FAIL suite:invalid_suite_format", 2)
        case_id = str(c.get("case_id", "")).strip()
        expected = str(c.get("expected_final_status", "")).strip().upper()
        if not case_id or not expected:
            _fail("FAIL suite:invalid_suite_format", 2)
        # CLARIFY cases may not have verifier outputs by design.
        if expected == "CLARIFY":
            continue

        request_id = _sanitize_request_id(suite_id, case_id)
        rd = BASE / "state" / "requests" / request_id
        if not rd.exists():
            _fail(f"FAIL suite:replay_failed {case_id}", 1)

        gate = _gate_for_request_dir(rd)
        if not gate:
            _fail(f"FAIL suite:replay_failed {case_id}", 1)

        p = subprocess.run(
            [sys.executable, str(BASE / "scripts" / "run_replay.py"), request_id, gate, "--replay-id", str(args.replay_id)],
            cwd=str(BASE),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if p.returncode != 0:
            # Preserve stable single-line token only.
            _fail(f"FAIL suite:replay_failed {case_id}", 1)

    sys.stdout.write("REPLAY_OK\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


