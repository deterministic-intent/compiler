#!/usr/bin/env python3
"""
Phase 2 audit tier:
- runs full audit (Phase 1 bounded E2E)
- then runs the golden suite runner against suites/v1/golden_pack.json

This script is a gate. It must fail fast and remain deterministic.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
import os


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
    # Phase 2 audit must be unconditional in the standard environment:
    # bootstrap the pinned venv and install pinned scraper deps deterministically.
    venv_dir = BASE / ".venv-m11"
    vpy = venv_dir / "bin" / "python3"
    if not vpy.exists():
        rc = run([sys.executable, "-m", "venv", str(venv_dir)], timeout_s=180, label="phase2 venv bootstrap", cwd=str(BASE))
        if rc != 0:
            return rc
    # Install pinned deps in the venv (idempotent).
    rc = run(
        [
            str(vpy),
            "-m",
            "pip",
            "install",
            "-r",
            str(BASE / "scripts" / "requirements" / "scraper.txt"),
            "--disable-pip-version-check",
            "--no-input",
        ],
        timeout_s=300,
        label="phase2 install scraper deps",
        cwd=str(BASE),
    )
    if rc != 0:
        return rc
    rc = run([str(vpy), "scripts/check_scraper_deps.py"], timeout_s=60, label="phase2 deps gate", cwd=str(BASE))
    if rc != 0:
        return rc

    # Phase 1 full audit must be green first (run using the pinned venv python).
    rc = run([str(vpy), "scripts/audit/run_audit_full.py"], timeout_s=600, label="phase1 audit_full", cwd=str(BASE))
    if rc != 0:
        return rc

    # Phase 2.0 preflight: golden suite coverage must be sufficient before hashing/running cases.
    rc = run(
        [
            str(vpy),
            "scripts/verify_suite_coverage.py",
            "--snapshot-id",
            os.environ.get("DCS_PROOF_SNAPSHOT_ID") or os.environ.get("AUDIT_CLOSURE_SNAPSHOT") or "",
            "--suite",
            str(BASE / "suites" / "v1" / "golden_pack.json"),
        ],
        timeout_s=60,
        label="phase2 suite coverage",
        cwd=str(BASE),
    )
    if rc != 0:
        return rc

    rc = run(
        [str(vpy), "scripts/suites/run_golden_suite.py", "--suite", str(BASE / "suites" / "v1" / "golden_pack.json")],
        timeout_s=300,
        label="phase2 golden suite",
        cwd=str(BASE),
    )
    if rc != 0:
        return rc

    # Phase 2.0 proof: replay is byte-identical for suite cases that produce verifier outputs.
    rc = run(
        [str(vpy), "scripts/suites/verify_golden_replay.py", "--suite", str(BASE / "suites" / "v1" / "golden_pack.json")],
        timeout_s=300,
        label="phase2 golden replay",
        cwd=str(BASE),
    )
    if rc != 0:
        return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


