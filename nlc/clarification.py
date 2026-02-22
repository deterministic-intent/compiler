#!/usr/bin/env python3
"""Clarification artifact generation - Step 3: deterministic ambiguity handling."""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from enum import Enum


class ClarificationReason(str, Enum):
    """Deterministic clarification reason codes."""
    AMBIGUOUS_INTENT = "AMBIGUOUS_INTENT"
    MISSING_REQUIRED_ARG = "MISSING_REQUIRED_ARG"
    TYPE_CONFLICT = "TYPE_CONFLICT"
    UNKNOWN_INTENT = "UNKNOWN_INTENT"
    POLICY_BLOCK = "POLICY_BLOCK"


def create_clarify_artifact(
    request_id: str,
    policy_version: str,
    knowledge_snapshot_id: Optional[str],
    manifest_bundle_hash: Optional[str],
    manifest_hashes: Optional[Dict[str, str]],
    reason: ClarificationReason,
    questions: List[str],
    candidate_intents: List[Dict[str, Any]],
    required_fields: List[str],
    request_dir: Path,
) -> Path:
    """
    Create CLARIFY.json artifact.
    
    Args:
        request_id: Request ID
        policy_version: Policy version
        knowledge_snapshot_id: Snapshot ID (if available)
        manifest_bundle_hash: Manifest bundle hash (if available)
        manifest_hashes: Individual manifest hashes (if bundle hash unavailable)
        reason: Clarification reason code
        questions: Explicit questions to user
        candidate_intents: Candidate intent IDs/names from snapshot manifest only
        required_fields: What must be supplied
        request_dir: Request directory to write CLARIFY.json
    
    Returns:
        Path to CLARIFY.json file
    """
    knowledge_snapshot_id = knowledge_snapshot_id or "unknown_snapshot"
    manifest_bundle_hash = manifest_bundle_hash or "unknown_manifest_bundle_hash"
    
    clarify_data = {
        "request_id": request_id,
        "policy_version": policy_version,
        "knowledge_snapshot_id": knowledge_snapshot_id,
        "manifest_bundle_hash": manifest_bundle_hash,
        "manifest_hashes": manifest_hashes or {},
        "reason": reason.value,
        "reason_codes": [reason.value],
        "questions": questions,
        "candidate_intents": candidate_intents,
        "required_fields": required_fields,
    }
    
    clarify_path = request_dir / "CLARIFY.json"
    clarify_path.write_text(
        json.dumps(clarify_data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )
    
    return clarify_path

