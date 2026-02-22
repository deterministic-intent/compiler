#!/usr/bin/env python3
"""LLM Parse Adapter - Step 3: Untrusted LLM interface for candidate intent generation."""

import json
import hashlib
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
    prompt: str,
    knowledge_snapshot_id: str,
    manifest_bundle_hash: str,
    policy_version: str,
) -> str:
    """
    Compute cache key for LLM parse results.
    
    Cache key includes:
    - prompt hash
    - knowledge_snapshot_id
    - manifest_bundle_hash
    - policy_version
    """
    prompt_hash = _sha256_bytes(prompt.encode("utf-8"))
    combined = f"{prompt_hash}:{knowledge_snapshot_id}:{manifest_bundle_hash}:{policy_version}"
    return _sha256_bytes(combined.encode("utf-8"))


def build_parse_prompt(
    prompt: str,
    intents_manifest: Dict[str, Any],
    capabilities: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """
    Build parse prompt for LLM.
    
    Returns: (prompt_text, prompt_hash)
    """
    prompt_parts = [
        "Analyze the following user request and propose candidate intents from the available intents.",
        "",
        f"User request: {prompt}",
        "",
        "Available intents:",
    ]
    
    # List available intents from manifest
    for intent_id, intent_data in sorted(intents_manifest.items()):
        name = intent_data.get("name", intent_id)
        prompt_parts.append(f"  - {intent_id}: {name}")
    
    if capabilities:
        supported = capabilities.get("supported_artifact_classes", [])
        if supported:
            prompt_parts.append("")
            prompt_parts.append("Supported artifact classes:")
            for ac in supported:
                prompt_parts.append(f"  - {ac}")
    
    prompt_parts.append("")
    prompt_parts.append("Output a JSON object with 'candidate_intent_set' containing:")
    prompt_parts.append("  - 'candidates': list of {intent_id, args, assumptions, missing, confidence}")
    prompt_parts.append("  - 'needs_clarification': boolean")
    prompt_parts.append("")
    prompt_parts.append("Only propose intents that exist in the available intents list.")
    
    prompt_text = "\n".join(prompt_parts)
    prompt_hash = _sha256_bytes(prompt_text.encode("utf-8"))
    
    return (prompt_text, prompt_hash)


def _call_llm_parse_provider(
    prompt_text: str,
    provider_config: Dict[str, Any],
    max_retries: int,
    timeout_seconds: int,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Call LLM provider for parse (stub or real implementation).
    
    Returns: (response_dict or None, metadata_dict)
    """
    provider_name = provider_config.get("default", "stub")
    
    if provider_name == "stub":
        # Stub provider: return None (will fall back to deterministic parse)
        return (None, {
            "model_name": "stub",
            "error": "stub provider: no LLM call made",
        })
    
    # TODO: Milestone 4.1+ - Implement real LLM provider calls
    # For now, stub provider is the only option
    # When implementing:
    # 1. Support OpenAI, Anthropic, etc. via environment variables
    # 2. Enforce timeout
    # 3. Retry on failures up to max_retries
    # 4. Validate response is valid JSON matching schema
    
    return (None, {
        "model_name": provider_name,
        "error": f"LLM provider '{provider_name}' not yet implemented",
    })


def parse_with_llm(
    prompt: str,
    knowledge_snapshot_id: str,
    manifest_bundle_hash: str,
    policy_version: str,
    intents_manifest: Dict[str, Any],
    capabilities: Optional[Dict[str, Any]] = None,
    cache_dir: Optional[Path] = None,
    repro_mode: bool = False,
    llm_dir: Optional[Path] = None,  # Milestone 4.1: directory for LLM I/O persistence
) -> Dict[str, Any]:
    """
    Parse prompt with LLM to generate candidate intent set.
    
    Args:
        prompt: User prompt text
        knowledge_snapshot_id: Snapshot ID (snapshot-bound)
        manifest_bundle_hash: Manifest bundle hash (snapshot-bound)
        policy_version: Policy version
        intents_manifest: Intents manifest from snapshot (for validation)
        capabilities: Optional capabilities.json (for validation)
        cache_dir: Optional cache directory for results
        repro_mode: If True, refuse LLM calls and require cache
        llm_dir: Directory for LLM I/O persistence (Milestone 4.1)
    
    Returns:
        Dict with:
        - candidate_intent_set: {
            "candidates": [
                {
                    "intent_id": str,
                    "args": dict,
                    "assumptions": list[str],
                    "missing": list[str],
                    "confidence": float (optional)
                }
            ],
            "needs_clarification": bool (optional)
          }
    
    Raises:
        RuntimeError: If repro_mode and cache missing
        ValueError: If LLM output is invalid
    """
    # Milestone 4.1: Persist prompt to llm_dir
    if llm_dir:
        llm_dir.mkdir(parents=True, exist_ok=True)
        prompt_text, prompt_hash = build_parse_prompt(prompt, intents_manifest, capabilities)
        (llm_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
    else:
        prompt_text, prompt_hash = build_parse_prompt(prompt, intents_manifest, capabilities)
    
    # Compute cache key
    cache_key = _compute_cache_key(prompt, knowledge_snapshot_id, manifest_bundle_hash, policy_version)
    
    # Check cache
    if cache_dir:
        cache_path = cache_dir / f"llm_parse_{cache_key}.json"
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                
                # Milestone 4.1: Persist cached response to llm_dir
                if llm_dir:
                    response_json = json.dumps(cached, indent=2, sort_keys=True)
                    (llm_dir / "response.txt").write_text(response_json, encoding="utf-8")
                    (llm_dir / "response.sha256").write_text(
                        _sha256_bytes(response_json.encode("utf-8")),
                        encoding="utf-8"
                    )
                
                return cached
            except Exception as e:
                pass
    
    # Milestone 4.1: In repro mode, refuse LLM calls
    if repro_mode:
        if cache_dir is None:
            raise RuntimeError("repro_mode requires cache_dir for LLM parse results")
        
        cache_path = cache_dir / f"llm_parse_{cache_key}.json"
        if not cache_path.exists():
            raise RuntimeError(
                f"repro_mode: LLM parse cache missing for key {cache_key}. "
                f"Refusing to call LLM. Cache path: {cache_path}"
            )
        
        # Load from cache (already handled above, but this is the explicit error path)
        raise RuntimeError(f"repro_mode: LLM parse cache missing for key {cache_key}")
    
    # Load policy to check LLM retry limits
    retry_limit = 3
    if load_policy:
        try:
            policy = load_policy(policy_version)
            llm_policy = policy.get_llm_policy()
            retry_limit = llm_policy.get("retry_limits", {}).get("parse", 3)
        except Exception:
            pass
    
    # Call LLM provider
    provider_config = {}
    if load_policy:
        try:
            policy = load_policy(policy_version)
            llm_policy = policy.get_llm_policy()
            provider_config = llm_policy.get("providers", {})
        except Exception:
            pass
    
    timeout_seconds = 30
    start_time = time.time()
    response_dict, provider_meta = _call_llm_parse_provider(
        prompt_text, provider_config, retry_limit, timeout_seconds
    )
    latency_ms = int((time.time() - start_time) * 1000)
    
    # Milestone 4.1: Persist response to llm_dir
    if llm_dir and response_dict:
        response_json = json.dumps(response_dict, indent=2, sort_keys=True)
        (llm_dir / "response.txt").write_text(response_json, encoding="utf-8")
        (llm_dir / "response.sha256").write_text(
            _sha256_bytes(response_json.encode("utf-8")),
            encoding="utf-8"
        )
    
    # Validate response against manifest
    if response_dict:
        is_valid, error_msg = validate_llm_output(response_dict, intents_manifest)
        if not is_valid:
            raise ValueError(f"LLM parse output validation failed: {error_msg}")
    
    # Cache result if cache_dir provided
    if cache_dir and response_dict:
        cache_path = cache_dir / f"llm_parse_{cache_key}.json"
        try:
            cache_path.write_text(
                json.dumps(response_dict, indent=2, sort_keys=True) + "\n",
                encoding="utf-8"
            )
        except Exception:
            pass
    
    # Return empty candidate set if LLM not available (fall back to deterministic parse)
    if not response_dict:
        return {
            "candidate_intent_set": {
                "candidates": [],
                "needs_clarification": False,
            }
        }
    
    return response_dict


def validate_llm_output(
    llm_output: Dict[str, Any],
    intents_manifest: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    """
    Validate LLM parse output against snapshot manifest.
    
    Returns:
        (is_valid, error_message)
    """
    if not isinstance(llm_output, dict):
        return False, "LLM output must be a JSON object"
    
    candidate_set = llm_output.get("candidate_intent_set")
    if not isinstance(candidate_set, dict):
        return False, "LLM output missing 'candidate_intent_set'"
    
    candidates = candidate_set.get("candidates", [])
    if not isinstance(candidates, list):
        return False, "'candidates' must be a list"
    
    # Validate each candidate
    valid_intent_ids = set(intents_manifest.keys())
    
    for i, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            return False, f"candidate[{i}] must be a dict"
        
        intent_id = candidate.get("intent_id")
        if not intent_id:
            return False, f"candidate[{i}] missing 'intent_id'"
        
        if intent_id not in valid_intent_ids:
            return False, f"candidate[{i}] intent_id '{intent_id}' not in snapshot manifest"
        
        # Check for implicit assumptions (must be explicit)
        args = candidate.get("args", {})
        assumptions = candidate.get("assumptions", [])
        if not isinstance(assumptions, list):
            return False, f"candidate[{i}] 'assumptions' must be a list"
        
        # All assumptions must be explicit strings
        for j, assumption in enumerate(assumptions):
            if not isinstance(assumption, str):
                return False, f"candidate[{i}] assumptions[{j}] must be a string"
    
    return True, None

