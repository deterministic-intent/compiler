#!/usr/bin/env python3
"""
Milestone 5.2: Auth + Permissions - Proof Script.

Proves:
- Unauthorized requests are rejected deterministically (401)
- No leakage across tenants (403 on cross-tenant access)
- Jobs are isolated per tenant namespace

Locked failure tokens (exact):
  FAIL m52:api_key_auth_missing
  FAIL m52:unauthorized_not_rejected
  FAIL m52:cross_tenant_leakage
  FAIL m52:tenant_isolation_violation
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from orchestrator.api_server import APIHandler
from http.server import HTTPServer
from orchestrator.job_queue import submit_job, get_job_state, TENANTS_ROOT, JOBS_ROOT
from orchestrator.job_runner import run_job, verify_job_isolation


def _fail(tok: str) -> None:
    sys.stdout.write(tok.strip() + "\n")
    sys.stdout.flush()
    raise SystemExit(1)


def _run_command(
    cmd: list[str],
    env: Optional[Dict[str, str]] = None,
    allow_fail: bool = False,
    capture_output: bool = True,
) -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    
    p = subprocess.run(
        cmd,
        cwd=str(BASE),
        env=full_env,
        capture_output=capture_output,
        text=True,
        check=False,
    )
    if p.returncode != 0 and not allow_fail:
        print(f"Command failed: {' '.join(cmd)}", file=sys.stderr)
        if capture_output:
            print(f"STDOUT:\n{p.stdout}", file=sys.stderr)
            print(f"STDERR:\n{p.stderr}", file=sys.stderr)
        raise SystemExit(p.returncode)
    return p


def _make_api_request(
    method: str,
    path: str,
    body: Optional[bytes] = None,
    api_key: Optional[str] = None,
    tenant_id: Optional[str] = None,
    port: int = 8888,
) -> tuple[int, bytes]:
    """Make an API request and return (status_code, response_body)."""
    url = f"http://localhost:{port}{path}"
    req = Request(url, data=body, method=method)
    if api_key:
        req.add_header("X-API-Key", api_key)
    if tenant_id:
        req.add_header("X-Tenant-ID", tenant_id)
    req.add_header("Content-Type", "application/json")
    
    try:
        with urlopen(req, timeout=5) as resp:
            return (resp.status, resp.read())
    except HTTPError as e:
        return (e.code, e.read())


def _start_api_server(port: int = 8888, api_key: Optional[str] = None) -> tuple[HTTPServer, threading.Thread]:
    """Start API server in background thread."""
    # Set API key in environment if provided
    old_api_key = os.environ.get("DCS_API_KEY")
    if api_key:
        os.environ["DCS_API_KEY"] = api_key
    elif "DCS_API_KEY" in os.environ:
        del os.environ["DCS_API_KEY"]
    
    server = HTTPServer(("localhost", port), APIHandler)
    
    def run_server():
        try:
            server.serve_forever()
        except Exception:
            pass
    
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    
    # Wait for server to start
    time.sleep(0.5)
    
    return server, thread


def main() -> int:
    env = os.environ.copy()
    env["NLC_POLICY_VERSION"] = "v1"
    snapshot_id = (os.environ.get("DCS_PROOF_SNAPSHOT_ID") or os.environ.get("AUDIT_CLOSURE_SNAPSHOT") or os.environ.get("NLC_DB_SNAPSHOT_ID") or "").strip()
    if not snapshot_id:
        _fail("MISSING_SNAPSHOT_ID: set DCS_PROOF_SNAPSHOT_ID or NLC_DB_SNAPSHOT_ID")
    env["NLC_DB_SNAPSHOT_ID"] = snapshot_id
    env["NLC_SNAPSHOT_ID"] = snapshot_id
    env["NLC_KB_SNAPSHOT_ID"] = snapshot_id

    # Clean up state
    if TENANTS_ROOT.exists():
        shutil.rmtree(TENANTS_ROOT, ignore_errors=True)
    if JOBS_ROOT.exists():
        shutil.rmtree(JOBS_ROOT, ignore_errors=True)
    (BASE / "state" / "api_logs").mkdir(parents=True, exist_ok=True)
    (BASE / "state" / "api_temp").mkdir(parents=True, exist_ok=True)

    # Test 1: Unauthorized requests are rejected (401)
    print("--- Test 1: Unauthorized requests rejected ---")
    api_key = "test-secret-key-12345"
    server, thread = _start_api_server(port=8888, api_key=api_key)
    
    try:
        # Request without API key
        status, body = _make_api_request("GET", "/v1/jobs/JOB-TEST123", api_key=None)
        if status != 401:
            _fail(f"FAIL m52:unauthorized_not_rejected: Expected 401, got {status}")
        
        # Request with wrong API key
        status, body = _make_api_request("GET", "/v1/jobs/JOB-TEST123", api_key="wrong-key")
        if status != 401:
            _fail(f"FAIL m52:unauthorized_not_rejected: Expected 401 with wrong key, got {status}")
        
        print("✓ Unauthorized requests correctly rejected")
    finally:
        server.shutdown()
        thread.join(timeout=1)

    # Test 2: Tenant isolation - no cross-tenant access
    print("\n--- Test 2: Tenant isolation (no cross-tenant access) ---")
    tenant_a = "tenant-a"
    tenant_b = "tenant-b"
    
    # Create a job for tenant_a
    sample_dcs = {
        "request_id": "M52-TEST-A",
        "artifact_class": "python_cli",
        "goal": "Make a CLI that prints hello",
        "constraints": [],
        "non_goals": [],
        "success_criteria": [],
        "policy_version": env["NLC_POLICY_VERSION"],
        "knowledge_snapshot_id": env["NLC_DB_SNAPSHOT_ID"],
        "manifest_bundle_hash": "test_hash",
        "answer_mode": "index_backed",
    }
    dcs_file_a = BASE / "state" / "api_temp" / "test_tenant_a.dcs"
    dcs_file_a.parent.mkdir(parents=True, exist_ok=True)
    dcs_file_a.write_text(json.dumps(sample_dcs, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    
    job_id_a = submit_job(dcs_file_a, env["NLC_DB_SNAPSHOT_ID"], env["NLC_POLICY_VERSION"], tenant_id=tenant_a)
    print(f"Created job {job_id_a} for tenant {tenant_a}")
    
    # Verify job is in tenant namespace
    job_dir_a = TENANTS_ROOT / tenant_a / "jobs" / job_id_a
    if not job_dir_a.exists():
        _fail(f"FAIL m52:tenant_isolation_violation: Job {job_id_a} not in tenant namespace")
    
    # Start API server with auth
    server, thread = _start_api_server(port=8889, api_key=api_key)
    
    try:
        # Try to access tenant_a's job as tenant_b (should fail with 403)
        status, body = _make_api_request(
            "GET", f"/v1/jobs/{job_id_a}", api_key=api_key, tenant_id=tenant_b, port=8889
        )
        if status != 403:
            _fail(f"FAIL m52:cross_tenant_leakage: Expected 403 for cross-tenant access, got {status}")
        
        # Test 2d: Correct tenant access → 200
        status, body = _make_api_request(
            "GET", f"/v1/jobs/{job_id_a}", api_key=api_key, tenant_id=tenant_a, port=8889
        )
        if status != 200:
            _fail(f"FAIL m52:tenant_isolation_violation: Expected 200 for same-tenant access, got {status}")
        
        print("✓ Tenant isolation verified (no cross-tenant access)")
    finally:
        server.shutdown()
        thread.join(timeout=1)

    # Test 3: Verify jobs are isolated per tenant namespace
    print("\n--- Test 3: Jobs isolated per tenant namespace ---")
    
    # Create jobs for two different tenants
    dcs_file_b = BASE / "state" / "api_temp" / "test_tenant_b.dcs"
    sample_dcs_b = sample_dcs.copy()
    sample_dcs_b["request_id"] = "M52-TEST-B"
    dcs_file_b.write_text(json.dumps(sample_dcs_b, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    
    job_id_b = submit_job(dcs_file_b, env["NLC_DB_SNAPSHOT_ID"], env["NLC_POLICY_VERSION"], tenant_id=tenant_b)
    print(f"Created job {job_id_b} for tenant {tenant_b}")
    
    # Verify jobs are in separate namespaces
    job_dir_b = TENANTS_ROOT / tenant_b / "jobs" / job_id_b
    if not job_dir_b.exists():
        _fail(f"FAIL m52:tenant_isolation_violation: Job {job_id_b} not in tenant namespace")
    
    # Verify job_id_a is NOT in tenant_b namespace
    if (TENANTS_ROOT / tenant_b / "jobs" / job_id_a).exists():
        _fail(f"FAIL m52:tenant_isolation_violation: Job {job_id_a} found in wrong tenant namespace")
    
    # Verify job_id_b is NOT in tenant_a namespace
    if (TENANTS_ROOT / tenant_a / "jobs" / job_id_b).exists():
        _fail(f"FAIL m52:tenant_isolation_violation: Job {job_id_b} found in wrong tenant namespace")
    
    # Verify isolation using verify_job_isolation
    is_isolated_a, violations_a = verify_job_isolation(job_id_a, tenant_a)
    if not is_isolated_a:
        _fail(f"FAIL m52:tenant_isolation_violation: Job {job_id_a} isolation check failed: {violations_a}")
    
    is_isolated_b, violations_b = verify_job_isolation(job_id_b, tenant_b)
    if not is_isolated_b:
        _fail(f"FAIL m52:tenant_isolation_violation: Job {job_id_b} isolation check failed: {violations_b}")
    
    print("✓ Jobs are isolated per tenant namespace")

    # Test 4: API key from environment (backward compatibility)
    print("\n--- Test 4: API key from environment ---")
    
    # Start server without API key (should allow all - backward compatibility)
    if "DCS_API_KEY" in os.environ:
        del os.environ["DCS_API_KEY"]
    
    server, thread = _start_api_server(port=8890, api_key=None)
    
    try:
        # Request without API key should succeed (backward compatibility)
        status, body = _make_api_request("GET", "/v1/jobs/JOB-TEST123", api_key=None, port=8890)
        # Should get 404 (job not found) or 200, not 401
        if status == 401:
            _fail("FAIL m52:api_key_auth_missing: API key required when DCS_API_KEY not set (backward compatibility broken)")
        
        print("✓ Backward compatibility maintained (no API key required when DCS_API_KEY not set)")
    finally:
        server.shutdown()
        thread.join(timeout=1)

    sys.stdout.write("✓ Milestone 5.2 proof: Auth + permissions are deterministic and tenant-isolated\n")
    sys.stdout.write("M52_PROOF_OK\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Milestone 5.2: Auth + Permissions - Proof Script")
    args = parser.parse_args()
    raise SystemExit(main())

