#!/usr/bin/env python3
"""
Aggregate per_req_hashes.json into proof_hashes.json (contract only).
Input: per_req_hashes.json only. No repo/env inspection.
Output: DIST_SHA256, VALIDATION_HASHES_SHA256, PROOF_BUNDLE_SHA256, PER_REQ, COMPOSITE_SHA256.
COMPOSITE_SHA256 = SHA256 of canonical JSON bytes of PER_REQ map (sorted keys, stable ordering).
"""
import hashlib
import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: aggregate_golden_suite.py <per_req_hashes.json>\n")
        return 2
    p = Path(sys.argv[1])
    if not p.exists():
        sys.stderr.write(f"FAIL: {p} not found\n")
        return 2

    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        sys.stderr.write("FAIL: per_req_hashes must be a JSON object\n")
        return 2

    # Canonical serializer: identical for rollups and PER_REQ (no newline, no stray whitespace)
    def _canon(obj) -> str:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"))

    # Suite-wide aggregates: deterministic across all REQs (no "first REQ")
    def _agg_sha(items: list) -> str:
        return hashlib.sha256(_canon(sorted(items)).encode("utf-8")).hexdigest()

    dist_list = []
    pb_list = []
    vh_list = []
    for req_id in sorted(data.keys()):
        rec = data.get(req_id) if isinstance(data.get(req_id), dict) else {}
        d = rec.get("dist_sha256", "")
        pb = rec.get("proof_bundle_sha256", "")
        v = rec.get("validation_sha256", "")
        if d and pb:
            dist_list.append([req_id, d])
            pb_list.append([req_id, pb])
            vh_list.append([req_id, v])

    if not dist_list:
        sys.stderr.write("FAIL: no REQ with both dist_sha256 and proof_bundle_sha256\n")
        return 2

    # Composite: SHA256 of canonical JSON of PER_REQ only (same serializer as rollups)
    composite_sha = hashlib.sha256(_canon(data).encode("utf-8")).hexdigest()

    out = {
        "COMPOSITE_SHA256": composite_sha,
        "DIST_SHA256": _agg_sha(dist_list),
        "PER_REQ": data,
        "PROOF_BUNDLE_SHA256": _agg_sha(pb_list),
        "VALIDATION_HASHES_SHA256": _agg_sha(vh_list),
    }

    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
