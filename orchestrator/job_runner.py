#!/usr/bin/env python3
"""
Milestone 5.0: Job Runner - Execute jobs in isolated workspaces.

Ensures:
- Per-job isolation (no cross-job writes)
- Deterministic provenance recording
- Gate-mirrored state machine
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, Optional

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

# Import job_queue - handle both package and direct import
try:
    from orchestrator.job_queue import (
        get_job_state,
        update_job_state,
        get_job_workspace,
        get_job_request_dir,
        JOBS_ROOT,
    )
except ImportError:
    # Fallback for direct script execution
    import importlib.util
    job_queue_path = BASE / "orchestrator" / "job_queue.py"
    job_queue_spec = importlib.util.spec_from_file_location("job_queue", job_queue_path)
    job_queue_module = importlib.util.module_from_spec(job_queue_spec)
    job_queue_spec.loader.exec_module(job_queue_module)
    get_job_state = job_queue_module.get_job_state
    update_job_state = job_queue_module.update_job_state
    get_job_workspace = job_queue_module.get_job_workspace
    get_job_request_dir = job_queue_module.get_job_request_dir
    JOBS_ROOT = job_queue_module.JOBS_ROOT
# Import orchestrator functions
# We need to patch request_dir() to use job workspace
import orchestrator.orchestrator as orch_module

# Monkey-patch REQS to use job workspace when in job mode
_original_REQS = None

def _setup_job_workspace(job_id: str, tenant_id: Optional[str] = None):
    """Patch orchestrator.REQS to use job workspace."""
    global _original_REQS
    if _original_REQS is None:
        _original_REQS = orch_module.REQS
    
    # Set REQS to job requests directory
    orch_module.REQS = get_job_request_dir(job_id, tenant_id)

def _restore_workspace():
    """Restore original REQS."""
    global _original_REQS
    if _original_REQS is not None:
        orch_module.REQS = _original_REQS


def _record_provenance(job_id: str, gate: int, command: list[str], exit_code: int, stdout: bytes, stderr: bytes) -> None:
    """
    Record deterministic provenance for a gate execution.
    """
    job_dir = JOBS_ROOT / job_id
    prov_dir = job_dir / "provenance"
    prov_dir.mkdir(parents=True, exist_ok=True)
    
    import hashlib
    stdout_sha256 = hashlib.sha256(stdout).hexdigest()
    stderr_sha256 = hashlib.sha256(stderr).hexdigest()
    
    prov_entry = {
        "gate": gate,
        "command": command,
        "exit_code": exit_code,
        "stdout_sha256": stdout_sha256,
        "stderr_sha256": stderr_sha256,
    }
    
    prov_file = prov_dir / f"gate{gate}.json"
    prov_file.write_text(
        json.dumps(prov_entry, indent=2, sort_keys=True) + "\n",
        encoding="utf-8"
    )


def run_job(job_id: str, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Run a job through all gates in isolated workspace.
    
    Args:
        job_id: Job identifier
        tenant_id: Optional tenant identifier for isolation
    
    Returns:
        Final job state dictionary
    """
    # Get job state to determine tenant_id if not provided
    if not tenant_id:
        try:
            job_state = get_job_state(job_id)
            tenant_id = job_state.get("tenant_id")
        except ValueError:
            pass
    
    # Determine job directory
    if tenant_id:
        from orchestrator.job_queue import TENANTS_ROOT, _safe_tenant_id
        if not _safe_tenant_id(tenant_id):
            raise ValueError(f"Invalid tenant_id: {tenant_id}")
        job_dir = TENANTS_ROOT / tenant_id / "jobs" / job_id
    else:
        job_dir = JOBS_ROOT / job_id
    
    if not job_dir.exists():
        raise ValueError(f"Job not found: {job_id}")
    
    job_meta = get_job_state(job_id, tenant_id)
    dcs_file = job_dir / "request.dcs"
    
    if not dcs_file.exists():
        update_job_state(job_id, "FAILED", gate=0, tenant_id=tenant_id, error="dcs_file missing")
        return get_job_state(job_id, tenant_id)
    
    # Load .dcs content
    dcs_content = json.loads(dcs_file.read_text(encoding="utf-8", errors="replace"))
    request_id = dcs_content.get("request_id", f"JOB-{job_id}")
    
    # Create isolated request directory within job workspace
    job_requests_dir = get_job_request_dir(job_id, tenant_id)
    request_dir = job_requests_dir / request_id
    
    # Clean up existing request dir if it exists (for re-runs)
    if request_dir.exists():
        import shutil
        shutil.rmtree(request_dir, ignore_errors=True)
    
    request_dir.mkdir(parents=True, exist_ok=True)
    
    # Set up isolated environment
    job_env = os.environ.copy()
    job_env["NLC_JOB_ID"] = job_id
    job_env["NLC_JOB_WORKSPACE"] = str(get_job_workspace(job_id, tenant_id))
    # Ensure job workspace is isolated
    job_env["NLC_ISOLATED"] = "1"
    
    # Patch REQS to use job workspace
    _setup_job_workspace(job_id, tenant_id)
    
    try:
        # Extract request parameters from .dcs
        objective = dcs_content.get("goal", "")
        constraints = dcs_content.get("constraints", [])
        non_goals = dcs_content.get("non_goals", [])
        dod = dcs_content.get("success_criteria", [])
        
        # Gate 0: Init
        update_job_state(job_id, "GATE0", gate=0, tenant_id=tenant_id)
        orch_module.gate0_init(request_id, objective, constraints, non_goals, dod)
        
        # Check gate0 result
        gate0_status_file = request_dir / "gate0.status"
        if gate0_status_file.exists():
            gate0_status = gate0_status_file.read_text(encoding="utf-8").strip()
            if gate0_status in ("BLOCKED", "FAIL"):
                update_job_state(job_id, "BLOCKED", gate=0, tenant_id=tenant_id, reason="gate0_blocked")
                return get_job_state(job_id, tenant_id)
            elif gate0_status == "CLARIFY":
                update_job_state(job_id, "CLARIFY", gate=0, tenant_id=tenant_id, reason="gate0_clarify")
                return get_job_state(job_id, tenant_id)
        
        # Gate 1: Planning
        update_job_state(job_id, "GATE1", gate=1, tenant_id=tenant_id)
        orch_module.gate1_planning(request_id)
        
        gate1_status_file = request_dir / "gate1.status"
        if gate1_status_file.exists():
            gate1_status = gate1_status_file.read_text(encoding="utf-8").strip()
            if gate1_status == "CLARIFY":
                update_job_state(job_id, "CLARIFY", gate=1, tenant_id=tenant_id, reason="gate1_clarify")
                _restore_workspace()
                return get_job_state(job_id, tenant_id)
            elif gate1_status in ("BLOCKED", "FAIL"):
                update_job_state(job_id, "BLOCKED", gate=1, tenant_id=tenant_id, reason="gate1_blocked")
                _restore_workspace()
                return get_job_state(job_id, tenant_id)
        
        # Gate 2: Delegation
        update_job_state(job_id, "GATE2", gate=2, tenant_id=tenant_id)
        orch_module.gate2_delegation(request_id)
        
        # Gate 3: Execution
        update_job_state(job_id, "GATE3", gate=3, tenant_id=tenant_id)
        orch_module.gate3_execution(request_id)
        
        # Gate 4: Review
        update_job_state(job_id, "GATE4", gate=4, tenant_id=tenant_id)
        orch_module.gate4_review(request_id)
        
        # Gate 5: Finalize
        update_job_state(job_id, "GATE5", gate=5, tenant_id=tenant_id)
        orch_module.gate5_finalize(request_id)
        
        # Gate 6: Complete
        update_job_state(job_id, "GATE6", gate=6, tenant_id=tenant_id)
        orch_module.gate6_complete(request_id)
        
        # Check final status
        gate6_status_file = request_dir / "gate6.status"
        if gate6_status_file.exists():
            gate6_status = gate6_status_file.read_text(encoding="utf-8").strip()
            if gate6_status == "PASS":
                update_job_state(job_id, "DONE", gate=6, tenant_id=tenant_id, final_status="PASS")
            else:
                update_job_state(job_id, "FAILED", gate=6, tenant_id=tenant_id, final_status=gate6_status)
        else:
            update_job_state(job_id, "DONE", gate=6, tenant_id=tenant_id, final_status="UNKNOWN")
        
    except Exception as e:
        import traceback
        error_detail = str(e)
        traceback_str = "".join(traceback.format_exc())
        
        # Record error in job state
        update_job_state(
            job_id,
            "FAILED",
            gate=job_meta.get("gate", 0),
            tenant_id=tenant_id,
            error=error_detail,
            traceback=traceback_str,
        )
    finally:
        # Always restore original REQS
        _restore_workspace()
    
    return get_job_state(job_id, tenant_id)


