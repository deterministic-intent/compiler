#!/usr/bin/env python3
"""
Regression guard: intent builders must compile.
Ensures nlc builder modules (manifest_builder, answer_builder, index_builder)
and related intent/executable code compile cleanly.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]

# Builder modules and intent-related code
BUILDER_TARGETS = [
    "nlc/db",
    "nlc/answer",
    "nlc/index",
    "nlc/prompt_compiler.py",
    "nlc/intent_to_tasks.py",
]


def main() -> int:
    targets = [str(BASE / t) for t in BUILDER_TARGETS]
    existing = [p for p in targets if Path(p).exists()]
    if not existing:
        return 0  # no targets to check
    rc = subprocess.run(
        [sys.executable, "-m", "compileall", "-q"] + existing,
        cwd=str(BASE),
        capture_output=True,
        timeout=60,
    )
    if rc.returncode != 0:
        sys.stderr.write((rc.stderr or b"").decode(errors="replace"))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
