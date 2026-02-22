#!/usr/bin/env python3
"""
Step 20: Full E2E Audit Gate (requires scraper deps).

Runs:
- Base audit (always runnable)
- Deps check (must be installed)
- Step 20 full E2E harness (scraper -> snapshot -> pipeline -> replay + replay negative control)
"""

from __future__ import annotations

import sys
import importlib.util
from pathlib import Path


BASE = Path(__file__).resolve().parents[2]


def _load_subproc_run():
    sp = BASE / "scripts" / "audit" / "subproc.py"
    spec = importlib.util.spec_from_file_location("llmhub_audit_subproc", sp)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load subproc module: {sp}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    fn = getattr(mod, "run", None)
    if not callable(fn):
        raise RuntimeError("subproc.run not found/callable")
    return fn


run = _load_subproc_run()


def main() -> int:
    # --- deps gate ---
    rc = run([sys.executable, "scripts/check_scraper_deps.py"], timeout_s=15, label="deps gate", cwd=str(BASE))
    if rc != 0:
        return rc

    # --- base audit ---
    rc = run([sys.executable, "scripts/audit/run_audit.py"], timeout_s=120, label="base audit", cwd=str(BASE))
    if rc != 0:
        return rc

    # --- step19 e2e ---
    rc = run([sys.executable, "scripts/verify_step19.py"], timeout_s=120, label="step19 e2e", cwd=str(BASE))
    if rc != 0:
        return rc

    # --- step20 bounded e2e ---
    rc = run([sys.executable, "scripts/verify_step20.py"], timeout_s=180, label="step20 bounded e2e", cwd=str(BASE))
    if rc != 0:
        return rc

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


