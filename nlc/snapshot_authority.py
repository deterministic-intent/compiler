"""
Snapshot authority: hash-protected inventory.
Exposes get_v1_supported_artifact_classes_from_snapshot() — all code paths must use this. No fallback lists.
"""
from __future__ import annotations

import json
from pathlib import Path

# Repo root (nlc/ is one level down)
BASE = Path(__file__).resolve().parents[1]
SNAP_ROOT = BASE / "nlc" / "db" / "snapshots"


def get_v1_languages_from_snapshot(snapshot_id: str) -> list[str]:
    """
    Load languages from snapshot capabilities.json. No fallback.
    """
    caps_path = SNAP_ROOT / snapshot_id / "capabilities.json"
    if not caps_path.exists():
        raise FileNotFoundError(
            f"snapshot authority missing: {caps_path}"
        )
    caps = json.loads(caps_path.read_text(encoding="utf-8", errors="replace"))
    langs = caps.get("languages")
    if isinstance(langs, list):
        return list(langs)
    matrix = caps.get("language_artifact_matrix", {})
    if isinstance(matrix, dict):
        return sorted(matrix.keys())
    return []


def get_v1_supported_artifact_classes_from_snapshot(snapshot_id: str) -> list[str]:
    """
    Load supported_artifact_classes from snapshot capabilities.json. No fallback.
    """
    caps_path = SNAP_ROOT / snapshot_id / "capabilities.json"
    if not caps_path.exists():
        raise FileNotFoundError(
            f"snapshot authority missing: {caps_path}"
        )
    caps = json.loads(caps_path.read_text(encoding="utf-8", errors="replace"))
    acs = caps.get("supported_artifact_classes")
    if not isinstance(acs, list):
        return []
    return list(acs)
