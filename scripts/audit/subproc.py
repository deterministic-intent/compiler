#!/usr/bin/env python3
"""
Step 20: subprocess wrapper with deterministic timeouts and stable phase headers.

This is harness-only. Do not import deterministic-core modules from here.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Optional, Dict, List


def run(
    cmd: List[str],
    *,
    timeout_s: int,
    label: str,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
) -> int:
    # Stable phase header (no timestamps).
    sys.stdout.write(f"--- {label} ---\n")
    sys.stdout.flush()
    try:
        p = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=int(timeout_s),
        )
    except subprocess.TimeoutExpired:
        sys.stdout.write(f"FAIL step20:timeout {label}\n")
        sys.stdout.flush()
        return 1

    # Stream captured output deterministically (stdout then stderr).
    if p.stdout:
        sys.stdout.write(p.stdout)
        if not p.stdout.endswith("\n"):
            sys.stdout.write("\n")
    if p.stderr:
        sys.stdout.write(p.stderr)
        if not p.stderr.endswith("\n"):
            sys.stdout.write("\n")
    sys.stdout.flush()
    return int(p.returncode)


if __name__ == "__main__":
    # Not intended as a standalone CLI.
    raise SystemExit(2)


