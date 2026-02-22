#!/usr/bin/env python3
"""Canonical path constants used across the pipeline."""

from pathlib import Path

# Repo root (nlc/ lives under it)
BASE = Path(__file__).resolve().parents[1]

# Root for all request state
REQUESTS_ROOT = BASE / "state" / "requests"

# Deliverables are stored relative to the request directory
def deliverables_root(request_dir: Path) -> Path:
    return Path(request_dir)

# Verifier outputs root relative to a request
def verifier_root(request_dir: Path) -> Path:
    return Path(request_dir) / "verifier"

# Repair root relative to a request
def repair_root(request_dir: Path) -> Path:
    return Path(request_dir) / "repair"

