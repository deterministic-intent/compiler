#!/usr/bin/env python3
"""Manifest builder for DB snapshots - Step 2: deterministic manifest generation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

BASE = Path(__file__).resolve().parents[2]


def _sha256_bytes(b: bytes) -> str:
    """Compute SHA256 hash."""
    return hashlib.sha256(b).hexdigest()


def _sha256_file(p: Path) -> str:
    """Compute SHA256 hash of file."""
    return _sha256_bytes(p.read_bytes())


def _stable_sort_key(item: Dict[str, Any]) -> tuple:
    """Generate stable sort key for deterministic ordering."""
    # Sort by id first, then name, then path
    return (
        str(item.get("intent_id", item.get("template_id", item.get("module_id", item.get("practice_id", ""))))),
        str(item.get("name", "")),
        str(item.get("path", "")),
    )


def build_intents_manifest(base: Path, snapshot_id: str) -> Dict[str, Any]:
    """
    Build intents manifest from registry v1.
    
    Source: nlc/registry/v1/intents/*.json
    """
    intents_dir = base / "nlc" / "registry" / "v1" / "intents"
    if not intents_dir.exists():
        return {"intents": []}
    
    intents: List[Dict[str, Any]] = []
    
    # Load all intent files deterministically sorted
    intent_files = sorted([f for f in intents_dir.glob("*.json") if f.is_file()], key=lambda p: p.name)
    
    for intent_file in intent_files:
        try:
            intent_data = json.loads(intent_file.read_text(encoding="utf-8"))
            intent_id = intent_data.get("intent_id", intent_file.stem)
            
            # Build manifest entry with stable structure
            manifest_entry = {
                "intent_id": intent_id,
                "name": intent_data.get("description", intent_id),
                "inputs_schema": intent_data.get("params_json", {}),
                "outputs_schema": intent_data.get("io_json", {}),
                "pipeline_type": intent_data.get("pipeline_type", "unknown"),
                "source_refs": [f"nlc/registry/v1/intents/{intent_file.name}"],
            }
            
            # Optional fields
            if intent_data.get("synonyms"):
                manifest_entry["synonyms"] = intent_data["synonyms"]
            
            intents.append(manifest_entry)
        except Exception:
            # Skip invalid intent files but continue
            continue
    
    # Deterministic sort
    intents.sort(key=_stable_sort_key)
    
    return {"intents": intents}


def build_templates_manifest(base: Path, snapshot_id: str) -> Dict[str, Any]:
    """
    Build templates manifest from DB snapshot.
    
    Source: DB-derived (from ingested content in snapshot DB).
    If templates not yet in DB, return empty valid structure.
    
    IMPORTANT: Do NOT source from orchestrator/modules/* (those are modules, not templates).
    """
    # For Step 2: templates are not yet in DB, so return empty but valid structure
    # This will be populated in later steps when templates are ingested into DB
    return {"templates": []}


def build_modules_manifest(base: Path, snapshot_id: str) -> Dict[str, Any]:
    """
    Build modules manifest from orchestrator modules.
    
    Source: orchestrator/modules/*/*.json
    """
    modules_dir = base / "orchestrator" / "modules"
    if not modules_dir.exists():
        return {"modules": []}
    
    modules: List[Dict[str, Any]] = []
    
    # Load all module files deterministically sorted
    module_files = sorted([f for f in modules_dir.rglob("*.json") if f.is_file()], 
                         key=lambda p: str(p.relative_to(modules_dir)))
    
    for module_file in module_files:
        try:
            module_data = json.loads(module_file.read_text(encoding="utf-8"))
            
            # Extract artifact class from path: orchestrator/modules/python_cli/argparse_setup.json -> python_cli
            rel_path = module_file.relative_to(modules_dir)
            artifact_class = rel_path.parts[0] if len(rel_path.parts) > 1 else "unknown"
            module_name = module_file.stem
            
            # Build stable module_id from path
            module_id = f"{artifact_class}:{module_name}"
            
            # Build manifest entry
            manifest_entry = {
                "module_id": module_id,
                "name": module_data.get("name", module_name),
                "artifact_class": artifact_class,
                "path": str(rel_path),
                "provides": module_data.get("provides", []),
                "source_ref": f"orchestrator/modules/{rel_path}",
            }
            
            # Optional fields
            if module_data.get("description"):
                manifest_entry["description"] = module_data["description"]
            if module_data.get("template"):
                manifest_entry["has_template"] = True
            
            modules.append(manifest_entry)
        except Exception:
            # Skip invalid module files but continue
            continue
    
    # Deterministic sort
    modules.sort(key=_stable_sort_key)
    
    return {"modules": modules}


def build_practices_manifest(base: Path, snapshot_id: str) -> Dict[str, Any]:
    """
    Build practices manifest.
    
    For Step 2: return empty but valid structure.
    Will be populated in later steps when practices are defined.
    """
    return {"practices": []}


def build_intents_v1_manifest(base: Path, snapshot_id: str) -> Dict[str, Any]:
    """
    Build intents_v1 manifest for module_refs enrichment.
    Maps executable intents (with intent_emitters) to python_cli module_refs.
    Deterministic: only intents with orchestrator/intent_emitters/<id>.json get module_refs.
    """
    intents_manifest = build_intents_manifest(base, snapshot_id)
    modules_manifest = build_modules_manifest(base, snapshot_id)
    intents = intents_manifest.get("intents", []) or []
    modules = modules_manifest.get("modules", []) or []

    # Find python_cli module path for module_ref (format: artifact_class/module_file for get_module_by_ref)
    python_cli_module_ref: Optional[str] = None
    for mod in modules:
        ac = str(mod.get("artifact_class", "")).strip()
        path = str(mod.get("path", "")).strip()
        if ac == "python_cli" and path:
            python_cli_module_ref = path if path.endswith(".json") else f"{path}.json"
            break
    if not python_cli_module_ref:
        return {"intents": []}

    emitters_dir = base / "orchestrator" / "intent_emitters"
    v1_intents: List[Dict[str, Any]] = []
    for intent in intents:
        intent_id = intent.get("intent_id", "")
        if not intent_id:
            continue
        # Only add module_refs for intents that have an executable emitter
        emitter_path = emitters_dir / f"{intent_id}.json"
        if not emitter_path.exists():
            continue
        v1_intents.append({
            "intent_id": intent_id,
            "module_refs": [python_cli_module_ref],
        })
    v1_intents.sort(key=_stable_sort_key)
    return {"intents": v1_intents}


def build_toolchain_pins_manifest(base: Path, snapshot_id: str, policy_version: Optional[str] = None) -> Dict[str, Any]:
    """
    Build toolchain pins manifest from policy.
    
    Source: policy-defined (from loaded policy) or deterministic defaults.
    """
    # Load policy to get toolchain pins
    try:
        from policy import load_policy, get_default_policy_version
        
        if policy_version is None:
            policy_version = get_default_policy_version()
        
        policy = load_policy(policy_version)
        toolchain_policy = policy.get_toolchain_policy()
        
        # Extract pins from policy (or use empty structure if not defined)
        pins = toolchain_policy.get("pins", {})
        
        return {
            "policy_version": policy_version,  # Snapshot-bound: records policy version used
            "pins": pins if pins else {},
        }
    except Exception:
        # If policy unavailable, return minimal valid structure with explicit policy_version
        return {
            "policy_version": policy_version or "v1",  # Snapshot-bound: records policy version used
            "pins": {},
        }


def build_all_manifests(base: Path, snapshot_id: str, policy_version: Optional[str] = None) -> Dict[str, str]:
    """
    Build all manifest files for a snapshot.
    
    Args:
        base: Repository root path
        snapshot_id: Snapshot ID (directory name under nlc/db/snapshots/)
        policy_version: Optional policy version (defaults to v1)
    
    Returns:
        Dict mapping manifest filename to SHA256 hash
    
    Raises:
        FileNotFoundError: If snapshot directory doesn't exist
        RuntimeError: If manifest directory cannot be created
    """
    # Canonical snapshot root
    snapshot_dir = base / "nlc" / "db" / "snapshots" / snapshot_id
    if not snapshot_dir.exists():
        raise FileNotFoundError(f"Snapshot directory not found: {snapshot_dir}")
    
    # Create manifest directory
    manifest_dir = snapshot_dir / "manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    
    # Build each manifest
    intents_manifest = build_intents_manifest(base, snapshot_id)
    templates_manifest = build_templates_manifest(base, snapshot_id)
    modules_manifest = build_modules_manifest(base, snapshot_id)
    practices_manifest = build_practices_manifest(base, snapshot_id)
    toolchain_pins_manifest = build_toolchain_pins_manifest(base, snapshot_id, policy_version)
    intents_v1_manifest = build_intents_v1_manifest(base, snapshot_id)
    
    # Write manifests with deterministic formatting
    manifest_hashes: Dict[str, str] = {}
    
    manifests = {
        "intents.json": intents_manifest,
        "templates.json": templates_manifest,
        "modules.json": modules_manifest,
        "practices.json": practices_manifest,
        "toolchain_pins.json": toolchain_pins_manifest,
        "intents_v1.json": intents_v1_manifest,
    }
    
    for filename, manifest_data in manifests.items():
        manifest_path = manifest_dir / filename
        
        # Write with consistent formatting (indent=2, sort_keys=True, trailing newline)
        # Note: sort_keys=True ensures determinism but may reorder nested object keys.
        # If human-friendly diffs become important later, consider explicit key ordering.
        json_content = json.dumps(manifest_data, indent=2, sort_keys=True, ensure_ascii=False)
        manifest_path.write_text(json_content + "\n", encoding="utf-8")
        
        # Compute hash from written file (source of truth)
        manifest_hashes[filename] = _sha256_file(manifest_path)
    
    return manifest_hashes


def compute_manifest_bundle_hash(manifest_hashes: Dict[str, str]) -> str:
    """
    Compute deterministic bundle hash over all manifest hashes.
    
    Args:
        manifest_hashes: Dict mapping filename to SHA256 hash
    
    Returns:
        SHA256 hash of sorted manifest hashes
    """
    # Sort by filename for deterministic ordering
    sorted_items = sorted(manifest_hashes.items())
    combined = "\n".join(f"{filename}:{hash_val}" for filename, hash_val in sorted_items)
    return _sha256_bytes(combined.encode("utf-8"))

