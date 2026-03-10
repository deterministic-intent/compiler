"""Normalize absolute paths in proof metadata for deterministic hashing."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_BASE = Path(__file__).resolve().parents[1]
_POLICY_PATH = _BASE / "policy" / "repro_path_normalize.json"


def _load_rules() -> list[tuple[str, str]]:
    """Load normalization rules from policy file; fallback to built-in if missing."""
    if _POLICY_PATH.exists():
        try:
            data = json.loads(_POLICY_PATH.read_text(encoding="utf-8"))
            rules = data.get("rules", [])
            return [(r["pattern"], r["replacement"]) for r in rules if "pattern" in r and "replacement" in r]
        except Exception:
            pass
    # Built-in fallback (frozen copy of policy)
    return [
        (r"/tmp/stab_run[0-9A-Za-z_-]+", "TMP_STAB_ROOT"),
        (r"/workspace/out/proof", "<PROOF_ROOT>"),
        (r"/opt/dcs-public/out/proof", "<PROOF_ROOT>"),
        (r"/__w/[^/]+/[^/]+/out/proof", "<PROOF_ROOT>"),
        (r"^/workspace(?=/|$)", "<REPO_ROOT>"),
        (r"^/opt/dcs-public(?=/|$)", "<REPO_ROOT>"),
        (r"^/__w/[^/]+/[^/]+(?=/|$)", "<REPO_ROOT>"),
    ]


def _normalize_path_string(s: str) -> str:
    """Replace machine-specific paths with stable logical placeholders."""
    if not isinstance(s, str) or not s:
        return s
    for pattern, replacement in _load_rules():
        s = re.sub(pattern, replacement, s)
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
