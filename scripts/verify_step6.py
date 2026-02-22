#!/usr/bin/env python3
"""
Step 6 verification: Contract enforcement produces canonical failures and is deterministic.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))


def die(msg: str, code: int = 2):
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("request_id")
    ap.add_argument("gate_name")
    args = ap.parse_args()

    src_request_id = args.request_id
    gate = args.gate_name
    if not gate.startswith("gate"):
        die("gate_name must look like gate3_execution")

    src_dir = BASE / "state" / "requests" / src_request_id
    if not src_dir.exists():
        die(f"Request directory not found: {src_dir}")

    # Copy to an isolated request so we can inject a deterministic contract violation.
    dst_request_id = f"{src_request_id}-STEP6"
    dst_dir = BASE / "state" / "requests" / dst_request_id
    if dst_dir.exists():
        shutil.rmtree(dst_dir, ignore_errors=True)
    shutil.copytree(src_dir, dst_dir)

    payload_path = dst_dir / "payload.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    deliverables = payload.get("deliverables")
    if not isinstance(deliverables, list):
        deliverables = []
        payload["deliverables"] = deliverables

    # Inject a missing deliverable path to force contract failure.
    missing_name = "MISSING_CONTRACT_DELIVERABLE.txt"
    if not any(isinstance(d, dict) and d.get("path") == missing_name for d in deliverables):
        deliverables.append({"path": missing_name, "format": "text"})
    payload_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # Ensure the file is actually missing.
    missing_path = dst_dir / missing_name
    if missing_path.exists():
        missing_path.unlink()

    from workers.run_verifier import verify_gate

    # Run twice to prove determinism (failures.json byte-identical).
    out1 = verify_gate(dst_request_id, gate, dst_dir)
    out2 = verify_gate(dst_request_id, gate, dst_dir)
    status1, _text1, failures1 = out1
    status2, _text2, failures2 = out2

    if status1 != "FAIL" or status2 != "FAIL":
        die(f"Expected FAIL/FAIL, got {status1}/{status2}")

    # Check for canonical contract failure kind + repro token.
    def _has_contract_failure(failures):
        for f in failures:
            if f.get("kind") == "contract_violation" and f.get("repro") == "contract:deliverables_exist":
                return True
        return False

    if not _has_contract_failure(failures1):
        die("Expected contract_violation with repro contract:deliverables_exist in failures")

    # Byte-identical determinism proof for canonical failures JSON
    b1 = json.dumps({"failures": failures1}, indent=2, sort_keys=True).encode("utf-8")
    b2 = json.dumps({"failures": failures2}, indent=2, sort_keys=True).encode("utf-8")
    if b1 != b2:
        die("FAIL: contract failures not deterministic (bytes differ)")

    print("✓ Step 6 contract checker emits canonical failures and is deterministic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


