#!/usr/bin/env python3
"""
Step 9: External data snapshotting (deterministic inputs).

Immutable raw-input snapshots:
  snapshots/external/<snapshot_id>/
    sources/
    sources.manifest.json
    snapshot.meta.json

Notes:
- Raw bytes only (no parsing/normalization).
- Deterministic filenames and manifest ordering.
- Snapshot meta fields are derived deterministically from the manifest (no ambient time).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


# Repo root (nlc/ lives under it)
BASE = Path(__file__).resolve().parents[1]


def _resolve_external_root() -> Path:
    """Precedence: DCS_EXTERNAL_SNAPSHOT_ROOT > DCS_PROOF_STATE_ROOT/snapshots/external > legacy."""
    root = os.environ.get("DCS_EXTERNAL_SNAPSHOT_ROOT", "").strip()
    if root:
        p = Path(root).resolve()
        if str(BASE).startswith("/workspace") and str(p).startswith("/opt/dcs-public"):
            raise SystemExit("CONTAINER_HOST_PATH_FORBIDDEN")
        return p
    proof_root = os.environ.get("DCS_PROOF_STATE_ROOT", "").strip()
    if proof_root:
        p = Path(proof_root).resolve() / "snapshots" / "external"
        if str(BASE).startswith("/workspace") and str(p).startswith("/opt/dcs-public"):
            raise SystemExit("CONTAINER_HOST_PATH_FORBIDDEN")
        return p
    return BASE / "snapshots" / "external"


EXTERNAL_ROOT = _resolve_external_root()


@dataclass(frozen=True)
class ExternalSnapshotWrite:
    snapshot_dir: Path
    source_id: str
    filename: str
    sha256: str
    byte_length: int


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _write_json(path: Path, obj: Any) -> None:
    _atomic_write_text(path, json.dumps(obj, indent=2, sort_keys=True) + "\n")


def _safe_snapshot_id(snapshot_id: str) -> str:
    t = (snapshot_id or "").strip()
    if not t:
        raise ValueError("external snapshot_id is empty")
    if any(x in t for x in ("..", "/", "\\", "\x00")):
        raise ValueError("external snapshot_id contains forbidden characters")
    return t


def deterministic_source_filename(source_id: str) -> str:
    """
    Deterministic filename for a source_id (URL, etc).
    """
    sid = (source_id or "").strip()
    if not sid:
        raise ValueError("source_id is empty")
    return sha256_bytes(sid.encode("utf-8"))[:16] + ".bin"


def _load_manifest(snapshot_dir: Path) -> Dict[str, Any]:
    mp = snapshot_dir / "sources.manifest.json"
    if not mp.exists():
        return {"entries": []}
    obj = _read_json(mp)
    if not isinstance(obj, dict):
        return {"entries": []}
    entries = obj.get("entries", [])
    if not isinstance(entries, list):
        return {"entries": []}
    return {"entries": entries}


def _upsert_manifest_entry(snapshot_dir: Path, entry: Dict[str, Any]) -> None:
    obj = _load_manifest(snapshot_dir)
    existing = obj.get("entries", [])
    by_id: Dict[str, Dict[str, Any]] = {}
    for e in existing:
        if isinstance(e, dict) and isinstance(e.get("source_id"), str):
            by_id[e["source_id"]] = e
    by_id[entry["source_id"]] = entry
    out_entries: List[Dict[str, Any]] = [by_id[k] for k in sorted(by_id.keys())]
    _write_json(snapshot_dir / "sources.manifest.json", {"entries": out_entries})


def compute_sha256_tree_hash(snapshot_dir: Path) -> str:
    """
    Deterministic tree hash over:
      - sources/* bytes
      - sources.manifest.json bytes
    Excludes snapshot.meta.json to avoid circularity.
    """
    parts: List[str] = []
    sources_dir = snapshot_dir / "sources"
    files: List[Path] = []
    if sources_dir.exists():
        files.extend([p for p in sources_dir.rglob("*") if p.is_file()])
    manifest = snapshot_dir / "sources.manifest.json"
    if manifest.exists():
        files.append(manifest)
    files = sorted(files, key=lambda p: str(p.relative_to(snapshot_dir)))
    for p in files:
        rel = str(p.relative_to(snapshot_dir))
        parts.append(rel)
        parts.append(sha256_bytes(p.read_bytes()))
    return sha256_bytes("\n".join(parts).encode("utf-8"))


def _update_snapshot_meta(
    snapshot_dir: Path,
    snapshot_id: str,
    policy_version: str,
    toolchain_pins: Dict[str, Any],
) -> None:
    manifest_obj = _load_manifest(snapshot_dir)
    entries = manifest_obj.get("entries", [])
    created_at = ""
    if isinstance(entries, list) and entries:
        ts = [str(e.get("fetch_timestamp", "")).strip() for e in entries if isinstance(e, dict)]
        ts = [t for t in ts if t]
        if ts:
            created_at = sorted(ts)[0]

    meta = {
        "snapshot_id": snapshot_id,
        "policy_version": policy_version,
        "toolchain_pins": toolchain_pins,
        "created_at": created_at,
        "sha256_tree_hash": compute_sha256_tree_hash(snapshot_dir),
    }
    _write_json(snapshot_dir / "snapshot.meta.json", meta)


def try_load_toolchain_pins() -> Dict[str, Any]:
    """
    Best-effort: load toolchain pins from pinned DB snapshot manifest, if available.
    Does NOT mutate any snapshot or DB.
    """
    import os

    sid = str(os.environ.get("NLC_DB_SNAPSHOT_ID", "")).strip()
    if not sid:
        latest = BASE / "nlc" / "db" / "latest"
        if latest.exists():
            sid = latest.read_text(encoding="utf-8", errors="replace").strip()
    if not sid:
        return {}
    p = BASE / "nlc" / "db" / "snapshots" / sid / "manifest" / "toolchain_pins.json"
    if not p.exists():
        return {}
    try:
        obj = _read_json(p)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def write_external_source(
    snapshot_id: str,
    policy_version: str,
    toolchain_pins: Optional[Dict[str, Any]],
    source_id: str,
    content_type: str,
    fetch_timestamp: str,
    raw_bytes: bytes,
) -> ExternalSnapshotWrite:
    """
    Write raw bytes + update manifests deterministically.
    """
    sid = _safe_snapshot_id(snapshot_id)
    pv = str(policy_version or "").strip() or "v1"
    pins = toolchain_pins if isinstance(toolchain_pins, dict) else {}
    src = str(source_id or "").strip()
    if not src:
        raise ValueError("source_id is empty")
    ts = str(fetch_timestamp or "").strip()
    if not ts:
        raise ValueError("fetch_timestamp is empty")
    ctype = str(content_type or "").strip()

    snap_dir = EXTERNAL_ROOT / sid
    sources_dir = snap_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    filename = deterministic_source_filename(src)
    out_path = sources_dir / filename
    digest = sha256_bytes(raw_bytes)
    _atomic_write_bytes(out_path, raw_bytes)

    entry = {
        "source_id": src,
        "fetch_timestamp": ts,
        "content_type": ctype,
        "byte_length": int(len(raw_bytes)),
        "sha256": digest,
        "filename": f"sources/{filename}",
    }
    _upsert_manifest_entry(snap_dir, entry)
    _update_snapshot_meta(snap_dir, sid, pv, pins)

    return ExternalSnapshotWrite(
        snapshot_dir=snap_dir,
        source_id=src,
        filename=filename,
        sha256=digest,
        byte_length=int(len(raw_bytes)),
    )


