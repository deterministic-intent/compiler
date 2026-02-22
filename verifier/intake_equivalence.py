#!/usr/bin/env python3
"""
Canonical normalization for --intent vs --req equivalence.
Hard fail with INTAKE_EQUIVALENCE_FAIL when they describe different requests.
"""
from __future__ import annotations

import json
from typing import Any


class IntakeEquivalenceError(Exception):
    """Raised when intent and req are not equivalent."""
    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"INTAKE_EQUIVALENCE_FAIL: {path} ({reason})")


def _sort_intent_key(item: dict) -> tuple:
    """Stable sort key for intent objects."""
    return (
        str(item.get("intent_id", "")),
        str(item.get("intent_type", "")),
        str(item.get("artifact_class", "")),
        str(item.get("language", "")),
        json.dumps(item.get("params") or {}, sort_keys=True),
    )


def _normalize_intent_item(item: dict) -> dict:
    """Normalize a single intent object for comparison."""
    out: dict[str, Any] = {}
    for k in sorted(["intent_type", "intent_id", "params", "module_refs", "artifact_class", "language", "io", "description"]):
        if k not in item:
            continue
        v = item[k]
        if k == "params" and isinstance(v, dict):
            out[k] = {str(kk): vv for kk, vv in sorted(v.items())}
        elif k == "module_refs" and isinstance(v, list):
            out[k] = sorted(v) if v else []
        else:
            out[k] = v
    return out


def _to_intents_format(obj: dict) -> dict:
    """Convert flat or intents-array format to canonical intents format."""
    intents = obj.get("intents")
    if isinstance(intents, list) and len(intents) > 0:
        items = [_normalize_intent_item(i) for i in intents]
    else:
        intent_id = str(obj.get("intent_id", "")).strip()
        lang = str(obj.get("language", "")).strip()
        params = obj.get("params")
        if not isinstance(params, dict):
            params = {}
        intent_type = intent_id or "unknown"
        items = [{
            "intent_type": intent_type,
            "intent_id": intent_id,
            "params": params,
            "module_refs": obj.get("module_refs") or [],
            "artifact_class": str(obj.get("artifact_class", "")).strip() or "python_cli",
            "language": lang,
        }]
    items.sort(key=_sort_intent_key)
    return {"schema_version": "req_v1", "intents": items}


def normalize_req(req_obj: dict) -> dict:
    """Produce stable canonical REQ for comparison. Sorted keys, sorted intents."""
    canonical = _to_intents_format(req_obj)
    return canonical


def normalize_intent(intent_obj: dict) -> dict:
    """Produce same canonical format from intent-style (flat) object."""
    return _to_intents_format(intent_obj)


def _json_path_diff(a: dict, b: dict, prefix: str = "") -> str | None:
    """Return first differing key path, or None if equal."""
    if type(a) != type(b):
        return prefix or "root"
    if isinstance(a, dict):
        all_keys = sorted(set(a.keys()) | set(b.keys()))
        for k in all_keys:
            p = f"{prefix}.{k}" if prefix else k
            va = a.get(k)
            vb = b.get(k)
            if va is None and vb is None:
                continue
            diff = _json_path_diff(va, vb, p)
            if diff:
                return diff
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{prefix}[{min(len(a), len(b))}]"
        for i, (ea, eb) in enumerate(zip(a, b)):
            diff = _json_path_diff(ea, eb, f"{prefix}[{i}]")
            if diff:
                return diff
        return None
    if a != b:
        return prefix or "root"
    return None


def assert_equivalent(intent_obj: dict, req_obj: dict) -> None:
    """
    Assert intent and req describe the same normalized request.
    Raises IntakeEquivalenceError with first differing key path on mismatch.
    """
    n_intent = normalize_intent(intent_obj)
    n_req = normalize_req(req_obj)
    a_bytes = json.dumps(n_intent, sort_keys=True, separators=(",", ":")).encode("utf-8")
    b_bytes = json.dumps(n_req, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if a_bytes != b_bytes:
        path = _json_path_diff(n_intent, n_req) or "root"
        raise IntakeEquivalenceError(path, "canonical JSON mismatch")
