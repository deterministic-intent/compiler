#!/usr/bin/env python3
"""LLM Patch Adapter - Milestone 4.0: Untrusted LLM interface for patch proposal generation (diff-only)."""

from __future__ import annotations

import json
import hashlib
import os
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# Policy loader
try:
    from policy import load_policy, get_default_policy_version
except ImportError:
    load_policy = None
    get_default_policy_version = None


def _sha256_bytes(b: bytes) -> str:
    """Compute SHA256 hash."""
    return hashlib.sha256(b).hexdigest()


def _compute_cache_key(
    request_id: str,
    iter_n: int,
    knowledge_snapshot_id: str,
    manifest_bundle_hash: str,
    policy_version: str,
    failure_bundle_hash: str,
    prompt_hash: str,
) -> str:
    """
    Compute cache key for LLM patch proposal.
    
    Cache key includes:
    - request_id
    - iter_n
    - knowledge_snapshot_id
    - manifest_bundle_hash
    - policy_version
    - failure_bundle_hash
    - prompt_hash
    """
    combined = f"{request_id}:{iter_n}:{knowledge_snapshot_id}:{manifest_bundle_hash}:{policy_version}:{failure_bundle_hash}:{prompt_hash}"
    return _sha256_bytes(combined.encode("utf-8"))


def build_repair_prompt(
    failures: List[Dict[str, Any]],
    workspace_context: Dict[str, str],  # file_path -> content (limited by max_context_bytes)
    policy_version: str,
    knowledge_snapshot_id: Optional[str],
    manifest_bundle_hash: Optional[str],
) -> Tuple[str, str]:
    """
    Build repair prompt for LLM.
    
    Returns: (prompt_text, prompt_hash)
    """
    # Build prompt from failures and minimal context
    prompt_parts = [
        "Generate a unified diff to fix the following failures:",
        "",
    ]
    
    for i, failure in enumerate(failures, 1):
        prompt_parts.append(f"Failure {i}:")
        prompt_parts.append(f"  Kind: {failure.get('kind', 'unknown')}")
        prompt_parts.append(f"  Artifact: {failure.get('artifact', 'unknown')}")
        prompt_parts.append(f"  Message: {failure.get('message', '')}")
        if failure.get('locator'):
            prompt_parts.append(f"  Location: {failure.get('locator', '')}")
        prompt_parts.append("")
    
    prompt_parts.append("Relevant file context:")
    for file_path, content in sorted(workspace_context.items()):
        prompt_parts.append(f"--- {file_path}")
        prompt_parts.append(content[:500])  # Limit context
        prompt_parts.append("")
    
    prompt_parts.append("Output ONLY a unified diff. No explanations, no markdown, just the diff.")
    
    prompt_text = "\n".join(prompt_parts)
    prompt_hash = _sha256_bytes(prompt_text.encode("utf-8"))
    
    return (prompt_text, prompt_hash)


