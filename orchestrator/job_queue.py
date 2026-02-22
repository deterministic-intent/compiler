#!/usr/bin/env python3
"""
Milestone 5.0: Job Queue + Isolation.

Job submission and state management with isolation guarantees.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

BASE = Path(__file__).resolve().parents[1]
import sys
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

JOBS_ROOT = BASE / "state" / "jobs"
TENANTS_ROOT = BASE / "state" / "tenants"


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _generate_job_id(dcs_content: str, snapshot_id: str, policy_version: str, tenant_id: Optional[str] = None) -> str:
    """
    Generate deterministic job_id from request content + snapshot + policy + tenant.
    """
    combined = f"{dcs_content}:{snapshot_id}:{policy_version}"
    if tenant_id:
        combined = f"{combined}:{tenant_id}"
    job_hash = _sha256_bytes(combined.encode("utf-8"))[:16]
    return f"JOB-{job_hash.upper()}"


def _safe_tenant_id(tenant_id: str) -> bool:
    """Validate tenant_id to prevent path traversal."""
    if not tenant_id:
        return False
    if ".." in tenant_id or "/" in tenant_id or "\\" in tenant_id:
        return False
    # Allow alphanumeric, hyphens, underscores
    return tenant_id.replace("-", "").replace("_", "").isalnum()


def submit_job(dcs_file: Path, snapshot_id: str, policy_version: str, tenant_id: Optional[str] = None) -> str:
    """
    Submit a job to the queue.
    
    Args:
        dcs_file: Path to .dcs request file
        snapshot_id: Knowledge snapshot ID
        policy_version: Policy version
        tenant_id: Optional tenant identifier for isolation
    
    Returns:
        job_id: Deterministic job identifier
    """
    if not dcs_file.exists():
        raise ValueError(f"dcs_file not found: {dcs_file}")
    
    if tenant_id and not _safe_tenant_id(tenant_id):
        raise ValueError(f"Invalid tenant_id: {tenant_id}")
    
    dcs_content = dcs_file.read_text(encoding="utf-8", errors="replace")
    job_id = _generate_job_id(dcs_content, snapshot_id, policy_version, tenant_id)
    
    # Use tenant-specific namespace if tenant_id provided
    if tenant_id:
        job_dir = TENANTS_ROOT / tenant_id / "jobs" / job_id
    else:
        job_dir = JOBS_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    
    # Store job metadata
    job_meta = {
        "job_id": job_id,
        "dcs_file": str(dcs_file.relative_to(BASE)) if dcs_file.is_relative_to(BASE) else str(dcs_file),
        "dcs_content_sha256": _sha256_bytes(dcs_content.encode("utf-8")),
        "snapshot_id": snapshot_id,
        "policy_version": policy_version,
        "tenant_id": tenant_id,
        "submitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
        "state": "SUBMITTED",
        "gate": 0,
    }
    
    (job_dir / "job.json").write_text(
        json.dumps(job_meta, indent=2, sort_keys=True) + "\n",
        encoding="utf-8"
    )
    
    # Copy .dcs file to job workspace
    (job_dir / "request.dcs").write_text(dcs_content, encoding="utf-8")
    
    return job_id


def get_job_state(job_id: str, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Get current job state.
    
    Args:
        job_id: Job identifier
        tenant_id: Optional tenant identifier for isolation
    
    Returns:
        Job state dictionary with gate, status, etc.
    """
    if tenant_id and not _safe_tenant_id(tenant_id):
        raise ValueError(f"Invalid tenant_id: {tenant_id}")
    
    # Try tenant-specific path first if tenant_id provided
    if tenant_id:
        job_dir = TENANTS_ROOT / tenant_id / "jobs" / job_id
        if not job_dir.exists():
            raise ValueError(f"Job not found: {job_id} (tenant: {tenant_id})")
    else:
        job_dir = JOBS_ROOT / job_id
        if not job_dir.exists():
            raise ValueError(f"Job not found: {job_id}")
    
    job_json = job_dir / "job.json"
    if not job_json.exists():
        raise ValueError(f"Job metadata not found: {job_json}")
    
    return json.loads(job_json.read_text(encoding="utf-8", errors="replace"))


