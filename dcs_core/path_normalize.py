"""Normalize absolute paths in proof metadata for deterministic hashing."""
from __future__ import annotations

import json
import re
from typing import Any


def _normalize_path_string(s: str) -> str:
    """Replace machine-specific paths with stable logical placeholders."""
    if not isinstance(s, str) or not s:
        return s
    s = re.sub(r"/tmp/stab_run[0-9A-Za-z_-]+", "TMP_STAB_ROOT", s)
    s = re.sub(r"/workspace/out/proof", "<PROOF_ROOT>", s)
    s = re.sub(r"/opt/dcs-public/out/proof", "<PROOF_ROOT>", s)
    s = re.sub(r"/__w/[^/]+/[^/]+/out/proof", "<PROOF_ROOT>", s)
    # Only replace root paths (at start); avoid replacing "workspace" as path component
    s = re.sub(r"^/workspace(?=/|$)", "<REPO_ROOT>", s)
    s = re.sub(r"^/opt/dcs-public(?=/|$)", "<REPO_ROOT>", s)
    s = re.sub(r"^/__w/[^/]+/[^/]+(?=/|$)", "<REPO_ROOT>", s)
    return s


def normalize_proof_text(text: str) -> str:
    """Normalize path strings in plain text."""
    return _normalize_path_string(text)


def normalize_proof_obj(obj: Any) -> Any:
    """Recursively normalize path strings in JSON-serializable objects."""
    if isinstance(obj, str):
        return _normalize_path_string(obj)
    if isinstance(obj, dict):
        return {k: normalize_proof_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalize_proof_obj(v) for v in obj]
    return obj
