#!/usr/bin/env python3
"""Test: python_cli deterministic factory when module_refs absent."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from workers.run_generator import generate_python_cli, load_module_refs


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        rd = Path(td)
        payload = {"artifact_class": "python_cli"}
        (rd / "payload.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        workspace_project = rd / "workspace" / "project"
        workspace_project.mkdir(parents=True, exist_ok=True)

        assert load_module_refs(rd) == [], "module_refs must be absent"

        files_written = generate_python_cli(rd, [], workspace_project)

        main_py = workspace_project / "src" / "main.py"
        lib_py = workspace_project / "src" / "lib.py"
        assert main_py.exists(), "src/main.py must exist"
        assert lib_py.exists(), "src/lib.py must exist"

        main_content = main_py.read_text(encoding="utf-8")
        lib_content = lib_py.read_text(encoding="utf-8")

        expected_main = "from lib import count\n\nif __name__ == \"__main__\":\n    for n in count():\n        print(n)\n"
        expected_lib = "def count():\n    return [1, 2, 3, 4, 5]\n"
        assert main_content == expected_main, f"main.py content mismatch:\n{repr(main_content)}"
        assert lib_content == expected_lib, f"lib.py content mismatch:\n{repr(lib_content)}"

        assert "src/main.py" in files_written
        assert "src/lib.py" in files_written

    print("test_python_cli_factory: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
