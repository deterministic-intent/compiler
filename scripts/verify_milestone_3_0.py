#!/usr/bin/env python3
"""
Milestone 3.0: Compile/Test Validation proof.

Proof:
- For a PASS request: validation artifacts exist and are byte-identical across two verifier runs.
- For a FAIL request (syntax error injected): validation emits compile_error and artifacts are deterministic.

Locked failure tokens (exact):
  FAIL m30:validation_missing
  FAIL m30:validation_not_deterministic
  FAIL m30:expected_compile_error_missing
"""

from __future__ import annotations

import hashlib
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


def _fail(tok: str) -> None:
    sys.stdout.write(tok.strip() + "\n")
    sys.stdout.flush()
    raise SystemExit(1)


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _run(cmd: List[str], env: Dict[str, str], allow_fail: bool = False) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, cwd=str(BASE), env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180)
    if p.returncode != 0 and not allow_fail:
        sys.stdout.write((p.stdout or "") + (p.stderr or ""))
        sys.stdout.flush()
        raise SystemExit(p.returncode or 2)
    return p


def _rd(rid: str) -> Path:
    return BASE / "state" / "requests" / rid


def _cleanup(rid: str) -> None:
    rd = _rd(rid)
    if rd.exists():
        shutil.rmtree(rd, ignore_errors=True)


def _gate0_1_2(rid: str, env: Dict[str, str]) -> None:
    orch = str(BASE / "orchestrator" / "orchestrator.py")
    _run([sys.executable, orch, "gate0_init", rid, json.dumps("Make a CLI that counts from 1 to 3 by 1"), json.dumps([]), json.dumps([]), json.dumps([])], env=env)
    _run([sys.executable, orch, "gate1_planning", rid], env=env)
    _run([sys.executable, orch, "gate2_delegation", rid], env=env)


def _run_verifier(rid: str, env: Dict[str, str]) -> None:
    rd = _rd(rid)
    _run([sys.executable, str(BASE / "workers" / "run_verifier.py"), rid, str(rd), "gate3_execution"], env=env, allow_fail=True)


def _validation_hashes(rid: str) -> Dict[str, str]:
    vdir = _rd(rid) / "validation"
    if not vdir.exists():
        _fail("FAIL m30:validation_missing")
    needed = ["result.json", "bundle.json", "py_compile.stdout.txt", "py_compile.stderr.txt", "unittest.stdout.txt", "unittest.stderr.txt"]
    out: Dict[str, str] = {}
    for n in needed:
        p = vdir / n
        if not p.exists():
            _fail("FAIL m30:validation_missing")
        out[n] = _sha256_file(p)
    return out


def main() -> int:
    env = os.environ.copy()
    env["NLC_POLICY_VERSION"] = "v1"
    snapshot_id = (os.environ.get("DCS_PROOF_SNAPSHOT_ID") or os.environ.get("AUDIT_CLOSURE_SNAPSHOT") or os.environ.get("NLC_DB_SNAPSHOT_ID") or "").strip()
    if not snapshot_id:
        _fail("MISSING_SNAPSHOT_ID: set DCS_PROOF_SNAPSHOT_ID or NLC_DB_SNAPSHOT_ID")
    env["NLC_DB_SNAPSHOT_ID"] = snapshot_id
    env["NLC_SNAPSHOT_ID"] = snapshot_id
    env["NLC_KB_SNAPSHOT_ID"] = snapshot_id

    # PASS case: determinism across two verifier runs
    rid_ok = "M30-OK"
    _cleanup(rid_ok)
    _gate0_1_2(rid_ok, env)
    orch = str(BASE / "orchestrator" / "orchestrator.py")
    _run([sys.executable, orch, "gate3_execution", rid_ok], env=env, allow_fail=True)
    _run_verifier(rid_ok, env)
    h1 = _validation_hashes(rid_ok)
    _run_verifier(rid_ok, env)
    h2 = _validation_hashes(rid_ok)
    if h1 != h2:
        _fail("FAIL m30:validation_not_deterministic")

    # FAIL case: inject syntax error and ensure compile_error is present and deterministic
    rid_bad = "M30-BAD"
    _cleanup(rid_bad)
    _gate0_1_2(rid_bad, env)
    _run([sys.executable, orch, "gate3_execution", rid_bad], env=env, allow_fail=True)
    main_py = _rd(rid_bad) / "workspace" / "project" / "main.py"
    if not main_py.exists():
        _fail("FAIL m30:validation_missing")
    main_py.write_text("def oops(:\n  pass\n", encoding="utf-8")
    _run_verifier(rid_bad, env)
    fpath = _rd(rid_bad) / "verifier" / "failures.json"
    obj = json.loads(fpath.read_text(encoding="utf-8", errors="replace"))
    fails = obj.get("failures", [])
    if not any(isinstance(x, dict) and x.get("kind") == "compile_error" and "validation:py_compile" in str(x.get("repro","")) for x in fails):
        _fail("FAIL m30:expected_compile_error_missing")
    hb1 = _validation_hashes(rid_bad)
    _run_verifier(rid_bad, env)
    hb2 = _validation_hashes(rid_bad)
    if hb1 != hb2:
        _fail("FAIL m30:validation_not_deterministic")

    sys.stdout.write("✓ Milestone 3.0 validation proof: PASS\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