def verify_job_isolation(job_id: str, tenant_id: Optional[str] = None) -> tuple[bool, list[str]]:
    """
    Verify job isolation: no writes outside job workspace.
    
    Args:
        job_id: Job identifier
        tenant_id: Optional tenant identifier for isolation
    
    Returns:
        (is_isolated, violations)
    """
    # Determine job directory
    if tenant_id:
        from orchestrator.job_queue import TENANTS_ROOT, _safe_tenant_id
        if not _safe_tenant_id(tenant_id):
            return (False, [f"Invalid tenant_id: {tenant_id}"])
        job_dir = TENANTS_ROOT / tenant_id / "jobs" / job_id
    else:
        job_dir = JOBS_ROOT / job_id
    
    violations = []
    
    # Check that all request artifacts are under job workspace
    job_workspace = get_job_workspace(job_id, tenant_id)
    requests_dir = get_job_request_dir(job_id, tenant_id)
    
    # All request directories must be under job workspace
    if requests_dir.exists():
        for req_dir in requests_dir.iterdir():
            if req_dir.is_dir():
                # Check that request_dir is not a symlink or outside job workspace
                try:
                    req_dir_real = req_dir.resolve()
                    if not str(req_dir_real).startswith(str(job_workspace.resolve())):
                        violations.append(f"Request dir outside job workspace: {req_dir}")
                except Exception:
                    violations.append(f"Cannot resolve request dir: {req_dir}")
    
    return (len(violations) == 0, violations)

