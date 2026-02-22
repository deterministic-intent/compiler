#!/usr/bin/env python3
"""Smoke: test_v1_intent_req_equivalence. Verifies normalize/assert_equivalent logic."""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def main() -> int:
    from verifier.intake_equivalence import (
        normalize_req,
        normalize_intent,
        assert_equivalent,
        IntakeEquivalenceError,
    )
    intent_flat = {
        "kind": "REQ",
        "intent_id": "print_sequence",
        "language": "python",
        "params": {"from": 1, "to": 5, "step": 1},
        "module_refs": [],
        "artifact_class": "python_cli",
    }
    req_intents = {
        "schema_version": "req_v1",
        "intents": [{
            "intent_type": "print_sequence",
            "intent_id": "print_sequence",
            "params": {"from": 1, "to": 5, "step": 1},
            "module_refs": [],
            "artifact_class": "python_cli",
            "language": "python",
        }],
    }
    assert_equivalent(intent_flat, req_intents)
    n1 = normalize_intent(intent_flat)
    n2 = normalize_req(req_intents)
    assert n1 == n2
    try:
        bad_req = {**req_intents, "intents": [{**req_intents["intents"][0], "params": {"from": 2}}]}
        assert_equivalent(intent_flat, bad_req)
    except IntakeEquivalenceError as e:
        assert "params" in str(e).lower() or "root" in str(e).lower()
    else:
        sys.stderr.write("expected IntakeEquivalenceError for mismatch\n")
        return 1
    print("test_v1_intent_req_equivalence: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
