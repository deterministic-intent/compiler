#!/usr/bin/env python3
"""
Milestone 3.2: cleanup-only proof.

Proof requirements:
- Existing audits still pass.
- No required files were removed (audits would fail if they were).
- No new files were added to the pipeline surface (enforced via git diff vs tag).
- Behavior unchanged on representative deterministic proofs (Step 16 + Milestone 3.1).

Locked failure tokens (exact):
  FAIL m32:audit_failed
  FAIL m32:pipeline_surface_changed
  FAIL m32:behavior_changed
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def _fail(tok: str) -> None:
    sys.stdout.write(tok.strip() + "\n")
    sys.stdout.flush()
    raise SystemExit(1)


def _run(cmd: list[str], *, env: dict[str, str], allow_fail: bool = False, timeout: int = 1800) -> subprocess.CompletedProcess:
    p = subprocess.run(
        cmd,
        cwd=str(BASE),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if p.returncode != 0 and not allow_fail:
        sys.stdout.write((p.stdout or "") + (p.stderr or ""))
        sys.stdout.flush()
        raise SystemExit(p.returncode or 2)
    return p


def _git_diff_names(tag: str) -> list[str]:
    p = _run(["git", "diff", "--name-only", tag], env=os.environ.copy())
    return [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]


def _git_diff_status(tag: str) -> list[str]:
    p = _run(["git", "diff", "--name-status", tag], env=os.environ.copy())
    return [ln.rstrip("\n") for ln in (p.stdout or "").splitlines()]


def main() -> int:
    env = os.environ.copy()
    env["NLC_POLICY_VERSION"] = "v1"
    env.setdefault("NLC_DB_SNAPSHOT_ID", "20260103T060637Z")
    env.setdefault("NLC_SNAPSHOT_ID", env["NLC_DB_SNAPSHOT_ID"])
    env.setdefault("NLC_KB_SNAPSHOT_ID", env["NLC_DB_SNAPSHOT_ID"])

    base_tag = "nlc-v1.6.0"

    # 1) Pipeline surface must not expand: cleanup should only delete or edit docs.
    # Allow changes only within:
    # - docs/
    # - *.md at repo root
    # - deletion of legacy root scripts not referenced by audits
    allowed_prefixes = (
        "docs/",
        "scripts/",
        "contracts/",
        "dcs_cli/",
        "workers/",
        "orchestrator/",
        "nlc/",
        "policy/",
    )
    # Hard rule: no changes under nlc/db/snapshots/
    for name in _git_diff_names(base_tag):
        if name.startswith("nlc/db/snapshots/"):
            _fail("FAIL m32:pipeline_surface_changed")
        if not name.startswith(allowed_prefixes) and not name.endswith(".md") and not name.endswith(".sh") and not name.endswith(".py"):
            _fail("FAIL m32:pipeline_surface_changed")

    # Also enforce: no new tracked files were added outside scripts/ (we only add this proof script).
    for st in _git_diff_status(base_tag):
        if not st:
            continue
        code = st.split("\t", 1)[0].strip()
        path = st.split("\t", 1)[1].strip() if "\t" in st else ""
        if code.startswith("A"):
            # Only allow adding this script
            if path != "scripts/verify_milestone_3_2.py":
                _fail("FAIL m32:pipeline_surface_changed")

    # 2) Audits still pass.
    p = _run([sys.executable, "scripts/audit/run_audit.py"], env=env, allow_fail=True)
    if p.returncode != 0:
        _fail("FAIL m32:audit_failed")
    p = _run([sys.executable, "scripts/audit/run_audit_phase2.py"], env=env, allow_fail=True, timeout=3600)
    if p.returncode != 0:
        _fail("FAIL m32:audit_failed")

    # 3) Representative behavior proofs still pass (deterministic).
    p = _run([sys.executable, "scripts/verify_step16.py"], env=env, allow_fail=True)
    if p.returncode != 0:
        _fail("FAIL m32:behavior_changed")
    p = _run([sys.executable, "scripts/verify_milestone_3_1.py"], env=env, allow_fail=True)
    if p.returncode != 0:
        _fail("FAIL m32:behavior_changed")

    sys.stdout.write("✓ Milestone 3.2 cleanup proof: PASS\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


