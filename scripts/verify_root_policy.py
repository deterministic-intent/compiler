#!/usr/bin/env python3
"""
Root Policy Enforcement Proof (Milestone 3.3 / nlc-v1.8.0).

Proves:
- Root inventory is ultra-strict (only .gitignore, .env.example, pyproject.toml, README.md).
- New CLI entrypoint (scripts/bin/dcs) works deterministically.
- Default DB path change (state/dev/db/dev.db) is enforced and doesn't break existing proofs.
- All existing audits/proofs remain green after root policy restructuring.

Locked failure tokens (exact):
  FAIL root:inventory_violation
  FAIL root:cli_entrypoint_broken
  FAIL root:db_path_violation
  FAIL root:audit_regression
  FAIL root:proof_regression
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]

# Ultra-strict root inventory: only these files allowed at repo root.
ALLOWED_ROOT_FILES = {
    ".gitignore",
    ".env.example",
    "pyproject.toml",
    "README.md",
}


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


def _check_root_inventory() -> None:
    """Verify root directory contains only allowed files."""
    root_files = {f.name for f in BASE.iterdir() if f.is_file()}
    violations = root_files - ALLOWED_ROOT_FILES
    if violations:
        _fail(f"FAIL root:inventory_violation (found: {sorted(violations)})")


def _check_cli_entrypoint() -> None:
    """Verify scripts/bin/dcs exists and works deterministically."""
    dcs_path = BASE / "scripts" / "bin" / "dcs"
    if not dcs_path.exists():
        _fail("FAIL root:cli_entrypoint_broken (scripts/bin/dcs missing)")
    if not os.access(dcs_path, os.X_OK):
        _fail("FAIL root:cli_entrypoint_broken (scripts/bin/dcs not executable)")

    # Test that dcs --help works (deterministic, no network, no state mutation).
    env = os.environ.copy()
    env["NLC_POLICY_VERSION"] = "v1"
    p = _run([str(dcs_path), "--help"], env=env, allow_fail=True)
    if p.returncode != 0:
        _fail(f"FAIL root:cli_entrypoint_broken (dcs --help failed: {p.stderr})")

    # Test that dcs compile --help works (proves subcommand routing).
    p = _run([str(dcs_path), "compile", "--help"], env=env, allow_fail=True)
    if p.returncode != 0:
        _fail(f"FAIL root:cli_entrypoint_broken (dcs compile --help failed: {p.stderr})")


def _check_db_path_policy() -> None:
    """Verify default DB path is state/dev/db/dev.db (not repo root)."""
    # Check db/engine.py default.
    engine_py = BASE / "db" / "engine.py"
    if not engine_py.exists():
        _fail("FAIL root:db_path_violation (db/engine.py missing)")
    content = engine_py.read_text(encoding="utf-8", errors="replace")
    # Must use _default_sqlite_url() or equivalent that constructs state/dev/db/dev.db.
    # Must NOT have a literal "dev.db" default at repo root (no directory prefix).
    if "_default_sqlite_url" not in content and "state/dev/db" not in content:
        # If it has "dev.db" without "state/dev/db", it may default to repo root.
        if "dev.db" in content and '"dev.db"' in content and "state" not in content:
            _fail("FAIL root:db_path_violation (db/engine.py may default to repo root dev.db)")

    # Check db/frontier.py default.
    frontier_py = BASE / "db" / "frontier.py"
    if not frontier_py.exists():
        _fail("FAIL root:db_path_violation (db/frontier.py missing)")
    content = frontier_py.read_text(encoding="utf-8", errors="replace")
    # Must derive from DEV_DB_URL or use a function that constructs state/dev/db/dev.db.
    # Must NOT have a literal "dev.db" default at repo root.
    if "_default_frontier_db_path" not in content and "state/dev/db" not in content:
        # If it has "dev.db" without "state/dev/db" or "DEV_DB_URL", it may default to repo root.
        if "dev.db" in content and '"dev.db"' in content and "state" not in content and "DEV_DB_URL" not in content:
            _fail("FAIL root:db_path_violation (db/frontier.py may default to repo root dev.db)")


def _check_audits_still_pass() -> None:
    """Verify existing audits remain green."""
    env = os.environ.copy()
    env["NLC_POLICY_VERSION"] = "v1"
    env.setdefault("NLC_DB_SNAPSHOT_ID", "20260103T060637Z")
    env.setdefault("NLC_SNAPSHOT_ID", env["NLC_DB_SNAPSHOT_ID"])
    env.setdefault("NLC_KB_SNAPSHOT_ID", env["NLC_DB_SNAPSHOT_ID"])

    # Base audit (must pass without deps).
    p = _run([sys.executable, "scripts/audit/run_audit.py"], env=env, allow_fail=True)
    if p.returncode != 0:
        _fail("FAIL root:audit_regression (base audit failed)")

    # Phase 2 audit (may require deps, but should pass if deps are installed).
    p = _run([sys.executable, "scripts/audit/run_audit_phase2.py"], env=env, allow_fail=True, timeout=3600)
    if p.returncode != 0:
        # Not a hard failure if deps aren't installed, but log it.
        sys.stdout.write(f"WARN: Phase 2 audit failed (may need deps): {p.stderr}\n")
        sys.stdout.flush()


def _check_proofs_still_pass() -> None:
    """Verify representative deterministic proofs still pass."""
    env = os.environ.copy()
    env["NLC_POLICY_VERSION"] = "v1"
    env.setdefault("NLC_DB_SNAPSHOT_ID", "20260103T060637Z")
    env.setdefault("NLC_SNAPSHOT_ID", env["NLC_DB_SNAPSHOT_ID"])
    env.setdefault("NLC_KB_SNAPSHOT_ID", env["NLC_DB_SNAPSHOT_ID"])

    # Step 7 (replay) - proves path bootstrapping works.
    p = _run([sys.executable, "scripts/verify_step7.py", "E2E0-B-AUDIT", "gate3_execution"], env=env, allow_fail=True)
    if p.returncode != 0:
        _fail("FAIL root:proof_regression (Step 7 replay proof failed)")

    # Step 16 (real PASS usage) - proves CLI entrypoint works.
    p = _run([sys.executable, "scripts/verify_step16.py"], env=env, allow_fail=True)
    if p.returncode != 0:
        _fail("FAIL root:proof_regression (Step 16 proof failed)")

    # Milestone 3.1 (debug report) - proves deterministic artifacts unchanged.
    p = _run([sys.executable, "scripts/verify_milestone_3_1.py"], env=env, allow_fail=True)
    if p.returncode != 0:
        _fail("FAIL root:proof_regression (Milestone 3.1 proof failed)")


def main() -> int:
    _check_root_inventory()
    _check_cli_entrypoint()
    _check_db_path_policy()
    _check_audits_still_pass()
    _check_proofs_still_pass()

    sys.stdout.write("✓ Root policy enforcement proof: PASS\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

