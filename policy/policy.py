#!/usr/bin/env python3
"""Policy loader - deterministic policy versioning and loading."""

import json
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass


BASE = Path(__file__).resolve().parent


@dataclass
class Policy:
    """Policy object - immutable policy configuration."""
    policy_version: str
    snapshot: Dict[str, Any]
    llm: Dict[str, Any]
    repair: Dict[str, Any]
    toolchain: Dict[str, Any]
    forbidden_paths: list[str]
    determinism: Dict[str, Any]
    
    def get_snapshot_policy(self) -> Dict[str, Any]:
        """Get snapshot policy section."""
        return self.snapshot
    
    def get_llm_policy(self) -> Dict[str, Any]:
        """Get LLM policy section."""
        return self.llm
    
    def get_repair_policy(self) -> Dict[str, Any]:
        """Get repair policy section."""
        return self.repair
    
    def get_toolchain_policy(self) -> Dict[str, Any]:
        """Get toolchain policy section."""
        return self.toolchain
    
    def get_forbidden_paths(self) -> list[str]:
        """Get forbidden paths list."""
        return self.forbidden_paths
    
    def get_determinism_policy(self) -> Dict[str, Any]:
        """Get determinism policy section."""
        return self.determinism


def load_policy(policy_version: str) -> Policy:
    """
    Load policy by version. Deterministic behavior:
    - Missing (empty/None): not handled here (caller should default before calling)
    - Unknown (file not found): hard fail
    
    Args:
        policy_version: Policy version string (e.g., "v1")
    
    Returns:
        Policy object
    
    Raises:
        ValueError: If policy_version is empty
        FileNotFoundError: If policy file does not exist (unknown version - hard fail)
        ValueError: If policy file is invalid JSON or missing required fields
    """
    if not policy_version:
        raise ValueError("policy_version is required (cannot be empty)")
    
    # Normalize version string
    version = policy_version.strip().lower()
    if not version.startswith("v"):
        version = f"v{version}"
    
    # Load policy file - unknown version = hard fail (no silent fallback)
    policy_file = BASE / f"policy_{version}.json"
    if not policy_file.exists():
        raise FileNotFoundError(
            f"Policy version '{policy_version}' not found: {policy_file}. "
            f"Available versions: {_list_available_versions()}"
        )
    
    try:
        policy_data = json.loads(policy_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Policy file {policy_file} is invalid JSON: {e}")
    
    # Validate required fields
    required_fields = ["policy_version", "snapshot", "llm", "repair", "toolchain", "forbidden_paths", "determinism"]
    for field in required_fields:
        if field not in policy_data:
            raise ValueError(f"Policy file {policy_file} missing required field: {field}")
    
    # Ensure policy_version matches
    if policy_data["policy_version"] != version and policy_data["policy_version"] != policy_version:
        raise ValueError(
            f"Policy file version mismatch: expected '{policy_version}', got '{policy_data['policy_version']}'"
        )
    
    return Policy(
        policy_version=policy_data["policy_version"],
        snapshot=policy_data.get("snapshot", {}),
        llm=policy_data.get("llm", {}),
        repair=policy_data.get("repair", {}),
        toolchain=policy_data.get("toolchain", {}),
        forbidden_paths=policy_data.get("forbidden_paths", []),
        determinism=policy_data.get("determinism", {})
    )


def _list_available_versions() -> list[str]:
    """List available policy versions on disk."""
    versions = []
    for p in BASE.glob("policy_v*.json"):
        # Extract version from filename policy_v1.json -> v1
        name = p.stem  # "policy_v1"
        if name.startswith("policy_"):
            versions.append(name[7:])  # Remove "policy_" prefix
    return sorted(versions)


def get_default_policy_version() -> str:
    """
    Get default policy version. Deterministic default for backward compatibility.
    
    This is used when policy_version is MISSING (not specified), not when it's UNKNOWN (file not found).
    
    Returns:
        Default policy version string ("v1")
    """
    return "v1"


def get_default_snapshot_id(policy_version: Optional[str] = None) -> Optional[str]:
    """
    Get default snapshot ID from policy defaults section (single-source).
    CLI may use this ONLY if present and non-empty. Never invents a snapshot id.
    
    Returns:
        Snapshot ID string if policy.defaults.snapshot_id is set, else None
    """
    pv = (policy_version or get_default_policy_version()).strip() or "v1"
    if not pv.startswith("v"):
        pv = f"v{pv}"
    policy_file = BASE / f"policy_{pv}.json"
    if not policy_file.exists():
        return None
    try:
        data = json.loads(policy_file.read_text(encoding="utf-8"))
        defaults = data.get("defaults")
        if isinstance(defaults, dict):
            sid = defaults.get("snapshot_id")
            if sid and str(sid).strip():
                return str(sid).strip()
    except Exception:
        pass
    return None

