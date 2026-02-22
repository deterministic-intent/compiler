#!/usr/bin/env python3
"""
Schema validation for IR (payload) and REQ. Hard fail on unknown fields or missing required.
Deterministic error codes: IR_SCHEMA_INVALID, REQ_SCHEMA_INVALID.
"""
from __future__ import annotations

from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SCHEMAS = BASE / "schemas"

# IR v1
IR_SCHEMA_VERSION = "ir_v1"
IR_V1_REQUIRED = frozenset({"schema_version", "request_id", "policy_version", "deliverables"})
IR_V1_ALLOWED = frozenset({
    "schema_version", "request_id", "policy_version", "deliverables",
    "goal", "artifact_class", "artifact_class_definition", "knowledge_snapshot_id",
    "manifest_bundle_hash", "req_sha256", "module_refs", "inputs", "constraints",
    "non_goals", "success_criteria", "tooling", "files", "entrypoint", "runtime_args", "answer_mode",
    "external_snapshot_id", "external_sources_required", "answer_queries",
})

# REQ v1
REQ_SCHEMA_VERSION = "req_v1"
REQ_V1_REQUIRED = frozenset({"schema_version", "intents"})
REQ_V1_ALLOWED = frozenset({"schema_version", "kind", "intents"})
REQ_INTENT_REQUIRED = frozenset({"intent_type", "params"})
REQ_INTENT_ALLOWED = frozenset({
    "intent_type", "intent_id", "params", "module_refs", "artifact_class", "language",
    "io", "description",
})


class SchemaValidationError(Exception):
    """Raised when schema validation fails."""
    def __init__(self, code: str, reason: str):
        self.code = code
        self.reason = reason
        super().__init__(f"{code}: {reason}")


def validate_ir(ir_obj: dict) -> None:
    """
    Validate payload (IR) against ir_v1. Hard fail on invalid.
    Raises SchemaValidationError with IR_SCHEMA_INVALID.
    """
    if not isinstance(ir_obj, dict):
        raise SchemaValidationError("IR_SCHEMA_INVALID", "IR must be a JSON object")

    # Reject unknown top-level keys
    unknown = set(ir_obj.keys()) - IR_V1_ALLOWED
    if unknown:
        raise SchemaValidationError("IR_SCHEMA_INVALID", f"unknown keys: {sorted(unknown)}")

    # Require schema_version
    version = ir_obj.get("schema_version")
    if not version or str(version).strip() != "ir_v1":
        raise SchemaValidationError("IR_SCHEMA_INVALID", "schema_version must be 'ir_v1'")

    # Require other keys
    missing = IR_V1_REQUIRED - set(ir_obj.keys())
    if missing:
        raise SchemaValidationError("IR_SCHEMA_INVALID", f"missing required: {sorted(missing)}")

    # deliverables must be array
    d = ir_obj.get("deliverables")
    if not isinstance(d, list):
        raise SchemaValidationError("IR_SCHEMA_INVALID", "deliverables must be an array")


def validate_req(req_obj: dict) -> None:
    """
    Validate REQ.json against req_v1. Hard fail on invalid.
    Raises SchemaValidationError with REQ_SCHEMA_INVALID.
    """
    if not isinstance(req_obj, dict):
        raise SchemaValidationError("REQ_SCHEMA_INVALID", "REQ must be a JSON object")

    unknown = set(req_obj.keys()) - REQ_V1_ALLOWED
    if unknown:
        raise SchemaValidationError("REQ_SCHEMA_INVALID", f"unknown keys: {sorted(unknown)}")

    version = req_obj.get("schema_version")
    if not version or str(version).strip() != "req_v1":
        raise SchemaValidationError("REQ_SCHEMA_INVALID", "schema_version must be 'req_v1'")

    missing = REQ_V1_REQUIRED - set(req_obj.keys())
    if missing:
        raise SchemaValidationError("REQ_SCHEMA_INVALID", f"missing required: {sorted(missing)}")

    intents = req_obj.get("intents")
    if not isinstance(intents, list):
        raise SchemaValidationError("REQ_SCHEMA_INVALID", "intents must be an array")
    if len(intents) == 0:
        raise SchemaValidationError("REQ_SCHEMA_INVALID", "intents array must not be empty")

    for i, intent in enumerate(intents):
        if not isinstance(intent, dict):
            raise SchemaValidationError("REQ_SCHEMA_INVALID", f"intent[{i}] must be object")
        uk = set(intent.keys()) - REQ_INTENT_ALLOWED
        if uk:
            raise SchemaValidationError("REQ_SCHEMA_INVALID", f"intent[{i}] unknown keys: {sorted(uk)}")
        miss = REQ_INTENT_REQUIRED - set(intent.keys())
        if miss:
            raise SchemaValidationError("REQ_SCHEMA_INVALID", f"intent[{i}] missing: {sorted(miss)}")


