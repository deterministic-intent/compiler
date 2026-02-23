#!/usr/bin/env python3
"""
Milestone 5.1: API v1 - REST API for job queue.

Endpoints:
- POST /v1/jobs - Submit a job
- POST /v1/jobs/{job_id}/run - Run a job
- GET /v1/jobs/{job_id} - Get job status
- GET /v1/jobs/{job_id}/download - Download artifact
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import urlparse, parse_qs

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

# Import job queue modules
from orchestrator.job_queue import submit_job, get_job_state, update_job_state, JOBS_ROOT
from orchestrator.job_runner import run_job


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _get_api_key() -> Optional[str]:
    """Get API key from environment."""
    return os.environ.get("DCS_API_KEY")


def _verify_api_key(request_key: Optional[str]) -> bool:
    """Verify API key against environment secret."""
    expected_key = _get_api_key()
    if not expected_key:
        # No API key configured - allow all (backward compatibility)
        return True
    if not request_key:
        return False
    # Constant-time comparison to prevent timing attacks
    if len(request_key) != len(expected_key):
        return False
    result = 0
    for a, b in zip(request_key.encode("utf-8"), expected_key.encode("utf-8")):
        result |= a ^ b
    return result == 0


def _extract_tenant_id(headers: Dict[str, str]) -> Optional[str]:
    """Extract tenant_id from X-Tenant-ID header."""
    tenant_id = headers.get("X-Tenant-ID", "").strip()
    if not tenant_id:
        return None
    # Validate tenant_id format
    from orchestrator.job_queue import _safe_tenant_id
    if _safe_tenant_id(tenant_id):
        return tenant_id
    return None


def _safe_job_id(job_id: str) -> bool:
    """Validate job_id to prevent path traversal."""
    if not job_id:
        return False
    if ".." in job_id or "/" in job_id or "\\" in job_id:
        return False
    if not job_id.startswith("JOB-"):
        return False
    # Only allow alphanumeric and hyphens after JOB-
    suffix = job_id[4:]
    return suffix.replace("-", "").replace("_", "").isalnum()


def _record_api_request(method: str, path: str, body: bytes, response_code: int, response_body: bytes) -> None:
    """Record API request/response deterministically."""
    api_log_dir = BASE / "state" / "api_logs"
    api_log_dir.mkdir(parents=True, exist_ok=True)
    
    request_hash = _sha256_bytes(f"{method}:{path}:{body}".encode("utf-8"))
    log_entry = {
        "method": method,
        "path": path,
        "request_body_sha256": _sha256_bytes(body),
        "response_code": response_code,
        "response_body_sha256": _sha256_bytes(response_body),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
    }
    
    log_file = api_log_dir / f"{request_hash[:16]}.json"
    log_file.write_text(
        json.dumps(log_entry, indent=2, sort_keys=True) + "\n",
        encoding="utf-8"
    )


class APIHandler(BaseHTTPRequestHandler):
    server_version = "llmhub-api/1.0"
    sys_version = ""
    
    def log_message(self, format, *args):
        """Suppress default logging to prevent secret leakage."""
        return
    
    def _check_auth(self) -> tuple[bool, Optional[str]]:
        """Check API key authentication and extract tenant_id."""
        # Get API key from header
        api_key = self.headers.get("X-API-Key", "").strip()
        if not _verify_api_key(api_key):
            return (False, None)
        
        # Extract tenant_id (headers is HTTPMessage, access directly)
        tenant_id_header = self.headers.get("X-Tenant-ID", "").strip()
        if tenant_id_header:
            from orchestrator.job_queue import _safe_tenant_id
            if _safe_tenant_id(tenant_id_header):
                return (True, tenant_id_header)
        return (True, None)
    
    def _send_json_response(self, code: int, data: Dict[str, Any]) -> bytes:
        """Send JSON response."""
        body = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
        except Exception:
            pass  # Connection may be closed
        return body
    
    def _send_error(self, code: int, message: str) -> bytes:
        """Send error response."""
        return self._send_json_response(code, {"error": message})
    
    def _read_body(self) -> bytes:
        """Read request body."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 10 * 1024 * 1024:  # 10MB limit
            return b""
        return self.rfile.read(content_length)
    
    def do_POST(self):
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_body()
        response_body = b""
        response_code = 500
        
        # Check authentication
        auth_ok, tenant_id = self._check_auth()
        if not auth_ok:
            response_body = self._send_error(401, "Unauthorized: invalid or missing API key")
            response_code = 401
            try:
                _record_api_request(self.command, self.path, body, response_code, response_body)
            except Exception:
                pass
            return
        
        try:
            # POST /v1/jobs
            if path == "/v1/jobs":
                response_body = self._handle_submit_job(body, tenant_id)
                response_code = 201 if response_body else 500
            
            # POST /v1/jobs/{job_id}/run
            elif path.startswith("/v1/jobs/") and path.endswith("/run"):
                job_id = path.split("/")[3]
                if not _safe_job_id(job_id):
                    response_body = self._send_error(400, "Invalid job_id")
                    response_code = 400
                else:
                    response_body = self._handle_run_job(job_id, tenant_id)
                    response_code = 200 if response_body else 500
            
            else:
                response_body = self._send_error(404, "Not found")
                response_code = 404
        
        except Exception as e:
            response_body = self._send_error(500, f"Internal error: {str(e)}")
            response_code = 500
        
        finally:
            try:
                _record_api_request(self.command, self.path, body, response_code, response_body)
            except Exception:
                pass  # Don't fail on logging errors
    
    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        response_body = b""
        response_code = 500
        
        # Check authentication
        auth_ok, tenant_id = self._check_auth()
        if not auth_ok:
            response_body = self._send_error(401, "Unauthorized: invalid or missing API key")
            response_code = 401
            try:
                _record_api_request(self.command, self.path, b"", response_code, response_body)
            except Exception:
                pass
            return
        
        try:
            # GET /v1/jobs/{job_id}
            if path.startswith("/v1/jobs/") and not path.endswith("/download"):
                parts = path.split("/")
                if len(parts) == 4:
                    job_id = parts[3]
                    if not _safe_job_id(job_id):
                        response_body = self._send_error(400, "Invalid job_id")
                        response_code = 400
                    else:
                        response_body = self._handle_get_job_status(job_id, tenant_id)
                        response_code = 200 if response_body else 500
                else:
                    response_body = self._send_error(404, "Not found")
                    response_code = 404
            
            # GET /v1/jobs/{job_id}/download
            elif path.endswith("/download"):
                parts = path.split("/")
                if len(parts) == 5 and parts[3] != "download":
                    job_id = parts[3]
                    if not _safe_job_id(job_id):
                        response_body = self._send_error(400, "Invalid job_id")
                        response_code = 400
                    else:
                        response_body = self._handle_download_artifact(job_id, tenant_id)
                        response_code = 200 if response_body else 500
                else:
                    response_body = self._send_error(404, "Not found")
                    response_code = 404
            
            else:
                response_body = self._send_error(404, "Not found")
                response_code = 404
        
        except Exception as e:
            response_body = self._send_error(500, f"Internal error: {str(e)}")
            response_code = 500
        
        finally:
            try:
                _record_api_request(self.command, self.path, b"", response_code, response_body)
            except Exception:
                pass  # Don't fail on logging errors
    
    def _handle_submit_job(self, body: bytes, tenant_id: Optional[str]) -> bytes:
        """Handle POST /v1/jobs - Submit a job."""
        try:
            data = json.loads(body.decode("utf-8", errors="replace"))
        except Exception:
            return self._send_error(400, "Invalid JSON")
        
        # Override tenant_id from request body if provided
        if "tenant_id" in data:
            request_tenant_id = str(data["tenant_id"]).strip()
            from orchestrator.job_queue import _safe_tenant_id
            if _safe_tenant_id(request_tenant_id):
                tenant_id = request_tenant_id
            else:
                return self._send_error(400, "Invalid tenant_id in request")
        
        # Extract request parameters
        request_text = data.get("request_text", "")
        dcs_content = data.get("dcs_content", "")
        snapshot_id = data.get("snapshot_id", os.environ.get("NLC_DB_SNAPSHOT_ID", "20260103T060637Z"))
        policy_version = data.get("policy_version", "v1")
        
        # Create .dcs content if request_text provided
        if request_text and not dcs_content:
            # For now, create a minimal .dcs structure
            # In production, this would call dcs compile
            dcs_obj = {
                "request_id": f"API-{_sha256_bytes(request_text.encode('utf-8'))[:12].upper()}",
                "artifact_class": "python_cli",
                "goal": request_text,
                "constraints": data.get("constraints", []),
                "non_goals": data.get("non_goals", []),
                "success_criteria": data.get("success_criteria", []),
                "policy_version": policy_version,
                "knowledge_snapshot_id": snapshot_id,
                "manifest_bundle_hash": "api_hash",
                "answer_mode": "index_backed",
            }
            dcs_content = json.dumps(dcs_obj, indent=2, sort_keys=True)
        
        if not dcs_content:
            return self._send_error(400, "Missing request_text or dcs_content")
        
        # Write .dcs file temporarily
        temp_dcs = BASE / "state" / "api_temp" / f"submit_{_sha256_bytes(dcs_content.encode('utf-8'))[:16]}.dcs"
        temp_dcs.parent.mkdir(parents=True, exist_ok=True)
        temp_dcs.write_text(dcs_content, encoding="utf-8")
        
        try:
            job_id = submit_job(temp_dcs, snapshot_id, policy_version, tenant_id)
            return self._send_json_response(201, {"job_id": job_id, "tenant_id": tenant_id})
        except Exception as e:
            return self._send_error(500, f"Failed to submit job: {str(e)}")
    
    def _handle_run_job(self, job_id: str, tenant_id: Optional[str]) -> bytes:
        """Handle POST /v1/jobs/{job_id}/run - Run a job."""
        try:
            result = run_job(job_id, tenant_id)
            return self._send_json_response(200, {
                "job_id": job_id,
                "tenant_id": tenant_id,
                "state": result.get("state", "UNKNOWN"),
                "gate": result.get("gate", 0),
            })
        except ValueError as e:
            return self._send_error(404, f"Job not found: {job_id}")
        except Exception as e:
            return self._send_error(500, f"Failed to run job: {str(e)}")
    
    def _handle_get_job_status(self, job_id: str, tenant_id: Optional[str]) -> bytes:
        """Handle GET /v1/jobs/{job_id} - Get job status."""
        from orchestrator.job_queue import find_job_owner_tenant, get_job_state, TENANTS_ROOT, JOBS_ROOT
        
        # Step 1: Find which tenant owns this job (if any)
        owner_tenant = find_job_owner_tenant(job_id)
        
        # Step 2: Determine response based on ownership and requested tenant
        if owner_tenant is None:
            # Job doesn't exist in any tenant namespace
            # Check global namespace
            from pathlib import Path
            global_job_path = JOBS_ROOT / job_id / "job.json"
            if not global_job_path.exists():
                return self._send_error(404, f"Job not found: {job_id}")
            # Job exists in global namespace (non-tenant job)
            if tenant_id:
                # Request has tenant but job is non-tenant - allow access
                pass
            else:
                # No tenant requested, job is non-tenant - allow access
                pass
        else:
            # Job exists in a tenant namespace
            if tenant_id is None:
                # Request has no tenant but job requires tenant - deny
                return self._send_error(403, "Forbidden: job requires tenant authentication")
            elif tenant_id != owner_tenant:
                # Request tenant doesn't match owner tenant - deny
                return self._send_error(403, "Forbidden: job belongs to different tenant")
            # tenant_id == owner_tenant - proceed
        
        # Step 3: Get job state (now that ownership is verified)
        try:
            if tenant_id:
                job_state = get_job_state(job_id, tenant_id)
            else:
                job_state = get_job_state(job_id, None)
        except ValueError:
            # This should not happen if ownership check was correct, but handle gracefully
            return self._send_error(500, "Internal error: job ownership verification failed")
        
        # Step 4: Get artifact paths (not raw bytes)
        if tenant_id:
            job_dir = TENANTS_ROOT / tenant_id / "jobs" / job_id
        else:
            job_dir = JOBS_ROOT / job_id
        artifact_paths = {}
        
        # Check for dist artifacts
        workspace = job_dir / "workspace"
        if workspace.exists():
            requests_dir = workspace / "requests"
            if requests_dir.exists():
                for req_dir in requests_dir.iterdir():
                    if req_dir.is_dir():
                        dist_dir = req_dir / "dist"
                        if dist_dir.exists():
                            for artifact in dist_dir.glob("*.zip"):
                                artifact_paths[artifact.name] = f"/v1/jobs/{job_id}/download"
        
        return self._send_json_response(200, {
            "job_id": job_id,
            "tenant_id": tenant_id,
            "state": job_state.get("state", "UNKNOWN"),
            "gate": job_state.get("gate", 0),
            "submitted_at": job_state.get("submitted_at"),
            "artifact_paths": artifact_paths,
        })
    
    def _handle_download_artifact(self, job_id: str, tenant_id: Optional[str]) -> bytes:
        """Handle GET /v1/jobs/{job_id}/download - Download artifact."""
        try:
            # Verify tenant access
            job_state = get_job_state(job_id, tenant_id)
            job_tenant_id = job_state.get("tenant_id")
            if tenant_id and job_tenant_id and tenant_id != job_tenant_id:
                return self._send_error(403, "Forbidden: job belongs to different tenant")
            if not tenant_id and job_tenant_id:
                return self._send_error(403, "Forbidden: job requires tenant authentication")
            
            from orchestrator.job_queue import TENANTS_ROOT
            if tenant_id:
                job_dir = TENANTS_ROOT / tenant_id / "jobs" / job_id
            else:
                job_dir = JOBS_ROOT / job_id
            
            if not job_dir.exists():
                return self._send_error(404, f"Job not found: {job_id}")
            
            # Find artifact zip
            workspace = job_dir / "workspace"
            artifact_path = None
            
            if workspace.exists():
                requests_dir = workspace / "requests"
                if requests_dir.exists():
                    for req_dir in requests_dir.iterdir():
                        if req_dir.is_dir():
                            dist_dir = req_dir / "dist"
                            if dist_dir.exists():
                                for artifact in dist_dir.glob("*.zip"):
                                    artifact_path = artifact
                                    break
            
            if not artifact_path or not artifact_path.exists():
                return self._send_error(404, "Artifact not found")
            
            # Stream artifact
            artifact_bytes = artifact_path.read_bytes()
            artifact_hash = _sha256_bytes(artifact_bytes)
            
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(artifact_bytes)))
            self.send_header("Content-Disposition", f'attachment; filename="{artifact_path.name}"')
            self.send_header("X-Artifact-SHA256", artifact_hash)
            self.end_headers()
            self.wfile.write(artifact_bytes)
            
            return artifact_bytes
        
        except ValueError as e:
            return self._send_error(404, f"Job not found: {job_id}")
        except Exception as e:
            return self._send_error(500, f"Failed to download artifact: {str(e)}")


def run_api_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    """Run the API server."""
    server = HTTPServer((host, port), APIHandler)
    print(f"API server running on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down API server...")
        server.shutdown()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LLM-Hub API Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind to")
    args = parser.parse_args()
    run_api_server(args.host, args.port)

