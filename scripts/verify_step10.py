#!/usr/bin/env python3
"""
Step 10 verification: Snapshot resolution & precedence.

Proof:
1) Create request with external + knowledge snapshot
2) Run gate1 to force resolver output
3) Verify snapshot_resolution.json bytes are stable across runs and in replay
4) Inject conflict and assert deterministic FAIL (snapshot_violation)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def die(msg: str, code: int = 2):
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def run(cmd, env=None, allow_fail: bool = False):
    p = subprocess.run(cmd, cwd=str(BASE), env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if not allow_fail and p.returncode != 0:
        die(f"command failed (exit {p.returncode}): {' '.join(cmd)}\nSTDERR:\n{p.stderr}\nSTDOUT:\n{p.stdout}", p.returncode)
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request-id", default="STEP10-AUDIT")
    ap.add_argument("--external-snapshot-id", default="STEP10-EXT-AUDIT")
    ap.add_argument("--knowledge-snapshot-id", default=os.environ.get("DCS_PROOF_SNAPSHOT_ID", "20260103T060637Z"))
    ap.add_argument("--policy", default="v1")
    ap.add_argument("--requests-root", help="Requests dir (default: BASE/state/requests)")
    args = ap.parse_args()

    req_id = args.request_id
    ext_id = args.external_snapshot_id
    know_id = args.knowledge_snapshot_id or os.environ.get("AUDIT_CLOSURE_SNAPSHOT", "20260103T060637Z")
    policy = args.policy
    req_root = Path(args.requests_root) if args.requests_root else BASE / "state" / "requests"

    req_dir = req_root / req_id
    if req_dir.exists():
        shutil.rmtree(req_dir, ignore_errors=True)

    # Ensure external snapshot exists (minimal raw snapshot via writer; no network).
    from nlc.external_snapshot import write_external_source, try_load_toolchain_pins
    pins = try_load_toolchain_pins()
    write_external_source(
        snapshot_id=ext_id,
        policy_version=policy,
        toolchain_pins=pins,
        source_id="step10://source",
        content_type="application/octet-stream",
        fetch_timestamp="1970-01-01T00:00:00Z",
        raw_bytes=b"step10",
    )

    env = os.environ.copy()
    env["NLC_REQUESTS_ROOT"] = str(req_root)
    env["NLC_POLICY_VERSION"] = policy
    env["NLC_DB_SNAPSHOT_ID"] = know_id
    env["NLC_SNAPSHOT_ID"] = know_id
    env["NLC_KB_SNAPSHOT_ID"] = know_id

    # Gate0 init
    run(
        [
            sys.executable,
            str(BASE / "orchestrator" / "orchestrator.py"),
            "gate0_init",
            req_id,
            json.dumps("Make a CLI that counts from 1 to 2 by 1"),
            json.dumps([]),
            json.dumps([]),
            json.dumps([]),
        ],
        env=env,
    )

    # Patch payload: CLI --knowledge-snapshot-id is authoritative (must exist in proof kit)
    payload_path = req_dir / "payload.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8", errors="replace"))
    payload["knowledge_snapshot_id"] = know_id
    from nlc.reproducibility import get_manifest_hashes
    manifest_info = get_manifest_hashes(know_id)
    if not manifest_info or not manifest_info.get("manifest_bundle_hash"):
        die(f"missing knowledge snapshot manifest bundle hash for {know_id}")
    payload["manifest_bundle_hash"] = manifest_info["manifest_bundle_hash"]
    payload["external_snapshot_id"] = ext_id
    payload["policy_version"] = policy
    payload_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Run gate1 twice; snapshot_resolution.json must be byte-identical.
    run([sys.executable, str(BASE / "orchestrator" / "orchestrator.py"), "gate1_planning", req_id], env=env, allow_fail=True)
    sr = req_dir / "snapshot_resolution.json"
    if not sr.exists():
        die("snapshot_resolution.json missing after gate1_planning")
    b1 = sr.read_bytes()
    run([sys.executable, str(BASE / "orchestrator" / "orchestrator.py"), "gate1_planning", req_id], env=env, allow_fail=True)
    b2 = sr.read_bytes()
    if b1 != b2:
        die("snapshot_resolution.json bytes not stable across runs")

    # Replay: resolver must not re-run; bytes must remain identical, verifier enforces match.
    env_repro = env.copy()
    env_repro["DCS_REPRO"] = "1"
    run([sys.executable, str(BASE / "workers" / "run_verifier.py"), req_id, str(req_dir), "gate1_planning"], env=env_repro, allow_fail=True)
    if sr.read_bytes() != b1:
        die("snapshot_resolution.json bytes changed in replay")

    # Inject conflict: external_snapshot_id == knowledge_snapshot_id should FAIL with snapshot_violation.
    payload_bad = dict(payload)
    payload_bad["external_snapshot_id"] = know_id
    payload_path.write_text(json.dumps(payload_bad, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Force resolver rerun (non-repro): remove resolution file then run gate1
    sr.unlink(missing_ok=True)
    run([sys.executable, str(BASE / "orchestrator" / "orchestrator.py"), "gate1_planning", req_id], env=env, allow_fail=True)
    # Verifier must surface snapshot_violation (resolution mismatch will appear in failures.json if file exists; otherwise gate blocked)
    v = run([sys.executable, str(BASE / "workers" / "run_verifier.py"), req_id, str(req_dir), "gate1_planning"], env=env, allow_fail=True)
    failures_path = req_dir / "verifier" / "failures.json"
    if not failures_path.exists():
        die("missing failures.json for conflict case")
    fobj = json.loads(failures_path.read_text(encoding="utf-8", errors="replace"))
    failures = fobj.get("failures", [])
    ok = any(isinstance(x, dict) and x.get("kind") == "snapshot_violation" for x in failures)
    if not ok:
        die("expected snapshot_violation failure for conflict case")

    print("✓ Step 10 snapshot resolution is deterministic and replay-pinned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


