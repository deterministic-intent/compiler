#!/usr/bin/env python3
"""
Documentation Alignment Proof (nlc-v1.8.1+).

Verifies that documentation accurately reflects the root policy structure:
- No references to legacy root-level paths
- All current paths are documented
- CLI entrypoint is correctly referenced

Locked failure tokens (exact):
  FAIL docs:legacy_path_found
  FAIL docs:missing_current_path
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]

# Forbidden legacy paths (must not appear in docs)
# These patterns match paths that are NOT under the correct directory
FORBIDDEN_PATTERNS = [
    (r'\./dcs\b', 'root-level ./dcs'),
    (r'`\./dcs\b', 'root-level `./dcs'),
    (r'(?<!scripts/bin/)`run_replay\.py\b', 'root-level run_replay.py (not scripts/run_replay.py)'),
    (r'(?<!workers/)`contract_checker\.py\b', 'root-level contract_checker.py (not workers/contract_checker.py)'),
    (r'(?<!nlc/)`paths\.py\b', 'root-level paths.py (not nlc/paths.py)'),
    (r'(?<!nlc/)`external_snapshot\.py\b', 'root-level external_snapshot.py (not nlc/external_snapshot.py)'),
    (r'(?<!nlc/)`snapshot_resolver\.py\b', 'root-level snapshot_resolver.py (not nlc/snapshot_resolver.py)'),
]

# Required current paths (must appear in docs)
REQUIRED_PATTERNS = [
    (r'scripts/bin/dcs\b', 'scripts/bin/dcs'),
    (r'scripts/run_replay\.py\b', 'scripts/run_replay.py'),
    (r'workers/contract_checker\.py\b', 'workers/contract_checker.py'),
    (r'nlc/paths\.py\b', 'nlc/paths.py'),
    (r'nlc/external_snapshot\.py\b', 'nlc/external_snapshot.py'),
    (r'nlc/snapshot_resolver\.py\b', 'nlc/snapshot_resolver.py'),
]

# Files to check (docs and README)
DOC_FILES = [
    BASE / "README.md",
    BASE / "docs" / "project_map.md",
    BASE / "docs" / "paths.md",
]


def _fail(tok: str) -> None:
    sys.stdout.write(tok.strip() + "\n")
    sys.stdout.flush()
    raise SystemExit(1)


def _check_forbidden_patterns() -> None:
    """Check for forbidden legacy paths in documentation."""
    violations = []
    for doc_file in DOC_FILES:
        if not doc_file.exists():
            continue
        content = doc_file.read_text(encoding="utf-8", errors="replace")
        for pattern, desc in FORBIDDEN_PATTERNS:
            matches = re.finditer(pattern, content, re.MULTILINE)
            for match in matches:
                line_num = content[:match.start()].count('\n') + 1
                violations.append(f"{doc_file.relative_to(BASE)}:{line_num}: {desc}")

    if violations:
        for v in violations:
            sys.stdout.write(f"FORBIDDEN: {v}\n")
        _fail("FAIL docs:legacy_path_found")


def _check_required_patterns() -> None:
    """Check that required current paths appear in documentation."""
    missing = []
    for doc_file in DOC_FILES:
        if not doc_file.exists():
            continue
        content = doc_file.read_text(encoding="utf-8", errors="replace")
        for pattern, desc in REQUIRED_PATTERNS:
            if not re.search(pattern, content):
                missing.append(f"{doc_file.relative_to(BASE)}: missing {desc}")

    if missing:
        for m in missing:
            sys.stdout.write(f"MISSING: {m}\n")
        _fail("FAIL docs:missing_current_path")


def main() -> int:
    _check_forbidden_patterns()
    _check_required_patterns()

    sys.stdout.write("✓ Documentation alignment proof: PASS\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