def _call_llm_provider(
    prompt_text: str,
    provider_config: Dict[str, Any],
    max_retries: int,
    timeout_seconds: int,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Call LLM provider (stub or real implementation).
    
    Returns: (response_text or None, metadata_dict)
    """
    provider_name = provider_config.get("default", "stub")
    
    if provider_name == "stub":
        # Stub provider: return None (will fall back to stub mode if proposal.diff exists)
        return (None, {
            "model_name": "stub",
            "error": "stub provider: no LLM call made",
        })
    
    # TODO: Milestone 4.0+ - Implement real LLM provider calls
    # For now, stub provider is the only option
    # When implementing:
    # 1. Support OpenAI, Anthropic, etc. via environment variables
    # 2. Enforce timeout
    # 3. Retry on failures up to max_retries
    # 4. Validate response is unified diff format
    
    return (None, {
        "model_name": provider_name,
        "error": f"LLM provider '{provider_name}' not yet implemented",
    })


def propose_patch(
    request_id: str,
    iter_n: int,
    failures: List[Dict[str, Any]],
    workspace_context: Dict[str, str],
    knowledge_snapshot_id: str,
    manifest_bundle_hash: str,
    policy_version: str,
    failure_bundle_hash: str,
    cache_dir: Optional[Path] = None,
    repro_mode: bool = False,
    llm_dir: Optional[Path] = None,  # Milestone 4.0: directory for LLM I/O persistence
) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Propose patch via LLM (or cache).
    
    Args:
        request_id: Request ID
        iter_n: Iteration number
        failures: Canonical failures list
        workspace_context: Limited file context (path -> content)
        knowledge_snapshot_id: Snapshot ID
        manifest_bundle_hash: Manifest bundle hash
        policy_version: Policy version
        failure_bundle_hash: Failure bundle hash
        cache_dir: Optional cache directory
        repro_mode: If True, refuse LLM calls and require cache
        llm_dir: Directory for LLM I/O persistence (Milestone 4.0)
    
    Returns:
        (diff_text or None, metadata_dict)
        metadata includes: cache_hit, model_name, latency, retry_count, etc.
    """
    # Load policy
    if not load_policy:
        return (None, {"error": "Policy module unavailable"})
    
    try:
        policy = load_policy(policy_version)
        llm_policy = policy.get_llm_policy()
        repair_config = llm_policy.get("repair", {})
    except Exception as e:
        return (None, {"error": f"Failed to load policy: {e}"})
    
    # Check if LLM repair is enabled
    if not repair_config.get("enabled", False):
        return (None, {"error": "LLM repair disabled by policy"})
    
    # Build prompt
    prompt_text, prompt_hash = build_repair_prompt(
        failures, workspace_context, policy_version, knowledge_snapshot_id, manifest_bundle_hash
    )
    
    # Milestone 4.0: Persist prompt to llm_dir
    if llm_dir:
        llm_dir.mkdir(parents=True, exist_ok=True)
        (llm_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
    
    # Compute cache key
    cache_key = _compute_cache_key(
        request_id, iter_n, knowledge_snapshot_id, manifest_bundle_hash,
        policy_version, failure_bundle_hash, prompt_hash
    )
    
    # Check cache
    if cache_dir:
        cache_path = cache_dir / f"llm_patch_{cache_key}.json"
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                diff_text = cached.get("diff_text")
                
                # Milestone 4.0: Persist cached response to llm_dir
                if llm_dir and diff_text:
                    (llm_dir / "response.txt").write_text(diff_text, encoding="utf-8")
                    (llm_dir / "response.sha256").write_text(
                        _sha256_bytes(diff_text.encode("utf-8")),
                        encoding="utf-8"
                    )
                
                return (diff_text, {
                    "cache_hit": True,
                    "cache_key": cache_key,
                    "prompt_hash": prompt_hash,
                })
            except Exception as e:
                pass
    
    # Replay mode: refuse LLM calls
    if repro_mode:
        if repair_config.get("cache_required_in_replay", True):
            return (None, {
                "error": "repro_mode: LLM patch cache missing",
                "cache_key": cache_key,
                "cache_path": str(cache_path) if cache_dir else None,
            })
    
    # Call LLM provider
    provider_config = llm_policy.get("providers", {})
    max_retries = repair_config.get("max_retries", 3)
    timeout_seconds = repair_config.get("timeout_seconds", 30)
    
    start_time = time.time()
    response_text, provider_meta = _call_llm_provider(
        prompt_text, provider_config, max_retries, timeout_seconds
    )
    latency_ms = int((time.time() - start_time) * 1000)
    
    # Milestone 4.0: Persist response to llm_dir
    if llm_dir and response_text:
        (llm_dir / "response.txt").write_text(response_text, encoding="utf-8")
        (llm_dir / "response.sha256").write_text(
            _sha256_bytes(response_text.encode("utf-8")),
            encoding="utf-8"
        )
    
    # Validate response is unified diff
    if response_text:
        is_valid, error_msg = validate_llm_diff_output(response_text)
        if not is_valid:
            return (None, {
                "error": f"LLM output validation failed: {error_msg}",
                "cache_key": cache_key,
                "prompt_hash": prompt_hash,
            })
    
    # Cache result if cache_dir provided
    if cache_dir and response_text:
        cache_path = cache_dir / f"llm_patch_{cache_key}.json"
        try:
            cache_path.write_text(
                json.dumps({
                    "diff_text": response_text,
                    "prompt_hash": prompt_hash,
                    "cache_key": cache_key,
                }, indent=2, sort_keys=True) + "\n",
                encoding="utf-8"
            )
        except Exception:
            pass
    
    return (response_text, {
        "cache_hit": False,
        "cache_key": cache_key,
        "prompt_hash": prompt_hash,
        "model_name": provider_meta.get("model_name", "unknown"),
        "latency_ms": latency_ms,
        "retry_count": provider_meta.get("retry_count", 0),
        "error": provider_meta.get("error"),
    })


def validate_llm_diff_output(llm_output: str) -> Tuple[bool, Optional[str]]:
    """
    Validate LLM output is a unified diff.
    
    Returns: (is_valid, error_message)
    """
    if not llm_output or not llm_output.strip():
        return (False, "Empty output")
    
    lines = llm_output.splitlines()
    
    # Must start with --- or +++ (unified diff format)
    found_header = False
    for line in lines[:10]:  # Check first 10 lines
        if line.startswith("--- ") or line.startswith("+++ "):
            found_header = True
            break
    
    if not found_header:
        return (False, "Not a unified diff format (missing --- or +++ header)")
    
    # Basic validation: should have at least one hunk
    has_hunk = any(line.startswith("@@") for line in lines)
    if not has_hunk:
        return (False, "No diff hunks found")
    
    return (True, None)
