#!/usr/bin/env python3
"""
Shared repo guards for sealing entrypoints. Hard-fail if wrong root or dirty tree.
All governance, snapshot, suite, proof work must run from /opt/dcs-public only.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REQUIRED_ROOT = "/opt/dcs-public"


def require_repo_root(expected: str = REQUIRED_ROOT) -> None:
    """Fail with WRONG_REPO_ROOT if not under expected repo root."""
    # Resolve from this script's dir (scripts/) so it works regardless of cwd
    _script_dir = Path(__file__).resolve().parent
    _repo_candidate = _script_dir.parent
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(_repo_candidate),
        )
        actual = result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        actual = ""
    if not actual or Path(actual).resolve() != Path(expected).resolve():
        sys.stderr.write(f"WRONG_REPO_ROOT: must run from {expected}, got {actual or 'unknown'}\n")
        sys.exit(2)


def require_clean_worktree() -> None:
    """Fail with DIRTY_WORKTREE_FORBIDDEN if working tree has uncommitted changes."""
    _script_dir = Path(__file__).resolve().parent
    _repo_candidate = _script_dir.parent
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(_repo_candidate),
        )
        porcelain = result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        porcelain = "?? unknown"
    if porcelain:
        sys.stderr.write("DIRTY_WORKTREE_FORBIDDEN: uncommitted changes or untracked files\n")
        sys.stderr.write("Run 'git status' for details.\n")
        sys.exit(2)
