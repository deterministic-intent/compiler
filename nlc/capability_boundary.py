#!/usr/bin/env python3
"""Capability Boundary - Defines and validates the finite set of supported intents."""
import json
from pathlib import Path
from typing import Dict, Any, List, Set, Optional
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parents[1]
EMITTERS_DIR = BASE / "orchestrator" / "intent_emitters"


def get_supported_intents() -> Set[str]:
    """Get set of all supported intent types."""
    intents = set()
    
    if not EMITTERS_DIR.exists():
        return intents
    
    for emitter_file in EMITTERS_DIR.glob("*.json"):
        if emitter_file.name == "index.json":
            continue
        
        try:
            emitter = json.loads(emitter_file.read_text())
            intent_type = emitter.get("intent_type")
            if intent_type:
                intents.add(intent_type)
        except:
            pass
    
    return intents


def validate_req_json(req_json: Dict[str, Any]) -> tuple[bool, Optional[str], List[str]]:
    """Validate REQ.json against capability boundary."""
    if "intents" not in req_json:
        return False, "REQ.json missing 'intents' field", []
    
    intents = req_json.get("intents", [])
    if not isinstance(intents, list) or len(intents) == 0:
        return False, "REQ.json 'intents' must be a non-empty array", []
    
    supported = get_supported_intents()
    unsupported = []
    
    for intent in intents:
        if not isinstance(intent, dict):
            return False, f"Intent must be an object, got {type(intent)}", []
        
        intent_type = intent.get("intent_type")
        if not intent_type:
            return False, "Intent missing 'intent_type' field", []
        
        if intent_type not in supported:
            unsupported.append(intent_type)
    
    if unsupported:
        supported_list = ", ".join(sorted(supported))
        error_msg = f"Unsupported intent types: {', '.join(unsupported)}. Supported: {supported_list}"
        return False, error_msg, unsupported
    
    return True, None, []


def generate_blocked_report(request_id: str, prompt: str, unsupported_intents: List[str], supported_intents: Set[str], matched_keywords: Optional[List[str]] = None) -> Dict[str, Any]:
    """Generate structured blocked report for unsupported prompts."""
    import hashlib
    
    # Generate deterministic hash for blocked report
    report_data = {
        "reason_code": "UNSUPPORTED_INTENT",
        "prompt": prompt,
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"
    }
    report_str = json.dumps(report_data, sort_keys=True)
    deterministic_hash = hashlib.sha256(report_str.encode()).hexdigest()[:16]
    
    # Determine next action (suggest first unsupported intent to add)
    next_action = None
    if unsupported_intents:
        first_unsupported = unsupported_intents[0]
        next_action = f"add intent emitter: {first_unsupported}"
    
    return {
        "status": "BLOCKED",
        "reason_code": "UNSUPPORTED_INTENT",
        "request_id": request_id,
        "prompt": prompt,
        "matched_keywords": matched_keywords or [],
        "unsupported_intents": unsupported_intents,
        "supported_intents": sorted(list(supported_intents)),
        "next_action": next_action,
        "deterministic_hash": deterministic_hash,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
        "message": f"Prompt requires unsupported intent types: {', '.join(unsupported_intents)}"
    }
