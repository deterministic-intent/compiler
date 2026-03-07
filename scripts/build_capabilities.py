#!/usr/bin/env python3
"""
Step 21 (Phase 2 prerequisite): Build capabilities catalog derived from a pinned snapshot.

Hard rules:
- No network calls
- Stable JSON formatting + ordering
- Output must be byte-identical for same snapshot id

Outputs:
- nlc/db/snapshots/<snapshot_id>/capabilities.json

Failure tokens (locked):
FAIL step21:missing_snapshot
FAIL step21:index_missing
FAIL step21:capability_claim_without_evidence
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple


BASE = Path(__file__).resolve().parents[1]
# Ensure repo root is importable when running as a script.
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
SNAP_ROOT = BASE / "nlc" / "db" / "snapshots"
REQ_ROOT = BASE / "state" / "requests"


def _fail(token: str) -> None:
    sys.stdout.write(f"FAIL {token}\n")
    sys.stdout.flush()
    raise SystemExit(1)


def _die(msg: str, code: int = 1) -> None:
    sys.stdout.write((msg.rstrip("\n") + "\n"))
    sys.stdout.flush()
    raise SystemExit(code)


def _read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8", errors="replace"))


def _write_json(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sanitize_request_id(snapshot_id: str) -> str:
    rid = f"CAPS-{snapshot_id}"
    rid = re.sub(r"[^A-Za-z0-9_.-]+", "_", rid)
    return rid[:80]


def _ensure_index_db(request_id: str, payload: Dict[str, Any]) -> Tuple[Path, str]:
    """
    Build a deterministic request-local index DB for evidence.
    Returns (index_db_path, index_sha256).
    """
    rd = REQ_ROOT / request_id
    if rd.exists():
        shutil.rmtree(rd, ignore_errors=True)
    rd.mkdir(parents=True, exist_ok=True)

    payload_path = rd / "payload.json"
    _write_json(payload_path, payload)

    # Snapshot resolution (deterministic; uses payload only).
    try:
        from nlc.snapshot_resolver import write_snapshot_resolution

        write_snapshot_resolution(rd)
    except Exception:
        _fail("step21:missing_snapshot")

    # Build index db using existing deterministic builder script.
    p = subprocess.run(
        [sys.executable, str(BASE / "scripts" / "build_index_db.py"), request_id],
        cwd=str(BASE),
        env={**os.environ},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if p.returncode != 0:
        _fail("step21:index_missing")

    index_db = rd / "index" / "index.db"
    index_sha = rd / "index" / "index.sha256"
    if not index_db.exists() or not index_sha.exists():
        _fail("step21:index_missing")
    sha_txt = index_sha.read_text(encoding="utf-8", errors="replace").strip().split()
    sha = sha_txt[0] if sha_txt else ""
    if not sha:
        _fail("step21:index_missing")
    return index_db, sha


def _derive_from_snapshot(snapshot_id: str, policy_version: str = "v1") -> Dict[str, Any]:
    snap_dir = SNAP_ROOT / snapshot_id
    if not snap_dir.exists():
        _fail("step21:missing_snapshot")

    modules_path = snap_dir / "manifest" / "modules.json"
    intents_path = snap_dir / "manifest" / "intents.json"
    mined_path = snap_dir / "manifest" / "intents_mined.json"
    classified_path = snap_dir / "manifest" / "intents_classified.json"
    if not modules_path.exists() or not intents_path.exists():
        _fail("step21:missing_snapshot")

    modules_obj = _read_json(modules_path)
    intents_obj = _read_json(intents_path)
    mined_obj = _read_json(mined_path) if mined_path.exists() else {"intents": []}
    classified_obj = _read_json(classified_path) if classified_path.exists() else {"intents": []}
    if not isinstance(modules_obj, dict) or not isinstance(intents_obj, dict):
        _fail("step21:missing_snapshot")

    mods = modules_obj.get("modules", [])
    ints = intents_obj.get("intents", [])
    if not isinstance(mods, list) or not isinstance(ints, list):
        _fail("step21:missing_snapshot")

    mined_intents = mined_obj.get("intents", []) if isinstance(mined_obj, dict) else []
    if not isinstance(mined_intents, list):
        mined_intents = []

    supported_artifact_classes: Set[str] = set()
    for m in mods:
        if not isinstance(m, dict):
            continue
        ac = m.get("artifact_class")
        if isinstance(ac, str) and ac.strip():
            supported_artifact_classes.add(ac.strip())

    tools: Set[str] = set()
    baseline_manifest_intents_ids: List[str] = []
    for it in ints:
        if not isinstance(it, dict):
            continue
        iid = it.get("intent_id")
        if isinstance(iid, str) and iid.strip():
            tools.add(iid.strip())
            baseline_manifest_intents_ids.append(iid.strip())

    # Extract mined intents stats
    mined_active: List[Dict[str, Any]] = []
    mined_active_ids: List[str] = []
    for it in mined_intents:
        if not isinstance(it, dict):
            continue
        if str(it.get("status", "")).strip() != "ACTIVE":
            continue
        mined_active.append(it)
        iid = str(it.get("intent_id", "")).strip()
        if iid:
            mined_active_ids.append(iid)

    # Read policy for reachability mode
    policy_path = BASE / "policy" / f"policy_{policy_version}.json"
    reachability_mode = "union"  # default
    if policy_path.exists():
        try:
            policy_obj = _read_json(policy_path)
            if isinstance(policy_obj, dict):
                caps_policy = policy_obj.get("capabilities", {})
                if isinstance(caps_policy, dict):
                    mode = str(caps_policy.get("reachability_mode", "union")).strip()
                    if mode in ("legacy_only", "mined_only", "union"):
                        reachability_mode = mode
        except Exception:
            pass  # Use default

    # Reachable intents based on policy mode
    reachable_intents: Set[str] = set()
    if reachability_mode == "legacy_only":
        reachable_intents = set(tools)
    elif reachability_mode == "mined_only":
        reachable_intents = set(mined_active_ids)
    else:  # union
        reachable_intents = set(tools)
        for iid in mined_active_ids:
            reachable_intents.add(iid)

    # Reachable artifact classes: python_cli (intent-driven) + mined ACTIVE artifact_class
    reachable_artifact_classes: Set[str] = set()
    if tools:
        reachable_artifact_classes.add("python_cli")
    for it in mined_active:
        ac = str(it.get("artifact_class", "")).strip()
        if ac:
            reachable_artifact_classes.add(ac)

    # Languages are derived deterministically from supported artifact classes (evidence-based).
    languages: Set[str] = set()
    for ac in supported_artifact_classes:
        if ac.startswith("python_"):
            languages.add("python")
        elif ac == "webview":
            languages.add("web")
        else:
            languages.add(ac)

    # language_artifact_matrix from contracts (v1). Matrix keys = snapshot languages.
    matrix_path = BASE / "contracts" / "v1_language_artifact_matrix.json"
    language_artifact_matrix: Dict[str, List[str]] = {}
    if matrix_path.exists():
        try:
            m = _read_json(matrix_path)
            language_artifact_matrix = dict(m.get("mapping", {}))
            language_artifact_matrix = dict(sorted(language_artifact_matrix.items()))
            for lang, acs in language_artifact_matrix.items():
                if not acs:
                    _fail(f"LANG_MATRIX_EMPTY_BINDING:{lang}")
            if language_artifact_matrix:
                languages = set(language_artifact_matrix.keys())
                for acs in language_artifact_matrix.values():
                    for ac in acs:
                        if isinstance(ac, str) and ac.strip():
                            supported_artifact_classes.add(ac.strip())
        except SystemExit:
            raise
        except Exception:
            pass

    # Extract classified intents (NOT executable - no per-intent module binding)
    classified_intents_list = classified_obj.get("intents", []) if isinstance(classified_obj, dict) else []
    if not isinstance(classified_intents_list, list):
        classified_intents_list = []
    classified_intent_ids = sorted([
        str(it.get("intent_id", "")).strip()
        for it in classified_intents_list
        if isinstance(it, dict) and str(it.get("intent_id", "")).strip()
    ])
    
    # Count artifact classes in classified intents
    classified_artifact_classes = sorted(set([
        str(it.get("artifact_class", "")).strip()
        for it in classified_intents_list
        if isinstance(it, dict) and str(it.get("artifact_class", "")).strip()
    ]))
    
    # Count intent-level executable (must have module_refs and non-empty invocation_shape)
    intent_level_executable_count = 0
    for it in classified_intents_list:
        if not isinstance(it, dict):
            continue
        if it.get("executable") is True:
            # Check if it has required fields for true executability
            has_module_refs = bool(it.get("module_refs")) and len(it.get("module_refs", [])) > 0
            inv_shape = it.get("invocation_shape", {})
            has_inputs = bool(inv_shape.get("inputs")) and len(inv_shape.get("inputs", [])) > 0
            has_outputs = bool(inv_shape.get("outputs")) and len(inv_shape.get("outputs", [])) > 0
            has_contract = bool(it.get("contract_ref"))
            if has_module_refs and (has_inputs or has_outputs) and has_contract:
                intent_level_executable_count += 1

    return {
        "supported_artifact_classes": sorted(supported_artifact_classes),
        "languages": sorted(languages),
        "tools": sorted(tools),
        "reachable_intents_from_text": sorted(reachable_intents),
        "reachable_artifact_classes_from_text": sorted(reachable_artifact_classes),
        "mined_intents_total": len(mined_intents),
        "mined_intents_active": len(mined_active_ids),
        "mined_intents_active_ids": sorted(mined_active_ids),
        "baseline_manifest_intents_ids": sorted(baseline_manifest_intents_ids),
        "reachability_mode": reachability_mode,
        "classified_intents": {
            "count": len(classified_intent_ids),
            "artifact_classes": classified_artifact_classes,
            "intent_ids": classified_intent_ids,
        },
        "intent_level_executable_count": intent_level_executable_count,
        "evidence": {
            "modules_manifest_relpath": "manifest/modules.json",
            "intents_manifest_relpath": "manifest/intents.json",
            "intents_mined_relpath": "manifest/intents_mined.json" if mined_path.exists() else "",
            "intents_classified_relpath": "manifest/intents_classified.json" if classified_path.exists() else "",
        },
        "language_artifact_matrix": language_artifact_matrix,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot-id", required=True)
    ap.add_argument("--policy", default="v1")
    args = ap.parse_args()

    snapshot_id = str(args.snapshot_id).strip()
    policy_version = str(args.policy).strip() or "v1"
    if not snapshot_id:
        _fail("step21:missing_snapshot")

    # Derive capabilities from snapshot manifests (and build index DB for evidence/pinning).
    derived = _derive_from_snapshot(snapshot_id, policy_version)

    # Build evidence index DB deterministically.
    request_id = _sanitize_request_id(snapshot_id)
    payload = {
        "request_id": request_id,
        "policy_version": policy_version,
        "knowledge_snapshot_id": snapshot_id,
        # No external snapshot; capability discovery is snapshot-only.
        "manifest_bundle_hash": derived.get("manifest_bundle_hash", None),
    }
    # Do not invent manifest_bundle_hash here; snapshot_resolver + index builder pin it via repro.
    # However, we do include it in the final capabilities.json by reading reproducibility metadata.
    try:
        from nlc.reproducibility import get_manifest_hashes

        payload["manifest_bundle_hash"] = get_manifest_hashes(snapshot_id).get("manifest_bundle_hash")
    except Exception:
        payload["manifest_bundle_hash"] = None

    _, index_sha256 = _ensure_index_db(request_id, payload)

    # Validate we are not claiming capabilities without evidence.
    if not derived["supported_artifact_classes"] or not derived["tools"] or not derived["languages"]:
        _fail("step21:capability_claim_without_evidence")

    # docker_base_image_ref from governed surface only (toolchain_pins.json; no code default)
    docker_base_image_ref: str | None = None
    toolchain_path = SNAP_ROOT / snapshot_id / "manifest" / "toolchain_pins.json"
    if toolchain_path.exists():
        try:
            tc = _read_json(toolchain_path)
            ref = tc.get("docker_base_image_ref")
            if isinstance(ref, str) and ref.strip() and re.match(r"^[^@]+@sha256:[a-f0-9]{64}$", ref.strip()):
                docker_base_image_ref = ref.strip()
        except Exception:
            pass
    if "docker_image" in derived["supported_artifact_classes"] and docker_base_image_ref is None:
        _fail("DOCKER_BASE_REF_MISSING")

    # Preserve truth-backed classes if present in existing capabilities (deterministic fallback).
    truth_backed: List[str] = []
    existing_caps = SNAP_ROOT / snapshot_id / "capabilities.json"
    if existing_caps.exists():
        try:
            prev = _read_json(existing_caps)
            tbc = prev.get("truth_backed_artifact_classes", [])
            if isinstance(tbc, list):
                truth_backed = [str(x).strip() for x in tbc if str(x).strip()]
        except Exception:
            truth_backed = []
    if not truth_backed:
        truth_backed = ["python_cli"]

    out = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "policy_version": policy_version,
        "manifest_bundle_hash": payload.get("manifest_bundle_hash"),
        "docker_base_image_ref": docker_base_image_ref,
        "languages": derived["languages"],
        "tools": derived["tools"],
        "supported_artifact_classes": derived["supported_artifact_classes"],
        "reachable_intents_from_text": derived["reachable_intents_from_text"],
        "reachable_artifact_classes_from_text": derived["reachable_artifact_classes_from_text"],
        "truth_backed_artifact_classes": truth_backed,
        # Mining visibility fields (from derived)
        "mined_intents_total": derived.get("mined_intents_total", 0),
        "mined_intents_active": derived.get("mined_intents_active", 0),
        "mined_intents_active_ids": derived.get("mined_intents_active_ids", []),
        "baseline_manifest_intents_ids": derived.get("baseline_manifest_intents_ids", []),
        "reachability_mode": derived.get("reachability_mode", "union"),
        "classified_intents": derived.get("classified_intents", {"count": 0, "artifact_classes": [], "intent_ids": []}),
        "intent_level_executable_count": derived.get("intent_level_executable_count", 0),
        "language_artifact_matrix": derived.get("language_artifact_matrix", {}),
        "evidence": {
            **derived["evidence"],
            "index_sha256": index_sha256,
            "index_request_id": request_id,
        },
    }

    out_path = SNAP_ROOT / snapshot_id / "capabilities.json"
    _write_json(out_path, out)
    sys.stdout.write(str(out_path) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


