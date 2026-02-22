"""Manifest hashes for snapshot-bound reproducibility."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Optional

_BASE = Path(__file__).resolve().parents[1]


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def get_manifest_hashes(snapshot_id: str, base: Optional[Path] = None) -> Dict[str, Any]:
    """
    Return manifest hashes for a snapshot. Builds manifests if missing.
    Returns dict with manifest_bundle_hash and manifest_hashes (filename -> sha256).
    """
    root = base or _BASE
    snapshot_dir = root / "nlc" / "db" / "snapshots" / snapshot_id
    if not snapshot_dir.exists():
        return {}

    try:
        from nlc.db.manifest_builder import build_all_manifests, compute_manifest_bundle_hash
    except ImportError:
        return {}

    manifest_dir = snapshot_dir / "manifest"
    if not manifest_dir.exists():
        try:
            manifest_hashes = build_all_manifests(root, snapshot_id)
        except Exception:
            return {}
    else:
        manifest_hashes = {}
        for f in sorted(manifest_dir.iterdir()):
            if f.is_file() and f.suffix == ".json":
                try:
                    manifest_hashes[f.name] = _sha256_file(f)
                except Exception:
                    pass
        if not manifest_hashes:
            try:
                manifest_hashes = build_all_manifests(root, snapshot_id)
            except Exception:
                return {}

    bundle_hash = compute_manifest_bundle_hash(manifest_hashes)
    return {
        "manifest_bundle_hash": bundle_hash,
        "manifest_hashes": manifest_hashes,
    }
