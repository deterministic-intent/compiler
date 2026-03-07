#!/usr/bin/env python3
"""
Generate contracts/v1_language_artifact_matrix.json from module discovery.
Deterministic, sorted. No snapshot seed. No hand editing.

Matrix keys = discovery languages (orchestrator/modules + generator branches). No silent omission.
Matrix values = discovery bindings. Empty bindings forbidden (LANG_MATRIX_EMPTY_BINDING).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
from scripts._repo_guard import require_repo_root
require_repo_root()

DISCOVERY_SCRIPT = BASE / "scripts" / "discover_implemented_language_bindings.py"
DISCOVERY_PATH = BASE / "out" / "debug_language_discovery.json"
MATRIX_PATH = BASE / "contracts" / "v1_language_artifact_matrix.json"


def main() -> int:
    # 1) Run discovery (authoritative source: orchestrator/modules)
    subprocess.run(
        [sys.executable, str(DISCOVERY_SCRIPT)],
        cwd=str(BASE),
        check=True,
        capture_output=True,
    )

    discovery = json.loads(DISCOVERY_PATH.read_text(encoding="utf-8"))
    bindings = discovery.get("implemented_language_bindings", {})

    # 2) Matrix keys = discovery keys. Values = bindings. No empty bindings.
    mapping: dict[str, list[str]] = {}
    for lang in sorted(bindings.keys()):
        discovered = bindings.get(lang, [])
        if not discovered:
            sys.stderr.write(f"LANG_MATRIX_EMPTY_BINDING:{lang}\n")
            return 2
        mapping[lang] = sorted(discovered)
    mapping = dict(sorted(mapping.items()))

    # 3) Write contract (no snapshot_id - derived from DB, not from a seed snapshot)
    out = {
        "schema_version": "v1",
        "policy": "v1",
        "description": "Generated from module discovery. Keys=discovery languages, values=implemented artifact classes. No snapshot seed.",
        "mapping": mapping,
    }
    MATRIX_PATH.parent.mkdir(parents=True, exist_ok=True)
    MATRIX_PATH.write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Generated {MATRIX_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
