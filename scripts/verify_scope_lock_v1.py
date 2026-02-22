#!/usr/bin/env python3
"""
PR0: Scope lock - reject PRs touching frozen v1 scope.
Ensures key v1 policy files exist and policy loads correctly.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def main() -> int:
    policy_v1 = BASE / "policy" / "policy_v1.json"
    if not policy_v1.exists():
        sys.stderr.write("FAIL scope_lock: policy/policy_v1.json missing\n")
        return 1
    try:
        from policy import load_policy, get_default_policy_version
        p = load_policy("v1")
        if p.policy_version != "v1":
            sys.stderr.write(f"FAIL scope_lock: policy_version != v1 (got {p.policy_version})\n")
            return 1
        if get_default_policy_version() != "v1":
            sys.stderr.write("FAIL scope_lock: default policy version != v1\n")
            return 1
    except Exception as e:
        sys.stderr.write(f"FAIL scope_lock: {e}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
