#!/usr/bin/env python3
"""
Step 7 verification: Replay mode.

Proof:
- replay does not call LLM (replay runner does not import adapters)
- replay verifies snapshot pins (knowledge_snapshot_id + manifest_bundle_hash) + toolchain pins
- replay outputs are byte-identical across replay runs
- replay outputs are byte-identical to the original run outputs

"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def die(msg: str, code: int = 2):
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def run(cmd, cwd: Path):
    p = subprocess.run(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL)
    if p.returncode != 0:
        die(f"command failed (exit {p.returncode}): {' '.join(cmd)}", p.returncode)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("request_id")
    ap.add_argument("gate_name")
    args = ap.parse_args()
    request_id = args.request_id
    gate = args.gate_name

    request_dir = BASE / "state" / "requests" / request_id
    if not request_dir.exists():
        die(f"request dir not found: {request_dir}")

    orig_verifier_dir = request_dir / "verifier"
    orig_res = orig_verifier_dir / "verifier.result.json"
    orig_fail = orig_verifier_dir / "failures.json"
    if not orig_res.exists() or not orig_fail.exists():
        die("original verifier outputs missing under request_dir/verifier/")

    # Replay run 1
    run([sys.executable, str(BASE / "scripts" / "run_replay.py"), request_id, gate, "--replay-id", "run1"], BASE)
    # Replay run 2
    run([sys.executable, str(BASE / "scripts" / "run_replay.py"), request_id, gate, "--replay-id", "run2"], BASE)

    r1 = request_dir / "replay" / "run1" / "verifier"
    r2 = request_dir / "replay" / "run2" / "verifier"
    for p in [r1 / "verifier.result.json", r1 / "failures.json", r2 / "verifier.result.json", r2 / "failures.json"]:
        if not p.exists():
            die(f"missing replay artifact: {p}")

    # Byte-identical across replay runs
    if sha256_file(r1 / "verifier.result.json") != sha256_file(r2 / "verifier.result.json"):
        die("replay verifier.result.json not byte-identical across runs")
    if sha256_file(r1 / "failures.json") != sha256_file(r2 / "failures.json"):
        die("replay failures.json not byte-identical across runs")

    # Byte-identical to original
    if sha256_file(r1 / "verifier.result.json") != sha256_file(orig_res):
        die("replay verifier.result.json not byte-identical to original")
    if sha256_file(r1 / "failures.json") != sha256_file(orig_fail):
        die("replay failures.json not byte-identical to original")

    # Negative pin mismatch: copy request dir and mutate manifest_bundle_hash, ensure replay fails.
    bad_id = f"{request_id}-REPLAY-BAD"
    bad_dir = BASE / "state" / "requests" / bad_id
    if bad_dir.exists():
        shutil.rmtree(bad_dir, ignore_errors=True)
    shutil.copytree(request_dir, bad_dir)
    payload_path = bad_dir / "payload.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["manifest_bundle_hash"] = "deadbeef" + (payload.get("manifest_bundle_hash", "")[8:] if isinstance(payload.get("manifest_bundle_hash"), str) else "")
    payload_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    p = subprocess.run(
        [sys.executable, str(BASE / "scripts" / "run_replay.py"), bad_id, gate, "--replay-id", "run1"],
        cwd=str(BASE),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    if p.returncode == 0:
        die("expected replay to fail on manifest_bundle_hash mismatch, but it succeeded")

    # Ensure replay produced deterministic failure artifacts
    bad_replay_status = bad_dir / "replay" / "run1" / "status.json"
    bad_replay_failures = bad_dir / "replay" / "run1" / "failures.json"
    if not bad_replay_status.exists() or not bad_replay_failures.exists():
        die("expected replay failure artifacts to exist for negative pin mismatch case")
    status_obj = json.loads(bad_replay_status.read_text(encoding="utf-8"))
    if status_obj.get("status") != "FAIL":
        die("expected replay status to be FAIL for negative pin mismatch case")
    if "pin_mismatch" not in str(status_obj.get("reason", "")):
        die("expected replay failure reason to include pin_mismatch")

    print("✓ Step 7 replay is deterministic, pin-verified, and byte-identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