def update_job_state(job_id: str, state: str, gate: Optional[int] = None, tenant_id: Optional[str] = None, **kwargs) -> None:
    """
    Update job state deterministically.
    
    Args:
        job_id: Job identifier
        state: New state (SUBMITTED, GATE0, GATE1, ..., GATEN, DONE, FAILED, CLARIFY, BLOCKED)
        gate: Optional gate number (0-6)
        tenant_id: Optional tenant identifier for isolation
        **kwargs: Additional state fields to update
    """
    if tenant_id and not _safe_tenant_id(tenant_id):
        raise ValueError(f"Invalid tenant_id: {tenant_id}")
    
    # Try tenant-specific path first if tenant_id provided
    if tenant_id:
        job_dir = TENANTS_ROOT / tenant_id / "jobs" / job_id
        if not job_dir.exists():
            raise ValueError(f"Job not found: {job_id} (tenant: {tenant_id})")
    else:
        job_dir = JOBS_ROOT / job_id
        if not job_dir.exists():
            raise ValueError(f"Job not found: {job_id}")
    
    job_json = job_dir / "job.json"
    job_meta = json.loads(job_json.read_text(encoding="utf-8", errors="replace"))
    
    # Update state
    job_meta["state"] = state
    if gate is not None:
        job_meta["gate"] = gate
    
    # Update additional fields
    job_meta.update(kwargs)
    
    # Record state transition
    if "transitions" not in job_meta:
        job_meta["transitions"] = []
    
    job_meta["transitions"].append({
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
        "state": state,
        "gate": gate if gate is not None else job_meta.get("gate", 0),
    })
    
    job_json.write_text(
        json.dumps(job_meta, indent=2, sort_keys=True) + "\n",
        encoding="utf-8"
    )


def get_job_workspace(job_id: str, tenant_id: Optional[str] = None) -> Path:
    """
    Get isolated workspace root for a job.
    
    Args:
        job_id: Job identifier
        tenant_id: Optional tenant identifier for isolation
    
    Returns:
        Path to job workspace
    """
    if tenant_id and not _safe_tenant_id(tenant_id):
        raise ValueError(f"Invalid tenant_id: {tenant_id}")
    
    if tenant_id:
        job_dir = TENANTS_ROOT / tenant_id / "jobs" / job_id
    else:
        job_dir = JOBS_ROOT / job_id
    workspace = job_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def get_job_request_dir(job_id: str, tenant_id: Optional[str] = None) -> Path:
    """
    Get request directory within job workspace.
    
    Args:
        job_id: Job identifier
        tenant_id: Optional tenant identifier for isolation
    
    Returns:
        Path to request directory
    """
    if tenant_id and not _safe_tenant_id(tenant_id):
        raise ValueError(f"Invalid tenant_id: {tenant_id}")
    
    if tenant_id:
        job_dir = TENANTS_ROOT / tenant_id / "jobs" / job_id
    else:
        job_dir = JOBS_ROOT / job_id
    requests_dir = job_dir / "workspace" / "requests"
    requests_dir.mkdir(parents=True, exist_ok=True)
    return requests_dir


def find_job_owner_tenant(job_id: str) -> Optional[str]:
    """
    Find which tenant owns a job by scanning tenant namespaces.
    
    Args:
        job_id: Job identifier
    
    Returns:
        tenant_id if job exists in a tenant namespace, None otherwise
    """
    if not TENANTS_ROOT.exists():
        return None
    
    for tenant_dir in TENANTS_ROOT.iterdir():
        if not tenant_dir.is_dir():
            continue
        tenant_id = tenant_dir.name
        if not _safe_tenant_id(tenant_id):
            continue
        job_path = tenant_dir / "jobs" / job_id / "job.json"
        if job_path.exists():
            return tenant_id
    
    return None


def tenant_job_exists(tenant_id: str, job_id: str) -> bool:
    """
    Check if a job exists in a specific tenant namespace.
    
    Args:
        tenant_id: Tenant identifier
        job_id: Job identifier
    
    Returns:
        True if job exists in tenant namespace, False otherwise
    """
    if not _safe_tenant_id(tenant_id):
        return False
    
    job_path = TENANTS_ROOT / tenant_id / "jobs" / job_id / "job.json"
    return job_path.exists()

