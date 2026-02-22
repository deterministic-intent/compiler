#!/usr/bin/env python3
"""
Step 10: Snapshot resolution & precedence (deterministic glue).

Writes:
  state/requests/<request_id>/snapshot_resolution.json

Rules:
- Explicit only (no defaults/inference).
- Deterministic total ordering: external -> knowledge -> db
- No merging; conflicts fail deterministically.
- In replay (NLC_REPRO=1): do not re-run; verifier must validate bytes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

# Repo root (nlc/ lives under it)
BASE = Path(__file__).resolve().parents[1]

ORDER = ["external", "knowledge", "db"]
SUPPORTED_FIELDS = {"knowledge_snapshot_id", "external_snapshot_id", "db_snapshot_id"}


class SnapshotResolutionError(Exception):
    def __init__(self, message: str, repro: str):
        super().__init__(message)
        self.message = message
        self.repro = repro


def _read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8", errors="replace"))


def _write_json(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fail(repro: str, msg: str) -> "SnapshotResolutionError":
    return SnapshotResolutionError(msg, repro=repro)


def _external_sha256(external_snapshot_id: str) -> str:
    meta = BASE / "snapshots" / "external" / external_snapshot_id / "snapshot.meta.json"
    if not meta.exists():
        raise _fail(f"snapshot:explicit_missing:{external_snapshot_id}", f"missing external snapshot.meta.json: {meta}")
    obj = _read_json(meta)
    if not isinstance(obj, dict):
        raise _fail(f"snapshot:explicit_missing:{external_snapshot_id}", f"invalid external snapshot.meta.json: {meta}")
    h = str(obj.get("sha256_tree_hash", "")).strip()
    if not h:
        raise _fail("snapshot:metadata_missing:sha256_tree_hash", f"external snapshot.meta.json missing sha256_tree_hash: {meta}")
    return h


def _knowledge_sha256(knowledge_snapshot_id: str) -> str:
    # Use deterministic manifest bundle hash (metadata only).
    from nlc.reproducibility import get_manifest_hashes

    info = get_manifest_hashes(knowledge_snapshot_id)
    h = str(info.get("manifest_bundle_hash", "")).strip()
    if not h:
        raise _fail(
            f"snapshot:explicit_missing:{knowledge_snapshot_id}",
            f"missing knowledge snapshot manifest bundle hash for {knowledge_snapshot_id}",
        )
    return h


def resolve_snapshot_set(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise _fail("snapshot:payload_invalid", "payload must be a JSON object")

    # Unknown snapshot fields -> FAIL
    for k in payload.keys():
        if isinstance(k, str) and k.endswith("_snapshot_id") and k not in SUPPORTED_FIELDS:
            raise _fail("snapshot:unknown_field", f"unknown snapshot field: {k}")

    request_id = str(payload.get("request_id", "")).strip() or ""

    external_id = payload.get("external_snapshot_id")
    knowledge_id = payload.get("knowledge_snapshot_id")
    db_id = payload.get("db_snapshot_id")

    # Normalize null/empty
    external_id = str(external_id).strip() if isinstance(external_id, str) and external_id.strip() else None
    knowledge_id = str(knowledge_id).strip() if isinstance(knowledge_id, str) and knowledge_id.strip() else None
    db_id = str(db_id).strip() if isinstance(db_id, str) and db_id.strip() else None

    # Explicit only: if field present but empty/null -> FAIL (except db can be null and is ignored)
    if "external_snapshot_id" in payload and external_id is None:
        raise _fail("snapshot:explicit_missing:external_snapshot_id", "payload.external_snapshot_id is missing/empty")
    if "knowledge_snapshot_id" in payload and knowledge_id is None:
        raise _fail("snapshot:explicit_missing:knowledge_snapshot_id", "payload.knowledge_snapshot_id is missing/empty")
    if "db_snapshot_id" in payload and payload.get("db_snapshot_id") is not None and db_id is None:
        raise _fail("snapshot:explicit_missing:db_snapshot_id", "payload.db_snapshot_id is missing/empty")

    # Conflict handling: same ID in multiple categories is a hard failure (no merge).
    ids = [x for x in [external_id, knowledge_id, db_id] if x]
    if len(set(ids)) != len(ids):
        # Find first duplicate pair deterministically in ORDER
        ordered = [("external", external_id), ("knowledge", knowledge_id), ("db", db_id)]
        seen = {}
        for _t, _id in ordered:
            if not _id:
                continue
            if _id in seen:
                raise _fail(f"snapshot:conflict:{seen[_id]}:{_id}", f"snapshot conflict: {seen[_id]} vs {_id}")
            seen[_id] = _id

    ordered_snapshots: List[Dict[str, str]] = []
    if external_id:
        ordered_snapshots.append({"type": "external", "snapshot_id": external_id, "sha256": _external_sha256(external_id)})
    if knowledge_id:
        ordered_snapshots.append({"type": "knowledge", "snapshot_id": knowledge_id, "sha256": _knowledge_sha256(knowledge_id)})
    if db_id:
        # Future: if/when a db snapshot metadata hash exists, wire it here.
        ordered_snapshots.append({"type": "db", "snapshot_id": db_id, "sha256": ""})

    # Enforce hard-coded ordering
    ordered_snapshots = sorted(ordered_snapshots, key=lambda e: ORDER.index(e["type"]))

    return {
        "request_id": request_id,
        "ordered_snapshots": ordered_snapshots,
    }


def write_snapshot_resolution(request_dir: Path) -> Path:
    payload_path = request_dir / "payload.json"
    if not payload_path.exists():
        raise _fail("snapshot:payload_missing", f"missing payload.json: {payload_path}")
    payload = _read_json(payload_path)
    if not isinstance(payload, dict):
        raise _fail("snapshot:payload_invalid", f"payload.json must be an object: {payload_path}")
    # Ensure request_id is present for output
    payload.setdefault("request_id", request_dir.name)
    out = resolve_snapshot_set(payload)
    out_path = request_dir / "snapshot_resolution.json"
    _write_json(out_path, out)
    return out_path


def expected_snapshot_resolution_bytes(request_dir: Path) -> bytes:
    payload_path = request_dir / "payload.json"
    payload = _read_json(payload_path)
    if not isinstance(payload, dict):
        raise _fail("snapshot:payload_invalid", "payload.json must be an object")
    payload.setdefault("request_id", request_dir.name)
    out = resolve_snapshot_set(payload)
    return (json.dumps(out, indent=2, sort_keys=True) + "\n").encode("utf-8")


